#!/usr/bin/env python3
"""Generate EFI/OC/config.plist for the iris-xe project from OpenCore's Sample.plist.

Why not hand-write the config: OpenCore's schema changes between releases. Starting
from the Sample.plist that ships inside the very release we bundle keeps every
section complete for that exact version; this script then applies the values this
machine needs, and prints a change log for CI review.

Usage:
  python3 tools/efi/configure.py --sample Docs/Sample.plist --out config.plist \
      --oc-version 1.0.7 --drivers OpenRuntime.efi OpenHfsPlus.efi ResetNvramEntry.efi \
      [--macserial /path/to/macserial]
"""
from __future__ import annotations

import argparse
import plistlib
import re
import subprocess
import sys
import uuid

# --- machine profile ---------------------------------------------------------
# Reference machine: Dell Latitude 5420 (i5-1145G7, Iris Xe 8086:9A49, display v12).
MODEL = "MacBookPro16,2"
BOOT_ARGS = (
    "-v debug=0x100 keepsyms=1 "  # verbose + symbols: Phase C is debugged from logs
    "alcid=21"                    # AppleALC layout guess for 8086:A0C8; test 21/69/13 after install
)

# Kernel extensions, in load order. Bundle names must match EFI/OC/Kexts/ contents
# that tools/efi/assemble.sh populates.
KEXTS = [
    ("Lilu.kext",              "Contents/MacOS/Lilu",              "patcher infrastructure - everything below depends on it"),
    ("VirtualSMC.kext",        "Contents/MacOS/VirtualSMC",        "SMC emulation - required with a Mac SMBIOS"),
    ("SMCProcessor.kext",      "Contents/MacOS/SMCProcessor",      "CPU sensors (VirtualSMC plugin)"),
    ("SMCBatteryManager.kext", "Contents/MacOS/SMCBatteryManager", "battery status (VirtualSMC plugin)"),
    ("WhateverGreen.kext",     "Contents/MacOS/WhateverGreen",     "GPU patches - inert while no Apple Intel driver matches"),
    ("AppleALC.kext",          "Contents/MacOS/AppleALC",          "audio for 8086:A0C8"),
    ("IntelMausi.kext",        "Contents/MacOS/IntelMausi",        "I219-LM ethernet - the install-time network"),
    ("IXFB.kext",              "Contents/MacOS/IXFB",              "iris-xe: display Phase-1 takeover (claims the firmware-lit pipe)"),
    ("IXRM.kext",              "Contents/MacOS/IXRM",              "iris-xe: GPU probe (declines until Phase D - log evidence only)"),
]

# NVRAM defaults applied through Add (and rewritten every boot via Delete).
NVRAM_APPLE_BOOT = "7C436110-AB2A-4BBB-A880-FE41995C9F82"
NVRAM_APPLE_GUI = "4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14"

CHANGES: list[str] = []


def ver_tuple(tag: str):
    parts = []
    for p in tag.lstrip("v").split("."):
        num = ""
        for ch in p:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num or 0))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def set_key(cfg: dict, path: list[str], value):
    """Set cfg[path] = value, creating parents; records the change."""
    d = cfg
    for k in path[:-1]:
        if k not in d or not isinstance(d[k], dict):
            d[k] = {}
        d = d[k]
    old = d.get(path[-1], "<absent>")
    if old != value:
        d[path[-1]] = value
        CHANGES.append("%s: %r -> %r" % ("/".join(path), old, value))


def set_if_present(cfg: dict, path: list[str], value):
    """Set cfg[path] = value only when the key already exists (schema safety)."""
    d = cfg
    for k in path[:-1]:
        if not isinstance(d, dict) or k not in d:
            return
        d = d[k]
    if path[-1] in d and d[path[-1]] != value:
        old = d[path[-1]]
        d[path[-1]] = value
        CHANGES.append("%s: %r -> %r (optional key)" % ("/".join(path), old, value))


def collect_serial(macserial: str) -> tuple[str, str]:
    """Run macserial for MODEL; return (serial, mlb) or ("", "")."""
    for cmd in (
        [macserial, "-m", MODEL, "-n", "1"],
        [macserial, "-m", MODEL, "-n", "1", "-g"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except Exception as ex:  # noqa: BLE001 - CI must never die here
            print("macserial: %r failed: %s" % (cmd, ex))
            continue
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        print("macserial output:\n%s" % out)
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2 and parts[0]:
                return parts[0], parts[1]
            if re.match(r"^[A-Z0-9]{8,}$", parts[0]):
                return parts[0], ""
    return "", ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True, help="OpenCore release's Docs/Sample.plist")
    ap.add_argument("--out", required=True, help="config.plist to write")
    ap.add_argument("--oc-version", required=True, help="OpenCore release tag, e.g. 1.0.7")
    ap.add_argument("--drivers", nargs="*", default=[], help="driver .efi files placed in EFI/OC/Drivers")
    ap.add_argument("--macserial", default=None, help="optional macserial binary for SMBIOS serials")
    args = ap.parse_args(argv)

    with open(args.sample, "rb") as f:
        cfg = plistlib.load(f)

    oc = ver_tuple(args.oc_version)
    # OpenCore 1.0.8 still requires Kernel/Add/Arch (validated by ocvalidate); it has
    # been part of the schema since 0.5.x, so always including "Any" is safe.

    # --- ACPI ----------------------------------------------------------------
    cfg.setdefault("ACPI", {})["Add"] = [{
        "Comment": "plugin-type for CPU power management (name PR00 from Dell TGL ACPI; verify via SysReport)",
        "Enabled": True,
        "Path": "SSDT-PLUG.aml",
    }]
    CHANGES.append("ACPI/Add: SSDT-PLUG.aml")
    set_key(cfg, ["ACPI", "Quirks", "ResetLogoStatus"], True)

    # --- Booter: Tiger Lake laptop baseline ---------------------------------
    # If boot stalls before macOS output, the doc lists what to flip and why.
    for k, v in {
        "AvoidRuntimeDefrag": True,
        "DevirtualiseMmio": False,
        "DisableVariableWrite": False,
        "DiscardHibernateMap": False,
        "EnableSafeModeSlide": True,
        "EnableWriteUnprotector": False,
        "ForceExitBootServices": False,
        "ProtectMemoryRegions": False,
        "ProtectSecureBoot": False,
        "ProtectUefiServices": True,
        "ProvideCustomSlide": True,
        "ProvideMaxSlide": 0,
        "RebuildAppleMemoryMap": True,
        "SetupVirtualMap": True,
        "SignalAppleOS": False,
        "SyncRuntimePermissions": True,
    }.items():
        set_key(cfg, ["Booter", "Quirks", k], v)

    # --- DeviceProperties ----------------------------------------------------
    dev_add = cfg.setdefault("DeviceProperties", {}).setdefault("Add", {})
    dev_add.setdefault("PciRoot(0x0)/Pci(0x2,0x0)", {})
    iGPU = dev_add["PciRoot(0x0)/Pci(0x2,0x0)"]
    if iGPU.get("model") != "Intel(R) Iris(R) Xe Graphics":
        iGPU["model"] = "Intel(R) Iris(R) Xe Graphics"
        CHANGES.append("DeviceProperties/Add/iGPU: model label")

    # --- Kernel --------------------------------------------------------------
    kext_add = []
    for bundle, exe, comment in KEXTS:
        kext_add.append({
            "Arch": "Any",
            "BundlePath": bundle,
            "Comment": comment,
            "Enabled": True,
            "ExecutablePath": exe,
            "MaxKernel": "",
            "MinKernel": "",
            "PlistPath": "Contents/Info.plist",
        })
    cfg.setdefault("Kernel", {})["Add"] = kext_add
    CHANGES.append("Kernel/Add: %d extensions (%s)" % (len(kext_add), ", ".join(k[0] for k in KEXTS)))

    for k, v in {
        "AppleCpuPmCfgLock": False,
        "AppleXcpmCfgLock": True,       # Dell BIOS does not expose the CFG-lock toggle
        "AppleXcpmExtraMsrs": False,
        "AppleXcpmForceBoost": False,
        "CustomSMBIOSGuid": False,
        "DisableIoMapper": True,        # VT-d stays enabled in BIOS; macOS ignores it
        "DisableLinkeditJettison": True,
        "DisableRtcChecksum": False,
        "ExtendBTFeatureFlags": False,
        "ExternalDiskIcons": False,
        "ForceAquantiaEthernet": False,
        "IncreasePciBarSize": False,
        "LapicKernelPanic": False,
        "LegacyCommpage": False,
        "PanicNoKextDump": True,
        "PowerTimeoutKernelPanic": True,
        "SetApfsTrimTimeout": -1,
        "ThirdPartyDrives": False,
    }.items():
        set_key(cfg, ["Kernel", "Quirks", k], v)
    for k, v in {
        "DisableIoMapperMapping": False,
        "ForceSecureBootScheme": False,
        "ProvideCurrentCpuInfo": False,
        "XhciPortLimit": False,
    }.items():
        set_if_present(cfg, ["Kernel", "Quirks", k], v)

    # --- Misc ----------------------------------------------------------------
    for k, v in {
        "HideAuxiliary": True,          # recovery/tools live behind the space bar
        "LauncherOption": "Full",
        "PickerAttributes": 17,
        "PickerMode": "Builtin",
        "PollAppleHotKeys": True,
        "ShowPicker": True,
        "TakeoffDelay": 0,
        "Timeout": 5,
    }.items():
        set_key(cfg, ["Misc", "Boot", k], v)
    set_if_present(cfg, ["Misc", "Boot", "LauncherPath"], "Default")
    set_if_present(cfg, ["Misc", "Boot", "PickerVariant"], "Auto")

    for k, v in {
        "AppleDebug": True,
        "ApplePanic": False,
        "DisableWatchDog": True,
        "DisplayDelay": 0,
        "DisplayLevel": 2147483714,     # 0x80000042: errors + warnings + info
        "SysReport": True,              # dumps ACPI tables to the ESP for remote fixing
        "Target": 75,                   # console + data hub + file + NVRAM -> log file on the ESP
    }.items():
        set_key(cfg, ["Misc", "Debug", k], v)

    for k, v in {
        "AllowSetDefault": True,
        "DmgLoading": "Signed",
        "ExposeSensitiveData": 6,
        "ScanPolicy": 0,                # show every bootable volume
        "SecureBootModel": "Disabled",  # unsigned kexts: Acidanthera + ours
        "Vault": "Optional",
    }.items():
        set_key(cfg, ["Misc", "Security", k], v)
    # AllowNvramReset existed up to OpenCore 0.9.x; newer versions dropped the key
    # (the ResetNvramEntry.efi driver provides the picker entry instead).
    set_if_present(cfg, ["Misc", "Security", "AllowNvramReset"], True)

    tools = cfg.get("Misc", {}).get("Tools")
    if tools:
        for t in tools:
            if isinstance(t, dict):
                t["Enabled"] = False
        CHANGES.append("Misc/Tools: all disabled (no tools are copied)")

    # --- NVRAM ---------------------------------------------------------------
    nv = cfg.setdefault("NVRAM", {})
    boot = nv.setdefault("Add", {}).setdefault(NVRAM_APPLE_BOOT, {})
    boot.update({
        "boot-args": BOOT_ARGS,
        "csr-active-config": b"\x00\x00\x00\x00",
        "prev-lang:kbd": b"en-US:0",
    })
    CHANGES.append("NVRAM/Add/boot-args: %r" % BOOT_ARGS)
    gui = nv["Add"].setdefault(NVRAM_APPLE_GUI, {})
    gui.update({"DefaultBackgroundColor": b"\x00\x00\x00\x00"})
    nv.setdefault("Delete", {})[NVRAM_APPLE_BOOT] = ["boot-args", "csr-active-config"]
    set_key(cfg, ["NVRAM", "WriteFlash"], True)

    # --- PlatformInfo --------------------------------------------------------
    set_key(cfg, ["PlatformInfo", "Automatic"], True)
    generic = cfg.setdefault("PlatformInfo", {}).setdefault("Generic", {})
    generic.update({
        "AdviseFeatures": True,
        "MaxBIOSVersion": False,
        "ProcessorType": 0,
        "SpoofVendor": True,
        "SystemMemoryStatus": "Auto",
        "SystemProductName": MODEL,
        "SystemUUID": str(uuid.uuid4()).upper(),
    })
    CHANGES.append("PlatformInfo/Generic: SMBIOS %s, UUID %s" % (MODEL, generic["SystemUUID"]))
    set_key(cfg, ["PlatformInfo", "UpdateDataHub"], True)
    set_key(cfg, ["PlatformInfo", "UpdateNVRAM"], True)
    set_key(cfg, ["PlatformInfo", "UpdateSMBIOSMode"], "Create")

    if args.macserial:
        serial, mlb = collect_serial(args.macserial)
        if serial:
            generic["SystemSerialNumber"] = serial
            if mlb:
                generic["MLB"] = mlb
            CHANGES.append("PlatformInfo/Generic: serial %s (MLB %s)" % (serial, mlb or "<blank>"))
        else:
            print("WARNING: macserial produced no usable serial - placeholders stay in config")
            print("         (generate later with GenSMBIOS on Windows or macserial on macOS)")
    else:
        print("WARNING: no macserial provided - serial/MLB placeholders stay in config")

    # --- UEFI ----------------------------------------------------------------
    if args.drivers:
        cfg.setdefault("UEFI", {})["Drivers"] = [
            {"Arguments": "", "Comment": "", "Enabled": True, "HideVerbose": False,
             "LoadEarly": False, "Path": d}
            for d in args.drivers
        ]
        CHANGES.append("UEFI/Drivers: " + ", ".join(args.drivers))

    for k, v in {
        "ForceOcWriteFlash": False,
        "RequestBootVarRouting": True,
        "ResizeGpuBars": -1,
        "ReleaseUsbOwnership": True,
        "UnblockFsConnect": False,
    }.items():
        set_key(cfg, ["UEFI", "Quirks", k], v)
    for k, v in {
        "ActivateHpetSupport": False,
        "EnableVmx": False,
        "ForgeUefiSupport": False,
        "IgnoreInvalidFlexRatio": False,
        "ReloadOptionRoms": False,
        "ResizeUsePciRbIo": False,
        "ShimRetainProtocol": False,
    }.items():
        set_if_present(cfg, ["UEFI", "Quirks", k], v)

    set_key(cfg, ["UEFI", "Output", "ProvideConsoleGop"], True)
    for k, v in {
        "ClearScreenOnModeSwitch": False,
        "DirectGopRendering": False,
        "UgaPassThrough": False,
    }.items():
        set_if_present(cfg, ["UEFI", "Output", k], v)
    set_if_present(cfg, ["UEFI", "Audio", "AudioSupport"], False)

    # --- write ---------------------------------------------------------------
    with open(args.out, "wb") as f:
        plistlib.dump(cfg, f, sort_keys=False, fmt=plistlib.FMT_XML)

    print("== applied changes (%d):" % len(CHANGES))
    for c in CHANGES:
        print("  " + c)
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
