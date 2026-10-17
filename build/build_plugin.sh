#!/bin/sh
# Build the Metal driver bundle stub: build/out/IXMTLDriver.bundle
# The real plugin contract (what Metal.framework loads from /Library/GPUBundles) is
# Phase D work; this keeps the layout and pipeline in place from day one.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC="$ROOT/plugin/IXMTLDriver"
OUT="$ROOT/build/out/IXMTLDriver.bundle"

mkdir -p "$OUT/Contents/MacOS"
xcrun clang -arch x86_64 -dynamiclib -fobjc-arc -framework Foundation \
  "$SRC/IXMTLDriver.m" -o "$OUT/Contents/MacOS/IXMTLDriver"
cp "$SRC/Info.plist" "$OUT/Contents/Info.plist"
echo "built $OUT"
