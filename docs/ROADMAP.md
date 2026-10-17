# Roadmap — Iris Xe (Gen12) macOS driver, NullMoth-style

The NullMoth NVIDIA driver works because of this chain (from their `docs/HOW-IT-WORKS.md`):

```
Metal app ─► NVMTLDriver.bundle ─► translator (Apple AIR → SPIR-V) ─► NVK (Mesa Vulkan) ─► NVRM.kext ─► GPU
```

Everything in it is reusable *as a pattern* for Intel. The reason it worked at all for NVIDIA:
NVIDIA **publishes open GPU kernel modules** (r610), which NullMoth ported to XNU under macOS.
**Intel has no such thing** — `i915`/`xe` are Linux-only. That is the critical gap, and why this
project is honest about being long-horizon research, not a weekend port.

## Phase A — IrisProbe: hardware sniffer + plist (done)

`tools/irisprobe/irisprobe.py` reads the target laptop (the way NullMoth's `1401-probe` reads a
PC) and produces:

- the machine report (CPU, PCI tree, iGPU `8086:9A49`, EDID of the internal panel, storage, Wi-Fi, audio, battery)
- `iris-config.plist` — OpenCore fragment with `DeviceProperties` for the iGPU and boot-args
- notes: BIOS settings for a Latitude 5420, and the per-component macOS reality table

This mirrors how their `tools/igfx/*.py` consume machine data: EDID → display register plans,
validated against recorded i915 MMIO traces.

## Phase B — Driver components (mirror of NullMoth, mapped to Intel)

| NullMoth (NVIDIA) | Ours (Intel Gen12) | Notes |
|---|---|---|
| `NVMTLDriver.bundle` (Metal on Vulkan, `nvmtl_vk.c`) | `IXMTLDriver.bundle` (Metal on Vulkan, `ixmtl_vk.c`) | same contracts: sample positions, samplers, argument buffers, physical bounds |
| `translator/` (AIR→SPIR-V, from metal2vulkan, LGPL-3.0) | reuse/port the same translator | LGPL compliance; this part is hardware-agnostic |
| `nvk/` — Mesa NVK + NAK, patched for macOS (`nvk-macos.patch` on Mesa `17ca6174`) | **Mesa ANV** (Intel Vulkan) patched for macOS | ANV supports Tiger Lake (Gen12LP) upstream |
| `NVRM.kext` — NVIDIA open kernel modules ported to XNU | `IXRM.kext` — **does not exist yet**; someone must port/write an Intel GPU kernel driver (GuC firmware, GGTT/PPGTT, command submission, power) | **the hard part**; Linux `i915`/`xe` is MIT, but very large |
| `NVRMFB.kext` — display framebuffer | `IXFB.kext` — we start from NullMoth's `NMIntelFB` Phase 1 (take over the firmware-lit pipe for display v12 = Tiger Lake), then add real mode-setting via the EDID→register planner | register layout from Linux `i915` display headers (MIT) |
| `NVAccel.kext` — `IOAccelerator` for WindowServer | `IXAccel.kext` | surface/compositing path |
| `NVRMAGDC.kext` — graphics device control policy | `IXAGDC.kext` | policy queries |
| `gatekeeper`-style install (`package/install.sh`, kmutil KC, OpenCore wiring) | same shape: boot-args `iris=1 irisfb=1 irisaccel=1`, `csr-active-config`, `/Library/Extensions`, auxiliary KC | unchanged method |

**Status (2026-10-17):** B1 scaffold, B2 `ixplan` (PLANE_STRIDE corrected to 64-byte
units per i915), B3 IXFB Phase-1 takeover and B4 IXRM probe are implemented and build
green in GitHub Actions; each step's hardware verification lands with Phase C.
The Phase C prerequisite — the OpenCore EFI (OpenCore + kexts + our IXFB/IXRM,
config generated from the release's own Sample.plist and ocvalidate-checked) —
is now assembled by the `efi` workflow: see `docs/PHASE-C-OPENCORE.md`.

## Phase C — Bring-up on the target laptop

0. Get the CI-built EFI (`iris-xe-efi` artifact), put it on a USB with a macOS
   Recovery image — full steps, sizes and BIOS table in `docs/PHASE-C-OPENCORE.md`.
1. Boot macOS Sequoia via OpenCore on the Latitude 5420 (no iGPU driver: display comes from
   the firmware framebuffer path until IXFB claims the pipe; expect a very slow, unaccelerated desktop).
2. Build `IXFB` Phase 1 (firmware-lit pipe takeover, like `NMIntelFB`) → internal panel shows a
   real `IOFramebuffer` with correct size/refresh.
3. Bring the `igfx`-style planner over: EDID → transcoder/pipe/plane register values, validated
   against Linux `i915` traces recorded from this exact machine.
4. Phase 2 display: actually program modes (backlight dimming, DP link training for eDP).

## Phase D — Acceleration (the research mountain)

1. Kernel driver (`IXRM`): the minimum Intel GPU services ANV needs — VRAM/GGTT management,
   ring/command submission, GuC/HuC firmware upload, power states. Scoped against what
   NullMoth's OS layer had to implement for `NVRM` on XNU (`os-xnu*.cpp` equivalents).
2. ANV port: new `anv-macos.patch` mirroring `nvk-macos.patch` (replace `libdrm`/`i915`
   ioctls with an `IXRM` interface).
3. Metal plugin: `IXMTLDriver.bundle` implementing Metal objects on Vulkan/ANV.
4. WindowServer integration: `IXAccel` + `IXAGDC` + correct `IOFramebuffer` handoff so the
   composited desktop lands on the panel.

## Rules kept from day one

- No NullMoth trademarks; independent name and identity.
- Study their code; write ours. Where code is reused verbatim, honor its license
  (PolyForm NC for `plugin/ kexts/ build/ package/`, LGPL-3.0 for `translator/`, MIT for the
  Mesa patches) and never commercialize.
- Before any big download (e.g. a Mesa clone is ~1.5–2 GB), the size is reported first.
