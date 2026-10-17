#!/bin/sh
# iris-xe uninstaller — scaffold phase. Runs as root on macOS.
# Removes the kexts and rebuilds the auxiliary kernel collection so the Mac returns
# to exactly what it was before install.
set -eu
PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH
KEXTS="IXFB IXRM IXAccel IXAGDC"

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
echo "   boot with the -ivxoff argument (or remove boot-args iris=* in OpenCore) first."
