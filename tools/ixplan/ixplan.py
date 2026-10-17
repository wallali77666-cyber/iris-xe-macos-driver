#!/usr/bin/env python3
"""ixplan — EDID -> Intel Gen12 (display v12, Tiger Lake) display register plan.

Computes the transcoder / pipe / plane register values for a panel's preferred mode,
the way Linux's i915 display code programs them (register map and formulas from the
MIT-licensed i915 display headers and source).

Confidence rules (honest by design):
  - Deterministic encodings are computed here: HTOTAL/HBLANK/HSYNC/VTOTAL/VBLANK/VSYNC,
    PIPESRC, PLANE_SIZE, PLANE_STRIDE.
  - Values that depend on runtime state or recorded behavior are NOT guessed:
    PLANE_CTL (format/enable bits), PLANE_SURF (address). They are read from the live
    machine by IXFB Phase 1 and validated against MMIO traces (tools/ixcheck) before
    anything writes to hardware.

usage:
  ixplan.py --report ../../reports/irisprobe-report.json     # internal panel from IrisProbe
  ixplan.py --edid panel.edid                                # raw 128-byte EDID file
  ixplan.py --edid-hex 00FFFFFFFFFFFF00...                   # EDID as hex string
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REPORTS = os.path.join(ROOT, "reports")


def parse_edid(b: bytes) -> dict:
    """Base-block EDID parse, preferred timing = first detailed timing descriptor."""
    if len(b) < 128 or b[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        raise ValueError("not an EDID base block")
    mfg = (b[8] << 8) | b[9]
    vendor = "".join(chr(((mfg >> off) & 0x1F) + 64) for off in (10, 5, 0))
    d = b[54:72]
    name = None
    for i in range(54, 126, 18):
        desc = b[i:i + 18]
        if desc[0:3] == b"\x00\x00\x00" and desc[3] in (0xFC, 0xFE):
            txt = "".join(chr(c) if 32 <= c < 127 else " " for c in desc[5:18])
            txt = " ".join(txt.split())
            if txt and not name:
                name = txt
    return {
        "vendor": vendor,
        "product_code": (b[11] << 8) | b[10],
        "name": name,
        "pclk_khz": ((d[1] << 8) | d[0]) * 10,
        "hactive": d[2] | ((d[4] & 0xF0) << 4),
        "hblank": d[3] | ((d[4] & 0x0F) << 8),
        "vactive": d[5] | ((d[7] & 0xF0) << 4),
        "vblank": d[6] | ((d[7] & 0x0F) << 8),
        "hso": d[8] | ((d[11] & 0xC0) << 2),
        "hsw": d[9] | ((d[11] & 0x30) << 4),
        "vso": (d[10] >> 4) | ((d[11] & 0x0C) << 2),
        "vsw": (d[10] & 0x0F) | ((d[11] & 0x03) << 4),
    }


def align64(v: int) -> int:
    return (v + 63) & ~63


def plan(m: dict) -> dict:
    hactive, hblank = m["hactive"], m["hblank"]
    vactive, vblank = m["vactive"], m["vblank"]
    htotal, vtotal = hactive + hblank, vactive + vblank
    hsync_s, hsync_e = hactive + m["hso"], hactive + m["hso"] + m["hsw"]
    vsync_s, vsync_e = vactive + m["vso"], vactive + m["vso"] + m["vsw"]
    refresh = round(m["pclk_khz"] * 1000 / (htotal * vtotal), 3)

    def reg(v: int) -> str:
        return f"0x{v:08X}"

    regs = {
        # transcoder 0 timing block: 0x60000 + 0x1000 per transcoder
        "HTOTAL":      {"off": "0x60000", "value": reg(((htotal - 1) << 16) | (hactive - 1)), "what": "h total / h active"},
        "HBLANK":      {"off": "0x60004", "value": reg(((htotal - 1) << 16) | (hactive - 1)), "what": "h blank end / start"},
        "HSYNC":       {"off": "0x60008", "value": reg(((hsync_e - 1) << 16) | (hsync_s - 1)), "what": "h sync end / start"},
        "VTOTAL":      {"off": "0x6000C", "value": reg(((vtotal - 1) << 16) | (vactive - 1)), "what": "v total / v active"},
        "VBLANK":      {"off": "0x60010", "value": reg(((vtotal - 1) << 16) | (vactive - 1)), "what": "v blank end / start"},
        "VSYNC":       {"off": "0x60014", "value": reg(((vsync_e - 1) << 16) | (vsync_s - 1)), "what": "v sync end / start"},
        "PIPESRC":     {"off": "0x6001C", "value": reg(((hactive - 1) << 16) | (vactive - 1)), "what": "pipe source size"},
        # plan block: 0x70180 + 0x1000 per pipe (pipe 0 here; the lit pipe is found at runtime)
        # PLANE_STRIDE counts 64-byte units on a linear surface (i915 writes stride / 64)
        "PLANE_STRIDE": {"off": "0x70188", "value": reg(align64(hactive * 4) // 64), "what": "linear stride in 64-byte units"},
        "PLANE_SIZE":   {"off": "0x70190", "value": reg(((hactive - 1) << 16) | (vactive - 1)), "what": "plane source size (1:1)"},
    }
    warn = []
    if hsync_e > htotal:
        warn.append("h sync end past h total")
    if vsync_e > vtotal:
        warn.append("v sync end past v total")
    for k, v in {"hso/hsw": (m["hso"], m["hsw"]), "vso/vsw": (m["vso"], m["vsw"])}.items():
        if v[0] <= 0 or v[1] <= 0:
            warn.append(f"suspicious sync geometry {k}={v}")
    return {
        "panel": {"name": m.get("name"), "vendor": m["vendor"], "product_code": f"0x{m['product_code']:04X}"},
        "mode": {
            "h_active": hactive, "h_blank": hblank, "h_sync_offset": m["hso"], "h_sync_width": m["hsw"],
            "v_active": vactive, "v_blank": vblank, "v_sync_offset": m["vso"], "v_sync_width": m["vsw"],
            "h_total": htotal, "v_total": vtotal,
            "pixel_clock_khz": m["pclk_khz"], "refresh_hz": refresh,
        },
        "registers": regs,
        "deferred": {
            "PLANE_CTL": "read from the lit pipe at runtime (IXFB Phase 1); format/enable bit positions validated from MMIO traces before any write",
            "PLANE_SURF": "surface address comes from the live allocation (aperture + plane GGTT offset), set at runtime",
            "TRANSCODER": "planned for transcoder 0 / pipe 0; IXFB detects the actually lit one",
            "eDP_LINK": "link rate/lane programming is Phase 2 (mode set), not part of Phase 1 takeover",
        },
        "warnings": warn,
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="EDID -> Gen12 display register plan")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--report", help="IrisProbe report JSON (uses the internal panel)")
    src.add_argument("--edid", help="raw 128-byte EDID file")
    src.add_argument("--edid-hex", help="EDID as a hex string")
    ap.add_argument("--out", help="write plan JSON here (default: reports/ixplan.json)")
    args = ap.parse_args()

    if args.report:
        with open(args.report, encoding="utf-8") as f:
            data = json.load(f)
        panel = None
        for m in data.get("monitors", []):
            if m.get("edid_hex"):
                panel = m
                if m.get("internal"):
                    break
        if not panel:
            print("no monitor with EDID in the report (rerun irisprobe on the target)", file=sys.stderr)
            return 2
        edid = bytes.fromhex(panel["edid_hex"])
    elif args.edid:
        with open(args.edid, "rb") as f:
            edid = f.read()
    else:
        edid = bytes.fromhex(args.edid_hex.replace(" ", ""))

    m = parse_edid(edid)
    p = plan(m)

    mode = p["mode"]
    print(f"panel  {p['panel']['name']} ({p['panel']['vendor']} {p['panel']['product_code']})")
    print(f"mode   {mode['h_active']}x{mode['v_active']} @ {mode['refresh_hz']} Hz  "
          f"pclk {mode['pixel_clock_khz'] / 1000:.2f} MHz  "
          f"h {mode['h_active']}+{mode['h_blank']}  v {mode['v_active']}+{mode['v_blank']}  "
          f"hs {mode['h_sync_offset']}+{mode['h_sync_width']}  vs {mode['v_sync_offset']}+{mode['v_sync_width']}")
    print()
    print("registers (transcoder 0 / pipe 0 — the lit one is detected at runtime):")
    for k, v in p["registers"].items():
        print(f"  {k:<13} {v['off']}  {v['value']}   {v['what']}")
    print()
    print("deferred (validated at runtime / against traces, never guessed):")
    for k, v in p["deferred"].items():
        print(f"  {k:<13} {v}")
    for w in p["warnings"]:
        print(f"warning: {w}")

    out = args.out or os.path.join(REPORTS, "ixplan.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
