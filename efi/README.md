# efi/ — OpenCore EFI sources

This folder does **not** contain a ready EFI. It holds the parts that enter one:

```
OC/ACPI/*.dsl    ACPI sources, compiled to .aml during assembly
```

The assembled EFI (OpenCore + kexts + config.plist) is produced by
`tools/efi/assemble.sh`, which CI runs on a GitHub macOS runner:

- downloads the latest OpenCore release (bootloader + drivers) **on the runner**
- downloads the latest Acidanthera kexts (Lilu, VirtualSMC, WhateverGreen, AppleALC, IntelMausi)
- adds **our** `IXFB.kext` and `IXRM.kext` from `build/out/`
- compiles the SSDTs here with `iasl`
- generates `config.plist` from OpenCore's own `Sample.plist`
  (`tools/efi/configure.py`) and validates it with the release's `ocvalidate`
- packages everything as `iris-xe-efi.zip` (artifact `iris-xe-efi`, ~4 MB)

Real-machine instructions (USB creation on Windows, BIOS settings, first boot,
what to send back): [`docs/PHASE-C-OPENCORE.md`](../docs/PHASE-C-OPENCORE.md).
