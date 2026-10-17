#!/bin/sh
# Build every component into build/out/. Runs on macOS with Xcode command line tools
# (locally or on the GitHub Actions macos-15 runner).
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)

for k in IXFB IXRM IXAccel IXAGDC; do
  sh "$ROOT/build/build_kext.sh" "$k"
done

sh "$ROOT/build/build_plugin.sh"

echo
echo "== build/out:"
ls -l "$ROOT/build/out"
