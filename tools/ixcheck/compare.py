#!/usr/bin/env python3
"""compare — diff the ixplan register plan against ground truth.

Sources it understands:

  --capture DIR|TARBALL   an ixcheck capture from a Linux live session (i915
                          debugfs text + the raw eDP EDID)
  --ixfb-log FILE         kernel-log text containing "IXFB:" lines (macOS side)
  --edid FILE / --edid-hex H / --report irisprobe-report.json
                          EDID to plan from when the capture has none

For every field the tool prints plan (ixplan) | i915 | IXFB with a verdict.
Exit code is 0 unless a DIFF is found and --strict was given.

The i915 parser is written against the real i915_display_info format (verified
against a live kernel-6.12 capture on the target Latitude 5420): the active
CRTC's `uapi ... mode=` line carries clock/totals/sync directly, and the active
primary plane's `hw: [FB..]` line carries the DRM fourcc and format modifier.
Two fields are deliberately special:

  - stride: debugfs does not print it; the i915 column derives width x 4 (the
    driver's own allocation pitch for this mode) and says so in the notes.
  - tiling: Linux allocates its own X-tiled scanout surface by design, while
    macOS adopts the firmware's linear one, so a tiled i915 value is expected
    (INFO), not a plan discrepancy. IXFB-vs-plan stays strict.

If a field shows "not found", the raw capture is still in the tarball - the
parser just needs one more pattern.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))

# DRM fourcc -> PLANE_CTL format code (8 = XRGB8888)
FOURCC_TO_PLANECFMT = {"XR24": 8}
# DRM format modifier -> our tiling code
MODIFIER_TO_TILING = {
    0x0000000000000000: 0,   # linear
    0x0100000000000001: 1,   # I915_FORMAT_MOD_X_TILED
    0x0100000000000002: 2,   # I915_FORMAT_MOD_Y_TILED
    0x0100000000000004: 3,   # I915_FORMAT_MOD_Yf_TILED
}
TILING_NAMES = {0: "linear", 1: "X", 2: "Y", 3: "Yf"}


def load_ixplan():
    spec = importlib.util.spec_from_file_location(
        "ixplan", os.path.join(HERE, "..", "ixplan", "ixplan.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ i915 side

MODE_RE = re.compile(
    r"uapi: enable=yes, active=yes.*?mode=\"[^\"]*\":\s*"
    r"(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)")
PLANE_RE = re.compile(
    r"\[FB:\d+\]\s+(\w+)\s+little-endian\s+\(0x[0-9a-fA-F]{8}\),\s*(0x[0-9a-fA-F]+),")


def parse_i915_display_info(text: str) -> dict:
    got: dict = {}
    plane_type = ""
    for line in text.splitlines():
        if "[PLANE:" in line and "]" in line and "type=" in line:
            m = re.search(r"type=(\w+)", line)
            plane_type = m.group(1) if m else ""
        if "h_total" not in got:
            m = MODE_RE.search(line)
            if m:
                vr, clk, ha, hss, hse, ht, va, vss, vse, vt = (
                    int(x) for x in m.groups())
                got.update({
                    "h_active": ha, "v_active": va,
                    "h_total": ht, "v_total": vt,
                    "hs_start": hss, "hs_end": hse,
                    "vs_start": vss, "vs_end": vse,
                    "pclk_khz": clk, "refresh_hz": float(vr),
                })
        if plane_type == "PRI" and "format" not in got and "hw:" in line:
            m = PLANE_RE.search(line)
            if m:
                fourcc, mod = m.group(1), int(m.group(2), 16)
                got["fourcc"] = fourcc
                if fourcc in FOURCC_TO_PLANECFMT:
                    got["format"] = FOURCC_TO_PLANECFMT[fourcc]
                    got["format_name"] = fourcc
                if mod in MODIFIER_TO_TILING:
                    got["tiling"] = MODIFIER_TO_TILING[mod]
                    got["tiling_name"] = TILING_NAMES[got["tiling"]]
    if "h_active" in got:
        # debugfs does not print the plane stride; derive the driver's own pitch
        got["stride"] = got["h_active"] * 4
        got["stride_derived"] = True
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

def _classify(name: str, data: bytes, texts: dict, edid: list) -> None:
    if len(data) in (128, 256) and data[:8] == b"\x00\xff\xff\xff\xff\xff\xff\x00":
        if not edid:
            edid.append(data)
        return
    if len(data) < 4 * 1024 * 1024:
        texts[name] = data.decode("utf-8", errors="replace")


def read_capture(path: str) -> tuple[dict, bytes | None]:
    """Return (name -> text, edid bytes or None) from an ixcheck dir or tarball.

    Everything is read in memory: tar member names must survive on every OS
    (the first real capture contained a `0000:00:02.0_...` name, which Windows
    cannot write to disk).
    """
    texts: dict = {}
    edid: list = []
    if os.path.isdir(path):
        for root, _dirs, names in os.walk(path):
            for n in names:
                try:
                    with open(os.path.join(root, n), "rb") as f:
                        data = f.read()
                except OSError:
                    continue
                _classify(n, data, texts, edid)
    else:
        with tarfile.open(path) as tf:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                fh = tf.extractfile(m)
                if fh is None:
                    continue
                try:
                    data = fh.read()
                finally:
                    fh.close()
                _classify(os.path.basename(m.name), data, texts, edid)
    return texts, (edid[0] if edid else None)


def pick_display_info(texts: dict) -> tuple[str | None, str | None]:
    candidates = [(n, c) for n, c in sorted(texts.items())
                  if "i915_display_info" in n and "CRTC" in c]
    if not candidates:
        candidates = [(n, c) for n, c in sorted(texts.items())
                      if "i915_display_info" in n]
    if not candidates:
        return None, None
    return candidates[0]


def edid_from_report(path: str) -> bytes | None:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    stack = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            h = cur.get("edid_hex")
            if isinstance(h, str) and h:
                return bytes.fromhex(h.replace(" ", "").replace(":", ""))
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


# ------------------------------------------------------------------ diffing

class Row:
    def __init__(self, label, plan, i915, ixfb, fmt="{}", tol=0, ixfb_tol=None,
                 info_note=None):
        self.label = label
        self.plan = plan
        self.i915 = i915
        self.ixfb = ixfb
        self.fmt = fmt
        self.tol = tol
        self.ixfb_tol = ixfb_tol if ixfb_tol is not None else tol
        self.info_note = info_note
        self.info_active = False

    def _cmp(self, a, b, tol):
        if a is None or b is None:
            return None
        return abs(a - b) <= tol

    def verdict(self):
        eq_915 = self._cmp(self.plan, self.i915, self.tol)
        ref = self.i915 if self.i915 is not None else self.plan
        if eq_915 is False and self.info_note is not None:
            self.info_active = True   # expected-by-design difference
            eq_915 = True
            ref = self.plan           # the i915 value is not the reference here
        eq_fb = self._cmp(ref, self.ixfb, self.ixfb_tol)
        if eq_915 is False:
            return "DIFF(i915)"
        if eq_fb is False:
            return "DIFF(ixfb)"
        if eq_915 is None and eq_fb is None:
            return "n/a"
        return "INFO" if self.info_active else "PASS"

    def show(self, v):
        return "-" if v is None else self.fmt.format(v)


def build_rows(plan: dict, i915: dict, ixfb: dict) -> list[Row]:
    p = plan["mode"]
    stride_reg = int(plan["registers"]["PLANE_STRIDE"]["value"], 16)
    hs0 = p["h_active"] + p["h_sync_offset"]
    hse = hs0 + p["h_sync_width"]
    vs0 = p["v_active"] + p["v_sync_offset"]
    vse = vs0 + p["v_sync_width"]
    return [
        Row("h active", p["h_active"], i915.get("h_active"), ixfb.get("h_active")),
        Row("v active", p["v_active"], i915.get("v_active"), ixfb.get("v_active")),
        Row("h total", p["h_total"], i915.get("h_total"), ixfb.get("h_total")),
        Row("v total", p["v_total"], i915.get("v_total"), ixfb.get("v_total")),
        Row("h sync start", hs0, i915.get("hs_start"), ixfb.get("hs_start")),
        Row("h sync end", hse, i915.get("hs_end"), ixfb.get("hs_end")),
        Row("v sync start", vs0, i915.get("vs_start"), ixfb.get("vs_start")),
        Row("v sync end", vse, i915.get("vs_end"), ixfb.get("vs_end")),
        Row("stride (bytes)", stride_reg * 64, i915.get("stride"), ixfb.get("stride")),
        Row("format code", 8, i915.get("format"), ixfb.get("format")),
        Row("tiling code", 0, i915.get("tiling"), ixfb.get("tiling"),
            info_note="Linux allocates its own X-tiled scanout surface; macOS adopts "
                      "the firmware's linear one - expected, not a discrepancy"),
        Row("pixel clock (kHz)", p["pixel_clock_khz"], i915.get("pclk_khz"),
            ixfb.get("pclk_khz"), tol=0, ixfb_tol=2000),
        Row("refresh (Hz)", p["refresh_hz"], i915.get("refresh_hz"),
            ixfb.get("refresh_hz"), fmt="{:.2f}", tol=0.51, ixfb_tol=1.5),
    ]


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
    src.add_argument("--edid", help="raw EDID file (when the capture has none)")
    src.add_argument("--edid-hex", help="EDID as a hex string")
    src.add_argument("--report", help="IrisProbe report JSON (takes its edid_hex)")
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
    elif args.report:
        edid = edid_from_report(args.report)
        if edid is None:
            print(f"no edid_hex found in {args.report}", file=sys.stderr)
            return 2

    if edid is None:
        print("no EDID available (the capture has none inside: give --edid, "
              "--edid-hex or --report)", file=sys.stderr)
        return 2

    ixplan = load_ixplan()
    try:
        plan = ixplan.plan(ixplan.parse_edid(edid))
    except ValueError as ex:
        print(f"EDID problem: {ex}", file=sys.stderr)
        return 2
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

    notes = []
    if i915.get("stride_derived"):
        notes.append("* i915 stride is derived (width x 4): this kernel's debugfs does "
                     "not print the plane stride.")
    for r in rows:
        if r.info_active:
            notes.append(f"* {r.label} INFO: {r.info_note}")
    if notes:
        print("notes:")
        for n in notes:
            print("  " + n)
    print()

    if diffs:
        print(f"verdict: {diffs} field(s) differ")
        return 1 if args.strict else 0
    print("verdict: all compared fields agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
