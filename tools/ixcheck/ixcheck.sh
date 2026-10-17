#!/usr/bin/env bash
# ixcheck — capture the running Linux i915 display state (ground truth) from the
# target machine, so the macOS side (IXFB logs) and the register planner (ixplan)
# can be validated against what the real driver actually programmed.
#
# READ-ONLY: this script never writes to hardware, sysfs or debugfs. It only reads
# debugfs/sysfs text and packs it into one tarball for you to copy back to Windows.
#
# Usage on a Linux live USB (the internal panel is already lit by i915/fbcon):
#   sudo bash ixcheck.sh [--out DIR]
# Output: <DIR>/ixcheck-<host>-<date>.tar.gz   (~a few hundred KB)
set -euo pipefail

OUT="."
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[ "$(id -u)" = "0" ] || { echo "ERROR: run with sudo (debugfs needs root)" >&2; exit 1; }
[ -d /sys/kernel/debug/dri ] || mount -t debugfs none /sys/kernel/debug 2>/dev/null || true
[ -d /sys/kernel/debug/dri ] || { echo "ERROR: /sys/kernel/debug/dri unavailable - is i915 loaded?" >&2; exit 1; }

mkdir -p "$OUT"
WK="$(mktemp -d)"
trap 'rm -rf "$WK"' EXIT

# --- 1. i915 debugfs text (every card; the file list is "copy what exists") ---
for d in /sys/kernel/debug/dri/[0-9]*; do
  [ -d "$d" ] || continue
  n="$(basename "$d")"
  for f in i915_display_info i915_edp_psr_status i915_power_domains \
           i915_runtime_pm_status i915_frequency_info i915_vbt i915_wm_disp; do
    if [ -r "$d/$f" ]; then
      cat "$d/$f" > "$WK/${n}_${f}.txt" 2>/dev/null || true
    fi
  done
done
[ -n "$(ls "$WK" 2>/dev/null)" ] || { echo "ERROR: no i915 debugfs files readable" >&2; exit 1; }

# --- 2. the eDP panel: raw EDID + connection status --------------------------
for c in /sys/class/drm/card*-eDP-*; do
  [ -e "$c" ] || continue
  n="$(basename "$c")"
  if [ -s "$c/edid" ]; then cp "$c/edid" "$WK/edid_${n}.bin"; fi
  if [ -r "$c/status" ]; then cat "$c/status" > "$WK/status_${n}.txt"; fi
  if [ -r "$c/modes" ]; then cat "$c/modes" > "$WK/modes_${n}.txt"; fi
done

# --- 3. PCI state, driver messages, kernel identity --------------------------
if command -v lspci >/dev/null 2>&1; then
  lspci -vv -s 00:02.0 > "$WK/lspci-igpu.txt" 2>&1 || true
fi
dmesg > "$WK/dmesg.txt" 2>/dev/null || true
dmesg 2>/dev/null | grep -iE 'i915|drm' > "$WK/dmesg-i915.txt" || true
uname -a > "$WK/uname.txt"
cat /proc/cmdline > "$WK/kernel-cmdline.txt" 2>/dev/null || true

# --- 4. optional: full register dump if igt-gpu-tools happens to be installed --
if command -v intel_reg >/dev/null 2>&1; then
  intel_reg dump > "$WK/intel_reg_dump.txt" 2>&1 || true
fi

# --- 5. manifest + package ----------------------------------------------------
{
  echo "ixcheck capture"
  echo "host: $(hostname)"
  echo "date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  echo "kernel: $(uname -r)"
  echo "panel EDIDs:"
  ls -l "$WK"/edid_* 2>/dev/null || echo "  (none - was the internal panel active?)"
} > "$WK/MANIFEST.txt"

TARBALL="$OUT/ixcheck-$(hostname)-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -C "$WK" -czf "$TARBALL" .
echo
echo "wrote $TARBALL ($(du -h "$TARBALL" | cut -f1))"
echo "next: copy it to a FAT32 stick (or send it over), then on Windows run"
echo "  python tools/ixcheck/compare.py --capture <tarball> --strict"
