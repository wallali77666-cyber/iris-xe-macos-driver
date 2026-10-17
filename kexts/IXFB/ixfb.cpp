// IXFB — framebuffer bring-up for Intel Gen12 (Tiger Lake) iGPUs whose panel macOS
// has no driver for. Phase 1 takes over the mode the firmware already lit; nothing is
// written to the display engine, so a machine this driver does not understand keeps
// exactly the screen it had (start() declines and the firmware framebuffer stays).
//
// Steps (registers: Linux i915 display headers, MIT):
//   1. probe(): accept only display device IDs (display_ids.inc) with display version 12
//   2. start(): map MMIO (BAR0); find the pipe whose primary plane is scanning out
//      (PLANE_CTL 0x70180 + pipe*0x1000, enabled + format = linear 32-bit XRGB)
//   3. read SURF/STRIDE/SIZE for that plane and the active transcoder timings
//      (HTOTAL 0x60000 + t*0x1000 ...), cross-check the EDID IrisProbe recorded
//   4. IOFramebuffer subclass publishes that surface with the panel's real size and
//      refresh (through the graphics aperture BAR2 + the plane's GGTT offset)
//   5. Phase 2 (later): program modes ourselves using the igfx-style EDID -> register
//      planner validated against i915 traces, dim the backlight, drive vblank
//
// This scaffold compiles and loads, declines cleanly, and logs why. Phase C turns the
// IOFramebuffer part on.

#include <IOKit/IOLib.h>
#include <IOKit/pci/IOPCIDevice.h>
#include <mach/kmod.h>

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

class com_irisxe_IXFB : public IOService {
    OSDeclareDefaultStructors(com_irisxe_IXFB)
public:
    IOService *probe(IOService *provider, SInt32 *score) override;
    bool       start(IOService *provider) override;
    void       stop(IOService *provider) override;
};

OSDefineMetaClassAndStructors(com_irisxe_IXFB, IOService)

IOService *com_irisxe_IXFB::probe(IOService *provider, SInt32 *score) {
    IOPCIDevice *pci = OSDynamicCast(IOPCIDevice, provider);
    if (!pci) return nullptr;
    UInt16 devId = pci->configRead16(kIOPCIConfigDeviceID);
    uint8_t ver = 0;
    for (const IXId &e : kIXIds) if (e.id == devId) { ver = e.version; break; }
    if (ver == 0) {
        IXFBLOG("probe: device %04X not in display_ids.inc — declining", devId);
        return nullptr;
    }
    if (score) *score += 100;
    IXFBLOG("probe: device %04X, display version %u — match", devId, ver);
    return this;
}

bool com_irisxe_IXFB::start(IOService *provider) {
    if (!IOService::start(provider)) return false;
    IOPCIDevice *pci = OSDynamicCast(IOPCIDevice, provider);
    if (!pci) { IOService::stop(provider); return false; }

    UInt16 devId  = pci->configRead16(kIOPCIConfigDeviceID);
    UInt16 subsys = pci->configRead16(kIOPCIConfigSubSystemID);
    IXFBLOG("start: %04X (subsys %04X) — scaffold, no display takeover yet", devId, subsys);

    // TODO(Phase C): map BAR0/BAR2, find the lit pipe, verify the plane, then move
    // this class onto IOFramebuffer and publish the surface. Until then, decline so
    // the firmware framebuffer keeps the panel exactly as it is.
    IXFBLOG("start: declining until Phase C brings the IOFramebuffer surface up");
    IOService::stop(provider);
    return false;
}

void com_irisxe_IXFB::stop(IOService *provider) {
    IXFBLOG("stop");
    IOService::stop(provider);
}
