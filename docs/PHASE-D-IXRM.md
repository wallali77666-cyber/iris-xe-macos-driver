# Phase D — IXRM: the acceleration stack, built the NullMoth way

Status: **started (2026-10-17)**. Facts pipeline (`tools/ixgen`) is live in CI,
the GT-side baseline capture is in `ixcheck.sh`, and the first IXRM code —
the read-only GGTT walker — is the next commit. This document is the plan of
record for everything between "display works" (Phase C) and "Metal on Iris Xe".

## The chain we are rebuilding

NullMoth's (from their `docs/HOW-IT-WORKS.md`):

```
Metal app → NVMTLDriver.bundle → translator (AIR→SPIR-V) → NVK (Mesa) → NVRM.kext → GPU
```

Ours, same shape, Intel surface:

```
Metal app → IXMTLDriver.bundle → translator (AIR→SPIR-V) → ANV (Mesa) → IXRM.kext → Iris Xe
```

The difference that defines this whole project: NVIDIA **published open kernel
modules** — NVRM could be ported. Intel never did: `i915`/`xe` are Linux-only.
IXRM is therefore **written from open-source facts**, not ported — and that is
why Phase D is staged with an exit exam per stage, and why every hardware fact
is pinned before any code uses it.

## Ground rules (unchanged, non-negotiable)

1. **No guessed values.** Registers, encodings and firmware interfaces come
   from pinned sources: `tools/ixgen` (i915, pinned to **v6.12** — the exact
   kernel of the first real capture) now; ANV/Mesa for the userspace side
   later. The CI log + artifact is the audit trail.
2. **Read before write.** A stage that programs hardware first ships a
   read-only tool for it, validated against a Linux capture from *this*
   machine (the ixcheck method that already validated B2).
3. **All heavy builds in CI.** The macOS runner compiles; the laptop only
   boots and captures. Every download is sized before it starts.
4. **Honest odds.** Each stage is falsifiable and has a stop condition.

## Stage map

| # | Stage | NullMoth mirror | Exit exam |
|---|---|---|---|
| D0 | **Facts pipeline** — `tools/ixgen`: pinned i915 fetch + extraction in CI (`ixgen-linux` job) | their `tools/igfx/*.py` validated against recorded traces | green run with GGTT window, PTE encode and flag facts extracted (log + artifact) |
| D1 | **Memory skeleton** — map BAR0, locate the GGTT window from D0 facts, read GGTT entries read-only from the IXRM probe | `nvrm_gpuva.cpp`, VRAM/GGTT in NVRM | IXRM log shows the boot framebuffer's GGTT entries; values consistent with Linux's `i915_gem_objects` capture of the same machine |
| D2 | **Allocation + scanout** — reserve + clear a framebuffer via our own GGTT entries; IXFB phase 2 presents it | `NVRMFB.kext` | panel lit from an IXRM-allocated framebuffer under macOS |
| D3 | **Firmware + submission** — HuC/GuC load, command ring, one context; a no-op batch completes | NVRM submission bits, `os-nvkms-xnu.cpp` | GPU reports the batch done; engine state compared to the `i915_engine_info` capture |
| D4 | **User-space bridge** — IOUserClient ABI + libdrm-free shim; ABI doc | `nv-xnu.h` OS layer | a userland test tool talks to IXRM through the client |
| D5 | **ANV port** — `anv-macos.patch` mirroring `nvk-macos.patch` | `nvk/` | `vulkaninfo` lists the Iris Xe under macOS |
| D6 | **Translator + Metal plugin** — `IXMTLDriver.bundle` on ANV; then WindowServer (`IXAccel`/`IXAGDC`) | `translator/`, `NVMTL*.m` | trivial Metal triangle renders; then composited desktop |

Tiered honesty, unchanged from day one: **display = done-provable** (Phase C),
**Vulkan compute on our own driver = plausible research**, **full Metal +
WindowServer = the mountain**. No stage promises the next one.

## D0 in detail (this week, landed)

`tools/ixgen/fetch_i915.sh` (CI job `ixgen-linux`) fetches a candidate list of
pinned i915 files and extracts, into `i915-ref/extract.txt` + the job log:

- **Section 1 — GGTT window:** where the page-table array lives inside BAR0
  (`gtt_base`/`gtt_offset`/`0x800000` candidates, probe functions in
  `intel_ggtt.c`). This answers the one question D1 cannot start without.
- **Section 2 — PTE encoding:** the `gen8_pte_encode` body (address + flag
  bits) and definitions (`_PAGE_PRESENT`, `_PAGE_RW`, `PPAT_*`,
  `GEN12_PPGTT_PTE*`). These become constants in IXRM **with the extract as
  reference**, never typed from memory.
- **Section 3 — structures:** `struct i915_ggtt` layout and the PTE
  read/write helpers.

`MISS` lines are information: the kernel tree moves files between releases; the
script prints the directory listing so each move is one small script edit, not
a mystery. When a stage needs new facts (GuC interfaces for D3, etc.), the file
list grows in the same pattern.

## D1 in detail (next code)

1. Read the D0 extract; write `ixrm_mmio.h` (constants + provenance comments
   pointing at file+section of the extract).
2. Extend the IXRM probe: after the existing read-only probe, locate the GGTT
   window and walk the first entries; log `IXRM: ggtt[%u] = 0x%016llx`.
3. Actually locate the boot framebuffer in the GGTT (its physical address is
   already known to IXFB from the firmware state) and print its entries.
4. Validation, both sides of the same machine:
   - Linux side: the new `3b` section of `ixcheck.sh` captures
     `i915_gem_objects` (object → GGTT offset/size) for the next live session.
   - macOS side: the `IXRM: ggtt[...]` lines from the installed system.
   - A small `tools/ixgen`-style checker compares them the way
     `compare.py` does for display (PASS/DIFF per entry), once both sides
     exist. Until then the raw values are just logged — nothing is written
     to hardware, so nothing can be harmed by a wrong guess, and no guess is
     made anyway.

## Current sprint

- [x] `tools/ixgen/fetch_i915.sh` + `ixgen-linux` CI job (pinned v6.12)
- [x] GT baseline added to `ixcheck.sh` (`i915_gem_objects`, `i915_engine_info`, `i915_guc_info`)
- [ ] `ixrm_mmio.h` + read-only GGTT walk in the IXRM probe — **next**
- [ ] Linux GT capture on the laptop (optional now; needed to finish D1's exam)
- [ ] D1 checker once both sides have data

Sizes for later, so nobody is surprised (all CI-side unless noted): Mesa
source ~1.5–2 GB in CI when D5 starts; TGL GuC/HuC blobs from linux-firmware
are a few hundred KB — reported first when that step arrives. Nothing on your
side downloads anything without the number being said out loud first.
