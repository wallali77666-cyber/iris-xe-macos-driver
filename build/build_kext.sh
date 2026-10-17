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

[ -f "$SRC/$NAME.cpp" ] || { echo "no source $SRC/$NAME.cpp"; exit 2; }
mkdir -p "$OUT/Contents/MacOS"

echo "== $NAME: compile"
xcrun clang++ \
  -arch x86_64 -mkernel -fapple-kext -nostdinc -I"$KHDR" -I"$SRC" \
  -DKERNEL -DKERNEL_PRIVATE -DDRIVER_PRIVATE -DAPPLE -DNeXT \
  -std=c++17 -fno-rtti -fno-exceptions -fno-builtin -fno-common \
  -Wall -Wno-unused-parameter -O2 \
  -c "$SRC/$NAME.cpp" -o "$OUT/Contents/MacOS/$NAME.o"

echo "== $NAME: link"
xcrun clang++ -arch x86_64 -fapple-kext -nostdlib -Xlinker -kext \
  -lkmodc++ -lkmod -lcc_kext \
  "$OUT/Contents/MacOS/$NAME.o" -o "$OUT/Contents/MacOS/$NAME"

rm -f "$OUT/Contents/MacOS/$NAME.o"
cp "$SRC/Info.plist" "$OUT/Contents/Info.plist"
echo "built $OUT"
