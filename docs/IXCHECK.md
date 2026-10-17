# ixcheck — tying the three sources together (never guess register values)

Every display register value in this project must survive three-way agreement:

```
EDID ──► ixplan            (computed from i915 source / MIT headers)
          ↕ compare
         i915              (the real Linux driver's runtime state — ground truth)
          ↕ compare
         IXFB              (our macOS takeover, reading the firmware-lit pipe)
```

`tools/ixcheck/compare.py` diffs all three per field and prints one table with
PASS / DIFF per row. `tools/ixcheck/ixcheck.sh` produces the i915 side.

## How a capture session goes (later, when you choose)

1. Boot the Latitude 5420 from a **Linux live USB** (no install — nothing is
   written to the disk; the internal panel is already lit by i915/fbcon at boot).
   Any distro works — Fedora, Ubuntu, or a Kali/Debian live image.
2. Put `tools/ixcheck/ixcheck.sh` on any FAT32 stick, open a terminal, run:

   ```
   sudo bash ixcheck.sh --out /media/<you>/<STICK>/ixcheck
   ```

   The script is read-only: it copies debugfs/sysfs text and the panel EDID into
   one tarball (a few hundred KB).
3. Back on Windows, run:

   ```
   python tools\ixcheck\compare.py --capture ixcheck-<host>-<date>.tar.gz --strict
   ```

   (`--ixfb-log <file>` adds the macOS column once the system is installed; on
   macOS produce that file with
   `log show --last boot --predicate 'eventMessage CONTAINS "IXFB:"' > ixfb.log`.)

**Download sizes, checked before anything is pulled:** if you don't already have
a live image — Fedora Workstation ≈ 2.5 GB, Ubuntu Desktop ≈ 6 GB, Kali ≈ 4 GB.
Your choice; nothing happens until you say go.

## What the capture contains (all read-only)

| file | why |
|---|---|
| `*_i915_display_info.txt` | mode, crtc timings, stride, format, tiling of the lit pipe |
| `edid_*.bin` | the exact panel EDID ixplan plans from |
| `*_i915_edp_psr_status.txt` etc. | bonus state, ignored by the v1 comparator |
| `lspci-igpu.txt`, `dmesg*.txt`, `uname.txt` | machine + driver context for the report |
| `intel_reg_dump.txt` | full MMIO dump, only if igt-gpu-tools happens to be installed |

## Reading the verdicts

- `PASS` — every source that has the field agrees
- `DIFF(i915)` — the computed plan disagrees with what the Linux driver actually
  programmed → either a real ixplan bug, or the live session picked a different
  mode (the table shows both)
- `DIFF(ixfb)` — the macOS register readback disagrees with the other source(s)
- `-` — that source did not provide the field (e.g. no IXFB log yet)

Tolerances apply only to *measured* values: IXFB's pixel clock ±2 MHz, refresh
±1.5 Hz. i915 values are exact.

## When a field shows "not found"

The i915 parser scans for stable markers (`crtc timings:`, `pipe src size:`,
`crtc clock:`, `stride`, `format`, `tiling`) rather than a rigid layout, so it
survives most kernel wording changes. If something still isn't found, the raw
capture is already in the tarball — send it and one more pattern is added; no
data is lost.

## Regression guard

`tools/ixcheck/test_compare.py` runs in CI on every push: it builds a synthetic
EDID + i915 capture + IXFB log that agree, proves compare passes, then proves a
wrong stride fails the run. This permanently locks in the PLANE_STRIDE fix
(64-byte units → 0x78 for a 1920-wide panel).
