#!/bin/sh
# iris-xe installer — scaffold phase. Runs as root on macOS.
# Copies the kexts into /Library/Extensions and rebuilds the auxiliary kernel collection.
# A guarded installer with rollback (like the NullMoth one) arrives once the stack
# actually loads and there is something to roll back.
#
# usage: sudo sh package/install.sh [payload-dir]      (default payload: package/pkgroot)
set -eu
PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH
HERE=$(cd "$(dirname "$0")" && pwd)
PAYLOAD=${1:-$HERE/pkgroot}
KEXTS="IXFB IXRM IXAccel IXAGDC"

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

== done. Before rebooting, wire OpenCore (see reports/iris-config-notes.md for the
   exact machine-specific values):

   NVRAM > Add > 7C436110-AB2A-4BBB-A880-FE41995C9F82
     boot-args        iris=1 irisfb=1 irisaccel=1 amfi_get_out_of_my_way=0x1 amfi=0x80 ipc_control_port_options=0
     csr-active-config <430A0000>
   Misc > Security > SecureBootModel: Disabled
   (and add every key you set to NVRAM > Delete as well)

   then: sudo shutdown -r now
EOF
