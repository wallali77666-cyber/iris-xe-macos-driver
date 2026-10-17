#!/bin/sh
# Assemble a ready-to-flash EFI folder for Iris Xe laptops (reference: Dell Latitude 5420).
#
# Everything is fetched on the machine running this script (the GitHub macOS runner in
# CI). The output is a zip you copy to a FAT32 USB stick - no Mac needed to *use* it.
#
# Inputs:  build/out/{IXFB,IXRM}.kext  (run build/build_all.sh first)
#          efi/OC/ACPI/*.dsl           (compiled here with iasl)
# Output:  dist/efi/EFI/ + dist/efi/VERSIONS.txt + dist/efi/iris-xe-efi.zip
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
DIST="$ROOT/dist/efi"
EFI="$DIST/EFI"
TMP="$DIST/.tmp"
API=https://api.github.com

log() { echo "[assemble] $*"; }
die() { echo "[assemble] ERROR: $*" >&2; exit 1; }

rm -rf "$DIST"
mkdir -p "$EFI/OC/Kexts" "$EFI/OC/Drivers" "$EFI/OC/ACPI" "$EFI/BOOT" "$TMP"
{
  echo "# iris-xe-macos-driver EFI - reference machine: Dell Latitude 5420 (i5-1145G7, Iris Xe 8086:9A49)"
  echo "# components resolved from their latest GitHub releases at build time"
} > "$DIST/VERSIONS.txt"

# GITHUB_TOKEN is optional; it only raises the GitHub API rate limit on CI runners.
api() {
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    curl -fsSL -H "Accept: application/vnd.github+json" \
         -H "Authorization: Bearer $GITHUB_TOKEN" "$1"
  else
    curl -fsSL -H "Accept: application/vnd.github+json" "$1"
  fi
}
release_tag() { python3 -c 'import sys, json; print(json.load(sys.stdin)["tag_name"])'; }
release_asset() { # $1 = fnmatch pattern over asset names
  python3 -c 'import sys, json, fnmatch
d = json.load(sys.stdin)
for a in d["assets"]:
    if fnmatch.fnmatch(a["name"], sys.argv[1]):
        print(a["browser_download_url"])
        break
else:
    raise SystemExit("no asset matching %s" % sys.argv[1])' "$1"
}

# ---- 1. our kexts ----------------------------------------------------------
for k in IXFB IXRM; do
  [ -d "$ROOT/build/out/$k.kext" ] || die "build/out/$k.kext missing - run build/build_all.sh first"
  cp -R "$ROOT/build/out/$k.kext" "$EFI/OC/Kexts/"
done
log "our kexts copied: IXFB, IXRM"

# ---- 2. SSDTs --------------------------------------------------------------
command -v iasl >/dev/null 2>&1 || die "iasl not found (install with: brew install acpica)"
for dsl in "$ROOT"/efi/OC/ACPI/*.dsl; do
  [ -e "$dsl" ] || die "no efi/OC/ACPI/*.dsl found"
  name=$(basename "$dsl" .dsl)
  iasl -vw 3144 -p "$EFI/OC/ACPI/$name" "$dsl" >/dev/null \
    || die "iasl failed for $dsl"
  log "ACPI compiled: $name.aml"
done

# ---- 3. OpenCore release (bootloader + drivers + utilities) ----------------
log "resolving latest OpenCore release"
ocjson=$(api "$API/repos/acidanthera/OpenCorePkg/releases/latest")
octag=$(printf '%s' "$ocjson" | release_tag)
echo "OpenCorePkg $octag" >> "$DIST/VERSIONS.txt"
mkdir -p "$TMP/oc"
printf '%s' "$ocjson" | python3 -c 'import sys, json
d = json.load(sys.stdin)
for a in d["assets"]:
    n = a["name"].lower()
    if n.endswith(".zip") and "debug" not in n:
        print(a["browser_download_url"])' | while read -r url; do
  log "download: $(basename "$url")"
  curl -fL -o "$TMP/oc/$(basename "$url")" "$url"
  unzip -oq "$TMP/oc/$(basename "$url")" -d "$TMP/oc"
done

[ -d "$TMP/oc" ] || die "OpenCore download/extract failed"
log "release layout (top levels):"
find "$TMP/oc" -mindepth 1 -maxdepth 2 | sort | head -n 20 | sed 's|^|  |'

BOOTX64=$(find "$TMP/oc" -type f -name BOOTx64.efi | head -n 1)
OCORE=$(find "$TMP/oc" -type f -name OpenCore.efi | head -n 1)
[ -n "$BOOTX64" ] || die "BOOTx64.efi not found anywhere in the OpenCore release"
[ -n "$OCORE" ] || die "OpenCore.efi not found anywhere in the OpenCore release"
cp "$BOOTX64" "$EFI/BOOT/BOOTx64.efi"
cp "$OCORE" "$EFI/OC/OpenCore.efi"

DRIVERS=""
for d in OpenRuntime.efi OpenHfsPlus.efi ResetNvramEntry.efi; do
  f=$(find "$TMP/oc" -type f -name "$d" | head -n 1)
  if [ -n "$f" ]; then
    cp "$f" "$EFI/OC/Drivers/"
    DRIVERS="$DRIVERS $d"
    log "driver: $d"
  else
    log "WARNING: $d not found in the OpenCore release"
  fi
done

MS=$(find "$TMP/oc" -type f -name macserial | head -n 1)
OCV=$(find "$TMP/oc" -type f -name ocvalidate | head -n 1)
if [ -n "$MS" ]; then chmod +x "$MS"; log "macserial found"; fi
if [ -n "$OCV" ]; then chmod +x "$OCV"; log "ocvalidate found"; fi

# ---- 4. Acidanthera kexts --------------------------------------------------
fetch_kext() { # $1 = repo, $2 = label
  json=$(api "$API/repos/$1/releases/latest")
  tag=$(printf '%s' "$json" | release_tag)
  url=$(printf '%s' "$json" | release_asset '*-RELEASE.zip')
  echo "$2 $tag" >> "$DIST/VERSIONS.txt"
  mkdir -p "$TMP/k_$2"
  log "$2 $tag"
  curl -fL -o "$TMP/$2.zip" "$url"
  unzip -oq "$TMP/$2.zip" -d "$TMP/k_$2"
}
fetch_kext acidanthera/Lilu         Lilu
fetch_kext acidanthera/VirtualSMC   VirtualSMC
fetch_kext acidanthera/WhateverGreen WhateverGreen
fetch_kext acidanthera/AppleALC     AppleALC
fetch_kext acidanthera/IntelMausi   IntelMausi

copy_kext() { # $1 = extracted dir, $2 = kext name
  f=$(find "$1" -maxdepth 4 -type d -name "$2" | head -n 1)
  [ -n "$f" ] || die "$2 not found in $1"
  cp -R "$f" "$EFI/OC/Kexts/"
  log "kext: $2"
}
copy_kext "$TMP/k_Lilu" Lilu.kext
copy_kext "$TMP/k_VirtualSMC" VirtualSMC.kext
copy_kext "$TMP/k_VirtualSMC" SMCProcessor.kext
copy_kext "$TMP/k_VirtualSMC" SMCBatteryManager.kext
copy_kext "$TMP/k_WhateverGreen" WhateverGreen.kext
copy_kext "$TMP/k_AppleALC" AppleALC.kext
copy_kext "$TMP/k_IntelMausi" IntelMausi.kext

# ---- 5. config.plist from the release's own Sample.plist -------------------
SAMPLE=$(find "$TMP/oc" -type f -name Sample.plist | head -n 1)
[ -n "$SAMPLE" ] || die "Sample.plist not found in the OpenCore release"
set -- --sample "$SAMPLE" --out "$EFI/OC/config.plist" --oc-version "$octag" --drivers $DRIVERS
if [ -n "$MS" ]; then
  set -- "$@" --macserial "$MS"
fi
if ! python3 "$ROOT/tools/efi/configure.py" "$@" > "$DIST/configure.log" 2>&1; then
  cat "$DIST/configure.log"
  die "configure.py failed"
fi
cat "$DIST/configure.log"

# ---- 6. validate -----------------------------------------------------------
python3 -c 'import plistlib, sys; plistlib.load(open(sys.argv[1], "rb")); print("config.plist parses")' \
  "$EFI/OC/config.plist"
if [ -n "$OCV" ]; then
  set +e
  "$OCV" "$EFI/OC/config.plist" > "$DIST/ocvalidate.log" 2>&1
  rc=$?
  set -e
  cat "$DIST/ocvalidate.log"
  [ "$rc" -eq 0 ] || die "ocvalidate flagged issues (exit $rc) - fix tools/efi/configure.py"
  log "ocvalidate: clean"
else
  log "ocvalidate not present in the release - plist parse check only"
fi

# ---- 6b. consistency: everything the config references must exist in the tree ---
# A config entry without its file (or with a wrong executable name) is exactly the
# class of bug that ends in a black screen on hardware day - fail the build instead.
python3 - "$EFI/OC/config.plist" "$EFI" <<'PYEOF' || die "EFI consistency check failed"
import os
import plistlib
import sys

cfg = plistlib.load(open(sys.argv[1], "rb"))
efi = sys.argv[2]
missing = []

for e in cfg.get("Kernel", {}).get("Add", []) or []:
    if not e.get("Enabled"):
        continue
    bundle = os.path.join(efi, "OC", "Kexts", e.get("BundlePath", ""))
    if not os.path.isdir(bundle):
        missing.append("Kexts/" + str(e.get("BundlePath")))
        continue
    exe = e.get("ExecutablePath")
    if exe and not os.path.isfile(os.path.join(bundle, exe)):
        missing.append("Kexts/%s -> %s" % (e.get("BundlePath"), exe))

for d in cfg.get("UEFI", {}).get("Drivers", []) or []:
    if d.get("Enabled") and not os.path.isfile(
            os.path.join(efi, "OC", "Drivers", d.get("Path", ""))):
        missing.append("Drivers/" + str(d.get("Path")))

for a in cfg.get("ACPI", {}).get("Add", []) or []:
    if a.get("Enabled") and not os.path.isfile(
            os.path.join(efi, "OC", "ACPI", a.get("Path", ""))):
        missing.append("ACPI/" + str(a.get("Path")))

for need in ("BOOT/BOOTx64.efi", "OC/OpenCore.efi"):
    if not os.path.isfile(os.path.join(efi, need)):
        missing.append(need)

if missing:
    print("MISSING from the EFI tree: " + ", ".join(missing))
    sys.exit(1)
print("consistency: every enabled kext/driver/ACPI entry exists in the tree")
PYEOF

# ---- 7. package ------------------------------------------------------------
(cd "$DIST" && zip -qr iris-xe-efi.zip EFI VERSIONS.txt)
log "tree:"
find "$EFI" -maxdepth 3 -mindepth 1 | sort | sed 's|^|  |'
log "versions:"
sed 's|^|  |' "$DIST/VERSIONS.txt"
ls -l "$DIST/iris-xe-efi.zip"
