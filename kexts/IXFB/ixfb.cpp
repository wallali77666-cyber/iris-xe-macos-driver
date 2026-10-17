// IXFB — framebuffer bring-up for Intel Gen12 (Tiger Lake) iGPUs whose panel macOS
// has no driver for. Phase 1 takes over the mode the firmware already lit: it finds
// the pipe whose primary plane is scanning out, verifies the plane is linear 32-bit
// XRGB8888, and publishes that surface (through the graphics aperture, BAR2 + the
// plane's GGTT offset) as an IOFramebuffer with the panel's real size and refresh.
// Nothing is written to the display engine, so a machine this driver does not
// understand keeps exactly the screen it had: start() fails with a logged reason and
// the firmware framebuffer keeps the panel.
//
// Register offsets: Linux i915 display headers (MIT). Plane 1 of pipe P: PLANE_CTL
// 0x70180 + P*0x1000, STRIDE +0x08, SIZE +0x10, SURF +0x1C. Transcoder T timings at
// 0x60000 + T*0x1000; PIPECONF 0x70008 + P*0x1000; frame counter 0x70040 + P*0x1000.
//
// WindowServer paces an accelerated display on its VBL interrupt, so a 60 Hz-class
// timer stands in for the hardware vblank until the real interrupt path is wired.

#include <IOKit/IOLib.h>
#include <IOKit/pci/IOPCIDevice.h>
#include <IOKit/graphics/IOFramebuffer.h>
#include <IOKit/IODeviceMemory.h>
#include <kern/thread_call.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>
#include <string.h>
#include <mach/kmod.h>

#include "ixregs.h"

#define IXFBLOG(fmt, ...) IOLog("IXFB: " fmt "\n", ##__VA_ARGS__)

// kmutil places a kext in a kernel collection only with a _kmod_info symbol
extern "C" kern_return_t _start(kmod_info_t *ki, void *d);
extern "C" kern_return_t _stop(kmod_info_t *ki, void *d);
extern "C" { KMOD_EXPLICIT_DECL(com.irisxe.IXFB, "0.1", _start, _stop) }
extern "C" kern_return_t _start(kmod_info_t *ki, void *d) { return KERN_SUCCESS; }
extern "C" kern_return_t _stop(kmod_info_t *ki, void *d) { return KERN_SUCCESS; }

struct IXId { uint16_t id; uint8_t version; };
static const IXId kIXIds[] = {
#include "display_ids.inc"
};

// the two power states registered with the power manager: off, and on + usable
static IOPMPowerState kIXPowerStates[2] = {
    { kIOPMPowerStateVersion1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    { kIOPMPowerStateVersion1, kIOPMDeviceUsable, kIOPMPowerOn, kIOPMPowerOn, 0, 0, 0, 0, 0, 0, 0, 0 },
};

class com_irisxe_IXFB : public IOFramebuffer {
    OSDeclareDefaultStructors(com_irisxe_IXFB)

public:
    IOService *probe(IOService *provider, SInt32 *score) APPLE_KEXT_OVERRIDE;
    bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
    void stop(IOService *provider) APPLE_KEXT_OVERRIDE;

    // The only display mode is the firmware-lit one (id 1); every query has a fixed
    // answer. WindowServer showed a panel at 0.00 Hz without a valid detailed timing,
    // so getTimingInfoForDisplayMode() rebuilds one from the live transcoder state.
    IOReturn enableController(void) APPLE_KEXT_OVERRIDE { return kIOReturnSuccess; }
    bool isConsoleDevice(void) APPLE_KEXT_OVERRIDE { return true; }
    IODeviceMemory *getApertureRange(IOPixelAperture aperture) APPLE_KEXT_OVERRIDE;
    IODeviceMemory *getVRAMRange(void) APPLE_KEXT_OVERRIDE { return getApertureRange(kIOFBSystemAperture); }
    const char *getPixelFormats(void) APPLE_KEXT_OVERRIDE { return IO32BitDirectPixels "\0"; }
    IOItemCount getDisplayModeCount(void) APPLE_KEXT_OVERRIDE { return 1; }
    IOReturn getDisplayModes(IODisplayModeID *modes) APPLE_KEXT_OVERRIDE { modes[0] = 1; return kIOReturnSuccess; }
    IOReturn getInformationForDisplayMode(IODisplayModeID mode, IODisplayModeInformation *info) APPLE_KEXT_OVERRIDE;
    UInt64 getPixelFormatsForDisplayMode(IODisplayModeID, IOIndex) APPLE_KEXT_OVERRIDE { return 0; }
    IOReturn getPixelInformation(IODisplayModeID mode, IOIndex depth, IOPixelAperture aperture,
                                 IOPixelInformation *pi) APPLE_KEXT_OVERRIDE;
    IOReturn getCurrentDisplayMode(IODisplayModeID *mode, IOIndex *depth) APPLE_KEXT_OVERRIDE
        { *mode = 1; *depth = 0; return kIOReturnSuccess; }
    IOReturn getStartupDisplayMode(IODisplayModeID *mode, IOIndex *depth) APPLE_KEXT_OVERRIDE
        { return getCurrentDisplayMode(mode, depth); }
    IOReturn getTimingInfoForDisplayMode(IODisplayModeID mode, IOTimingInformation *info) APPLE_KEXT_OVERRIDE;
    IOReturn setDisplayMode(IODisplayModeID mode, IOIndex depth) APPLE_KEXT_OVERRIDE
        { return (mode == 1 && depth == 0) ? kIOReturnSuccess : kIOReturnUnsupported; }
    IOItemCount getConnectionCount(void) APPLE_KEXT_OVERRIDE { return 1; }
    IOReturn registerForInterruptType(IOSelect type, IOFBInterruptProc proc, OSObject *target,
                                      void *ref, void **iref) APPLE_KEXT_OVERRIDE;
    IOReturn unregisterInterrupt(void *) APPLE_KEXT_OVERRIDE { return kIOReturnSuccess; }
    IOReturn setInterruptState(void *, UInt32) APPLE_KEXT_OVERRIDE { return kIOReturnSuccess; }
    IOReturn setGammaTable(UInt32, UInt32, UInt32, void *) APPLE_KEXT_OVERRIDE { return kIOReturnSuccess; }
    IOReturn setGammaTable(UInt32, UInt32, UInt32, void *, bool) APPLE_KEXT_OVERRIDE { return kIOReturnSuccess; }
    IOReturn setCLUTWithEntries(IOColorEntry *, UInt32, UInt32, IOOptionBits) APPLE_KEXT_OVERRIDE { return kIOReturnSuccess; }
    IOReturn setApertureEnable(IOPixelAperture, IOOptionBits) APPLE_KEXT_OVERRIDE { return kIOReturnSuccess; }
    IOReturn setStartupDisplayMode(IODisplayModeID, IOIndex) APPLE_KEXT_OVERRIDE { return kIOReturnSuccess; }
    IOReturn setPowerState(unsigned long ordinal, IOService *) APPLE_KEXT_OVERRIDE;
    IOReturn setAttribute(IOSelect attribute, uintptr_t value) APPLE_KEXT_OVERRIDE;
    IOReturn getAttribute(IOSelect attribute, uintptr_t *value) APPLE_KEXT_OVERRIDE;
    IOReturn setAttributeForConnection(IOIndex idx, IOSelect attribute, uintptr_t value) APPLE_KEXT_OVERRIDE;
    IOReturn getAttributeForConnection(IOIndex idx, IOSelect attribute, uintptr_t *value) APPLE_KEXT_OVERRIDE;
    IOReturn connectFlags(IOIndex, IODisplayModeID, IOOptionBits *flags) APPLE_KEXT_OVERRIDE;

private:
    struct FbIrq { IOFBInterruptProc proc; OSObject *target; void *ref; };

    UInt32 rd(UInt32 off) const;
    bool   adoptLitPipe(void);
    void   armVblank(void);
    static void vblankFire(thread_call_param_t arg0, thread_call_param_t arg1);

    IOPCIDevice *fPCI = nullptr;
    IOMemoryMap *fMMIO = nullptr;             // BAR0 (MMIO registers)
    volatile UInt8 *fRegs = nullptr;
    IOPhysicalAddress fApertureBase = 0;      // BAR2: graphics aperture (GGTT window)
    IOPhysicalLength fApertureLen = 0;

    // what adoptLitPipe() found; zero until it succeeds
    UInt8  fDisplayVersion = 0;
    int    fPipe = -1;
    UInt32 fWidth = 0, fHeight = 0, fRowBytes = 0, fSurf = 0;
    UInt32 fRefresh16 = 60 << 16;
    UInt32 fHT = 0, fVT = 0, fHSS = 0, fHSE = 0, fVSS = 0, fVSE = 0;
    UInt64 fPclk = 0;
    UInt64 fFrameNs = 16666667ull;            // vblank period; measured at capture

    FbIrq fVbl = {}, fConnect = {};
    thread_call_t fVblTimer = nullptr;        // stand-in vblank until hardware interrupts
    UInt64 fVblNext = 0;
    volatile bool fStopping = false;
};

OSDefineMetaClassAndStructors(com_irisxe_IXFB, IOFramebuffer)

// ---------------------------------------------------------------------------
#pragma mark probe / start / stop

IOService *com_irisxe_IXFB::probe(IOService *provider, SInt32 *score) {
    IOPCIDevice *pci = OSDynamicCast(IOPCIDevice, provider);
    if (!pci) return nullptr;
    if (PE_parse_boot_argn("-ixfboff", nullptr, 0)) { IXFBLOG("disabled by boot-arg -ixfboff"); return nullptr; }
    const UInt16 devId = pci->configRead16(kIOPCIConfigDeviceID);
    UInt8 ver = 0;
    for (const IXId &e : kIXIds) if (e.id == devId) { ver = e.version; break; }
    if (ver == 0) return nullptr;   // an Intel display this driver does not know
    fDisplayVersion = ver;
    IXFBLOG("%04X:%04X display version %u", pci->configRead16(kIOPCIConfigVendorID), devId, ver);
    return IOFramebuffer::probe(provider, score);
}

bool com_irisxe_IXFB::start(IOService *provider) {
    fPCI = OSDynamicCast(IOPCIDevice, provider);
    if (!fPCI) return false;

    fPCI->setMemoryEnable(true);
    fMMIO = fPCI->mapDeviceMemoryWithRegister(kIOPCIConfigBaseAddress0);
    IODeviceMemory *ap = fPCI->getDeviceMemoryWithRegister(kIOPCIConfigBaseAddress2);
    if (!fMMIO || !ap) {
        IXFBLOG("BAR0 or BAR2 unavailable — leaving the firmware screen");
        OSSafeReleaseNULL(fMMIO);
        return false;
    }
    fRegs = (volatile UInt8 *)fMMIO->getVirtualAddress();
    fApertureBase = ap->getPhysicalAddress();
    fApertureLen = ap->getLength();

    if (!adoptLitPipe()) {
        OSSafeReleaseNULL(fMMIO);
        fRegs = nullptr;
        return false;
    }
    if (!IOFramebuffer::start(provider)) {
        OSSafeReleaseNULL(fMMIO);
        fRegs = nullptr;
        return false;
    }

    setProperty("IXFBPipe", (UInt32)fPipe, 32);
    setProperty("IXFBDisplayVersion", (UInt32)fDisplayVersion, 32);
    setProperty("built-in", kOSBooleanTrue);   // the laptop's own panel
    armVblank();
    registerPowerDriver(this, kIXPowerStates, 2);
    IXFBLOG("built-in panel published (%ux%u)", fWidth, fHeight);
    return true;
}

void com_irisxe_IXFB::stop(IOService *provider) {
    fStopping = true;
    // thread_call_cancel_wait is not exported to kexts: cancel, then retry the free
    // until the callback has run out
    if (fVblTimer) {
        thread_call_cancel(fVblTimer);
        while (!thread_call_free(fVblTimer)) { thread_call_cancel(fVblTimer); IOSleep(5); }
        fVblTimer = nullptr;
    }
    OSSafeReleaseNULL(fMMIO);
    fRegs = nullptr;
    IOFramebuffer::stop(provider);
}

// ---------------------------------------------------------------------------
#pragma mark capture

UInt32 com_irisxe_IXFB::rd(UInt32 off) const {
    return *(volatile UInt32 *)(fRegs + off);
}

// Find the pipe the firmware lit and describe it. Read-only; every raw value that
// matters is logged so a Phase C run can be compared with the ixplan.py expectations
// computed from the same panel's EDID.
bool com_irisxe_IXFB::adoptLitPipe(void) {
    for (UInt32 p = 0; p < kIXPipeCount; p++) {
        const UInt32 conf = rd(ixPipeConf(p));
        const UInt32 ctl  = rd(ixPlaneCtl(p));
        IXFBLOG("scan: pipe %u PIPECONF %08X PLANE_CTL %08X", p, conf, ctl);
        if (!(conf & kIXEnableBit) || !(ctl & kIXEnableBit)) continue;

        const UInt32 fmt = ixPlaneCtlFormat(ctl);
        if (fmt != kIXFormatXRGB8888) {
            IXFBLOG("pipe %u: plane format %u is not XRGB8888 — leaving the firmware screen", p, fmt);
            return false;
        }
        const UInt32 tiling = ixPlaneCtlTiling(ctl);
        if (tiling != 0) {
            IXFBLOG("pipe %u: plane is tiled (%u) — Phase 1 handles linear surfaces only", p, tiling);
            return false;
        }

        const UInt32 size = rd(ixPlaneSize(p));
        fRowBytes = ixStrideBytes(rd(ixPlaneStride(p)));
        fWidth    = ixLowMinusOne(size);
        fHeight   = ixHighMinusOne(size);
        fSurf     = rd(ixPlaneSurf(p)) & kIXSurfAddrMask;

        if (fWidth < 640 || fHeight < 480 || fRowBytes < fWidth * 4) {
            IXFBLOG("pipe %u: surface %ux%u stride %u is not usable — leaving the firmware screen",
                    p, fWidth, fHeight, fRowBytes);
            return false;
        }
        if ((UInt64)fSurf + (UInt64)fRowBytes * fHeight > fApertureLen) {
            IXFBLOG("pipe %u: surface at 0x%X is past the %llu MiB aperture", p, fSurf,
                    (unsigned long long)(fApertureLen >> 20));
            return false;
        }

        // the transcoder that feeds pipe p is p on these display versions
        fHT = ixHighMinusOne(rd(ixHTotal(p)));
        fVT = ixHighMinusOne(rd(ixVTotal(p)));
        const UInt32 hsync = rd(ixHSync(p)), vsync = rd(ixVSync(p));
        fHSS = ixLowMinusOne(hsync);  fHSE = ixHighMinusOne(hsync);
        fVSS = ixLowMinusOne(vsync);  fVSE = ixHighMinusOne(vsync);

        // the real refresh without reading back the PLL: count vblanks over 250 ms
        const UInt32 c0 = rd(ixFrameCount(p));
        const UInt64 t0 = mach_absolute_time();
        IOSleep(250);
        const UInt32 c1 = rd(ixFrameCount(p));
        const UInt64 t1 = mach_absolute_time();
        UInt64 ns = 0;
        absolutetime_to_nanoseconds(t1 - t0, &ns);
        const UInt32 frames = c1 - c0;
        if (frames >= 5 && frames <= 100 && ns) {
            const UInt64 mhz = (UInt64)frames * 1000000000000ull / ns;   // milli-hertz
            fFrameNs = ns / frames;
            fRefresh16 = (UInt32)((mhz << 16) / 1000);
            fPclk = (UInt64)fHT * fVT * mhz / 1000;
        } else {
            fPclk = (UInt64)fHT * fVT * 60;
        }

        fPipe = (int)p;
        IXFBLOG("pipe %u: %ux%u stride %u surface 0x%X totals %ux%u, %u vblanks in %llu ms -> %u.%02u Hz, pclk %llu MHz",
                p, fWidth, fHeight, fRowBytes, fSurf, fHT, fVT, frames,
                (unsigned long long)(ns / 1000000),
                fRefresh16 >> 16, ((fRefresh16 & 0xFFFF) * 100) >> 16,
                (unsigned long long)(fPclk / 1000000));
        return true;
    }
    IXFBLOG("no pipe is scanning out — the firmware left the panel off; leaving it to the firmware framebuffer");
    return false;
}

// ---------------------------------------------------------------------------
#pragma mark vblank

void com_irisxe_IXFB::armVblank(void) {
    fVblTimer = thread_call_allocate(&com_irisxe_IXFB::vblankFire, this);
    if (fVblTimer) {
        UInt64 deadline = 0;
        clock_interval_to_deadline((UInt32)(fFrameNs / 1000), kMicrosecondScale, &deadline);
        fVblNext = deadline;
        thread_call_enter_delayed(fVblTimer, deadline);
    }
    IXFBLOG("vblank timer %s", fVblTimer ? "armed" : "ALLOCATE FAILED");
}

void com_irisxe_IXFB::vblankFire(thread_call_param_t arg0, thread_call_param_t) {
    com_irisxe_IXFB *me = (com_irisxe_IXFB *)arg0;
    if (me->fStopping) return;
    if (me->fVbl.proc) me->fVbl.proc(me->fVbl.target, me->fVbl.ref);
    UInt64 period = 0;
    nanoseconds_to_absolutetime(me->fFrameNs, &period);
    const UInt64 now = mach_absolute_time();
    me->fVblNext = (me->fVblNext && me->fVblNext + period > now) ? (me->fVblNext + period)
                                                                 : (now + period);
    thread_call_enter_delayed(me->fVblTimer, me->fVblNext);
}

IOReturn com_irisxe_IXFB::registerForInterruptType(IOSelect type, IOFBInterruptProc proc,
                                                   OSObject *target, void *ref, void **iref) {
    if (type == kIOFBVBLInterruptType) {
        fVbl = FbIrq{proc, target, ref};
        if (iref) *iref = &fVbl;
        return kIOReturnSuccess;
    }
    if (type == kIOFBConnectInterruptType) {
        fConnect = FbIrq{proc, target, ref};
        if (iref) *iref = &fConnect;
        return kIOReturnSuccess;
    }
    return kIOReturnUnsupported;
}

// ---------------------------------------------------------------------------
#pragma mark IOFramebuffer surface

IODeviceMemory *com_irisxe_IXFB::getApertureRange(IOPixelAperture aperture) {
    if (aperture != kIOFBSystemAperture) return nullptr;
    // BAR2 aperture base + the plane's GGTT offset = physical address of the surface
    return IODeviceMemory::withRange(fApertureBase + fSurf, (IOPhysicalLength)fRowBytes * fHeight);
}

IOReturn com_irisxe_IXFB::getInformationForDisplayMode(IODisplayModeID mode, IODisplayModeInformation *info) {
    if (mode != 1 || !info) return kIOReturnBadArgument;
    bzero(info, sizeof(*info));
    info->maxDepthIndex = 0;
    info->nominalWidth = fWidth;
    info->nominalHeight = fHeight;
    info->refreshRate = fRefresh16;
    info->flags = kDisplayModeValidFlag | kDisplayModeSafeFlag | kDisplayModeDefaultFlag;
    return kIOReturnSuccess;
}

IOReturn com_irisxe_IXFB::getPixelInformation(IODisplayModeID mode, IOIndex depth,
                                              IOPixelAperture aperture, IOPixelInformation *pi) {
    if (mode != 1 || depth != 0 || aperture != kIOFBSystemAperture || !pi) return kIOReturnUnsupportedMode;
    bzero(pi, sizeof(*pi));
    pi->bytesPerRow = fRowBytes;
    pi->bytesPerPlane = 0;
    pi->bitsPerPixel = 32;
    pi->pixelType = kIORGBDirectPixels;
    pi->componentCount = 3;
    pi->bitsPerComponent = 8;
    pi->componentMasks[0] = 0x00FF0000;   // red
    pi->componentMasks[1] = 0x0000FF00;   // green
    pi->componentMasks[2] = 0x000000FF;   // blue
    strlcpy(pi->pixelFormat, IO32BitDirectPixels, sizeof(pi->pixelFormat));
    pi->activeWidth = fWidth;
    pi->activeHeight = fHeight;
    return kIOReturnSuccess;
}

// The detailed timing is rebuilt from the live transcoder, so WindowServer knows the
// real refresh instead of a 0.00 Hz placeholder.
IOReturn com_irisxe_IXFB::getTimingInfoForDisplayMode(IODisplayModeID mode, IOTimingInformation *info) {
    if (mode != 1 || !info) return kIOReturnUnsupportedMode;
    bzero(info, sizeof(*info));
    info->appleTimingID = kIOTimingIDInvalid;
    if (!fPclk || fHT <= fWidth || fVT <= fHeight) return kIOReturnSuccess;
    IODetailedTimingInformationV2 &d = info->detailedInfo.v2;
    d.pixelClock = d.minPixelClock = d.maxPixelClock = fPclk;
    d.horizontalActive = fWidth;
    d.horizontalBlanking = fHT - fWidth;
    d.horizontalSyncOffset = fHSS > fWidth ? fHSS - fWidth : 0;
    d.horizontalSyncPulseWidth = fHSE > fHSS ? fHSE - fHSS : 0;
    d.verticalActive = fHeight;
    d.verticalBlanking = fVT - fHeight;
    d.verticalSyncOffset = fVSS > fHeight ? fVSS - fHeight : 0;
    d.verticalSyncPulseWidth = fVSE > fVSS ? fVSE - fVSS : 0;
    info->flags = kIODetailedTimingValid;
    return kIOReturnSuccess;
}

// ---------------------------------------------------------------------------
#pragma mark power / connection attributes

IOReturn com_irisxe_IXFB::setPowerState(unsigned long ordinal, IOService *) {
    // answer at once; the base class would otherwise wait for an acknowledge that
    // never comes and stall a display transition for 45 s
    handleEvent(ordinal ? kIOFBNotifyDidPowerOn : kIOFBNotifyWillPowerOff);
    return kIOPMAckImplied;
}

IOReturn com_irisxe_IXFB::setAttribute(IOSelect attribute, uintptr_t value) {
    if (attribute == kIOWindowServerActiveAttribute) return kIOReturnSuccess;
    if (attribute == kIOPowerAttribute) {
        if (value) {
            const IOReturn r = IOFramebuffer::setAttribute(attribute, value);
            handleEvent(kIOFBNotifyDidPowerOn);
            return r == kIOReturnUnsupported ? kIOReturnSuccess : r;
        }
        handleEvent(kIOFBNotifyWillPowerOff);
        const IOReturn r = IOFramebuffer::setAttribute(attribute, value);
        return r == kIOReturnUnsupported ? kIOReturnSuccess : r;
    }
    return IOFramebuffer::setAttribute(attribute, value);
}

IOReturn com_irisxe_IXFB::getAttribute(IOSelect attribute, uintptr_t *value) {
    if (attribute == kIOWindowServerActiveAttribute) { if (value) *value = 1; return kIOReturnSuccess; }
    return IOFramebuffer::getAttribute(attribute, value);
}

IOReturn com_irisxe_IXFB::setAttributeForConnection(IOIndex idx, IOSelect attribute, uintptr_t value) {
    switch (attribute) {
    case kConnectionPower:
    case kConnectionColorModesSupported:
    case kConnectionColorDepthsSupported:
    case kConnectionControllerColorDepth:
    case kConnectionControllerDepthsSupported:
    case kConnectionColorMode:
    case kConnectionDisplayFlags:
    case kConnectionFlags:
        return kIOReturnSuccess;
    default:
        return IOFramebuffer::setAttributeForConnection(idx, attribute, value);
    }
}

IOReturn com_irisxe_IXFB::getAttributeForConnection(IOIndex idx, IOSelect attribute, uintptr_t *value) {
    if (idx != 0 || !value) return kIOReturnBadArgument;
    switch (attribute) {
    case kConnectionEnable:
    case kConnectionCheckEnable:
        *value = 1;
        return kIOReturnSuccess;
    case kConnectionFlags:
        *value = kIOConnectionBuiltIn;
        return kIOReturnSuccess;
    case kConnectionColorModesSupported:
    case kConnectionColorMode:
        *value = 0x00000001;   // RGB colour mode
        return kIOReturnSuccess;
    case kConnectionColorDepthsSupported:
    case kConnectionControllerColorDepth:
    case kConnectionControllerDepthsSupported:
        *value = 0x00000002;   // 8 bits per component
        return kIOReturnSuccess;
    default:
        return IOFramebuffer::getAttributeForConnection(idx, attribute, value);
    }
}

IOReturn com_irisxe_IXFB::connectFlags(IOIndex, IODisplayModeID, IOOptionBits *flags) {
    if (flags) *flags = kDisplayModeValidFlag | kDisplayModeSafeFlag | kDisplayModeDefaultFlag;
    return kIOReturnSuccess;
}
