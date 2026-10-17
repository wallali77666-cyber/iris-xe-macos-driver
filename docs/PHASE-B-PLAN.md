# Phase B — execution plan

Order matters: every step is verifiable before the next one starts, and everything that
can run without a Mac runs on Windows or in GitHub's cloud macOS runners first.

## B1 — Scaffold live on GitHub, CI green ✅ (this commit)

All four kexts (`IXFB`, `IXRM`, `IXAccel`, `IXAGDC`), the plugin stub, build scripts and
the sniffer build/run in GitHub Actions on every push. Success = green badge + downloadable
`iris-xe-build` artifact containing the `.kext` bundles.

## B2 — Tools that run anywhere (Windows, no Mac needed) ← next

The display values `IXFB` will need, computed and testable **here**, before any Mac exists:

- `tools/ixplan/` — EDID → Gen12 display register plan:
  - transcoder timings (HTOTAL/HBLANK/HSYNC/VTOTAL/VBLANK/VSYNC @ 0x60000 + T*0x1000)
  - `PIPESRC`, plane stride (64-byte aligned), linear XRGB format
  - built from Linux `i915` display register formulas (MIT); every formula documented
  - validated against the reference machine's real panel (AUO B140HAK, 1920×1080 @ 60.05)
- `tools/ixcheck/` (later, needs Linux) — compares the plan against MMIO traces recorded
  from the same laptop running Linux (live USB), the way NullMoth's `igfx_check.py`
  validates their planner against recorded i915 writes. **No register formula is trusted
  until a real machine agrees with it.**

## B3 — IXFB: real Phase-1 display takeover

- map BAR0 (MMIO) + BAR2 (graphics aperture)
- scan pipes 0-3 for the pipe whose primary plane is enabled and linear-XRGB (the mode
  firmware already lit)
- cross-check live timings against the EDID IrisProbe recorded
- move `com_irisxe_IXFB` onto `IOFramebuffer` (add `IOMatchCategory=IOFramebuffer`),
  publish the surface; decline with full logging on anything unexpected
- success = panel keeps its exact current picture but is now owned by our driver
  (verifiable in `ioreg`), with correct size/refresh reported

## B4 — IXRM: first real hardware probe

- map BAR0/BAR2, read the GPU's identification registers (GMD_ID on Gen12), check for
  GuC/HuC firmware presence on disk; log-only, still declining
- success = `IXRM: GMD_ID ... / firmware ...` lines in `dmesg` on the target

## B5 — Plugin + translator

Stay stubs until B3/B4 exist; their contract work is Phase D (Metal objects on ANV,
AIR → SPIR-V). Building them early would be fake progress.

## Rules

- No NullMoth code is copied (their license: PolyForm Noncommercial — study/reference
  only). We mirror the *method*, write our own code.
- Whatever runs on the cloud (CI) runs there; the laptop only pushes/pulls text.
- Before any big download, the size is reported first.
- Nothing touches a real Mac's display engine until the plan is validated against
  recorded traces (B2).
