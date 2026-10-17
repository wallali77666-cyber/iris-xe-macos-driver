#!/usr/bin/env python3
"""recovery-info.py - ask Apple's recovery service what image a board-id gets,
and print its EXACT size from the tiny chunklist - before any large download.

Run next to macrecovery.py (same directory), as documented in
docs/PHASE-C-OPENCORE.md section 2 step 4.

The board-id/MLB below are the same values the docs pin (and macrecovery's own
defaults): MacPro7,1 + zero MLB + os 'default' -> latest recovery for that
board.
"""
import sys

import macrecovery as m


class A:
    pass


a = A()
a.verbose = False
a.board_id = 'Mac-27AD2F918AE68F61'
a.mlb = '00000000000000000'
a.diagnostics = False
a.os_type = 'default'
a.outdir = 'meta'

try:
    session = m.get_session(a)
    info = m.get_image_info(session, bid=a.board_id, mlb=a.mlb,
                            diag=False, os_type=a.os_type)
except Exception as exc:
    print('METADATA FAILED: %r' % (exc,))
    sys.exit(2)

for key in sorted(info):
    print('  %s = %s' % (key, info[key]))

try:
    cnk = m.save_image(info['CU'], info['CT'], 'BaseSystem.chunklist', 'meta')
    chunks = list(m.verify_chunklist(cnk))
except Exception as exc:
    print('CHUNKLIST FAILED: %r' % (exc,))
    sys.exit(3)

total = sum(size for size, _ in chunks)
name = info.get('AU', '').rsplit('/', 1)[-1]
print('DMG_NAME %s' % name)
print('EXACT_SIZE_BYTES %d' % total)
print('EXACT_SIZE_MB %.1f' % (total / 1048576.0))
print('CHUNKS %d' % len(chunks))
