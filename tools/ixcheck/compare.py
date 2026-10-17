#!/usr/bin/env python3
"""compare — diff the ixplan register plan against ground truth.

Sources it understands:

  --capture DIR|TARBALL   an ixcheck capture from a Linux live session (raw eDP EDID
                          + i915_display_info and friends)
  --ixfb-log FILE         kernel-log text containing "IXFB:" lines (macOS side)
  --edid FILE / --edid-hex H
                          EDID to plan from when no capture is given

For every field the tool prints plan (ixplan) | i915 | IXFB with a verdict, so a
Phase C session produces one self-contained answer. Exit code is 0 unless a DIFF is
found and --strict was given.

The i915 parser scans text lines for stable markers ("crtc timings:", "pipe src
size:", "crtc clock:", "stride", "format", "tiling") instead of a rigid layout, so
small kernel-version wording changes don't break it. If a field shows "not found",
the raw capture still contains the data — the parser just needs one more pattern.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

FORMAT_NAMES = {"XRGB8888": 8, "XBGR8888": 9, "RGB565": 2, "XRGB2101010": 16}
TILING_NAMES = {"linear": 0, "x": 1, "y": 2, "yf": 3}


def load_ixplan():
    spec = importlib.util.spec_from_file_location(
        "ixplan", os.path.join(HERE, "..", "ixplan", "ixplan.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ i915 side

def parse_i915_display_info(text: str) -> dict:
    got: dict = {}
    for line in text.splitlines():
        low = line.lower()
        if "crtc timings:" in line and "h_total" not in got:
            nums = re.findall(r"-?\d+", line.split("crtc timings:", 1)[1])
            if len(nums) >= 8:
                ha, hf, hsw, hb, va, vf, vsw, vb = (int(n) for n in nums[:8])
                got.update({
                    "h_active": ha, "v_active": va,
                    "h_total": ha + hf + hsw + hb, "v_total": va + vf + vsw + vb,
                    "hs_start": ha + hf, "hs_end": ha + hf + hsw,
                    "vs_start": va + vf, "vs_end": va + vf + vsw,
                })
        if "pipe src size:" in line and "src_w" not in got:
            m = re.search(r"pipe src size:\s*(\d+)x(\d+)", line)
            if m:
                got["src_w"], got["src_h"] = int(m.group(1)), int(m.group(2))
        if "crtc clock:" in line and "pclk_khz" not in got:
            m = re.search(r"crtc clock:\s*(\d+)", line)
            if m:
                got["pclk_khz"] = int(m.group(1))
        if "stride" in low and "stride" not in got:
            m = re.search(r"stride:?\s+(\d+)", line, re.I)
            if m:
                got["stride"] = int(m.group(1))
        if "format" in low and "format" not in got:
            m = re.search(r"format:?\s+([A-Za-z0-9_]+)", line)
            if m and m.group(1) in FORMAT_NAMES:
                got["format_name"] = m.group(1)
                got["format"] = FORMAT_NAMES[m.group(1)]
        if "tiling" in low and "tiling" not in got:
            m = re.search(r"tiling:?\s+(\S+)", line, re.I)
            if m:
                t = m.group(1).rstrip(",").lower()
                got["tiling_name"] = t
                got["tiling"] = TILING_NAMES.get(t)
    if "h_total" in got and "pclk_khz" in got:
        got["refresh_hz"] = round(got["pclk_khz"] * 1000.0 / (got["h_total"] * got["v_total"]), 2)
    return got


# ------------------------------------------------------------------ IXFB side

IXFB_RE = re.compile(
    r"pipe (?P<pipe>\d+): (?P<w>\d+)x(?P<h>\d+) stride (?P<stride>\d+) "
    r"(?:fmt (?P<fmt>\d+) tiling (?P<tiling>\d+) )?"
    r"surface 0x(?P<surf>[0-9A-Fa-f]+) "
    r"(?:hs (?P<hss>\d+)-(?P<hse>\d+) vs (?P<vss>\d+)-(?P<vse>\d+) )?"
    r"totals (?P<ht>\d+)x(?P<vt>\d+), (?P<frames>\d+) vblanks in (?P<ms>\d+) ms -> "
    r"(?P<rhz>\d+)\.(?P<r100>\d+) Hz, pclk (?P<pclk>\d+) MHz")


def parse_ixfb_log(text: str) -> dict:
    matches = list(IXFB_RE.finditer(text))
    if not matches:
        return {}
    m = matches[-1]  # most recent takeover line in the text
    g = m.groupdict()
    got = {
        "h_active": int(g["w"]), "v_active": int(g["h"]),
        "stride": int(g["stride"]),
        "h_total": int(g["ht"]), "v_total": int(g["vt"]),
        "pclk_khz": int(g["pclk"]) * 1000,
        "refresh_hz": int(g["rhz"]) + int(g["r100"]) / 100.0,
        "pipe": int(g["pipe"]),
    }
    if g["fmt"] is not None:
        got["format"] = int(g["fmt"])
    if g["tiling"] is not None:
        got["tiling"] = int(g["tiling"])
    if g["hss"] is not None:
        got.update({
            "hs_start": int(g["hss"]), "hs_end": int(g["hse"]),
            "vs_start": int(g["vss"]), "vs_end": int(g["vse"]),
        })
    return got


# ------------------------------------------------------------------ capture io

def read_capture(path: str) -> tuple[dict, bytes | None]:
    """Return (name -> text, edid bytes or None) from an ixcheck dir or tarball."""
    tmp = None
    if not os.path.isdir(path):
        tmp = tempfile.mkdtemp(prefix="ixcheck-")
        with tarfile.open(path) as tf:
            try:
                tf.extractall(tmp, filter="data")
            except TypeError:  # Python < 3.12
                tf.extractall(tmp)
        path = tmp

    texts: dict = {}
    edid: bytes | None = None
    for root, _dirs, names in os.walk(path):
        for n in names:
            p = os.path.join(root, n)
            try:
                with open(p, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            if len(data) in (128, 256) and data[:8] == b"\x00\xff\xff\xff\xff\xff\xff\x00":
                if edid is None:
                    edid = data
                continue
            if len(data) < 4 * 1024 * 1024:
                try:
                    texts[n] = data.decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    pass
    return texts, edid


def pick_display_info(texts: dict) -> tuple[str | None, str | None]:
    for name, content in sorted(texts.items()):
        if "i915_display_info" in name:
            return name, content
    return None, None


# ------------------------------------------------------------------ diffing

class Row:
    def __init__(self, label, plan, i915, ixfb, fmt="{}", tol=0, ixfb_tol=None):
        self.label = label
        self.plan = plan
        self.i915 = i915
        self.ixfb = ixfb
        self.fmt = fmt
        self.tol = tol
        self.ixfb_tol = ixfb_tol if ixfb_tol is not None else tol

    def _cmp(self, a, b, tol):
        if a is None or b is None:
            return None
        return abs(a - b) <= tol

    def verdict(self):
        eq_915 = self._cmp(self.plan, self.i915, self.tol)
        eq_fb = self._cmp(
            self.i915 if self.i915 is not None else self.plan, self.ixfb, self.ixfb_tol)
        if eq_915 is False:
            return "DIFF(i915)"
        if eq_fb is False:
            return "DIFF(ixfb)"
        if eq_915 is None and eq_fb is None:
            return "n/a"
        return "PASS"

    def show(self, v):
        return "-" if v is None else self.fmt.format(v)


def build_rows(plan: dict, i915: dict, ixfb: dict) -> list[Row]:
    p = plan["mode"]
    stride_reg = int(plan["registers"]["PLANE_STRIDE"]["value"], 16)
    rows = [
        Row("h active", p["h_active"], i915.get("h_active"), ixfb.get("h_active")),
        Row("v active", p["v_active"], i915.get("v_active"), ixfb.get("v_active")),
        Row("h total", p["h_total"], i915.get("h_total"), ixfb.get("h_total")),
        Row("v total", p["v_total"], i915.get("v_total"), ixfb.get("v_total")),
        Row("h sync start", None, i915.get("hs_start"), ixfb.get("hs_start")),
        Row("h sync end", None, i915.get("hs_end"), ixfb.get("hs_end")),
        Row("v sync start", None, i915.get("vs_start"), ixfb.get("vs_start")),
        Row("v sync end", None, i915.get("vs_end"), ixfb.get("vs_end")),
        Row("stride (bytes)", stride_reg * 64, i915.get("stride"), ixfb.get("stride")),
        Row("format code", 8, i915.get("format"), ixfb.get("format")),
        Row("tiling code", 0, i915.get("tiling"), ixfb.get("tiling")),
        Row("pixel clock (kHz)", p["pixel_clock_khz"], i915.get("pclk_khz"),
            ixfb.get("pclk_khz"), tol=0, ixfb_tol=2000),
        Row("refresh (Hz)", p["refresh_hz"], i915.get("refresh_hz"),
            ixfb.get("refresh_hz"), fmt="{:.2f}", tol=0.05, ixfb_tol=1.5),
    ]
    return rows


def print_table(rows: list[Row]) -> int:
    w = 18
    print(f"{'field':<{w}} {'plan':>12} {'i915':>12} {'ixfb':>12}  verdict")
    print("-" * (w + 1 + 13 * 3 + 9))
    diffs = 0
    for r in rows:
        v = r.verdict()
        if v.startswith("DIFF"):
            diffs += 1
        print(f"{r.label:<{w}} {r.show(r.plan):>12} {r.show(r.i915):>12} "
              f"{r.show(r.ixfb):>12}  {v}")
    return diffs


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="diff ixplan vs i915 capture / IXFB logs")
    ap.add_argument("--capture", help="ixcheck capture: directory or .tar.gz")
    ap.add_argument("--ixfb-log", help="text file containing IXFB: log lines")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--edid", help="raw EDID file (when no capture is given)")
    src.add_argument("--edid-hex", help="EDID as a hex string")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any field differs")
    args = ap.parse_args()

    edid: bytes | None = None
    texts: dict = {}
    content: str | None = None
    if args.capture:
        if not os.path.exists(args.capture):
            print(f"capture not found: {args.capture}", file=sys.stderr)
            return 2
        texts, edid = read_capture(args.capture)
        name, content = pick_display_info(texts)
        if name:
            print(f"capture:  {args.capture} (using {name})")
        else:
            print(f"capture:  {args.capture} (no i915_display_info found in it?)")
    if args.edid:
        with open(args.edid, "rb") as f:
            edid = f.read()
    elif args.edid_hex:
        edid = bytes.fromhex(args.edid_hex.replace(" ", ""))

    if edid is None:
        print("no EDID available (give --capture with an edid_*.bin inside, or --edid)",
              file=sys.stderr)
        return 2

    ixplan = load_ixplan()
    try:
        plan = ixplan.plan(ixplan.parse_edid(edid))
    except ValueError as ex:
        print(f"EDID problem: {ex}", file=sys.stderr)
        return 2
    if len(edid) >= 128:
        print(f"edid:     {len(edid)} bytes -> {plan['panel']['name']} "
              f"({plan['panel']['vendor']} {plan['panel']['product_code']})")

    i915 = parse_i915_display_info(content) if content else {}
    if args.capture and not i915:
        print("note: no comparable i915 fields found - if the file was captured on real "
              "hardware, send it over; the parser needs one more pattern")

    ixfb_text = ""
    if args.ixfb_log:
        with open(args.ixfb_log, encoding="utf-8", errors="replace") as f:
            ixfb_text = f.read()
    ixfb = parse_ixfb_log(ixfb_text)
    if args.ixfb_log and not ixfb:
        print(f"note: no IXFB takeover line found in {args.ixfb_log}")

    m = plan["mode"]
    print(f"plan:     {m['h_active']}x{m['v_active']} @ {m['refresh_hz']} Hz, "
          f"h_total {m['h_total']}, v_total {m['v_total']}, pclk {m['pixel_clock_khz']} kHz")
    print()

    rows = build_rows(plan, i915, ixfb)
    diffs = print_table(rows)
    print()
    if diffs:
        print(f"verdict: {diffs} field(s) differ")
        return 1 if args.strict else 0
    print("verdict: all compared fields agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
