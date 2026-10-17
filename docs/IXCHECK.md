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

**Carrier options (getting the script in, the tarball out):** a second plain FAT32
USB stick is the simplest. With no spare stick, a small FAT32 partition on the
internal disk works the same way: Windows -> Disk Management -> shrink a volume by
~1 GB -> "New Simple Volume", **FAT32**, label it `SHARE`; Kali auto-mounts it
under `/media/kali/SHARE`. The tarball is only a few hundred KB. Do *not* write into
the Windows system partition from Linux instead - fast startup/hibernation makes
that the one route that can actually corrupt something. And leave the existing EFI
system partition alone until install day.

## What the capture contains (all read-only)

| file | why |
|---|---|
| `*_i915_display_info.txt` | mode, crtc timings, stride, format, tiling of the lit pipe |
| `edid_*.bin` | the exact panel EDID ixplan plans from |
| `*_i915_edp_psr_status.txt` etc. | bonus state, ignored by the v1 comparator |
| `*_i915_gem_objects/engine_info/guc_info.txt` | GT baseline (objects → GGTT offsets) — Phase D ground truth for IXRM, ignored by the v1 comparator |
| `lspci-igpu.txt`, `dmesg*.txt`, `uname.txt` | machine + driver context for the report |
| `intel_reg_dump.txt` | full MMIO dump, only if igt-gpu-tools happens to be installed |

## Reading the verdicts

- `PASS` — every source that has the field agrees
- `INFO` — an expected-by-design difference (explained in the notes under the
  table; never fails the run)
- `DIFF(i915)` — the computed plan disagrees with what the Linux driver actually
  programmed → either a real ixplan bug, or the live session picked a different
  mode (the table shows both)
- `DIFF(ixfb)` — the macOS register readback disagrees with the other source(s)
- `-` — that source did not provide the field (e.g. no IXFB log yet)

Tolerances apply only to *measured* values: IXFB's pixel clock ±2 MHz, refresh
±1.5 Hz. i915 values are exact.

## The i915 column, exactly (from the first real capture, 2026-10-17)

The parser is written against kernel 6.12's actual `i915_display_info`, verified
by the first live capture on the target Latitude 5420: the active CRTC's
`uapi ... mode=` line carries clock/totals/hsync/vsync directly, and the active
primary plane's `hw: [FB..]` line carries the DRM fourcc (`XR24` = XRGB8888)
and format modifier. Two fields are special by design:

- **stride** — debugfs does not print it; the i915 value is derived as
  width × 4 (the driver's own pitch for this mode) and marked as such in the
  notes under the table.
- **tiling** — Linux allocates its own X-tiled scanout surface; macOS adopts the
  firmware's linear one, so a tiled i915 value shows as `INFO`, not a DIFF. The
  IXFB-vs-plan comparison stays strict.

If a field ever shows "not found", the raw file is already in the tarball — one
more pattern and it is parsed; no data is lost.

## Regression guard

`tools/ixcheck/test_compare.py` runs in CI on every push: it builds a synthetic
EDID + i915 capture + IXFB log that agree, proves compare passes, then proves a
wrong stride fails the run. This permanently locks in the PLANE_STRIDE fix
(64-byte units → 0x78 for a 1920-wide panel).
