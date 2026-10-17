// IXRM — the Intel Gen12 resource manager: the piece that does not exist for macOS yet,
// and the reason full Metal support is a research project rather than a port.
//
// What this must eventually provide (the minimum Mesa's ANV driver needs on top of it):
//   - GGTT / PPGTT page-table management and video-memory views
//   - command submission (render / compute rings) and fence / sync objects
//   - GuC + HuC firmware upload, engine bring-up (RCS/BCS/VCS), power states
//   - our own IOKit API surface (IOUserClient) that the user-space Vulkan back end calls
//
// Reference material: Linux i915 / xe (MIT-licensed). NVIDIA made NullMoth's NVRM
// possible by publishing open GPU kernel modules; Intel has no such macOS-usable
// code, so IXRM is written from the register documentation and i915 behavior instead.
//
// Phase B state: real probe. Maps both BARs (read-only use), identifies the part from
// PCI configuration space, logs what a bring-up would face, and declines. Nothing is
// claimed and nothing is written — Phase D flips it on together with IXFB's surface.

#include <IOKit/IOLib.h>
#include <IOKit/pci/IOPCIDevice.h>
#include <mach/kmod.h>

#define IXRMLOG(fmt, ...) IOLog("IXRM: " fmt "\n", ##__VA_ARGS__)

extern "C" kern_return_t _start(kmod_info_t *ki, void *d);
extern "C" kern_return_t _stop(kmod_info_t *ki, void *d);
extern "C" { KMOD_EXPLICIT_DECL(com.irisxe.IXRM, "0.1", _start, _stop) }
extern "C" kern_return_t _start(kmod_info_t *ki, void *d) { return KERN_SUCCESS; }
extern "C" kern_return_t _stop(kmod_info_t *ki, void *d) { return KERN_SUCCESS; }

class com_irisxe_IXRM : public IOService {
    OSDeclareDefaultStructors(com_irisxe_IXRM)
public:
    IOService *probe(IOService *provider, SInt32 *score) override;
    bool       start(IOService *provider) override;
    void       stop(IOService *provider) override;
};

OSDefineMetaClassAndStructors(com_irisxe_IXRM, IOService)

IOService *com_irisxe_IXRM::probe(IOService *provider, SInt32 *score) {
    if (!OSDynamicCast(IOPCIDevice, provider)) return nullptr;
    if (score) *score += 100;
    return this;
}

bool com_irisxe_IXRM::start(IOService *provider) {
    if (!IOService::start(provider)) return false;
    IOPCIDevice *pci = OSDynamicCast(IOPCIDevice, provider);
    if (!pci) { IOService::stop(provider); return false; }

    // --- identification (config space only) --------------------------------
    const UInt16 devId  = pci->configRead16(kIOPCIConfigDeviceID);
    const UInt16 vendId = pci->configRead16(kIOPCIConfigVendorID);
    const UInt16 ssId   = pci->configRead16(kIOPCIConfigSubSystemID);
    const UInt16 ssVend = pci->configRead16(kIOPCIConfigSubSystemVendorID);
    const UInt8  rev    = pci->configRead8(kIOPCIConfigRevisionID);
    IXRMLOG("probe: %04X:%04X rev %02X, subsys %04X:%04X at PCI %u:%u.%u",
            vendId, devId, rev, ssVend, ssId,
            pci->getBusNumber(), pci->getDeviceNumber(), pci->getFunctionNumber());

    // --- map the two windows a full bring-up needs -------------------------
    IOMemoryMap *bar0 = pci->mapDeviceMemoryWithRegister(kIOPCIConfigBaseAddress0);
    IOMemoryMap *bar2 = pci->mapDeviceMemoryWithRegister(kIOPCIConfigBaseAddress2);
    IXRMLOG("BAR0 (MMIO registers): %s, %llu bytes",
            bar0 ? "mapped" : "UNAVAILABLE",
            bar0 ? (unsigned long long)bar0->getLength() : 0ull);
    IXRMLOG("BAR2 (graphics aperture): %s, %llu bytes",
            bar2 ? "mapped" : "UNAVAILABLE",
            bar2 ? (unsigned long long)bar2->getLength() : 0ull);

    if (bar0) {
        // One raw read for the record; not interpreted (no name attached to offset
        // 0x0000 is asserted here). Real register decode lands in Phase D with the
        // ixcheck trace baseline.
        volatile UInt32 *regs = (volatile UInt32 *)bar0->getVirtualAddress();
        IXRMLOG("MMIO[00000] = %08X (raw, uninterpreted)", regs ? regs[0] : 0u);
    }

    IXRMLOG("bring-up plan (Phase D): GGTT/PPGTT setup, GuC/HuC upload from a user-space");
    IXRMLOG("  loader, RCS/BCS/VCS engine bring-up, IOUserClient API for the Vulkan back end");

    // --- still declining ----------------------------------------------------
    IXRMLOG("start: declining until Phase D (IXRM bring-up)");
    if (bar2) bar2->release();
    if (bar0) bar0->release();
    IOService::stop(provider);
    return false;
}

void com_irisxe_IXRM::stop(IOService *provider) {
    IXRMLOG("stop");
    IOService::stop(provider);
}
