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
//   gt/intel_ggtt.c:1164          phys_addr = BAR0_start + gen6_gttadr_offset
//                                  (the non-direct-stolen path; TGL takes it)
//   gt/intel_ggtt.c:443,556       entries indexed by offset / I915_GTT_PAGE_SIZE
//   gt/intel_ggtt.c:277-287       gen8_ggtt_pte_encode — the GGTT encoder for
//                                  gen12 < 12.70 (TGL chooses it at :1286-1289):
//                                  pte = addr | GEN8_PAGE_PRESENT

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

} // namespace ixrm
