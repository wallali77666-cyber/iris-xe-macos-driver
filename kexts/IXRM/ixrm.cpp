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
// Scaffold state: probes the iGPU, logs, declines. Nothing claims the device yet.

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
    UInt16 devId = pci ? pci->configRead16(kIOPCIConfigDeviceID) : 0;
    IXRMLOG("start: device %04X — scaffold, no GPU bring-up yet", devId);

    // TODO(Phase D): map BAR0 (MMIO) and BAR2 (aperture), upload GuC/HuC firmware,
    // initialize the rings, expose the IOUserClient the Vulkan back end will use.
    IXRMLOG("start: declining until Phase D (IXRM bring-up)");
    IOService::stop(provider);
    return false;
}

void com_irisxe_IXRM::stop(IOService *provider) {
    IXRMLOG("stop");
    IOService::stop(provider);
}
