// ixrm_mmio.h — IXRM memory-map facts, every value pinned to Linux i915 v6.12
// (tag v6.12 = commit adc218676eef25575469234709c2d87185ca223a — the exact
// kernel of the project's first live hardware capture). Extracted by
// tools/ixgen/fetch_i915.sh; the CI job log and its i915-ref/extract.txt
// artifact are the audit trail. House rule: do not add a value here that is
// not in that extract — extend the extractor first.
//
//   file:line (v6.12 tree)        fact
//   gt/intel_gtt.h:62             gen8_pte_t = u64  (8-byte entries)
//   gt/intel_gtt.h:45,49          I915_GTT_PAGE_SIZE = BIT_ULL(12) = 4096
//   gt/intel_gtt.h:152            GEN8_PAGE_PRESENT = BIT_ULL(0)
//   gt/intel_gtt.h:97             GEN12_GGTT_PTE_LM = BIT_ULL(1)   (LMEM only)
//   gt/intel_gtt.h:100            GEN12_GGTT_PTE_ADDR_MASK = GENMASK_ULL(45,12)
//   gt/intel_ggtt.c:1136-1141     "GEN8: GTTMMADR size is 16MB and GTTADR
//                                  starts at 8MB offset" -> SZ_16M for gen>=8
//   gt/intel_ggtt.c:1144-1146     gen6_gttadr_offset = gen6_gttmmadr_size/2
//   gt/intel_ggtt.c:1160-1164     phys_addr = BAR0_start + gen6_gttadr_offset
//                                  unless i915_direct_stolen_access() — that
//                                  function is MTL-only (Wa_22018444074):
//                                  i915_utils.c:89-103 => false on TGL.
//   gt/intel_ggtt.c:443,556       entries indexed by offset / I915_GTT_PAGE_SIZE
//   gt/intel_ggtt.c:277-287       gen8_ggtt_pte_encode — the GGTT encoder for
//                                  gen12 < 12.70 (TGL chooses it at :1286-1289):
//                                  pte = addr | GEN8_PAGE_PRESENT
//   include/drm/intel/i915_drm.h:49-55
//                                 GMCH defines: SNB_GMCH_CTRL = 0x50 (PCI
//                                 config word); BDW_GMCH_GGMS_SHIFT = 6,
//                                 MASK = 0x3 (SNB-era shift 8 — not TGL)
//   gt/intel_ggtt.c:1107-1121     gen8_get_total_gtt_size(): table bytes =
//                                 ((ctl>>6)&3) ? 1<<((ctl>>6)&3) : 0, << 20
//                                 => 0 / 2 / 4 / 8 MB; entries = bytes / 8

#pragma once

#include <IOKit/IOLib.h>

namespace ixrm {

// The BAR0 window exposing the GGTT page-table array (entries, not data):
// SZ_16M / 2. Verified by probe on the real machine; if the sample walk shows
// an empty window, this constant must be re-derived from the extract first.
static constexpr UInt64 kGttWindowOffset = 0x00800000ULL;   // gen6_gttmmadr_size/2

// Geometry: one 8-byte entry per 4 KiB page of GTT address space.
static constexpr UInt64 kGttEntrySize    = 8ULL;            // sizeof(gen8_pte_t)
static constexpr UInt64 kGttPageSize     = 4096ULL;         // I915_GTT_PAGE_SIZE

// Entry bits interpreted while *reading*. The write path lands in D2.
static constexpr UInt64 kGttPtePresent   = 1ULL << 0;       // GEN8_PAGE_PRESENT
static constexpr UInt64 kGttPteAddrMask  = ((1ULL << 46) - 1) & ~0xFFFULL; // GENMASK_ULL(45,12)

// D2 groundwork: the *real* table size is firmware-programmed, not a BAR
// constant. It lives in PCI config space, word SNB_GMCH_CTRL, decoded the
// gen8 way (what gen8_gmch_probe() uses on TGL):
//     v = (ctl >> kGmchGgmsShift) & kGmchGgmsMask;
//     sizeBytes = (v ? 1 << v : 0) << 20;          // 0, 2, 4 or 8 MB
// Sanity tie-in: the D1 walk logged the window capacity it measured; D2 may
// only trust a decoded size that fits within it.
static constexpr UInt32 kGmchCtrlConfigOffset = 0x50;   // SNB_GMCH_CTRL
static constexpr UInt32 kGmchGgmsShift        = 6;      // BDW_GMCH_GGMS_SHIFT
static constexpr UInt32 kGmchGgmsMask         = 0x3;    // BDW_GMCH_GGMS_MASK

} // namespace ixrm
