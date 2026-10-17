#!/bin/sh
# iris-xe kext installer for the /Library/Extensions (auxiliary kernel collection) route.
#
# IMPORTANT — Phase C does not need this script: the CI-built OpenCore EFI
# (docs/PHASE-C-OPENCORE.md) already injects IXFB/IXRM on every boot, installer
# included. Use this script only if you deliberately want the kexts resident in
# macOS itself (for example after removing them from the EFI config).
#
# Runs as root on macOS. Copies the kexts into /Library/Extensions and rebuilds the
# auxiliary kernel collection with kmutil (the method studied from NullMoth's installer).
#
# usage: sudo sh package/install.sh [payload-dir]      (default payload: package/pkgroot)
set -eu
PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH
HERE=$(cd "$(dirname "$0")" && pwd)
PAYLOAD=${1:-$HERE/pkgroot}
KEXTS="IXFB IXRM IXAccel IXAGDC"

[ "$(id -u)" = 0 ] || { echo "STOP: run as root:  sudo sh package/install.sh"; exit 1; }
command -v kmutil >/dev/null 2>&1 || { echo "STOP: kmutil not found (this script runs on macOS)"; exit 1; }

echo "== checking payload in $PAYLOAD"
for k in $KEXTS; do
  [ -d "$PAYLOAD/Library/Extensions/$k.kext" ] || { echo "STOP: $k.kext missing in payload"; exit 2; }
done

echo "== copying kexts to /Library/Extensions"
for k in $KEXTS; do
  rm -rf "/Library/Extensions/$k.kext"
  ditto "$PAYLOAD/Library/Extensions/$k.kext" "/Library/Extensions/$k.kext"
  chown -R root:wheel "/Library/Extensions/$k.kext"
  chmod -R go-w "/Library/Extensions/$k.kext"
done

echo "== rebuilding the auxiliary kernel collection"
K=/System/Library/Kernels/kernel
KARG=""
if [ -f "$K" ]; then KARG="--kernel $K"; fi
# shellcheck disable=SC2086
kmutil create -n aux --allow-missing-kdk -a x86_64 --volume-root / $KARG \
  -B /System/Library/KernelCollections/BootKernelExtensions.kc \
  --repository /Library/Extensions \
  -p /Library/Extensions/IXFB.kext -p /Library/Extensions/IXRM.kext \
  -p /Library/Extensions/IXAccel.kext -p /Library/Extensions/IXAGDC.kext \
  -A /Library/KernelCollections/AuxiliaryKernelExtensions.kc -z

cat <<'EOF'

== done. Reboot to load the kexts.

   Notes:
   - SecureBootModel must be Disabled for unsigned kexts (the CI EFI already sets
     this). If kmutil refuses the collection with a signature error, this route is
     blocked on your install — keep using OpenCore injection instead, which is the
     default path anyway.
   - To keep the panel on the firmware framebuffer for one boot, add boot-arg
     -ixfboff (IXFB declines and the screen is left alone).
   - Details and the hardware-bring-up steps: docs/PHASE-C-OPENCORE.md
EOF
