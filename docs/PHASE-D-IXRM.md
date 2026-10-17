# Phase D — IXRM: the acceleration stack, built the NullMoth way

Status: **started (2026-10-17)**. Facts pipeline (`tools/ixgen`) is live in CI,
the GT-side baseline capture is in `ixcheck.sh`, and the first IXRM code — the
read-only GGTT walker (`kexts/IXRM/ixrm_mmio.h` + the `ggtt:` walk in the probe)
— has landed. This document is the plan of record for everything between
"display works" (Phase C) and "Metal on Iris Xe".

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

## D1 — the read-only GGTT walk (code landed 2026-10-17; hardware run pending)

What the pinned extract settled (v6.12; the file:line table lives in
`kexts/IXRM/ixrm_mmio.h`):

- the GGTT page-table array sits in **BAR0 at +0x800000** on gen>=8 — i915
  computes `phys_addr = BAR0_start + gen6_gttmmadr_size()/2`, and the code's own
  comment says "GTTADR starts at 8MB offset";
- entries are 8-byte `gen8_pte_t`, one per 4 KiB page, indexed by
  `offset / I915_GTT_PAGE_SIZE`;
- Tiger Lake's GGTT encoder is `gen8_ggtt_pte_encode` (the `gen12 < 12.70`
  choice): `pte = addr | GEN8_PAGE_PRESENT` — no RW bit, no PAT on the GGTT;
- the address field to decode with is `GENMASK_ULL(45, 12)`
  (`GEN12_GGTT_PTE_ADDR_MASK`).

The probe (`ixrmWalkGgtt`) walks the window read-only: first 16 entries
verbatim, then every present entry (first 48) with its decoded address, then a
count. Nothing is written anywhere — the walk feeds the D1 exit exam, which
needs both sides of the same machine:

- Linux side: `ixcheck.sh`'s `3b` section captures `i915_gem_objects`
  (object → GGTT offset/size) on the next live session;
- macOS side: the `IXRM: ggtt...` lines from the installed system;
- then a small checker (like `compare.py`) diffs the two — that PASS/DIFF table
  becomes the permanent regression guard for IXRM's memory code.

Until the comparison runs, raw values are all the walker claims; a zero-present
scan is treated as "the window fact must be re-checked", never as success.

The window-location fact itself no longer rests on inference: the BAR-vs-GSMBASE
branch is pinned too (`i915_direct_stolen_access()` is MTL-only —
`i915_utils.c:89-103`, Wa_22018444074), so Tiger Lake reads the window at
`BAR0 + gen6_gttadr_offset()`, the exact bytes the walker walks. The D2 table
size decode is also pinned now (`include/drm/intel/i915_drm.h:49-55` +
`gt/intel_ggtt.c:1107-1121`; constants in `ixrm_mmio.h`).

## Current sprint

- [x] `tools/ixgen/fetch_i915.sh` + `ixgen-linux` CI job (pinned v6.12; v4 adds the GMCH/GGMS size decode for D2)
- [x] GT baseline added to `ixcheck.sh` (`i915_gem_objects`, `i915_engine_info`, `i915_guc_info`)
- [x] `ixrm_mmio.h` + read-only GGTT walk in the IXRM probe (D1 code)
- [ ] First macOS boot → read the `IXRM: ggtt...` lines (needs the Phase C install)
- [ ] Linux GT capture on the laptop + the D1 checker (once both sides exist)

Sizes for later, so nobody is surprised (all CI-side unless noted): Mesa
source ~1.5–2 GB in CI when D5 starts; TGL GuC/HuC blobs from linux-firmware
are a few hundred KB — reported first when that step arrives. Nothing on your
side downloads anything without the number being said out loud first.
