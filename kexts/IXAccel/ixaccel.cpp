// IXAccel — the IOAccelerator that WindowServer and IOSurface composite through.
// WindowServer does not render on the framebuffer's screen directly; it hands composited
// surfaces to an accelerator. Until IXAccel publishes one (and IXRM exists to back it),
// there is nothing for WindowServer to composite with on this iGPU.
//
// Scaffold state: probes the iGPU, logs, declines.

#include <IOKit/IOLib.h>
#include <IOKit/pci/IOPCIDevice.h>
#include <mach/kmod.h>

#define IXALOG(fmt, ...) IOLog("IXAccel: " fmt "\n", ##__VA_ARGS__)

extern "C" kern_return_t _start(kmod_info_t *ki, void *d);
extern "C" kern_return_t _stop(kmod_info_t *ki, void *d);
extern "C" { KMOD_EXPLICIT_DECL(com.irisxe.IXAccel, "0.1", _start, _stop) }
extern "C" kern_return_t _start(kmod_info_t *ki, void *d) { return KERN_SUCCESS; }
extern "C" kern_return_t _stop(kmod_info_t *ki, void *d) { return KERN_SUCCESS; }

class com_irisxe_IXAccel : public IOService {
    OSDeclareDefaultStructors(com_irisxe_IXAccel)
public:
    IOService *probe(IOService *provider, SInt32 *score) override;
    bool       start(IOService *provider) override;
    void       stop(IOService *provider) override;
};

OSDefineMetaClassAndStructors(com_irisxe_IXAccel, IOService)

IOService *com_irisxe_IXAccel::probe(IOService *provider, SInt32 *score) {
    if (!OSDynamicCast(IOPCIDevice, provider)) return nullptr;
    if (score) *score += 100;
    return this;
}

bool com_irisxe_IXAccel::start(IOService *provider) {
    if (!IOService::start(provider)) return false;

    // TODO(Phase C/D): subclass IOAccelerator, publish the accelerator,
    // and route surfaces to the IXRM-backed render engine.
    IXALOG("start: scaffold — no accelerator surface yet, declining");
    IOService::stop(provider);
    return false;
}

void com_irisxe_IXAccel::stop(IOService *provider) {
    IXALOG("stop");
    IOService::stop(provider);
}
