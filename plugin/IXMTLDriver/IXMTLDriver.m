// IXMTLDriver — the Metal driver bundle for Intel Gen12 (Phase D research scaffold).
//
// The real work: implement Metal's device / queue / command buffer / encoder /
// resource objects on top of the Mesa ANV Vulkan back end, the way NullMoth's
// NVMTLDriver.bundle does on top of NVK. Shaders arrive as Apple AIR bitcode and are
// translated to SPIR-V (see ../translator/README.md).
//
// This stub exists so the bundle layout, build pipeline and CI are in place.
// Nothing loads it yet; it logs a banner when injected.
//
// Layout when real: /Library/GPUBundles/IXMTLDriver.bundle

#import <Foundation/Foundation.h>

__attribute__((constructor))
static void ixmtl_banner(void) {
    NSLog(@"IXMTLDriver: stub bundle loaded — Phase D scaffold (no Metal objects yet)");
}
