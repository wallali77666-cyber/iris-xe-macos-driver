# plugin/ — the Metal driver bundle (Phase D)

What NullMoth's `NVMTLDriver.bundle` is for NVIDIA, `IXMTLDriver.bundle` is for Intel:
the component Metal.framework loads from `/Library/GPUBundles/`, implementing Metal's
device, queues, command buffers, encoders, resources, argument buffers and pipelines
**on top of Vulkan** (Mesa ANV for us; NVK for them).

Pipeline for our stack:

```
Metal app ─► IXMTLDriver.bundle ─► translator (Apple AIR → SPIR-V) ─► Mesa ANV ─► IXRM.kext ─► Iris Xe
```

Current contents are a stub: bundle layout + build script + CI, so the pipeline exists
before the contract work starts. Nothing is loaded by Metal yet.
