#!/usr/bin/env python3
"""test_compare — CI self-test for the ixcheck toolchain (no hardware needed).

Builds a synthetic EDID + i915_display_info + IXFB log that *agree*, then proves:

  1. ixplan computes the known-good values for a 1920x1080 panel
     (PLANE_STRIDE regression guard: 0x78 = 7680 bytes / 64)
  2. compare.py passes when all three sources agree
  3. the X-tiled Linux surface shows as INFO (expected), never as a failing DIFF
  4. a wrong htotal in the capture fails the run (exit 1 with --strict)
  5. captures work as .tar.gz, including tar member names Windows cannot write
     to disk (PCI-address names with a colon) - regression guard for the first
     real capture
  6. the old-format IXFB log line (no fmt/tiling/hs/vs fields) still parses

The i915 sample mirrors the real kernel-6.12 format seen on the target laptop
(ixcheck capture 2026-10-17).

Run:  python3 tools/ixcheck/test_compare.py   (or on Windows: python ...)
"""
from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
COMPARE = os.path.join(HERE, "compare.py")


def load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_edid(h=1920, hblank=160, v=1080, vblank=31,
              hso=48, hsw=32, vso=3, vsw=5, pclk_khz=138500) -> bytes:
    """Minimal valid EDID base block with one detailed timing descriptor."""
    b = bytearray(128)
    b[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    mfg = ((ord("A") - 64) << 10) | ((ord("U") - 64) << 5) | (ord("O") - 64)
    b[8], b[9] = mfg >> 8, mfg & 0xFF
    b[10], b[11] = 0x21, 0x08          # product code 0x0821
    b[12:16] = b"\x01\x02\x03\x04"     # serial (fake)
    b[16], b[17] = 30, 2024 - 1990     # week/year (EDID stores year-1990)
    b[18], b[19] = 1, 4                # EDID 1.4
    b[20] = 0xA5                       # digital input
    b[21], b[22] = 34, 19              # 34 cm x 19 cm
    b[23] = 120                        # gamma 2.2
    b[24] = 0x0A                       # RGB + preferred timing set

    d = 54  # descriptor 1: detailed timing
    b[d + 0], b[d + 1] = pclk_khz // 10 & 0xFF, (pclk_khz // 10) >> 8
    b[d + 2], b[d + 3] = h & 0xFF, hblank & 0xFF
    b[d + 4] = ((h >> 8) << 4) | ((hblank >> 8) & 0xF)
    b[d + 5], b[d + 6] = v & 0xFF, vblank & 0xFF
    b[d + 7] = ((v >> 8) << 4) | ((vblank >> 8) & 0xF)
    b[d + 8], b[d + 9] = hso & 0xFF, hsw & 0xFF
    b[d + 10] = ((vso & 0xF) << 4) | (vsw & 0xF)
    b[d + 11] = 0

    n = 72  # descriptor 2: monitor name
    b[n + 3], b[n + 4] = 0xFC, 0
    for i, ch in enumerate("IXCHECK TEST"):
        b[n + 5 + i] = ord(ch)
    b[n + 5 + 12] = 0x0A

    b[90 + 3] = 0xFD   # descriptor 3: range limits (unused by the parser)
    b[108 + 3] = 0x10  # descriptor 4: dummy

    b[127] = (256 - (sum(b[:127]) & 0xFF)) & 0xFF  # checksum
    return bytes(b)


# Same shape as the real capture from the Latitude 5420 (kernel 6.12), with the
# synthetic EDID's timing above: htotal 2080, vtotal 1111, pclk 138500 kHz,
# hsync 1968-2000, vsync 1083-1088, XR24 + I915_FORMAT_MOD_X_TILED.
DISPLAY_INFO = (
    "CRTC info\n"
    "---------\n"
    "[CRTC:100:pipe A]:\n"
    '\tuapi: enable=yes, active=yes, mode="": 60 138500 1920 1968 2000 2080 1080 1083 1088 1111 0x0 0x9\n'
    "\thw: enable=yes, active=yes\n"
    "\tpipe src=1920x1080+0+0, dither=no, bpp=24\n"
    "\t[PLANE:32:plane 1A]: type=PRI\n"
    "\t\tuapi: [FB:358] XR24 little-endian (0x34325258),0x100000000000001,1920x1080, visible=visible\n"
    "\t\thw: [FB:358] XR24 little-endian (0x34325258),0x100000000000001,1920x1080, visible=yes\n"
    "[CRTC:170:pipe B]:\n"
    '\tuapi: enable=no, active=no, mode="": 0 0 0 0 0 0 0 0 0 0 0x0 0x0\n'
    "\thw: enable=no, active=no\n"
    "\n"
    "Connector info\n"
    "--------------\n"
    "[CONNECTOR:313:eDP-1]: status: connected\n"
)

IXFB_LOG = """\
IXFB: probe: Iris Xe 8086:9A49 (display v12)
IXFB: scan: pipe 0 PIPECONF 00000000 PLANE_CTL 00000000
IXFB: scan: pipe 1 PIPECONF 80000000 PLANE_CTL 84010000
IXFB: pipe 1: 1920x1080 stride 7680 fmt 8 tiling 0 surface 0x10000000 \
hs 1968-2000 vs 1083-1088 totals 2080x1111, 15 vblanks in 250 ms -> 60.00 Hz, pclk 138 MHz
"""

IXFB_LOG_OLD = """\
IXFB: pipe 1: 1920x1080 stride 7680 surface 0x10000000 totals 2080x1111, \
15 vblanks in 250 ms -> 60.00 Hz, pclk 138 MHz
"""


def run_compare(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, COMPARE, *argv],
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    failures = []

    def check(name: str, ok: bool, extra: str = ""):
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            failures.append(name)
            if extra:
                print("        " + extra.replace("\n", "\n        "))

    print("== 1. ixplan plan for a synthetic 1920x1080 panel")
    ixplan = load_module("ixplan", os.path.join(HERE, "..", "ixplan", "ixplan.py"))
    edid = make_edid()
    plan = ixplan.plan(ixplan.parse_edid(edid))
    m = plan["mode"]
    check("mode 1920x1080", m["h_active"] == 1920 and m["v_active"] == 1080)
    check("h_total 2080", m["h_total"] == 2080, f"got {m['h_total']}")
    check("v_total 1111", m["v_total"] == 1111, f"got {m['v_total']}")
    check("PLANE_STRIDE 0x78 (stride/64 units)",
          plan["registers"]["PLANE_STRIDE"]["value"] == "0x00000078",
          f"got {plan['registers']['PLANE_STRIDE']['value']}")

    with tempfile.TemporaryDirectory(prefix="ixcheck-test-") as td:
        cap = os.path.join(td, "capture")
        os.makedirs(cap)
        with open(os.path.join(cap, "0_i915_display_info.txt"), "w", encoding="utf-8") as f:
            f.write(DISPLAY_INFO)
        with open(os.path.join(cap, "edid_card0-eDP-1.bin"), "wb") as f:
            f.write(edid)
        ixfb_path = os.path.join(td, "ixfb.log")
        with open(ixfb_path, "w", encoding="utf-8") as f:
            f.write(IXFB_LOG)

        print("== 2. compare: agreeing capture + IXFB log -> pass (tiling INFO only)")
        r = run_compare("--capture", cap, "--ixfb-log", ixfb_path, "--strict")
        check("exit 0", r.returncode == 0, r.stdout + r.stderr)
        check("report says all agree", "all compared fields agree" in r.stdout, r.stdout)
        check("tiling shown as INFO", "INFO" in r.stdout, r.stdout)
        check("notes printed", "notes:" in r.stdout and "derived" in r.stdout, r.stdout)

        # wrong htotal in the capture: a DIFF must appear and --strict must fail
        bad = os.path.join(td, "bad")
        os.makedirs(bad)
        with open(os.path.join(bad, "0_i915_display_info.txt"), "w", encoding="utf-8") as f:
            f.write(DISPLAY_INFO.replace("2000 2080 1080", "2000 2064 1080"))
        with open(os.path.join(bad, "edid_card0-eDP-1.bin"), "wb") as f:
            f.write(edid)

        print("== 3. compare: wrong htotal in capture -> DIFF + exit 1")
        r = run_compare("--capture", bad, "--strict")
        check("exit 1", r.returncode == 1, r.stdout + r.stderr)
        check("DIFF reported", "DIFF" in r.stdout, r.stdout)

        print("== 4. compare: tarball capture with a colon member name (first-real-capture shape)")
        tarball = os.path.join(td, "capture.tar.gz")
        with tarfile.open(tarball, "w:gz") as tf:
            def add(name: str, data: bytes) -> None:
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
            add("0000:00:02.0_i915_display_info.txt", DISPLAY_INFO.encode("utf-8"))
            add("edid_card0-eDP-1.bin", edid)
        r = run_compare("--capture", tarball, "--strict")
        check("exit 0", r.returncode == 0, r.stdout + r.stderr)
        check("edid found inside the tarball", "edid:" in r.stdout, r.stdout)

        print("== 5. old-format IXFB log line still parses")
        old_path = os.path.join(td, "ixfb-old.log")
        with open(old_path, "w", encoding="utf-8") as f:
            f.write(IXFB_LOG_OLD)
        r = run_compare("--capture", cap, "--ixfb-log", old_path)
        check("exit 0", r.returncode == 0, r.stdout + r.stderr)
        check("totals compared from old line", "2080" in r.stdout, r.stdout)

    print()
    if failures:
        print(f"SELFTEST FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("SELFTEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
