// IXAGDC — the graphics-device-control policy shim.
// macOS asks the GPU side for display policy decisions (boot display, head limits,
// swap policy). Without an answer from a driver that owns the GPU, the window server
// refuses to start on that device. Scaffold state: probes, logs, declines.

#include <IOKit/IOLib.h>
#include <IOKit/pci/IOPCIDevice.h>
#include <mach/kmod.h>

#define IXGLOG(fmt, ...) IOLog("IXAGDC: " fmt "\n", ##__VA_ARGS__)

extern "C" kern_return_t _start(kmod_info_t *ki, void *d);
extern "C" kern_return_t _stop(kmod_info_t *ki, void *d);
extern "C" { KMOD_EXPLICIT_DECL(com.irisxe.IXAGDC, "0.1", _start, _stop) }
extern "C" kern_return_t _start(kmod_info_t *ki, void *d) { return KERN_SUCCESS; }
extern "C" kern_return_t _stop(kmod_info_t *ki, void *d) { return KERN_SUCCESS; }

class com_irisxe_IXAGDC : public IOService {
    OSDeclareDefaultStructors(com_irisxe_IXAGDC)
public:
    IOService *probe(IOService *provider, SInt32 *score) override;
    bool       start(IOService *provider) override;
    void       stop(IOService *provider) override;
};

OSDefineMetaClassAndStructors(com_irisxe_IXAGDC, IOService)

IOService *com_irisxe_IXAGDC::probe(IOService *provider, SInt32 *score) {
    if (!OSDynamicCast(IOPCIDevice, provider)) return nullptr;
    if (score) *score += 100;
    return this;
}

bool com_irisxe_IXAGDC::start(IOService *provider) {
    if (!IOService::start(provider)) return false;
    // TODO(Phase C): answer the policy queries (mirroring the AGDC contract).
    IXGLOG("start: scaffold — no policy answers yet, declining");
    IOService::stop(provider);
    return false;
}

void com_irisxe_IXAGDC::stop(IOService *provider) {
    IXGLOG("stop");
    IOService::stop(provider);
}
