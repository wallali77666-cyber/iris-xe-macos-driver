#!/bin/sh
# Build one kext bundle: sh build/build_kext.sh <name>   (IXFB, IXRM, IXAccel, IXAGDC)
#
# Toolchain: macOS SDK's Kernel.framework headers (the same approach NullMoth's build
# scripts use — no MacKernelSDK needed). Output: build/out/<name>.kext
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
NAME=${1:?usage: build_kext.sh <kext name>}
SRC="$ROOT/kexts/$NAME"
OUT="$ROOT/build/out/$NAME.kext"
SDK=$(xcrun --show-sdk-path)
KHDR="$SDK/System/Library/Frameworks/Kernel.framework/Headers"

[ -d "$SRC" ] || { echo "no source dir $SRC"; exit 2; }
ls "$SRC"/*.cpp >/dev/null 2>&1 || { echo "no sources in $SRC"; exit 2; }
mkdir -p "$OUT/Contents/MacOS"

echo "== $NAME: compile"
OBJS=""
for f in "$SRC"/*.cpp; do
  o="$OUT/Contents/MacOS/$(basename "$f" .cpp).o"
  echo "   $(basename "$f")"
  xcrun clang++ \
    -arch x86_64 -mkernel -fapple-kext -nostdinc -I"$KHDR" -I"$SRC" \
    -DKERNEL -DKERNEL_PRIVATE -DDRIVER_PRIVATE -DAPPLE -DNeXT \
    -std=c++17 -fno-rtti -fno-exceptions -fno-builtin -fno-common \
    -Wall -Wno-unused-parameter -O2 \
    -c "$f" -o "$o"
  OBJS="$OBJS $o"
done

echo "== $NAME: link"
# shellcheck disable=SC2086
xcrun clang++ -arch x86_64 -fapple-kext -nostdlib -Xlinker -kext \
  -lkmodc++ -lkmod -lcc_kext \
  $OBJS -o "$OUT/Contents/MacOS/$NAME"

rm -f $OBJS
cp "$SRC/Info.plist" "$OUT/Contents/Info.plist"
echo "built $OUT"
