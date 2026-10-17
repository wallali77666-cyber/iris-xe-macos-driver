# iris-xe-macos-driver

[![build](https://github.com/wallali77666-cyber/iris-xe-macos-driver/actions/workflows/build.yml/badge.svg)](https://github.com/wallali77666-cyber/iris-xe-macos-driver/actions/workflows/build.yml)

Native macOS support project for **Intel Iris Xe (Tiger Lake, Gen12)** integrated graphics,
modeled after [NullMoth's NVIDIA driver](https://github.com/nullmoth/nvidia-macos-driver)
architecture (study clone kept at `../nvidia-macos-driver`).

Target machine: **Dell Latitude 5420 — Intel Core i5-1145G7, Iris Xe Graphics (PCI `8086:9A49`)**.

This is an independent, non-commercial research project. It is **not affiliated with NullMoth
Systems**, and reuses no NullMoth trademarks. Their public source is studied as a reference for
architecture only (PolyForm Noncommercial 1.0.0 — personal/research/educational use allowed;
their `translator/` is LGPL-3.0 as it derives from metal2vulkan).

## Status

| Phase | What | State |
|---|---|---|
| A | **IrisProbe** — hardware sniffer + laptop OpenCore plist generator | ✅ built, run on target |
| B | Driver scaffold mirroring NullMoth: kexts / Metal plugin / translator / ANV back end | 🟨 scaffolded: `kexts/` IXFB+IXRM+IXAccel+IXAGDC, `plugin/` stub, `build/`, `package/`, CI |
| C | Bring-up tooling on macOS (EDID→register planner, MMIO tracing, display Phase-1 takeover) | 🟨 OpenCore EFI assembles + validates in CI (`docs/PHASE-C-OPENCORE.md`); hardware boot pending |
| D | Metal acceleration (AIR→SPIR-V → Mesa ANV → new Intel kernel driver) | ⬜ research |

## Layout

```
tools/irisprobe/     hardware sniffer (Python, stdlib only, runs on Windows)
tools/ixplan/        EDID -> display register plan (validated against i915)
tools/efi/           assembles the ready OpenCore EFI from the latest releases (CI)
efi/                 OpenCore EFI sources (SSDT .dsl; the zip lives in CI artifacts)
reports/             sniffer output (git-ignored): report + plist + notes
kexts/               IXFB (framebuffer), IXRM (resource manager), IXAccel, IXAGDC
plugin/IXMTLDriver/  the Metal driver bundle (stub until Phase D)
translator/          Apple AIR → SPIR-V (LGPL boundary, no code yet)
build/               build scripts (run by CI on macOS runners)
package/             install.sh / uninstall.sh for the target machine
docs/ROADMAP.md      the full plan, mirroring NullMoth's stack onto Intel Gen12
.github/workflows/   CI: builds everything on GitHub's macOS machines
```

## Run the sniffer

```powershell
python tools\irisprobe\irisprobe.py
```

Writes, for the machine it runs on:

- `reports/irisprobe-report.json` — everything sniffed, machine-readable
- `reports/irisprobe-report.txt` — human-readable summary
- `reports/iris-config.plist` — OpenCore fragment (`DeviceProperties` + `NVRAM/boot-args`)
- `reports/iris-config-notes.md` — how to merge it, BIOS settings, macOS status per component
