// IXFB register map — the subset of the Intel Gen12 (Tiger Lake, display version 12)
// display engine that Phase 1 touches. Offsets and field layouts: Linux i915 display
// headers/source (MIT); unit encodings cross-checked against i915 and recorded MMIO
// behavior. Everything is read-only in Phase 1 — bit positions used only to validate
// are documented as such, and nothing here is ever written.
#ifndef IXREGS_H
#define IXREGS_H

#include <IOKit/IOLib.h>

// --- transcoder timing block: 0x60000 + 0x1000 * transcoder ---------------------
// [31:16] = value - 1, [15:0] = value - 1 (each register has its own pair)
constexpr UInt32 ixHTotal(UInt32 t)  { return 0x60000u + t * 0x1000u; }  // total / active
constexpr UInt32 ixHBlank(UInt32 t)  { return 0x60004u + t * 0x1000u; }  // blank end / start
constexpr UInt32 ixHSync(UInt32 t)   { return 0x60008u + t * 0x1000u; }  // sync end / start
constexpr UInt32 ixVTotal(UInt32 t)  { return 0x6000Cu + t * 0x1000u; }  // total / active
constexpr UInt32 ixVBlank(UInt32 t)  { return 0x60010u + t * 0x1000u; }  // blank end / start
constexpr UInt32 ixVSync(UInt32 t)   { return 0x60014u + t * 0x1000u; }  // sync end / start
constexpr UInt32 ixPipeSrc(UInt32 t) { return 0x6001Cu + t * 0x1000u; }  // width / height

// --- pipe / transcoder config (one register on display v12): 0x70008 + 0x1000 * p
constexpr UInt32 ixPipeConf(UInt32 p) { return 0x70008u + p * 0x1000u; }

// --- primary plane ("plane 1") of pipe p: 0x70180 + 0x1000 * p ------------------
constexpr UInt32 ixPlaneCtl(UInt32 p)    { return 0x70180u + p * 0x1000u; }
constexpr UInt32 ixPlaneStride(UInt32 p) { return 0x70188u + p * 0x1000u; }
constexpr UInt32 ixPlaneSize(UInt32 p)   { return 0x70190u + p * 0x1000u; }
constexpr UInt32 ixPlaneSurf(UInt32 p)   { return 0x7019Cu + p * 0x1000u; }

// --- pipe frame counter: +1 per vblank (i915 PIPE_FRMCOUNT_G4X) -----------------
constexpr UInt32 ixFrameCount(UInt32 p)  { return 0x70040u + p * 0x1000u; }

// --- bit layouts ----------------------------------------------------------------
// enable is bit 31 in both PIPECONF and PLANE_CTL
static const UInt32 kIXEnableBit = 1u << 31;
// PLANE_CTL format field [27:23]; 8 = XRGB8888 on display 11+ (i915 PLANE_CTL_FORMAT_XRGB_8888)
static const UInt32 kIXFormatXRGB8888 = 8u;
// PLANE_CTL tiling field [12:10]; 0 = linear
// PLANE_SURF carries the surface's GGTT offset, 4 KiB aligned
static const UInt32 kIXSurfAddrMask = 0xFFFFF000u;

constexpr UInt32 ixPlaneCtlFormat(UInt32 ctl) { return (ctl >> 23) & 0x1Fu; }
constexpr UInt32 ixPlaneCtlTiling(UInt32 ctl) { return (ctl >> 10) & 0x7u; }

// Register pair fields are "minus one" encodings.
constexpr UInt32 ixLowMinusOne(UInt32 v)  { return (v & 0xFFFFu) + 1u; }
constexpr UInt32 ixHighMinusOne(UInt32 v) { return (v >> 16) + 1u; }

// PLANE_STRIDE of a linear surface counts 64-byte units (i915 writes stride / 64);
// the field is 11 bits wide on this hardware generation.
constexpr UInt32 ixStrideBytes(UInt32 reg) { return (reg & 0x7FFu) << 6; }

static const UInt32 kIXPipeCount = 4;

#endif // IXREGS_H
