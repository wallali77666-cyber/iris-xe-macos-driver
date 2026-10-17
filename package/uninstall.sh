#!/bin/sh
# iris-xe uninstaller for the /Library/Extensions route. Runs as root on macOS.
# Removes the kexts and rebuilds the auxiliary kernel collection so the Mac returns
# to exactly what it was before install.
#
# (If you use the CI OpenCore EFI path instead, uninstalling is just removing
#  IXFB/IXRM from EFI/OC/Kexts + config.plist — nothing on the system to undo.)
set -eu
PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH
KEXTS="IXFB IXRM IXAccel IXAGDC"

[ "$(id -u)" = 0 ] || { echo "STOP: run as root:  sudo sh package/uninstall.sh"; exit 1; }
command -v kmutil >/dev/null 2>&1 || { echo "STOP: kmutil not found (this script runs on macOS)"; exit 1; }

echo "== removing kexts from /Library/Extensions"
for k in $KEXTS; do
  rm -rf "/Library/Extensions/$k.kext"
done

echo "== rebuilding the auxiliary kernel collection"
K=/System/Library/Kernels/kernel
KARG=""
if [ -f "$K" ]; then KARG="--kernel $K"; fi
# no -p list: the collection is rebuilt from whatever remains in /Library/Extensions
# shellcheck disable=SC2086
kmutil create -n aux --allow-missing-kdk -a x86_64 --volume-root / $KARG \
  -B /System/Library/KernelCollections/BootKernelExtensions.kc \
  --repository /Library/Extensions \
  -A /Library/KernelCollections/AuxiliaryKernelExtensions.kc -z

echo "== done. Reboot to finish removal. If the driver stopped macOS from starting,"
echo "   boot with boot-arg -ixfboff (or remove the kext from the OpenCore config) first."
