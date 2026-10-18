#!/bin/sh
# Download the macOS Recovery image from Apple and verify it, entirely on the
# machine running this script (the CI runner in workflows/boot-bundle.yml), for
# the board-id the docs pin (docs/PHASE-C-OPENCORE.md section 2 step 4):
#
#   -b Mac-27AD2F918AE68F61 -m 00000000000000000   (os default)
#
# The exact image size is read from Apple's chunklist metadata BEFORE the
# ~884 MB dmg is fetched. Output:
#   dist/bundle/com.apple.recovery.boot/{BaseSystem.dmg,BaseSystem.chunklist}
#   dist/bundle/com.apple.recovery.boot/RECOVERY-INFO.txt
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT="$ROOT/dist/bundle/com.apple.recovery.boot"
TMP="$ROOT/dist/.tmp-recovery"
RECOVERY_BOARD=Mac-27AD2F918AE68F61
RECOVERY_MLB=00000000000000000

log() { echo "[recovery] $*"; }
die() { echo "[recovery] ERROR: $*" >&2; exit 1; }

mkdir -p "$TMP" "$OUT"

log "fetching macrecovery.py"
curl -fsSL -o "$TMP/macrecovery.py" \
  https://raw.githubusercontent.com/acidanthera/OpenCorePkg/master/Utilities/macrecovery/macrecovery.py
grep -q 'osrecovery.apple.com' "$TMP/macrecovery.py" \
  || die "macrecovery.py does not look like macrecovery - aborting before any download"

cat > "$TMP/rcsteps.py" <<'PYEOF'
import subprocess
import sys
import os

tmp = sys.argv[1]
board = sys.argv[2]
mlb = sys.argv[3]
mode = sys.argv[4]
outdir = sys.argv[5]

sys.path.insert(0, tmp)
import macrecovery as m

class A:
    pass

a = A()
a.verbose = False
a.board_id = board
a.mlb = mlb
a.diagnostics = False
a.os_type = 'default'
a.outdir = outdir

if mode == 'probe':
    # metadata only: session, image info, chunklist (tiny) -> exact byte size
    session = m.get_session(a)
    info = m.get_image_info(session, bid=board, mlb=mlb, diag=False, os_type='default')
    cnk = m.save_image(info['CU'], info['CT'], 'BaseSystem.chunklist', outdir)
    total = sum(size for size, _ in m.verify_chunklist(cnk))
    print('PRODUCT=%s' % info['AP'])
    print('BYTES=%d' % total)
elif mode == 'download':
    r = subprocess.run([sys.executable, os.path.join(tmp, 'macrecovery.py'),
                        '-b', board, '-m', mlb, 'download', '-o', outdir])
    sys.exit(r.returncode)
elif mode == 'verify':
    m.verify_image(outdir + '/BaseSystem.dmg', outdir + '/BaseSystem.chunklist')
    print('VERIFIED')
else:
    sys.exit(1)
PYEOF

log "metadata first: which image, exactly how many bytes"
PROBE=$(python3 "$TMP/rcsteps.py" "$TMP" "$RECOVERY_BOARD" "$RECOVERY_MLB" probe "$OUT") \
  || die "Apple metadata step failed"
printf '%s\n' "$PROBE" | sed 's/^/[recovery] /'
PRODUCT=$(printf '%s\n' "$PROBE" | sed -n 's/^PRODUCT=//p')
BYTES=$(printf '%s\n' "$PROBE" | sed -n 's/^BYTES=//p')
[ -n "$PRODUCT" ] || die "no product id"
[ -n "$BYTES" ] || die "no byte size"
log "Apple offers product $PRODUCT ($BYTES bytes) - fetching the dmg"
python3 "$TMP/rcsteps.py" "$TMP" "$RECOVERY_BOARD" "$RECOVERY_MLB" download "$OUT" \
  || die "recovery download failed"
[ -f "$OUT/BaseSystem.dmg" ] || die "BaseSystem.dmg missing after download"
SIZE=$(stat -f%z "$OUT/BaseSystem.dmg")
[ "$SIZE" = "$BYTES" ] || die "size mismatch: got $SIZE bytes, expected $BYTES"
log "verifying every chunk against Apple's signed chunklist"
python3 "$TMP/rcsteps.py" "$TMP" "$RECOVERY_BOARD" "$RECOVERY_MLB" verify "$OUT" | sed 's/^/[recovery] /'

cat > "$OUT/RECOVERY-INFO.txt" <<EOFINFO
# macOS Recovery for the Iris Xe bring-up (Dell Latitude 5420, i5-1145G7)
# board-id: $RECOVERY_BOARD   MLB: $RECOVERY_MLB (os default)
# product:  $PRODUCT
# bytes:    $BYTES
# integrity: every chunk SHA-256-verified against Apple's signed chunklist
EOFINFO
log "done: $OUT"
