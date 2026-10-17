#!/usr/bin/env python3
"""IrisProbe — hardware sniffer for the iris-xe-macos-driver project.

Reads the machine it runs on (Windows, stdlib only, no network) the way NullMoth's
1401-probe reads a PC, and writes four files into <project>/reports/:

  irisprobe-report.json    everything sniffed + analysis, machine-readable
  irisprobe-report.txt     human-readable summary
  iris-config.plist        OpenCore fragment for THIS machine (DeviceProperties + boot-args)
  iris-config-notes.md     how to merge it, BIOS settings, per-component macOS status

Privacy: serial numbers, UUIDs and network addresses are never collected, and the
EDID's serial is redacted in the parsed output (raw hex kept local-only).

usage: python irisprobe.py
"""
from __future__ import annotations

import datetime
import json
import os
import plistlib
import re
import socket
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUTDIR = os.path.join(ROOT, "reports")

VERSION = "0.1"


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------- powershell

def ps(script: str, timeout: int = 240):
    """Run a PowerShell snippet that must end in ConvertTo-Json; return parsed JSON."""
    wrapped = "chcp 65001 >$null; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8;" + script
    try:
        cp = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", wrapped],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except Exception as e:  # noqa: BLE001
        log(f"  ! powershell failed: {e}")
        return None
    txt = (cp.stdout or "").strip()
    if not txt:
        if (cp.stderr or "").strip():
            log(f"  ! ps stderr: {cp.stderr.strip()[:300]}")
        return None
    try:
        return json.loads(txt)
    except Exception as e:  # noqa: BLE001
        log(f"  ! bad json from powershell: {e}")
        return None


def one(x):
    """Normalize: single object -> [object]; None -> []."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


# --------------------------------------------------------------------------- sniff

def sniff_system():
    return ps(r"""
$sys  = Get-CimInstance Win32_ComputerSystem  | Select-Object Manufacturer,Model,SystemFamily,SystemSKUNumber,TotalPhysicalMemory;
$bios = Get-CimInstance Win32_BIOS            | Select-Object Manufacturer,SMBIOSBIOSVersion,Version,ReleaseDate;
$brd  = Get-CimInstance Win32_BaseBoard       | Select-Object Manufacturer,Product,Version;
$enc  = Get-CimInstance Win32_SystemEnclosure | Select-Object Manufacturer,ChassisTypes;
@{ system=$sys; bios=$bios; board=$brd; enclosure=$enc } | ConvertTo-Json -Depth 4
""")


def sniff_cpu_mem():
    return ps(r"""
$c = Get-CimInstance Win32_Processor     | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,Manufacturer;
$m = Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,Manufacturer,PartNumber,DeviceLocator;
@{ cpu=$c; memory=$m } | ConvertTo-Json -Depth 4
""")


def sniff_gpus_pci():
    return ps(r"""
$gpu = Get-CimInstance Win32_VideoController | Select-Object Name,PNPDeviceID,DriverVersion,VideoProcessor,AdapterCompatibility;
$pci = Get-CimInstance Win32_PnPEntity -Filter "PNPDeviceID LIKE 'PCI%'" |
       Select-Object Name,PNPDeviceID,PNPClass,Status,ConfigManagerErrorCode;
$loc = Get-PnpDevice -PresentOnly | Where-Object {
         $_.InstanceId -like 'PCI\VEN_8086*' -or $_.Class -in @('Display','SCSIAdapter','Net','Bluetooth')
       } | ForEach-Object {
         $l = $null;
         try { $l = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_LocationInfo' -ErrorAction Stop).Data } catch {}
         [pscustomobject]@{ InstanceId=$_.InstanceId; Class=$_.Class; Location=$l }
       };
@{ gpus=$gpu; pci=$pci; locations=$loc } | ConvertTo-Json -Depth 5
""", timeout=300)


def sniff_monitors():
    return ps(r"""
$a = Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorID             | Select-Object InstanceName,Active,ManufacturerName,ProductCodeID,UserFriendlyName;
$b = Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorConnectionParams | Select-Object InstanceName,VideoOutputTechnology;
$c = Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorBasicDisplayParams | Select-Object InstanceName,MaxHorizontalImageSize,MaxVerticalImageSize;
@{ monitors=$a; connections=$b; sizes=$c } | ConvertTo-Json -Depth 5
""")


def sniff_edids():
    return ps(r"""
$r = Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Enum\DISPLAY' -ErrorAction SilentlyContinue | ForEach-Object {
       $m = $_.PSChildName;
       Get-ChildItem $_.PSPath -ErrorAction SilentlyContinue | ForEach-Object {
         $e = (Get-ItemProperty -Path ($_.PSPath + '\Device Parameters') -Name EDID -ErrorAction SilentlyContinue).EDID;
         if ($e) { [pscustomobject]@{ Monitor=$m; Instance=$_.PSChildName;
                   EdidHex=([BitConverter]::ToString($e) -replace '-','') } }
       }
     };
$r | ConvertTo-Json -Depth 4
""")


def sniff_misc():
    return ps(r"""
$bat = Get-CimInstance Win32_Battery      | Select-Object Name,DesignCapacity,FullChargeCapacity,EstimatedChargeRemaining,Chemistry;
$snd = Get-CimInstance Win32_SoundDevice  | Select-Object Name,Manufacturer;
try { $disk = Get-PhysicalDisk | Select-Object FriendlyName,BusType,MediaType,Size } catch { $disk = $null }
$bw = @{};
try { $bw.Design = (Get-CimInstance -Namespace root\wmi -ClassName BatteryStaticData          -ErrorAction Stop).DesignedCapacity    } catch {}
try { $bw.Full   = (Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity -ErrorAction Stop).FullChargedCapacity } catch {}
try { $bw.Cycles = (Get-CimInstance -Namespace root\wmi -ClassName BatteryCycleCount         -ErrorAction Stop).CycleCount           } catch {}
$bt = Get-CimInstance Win32_PnPEntity -Filter "PNPClass='Bluetooth'" | Select-Object Name,PNPDeviceID;
@{ battery=$bat; sound=$snd; disks=$disk; battery_wmi=$bw; bluetooth=$bt } | ConvertTo-Json -Depth 4
""")


# --------------------------------------------------------------------------- parsing

PNP_RE = re.compile(r"VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})(?:&SUBSYS_([0-9A-F]{8}))?(?:&REV_([0-9A-F]{2}))?", re.I)


def parse_pnp(instance_id: str) -> dict:
    m = PNP_RE.search(instance_id or "")
    if not m:
        return {}
    ven, dev, subsys, rev = m.groups()
    out = {"vendor_id": int(ven, 16), "device_id": int(dev, 16)}
    if subsys:
        out["subsystem_id"] = int(subsys[:4], 16)        # SUBSYS_AABBCCDD: AABB=subsys id, CCDD=subsys vendor
        out["subsystem_vendor_id"] = int(subsys[4:], 16)
    if rev:
        out["revision"] = int(rev, 16)
    return out


LOC_RE = re.compile(r"PCI bus (\d+), device (\d+), function (\d+)")


def parse_location(text: str):
    m = LOC_RE.search(text or "")
    if not m:
        return None
    return tuple(int(g) for g in m.groups())


def parse_edid(b: bytes) -> dict | None:
    if len(b) < 128 or b[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return None
    mfg = (b[8] << 8) | b[9]
    letters = "".join(chr(((mfg >> off) & 0x1F) + 64) for off in (10, 5, 0))
    d = b[54:72]  # first detailed timing descriptor = preferred mode
    pclk_khz = ((d[1] << 8) | d[0]) * 10
    hact = d[2] | ((d[4] & 0xF0) << 4)
    hbl = d[3] | ((d[4] & 0x0F) << 8)
    vact = d[5] | ((d[7] & 0xF0) << 4)
    vbl = d[6] | ((d[7] & 0x0F) << 8)
    htotal, vtotal = hact + hbl, vact + vbl
    refresh = round(pclk_khz * 1000 / (htotal * vtotal), 2) if htotal and vtotal else None
    def clean(t: bytes) -> str:
        s = "".join(chr(c) if 32 <= c < 127 else " " for c in t)
        return " ".join(s.split())

    name_fc, name_fe = None, None
    for i in range(54, 126, 18):
        desc = b[i:i + 18]
        if desc[0:3] == b"\x00\x00\x00":
            txt = clean(desc[5:18])
            if desc[3] == 0xFC and txt and not name_fc:
                name_fc = txt
            elif desc[3] == 0xFE and txt and not name_fe:
                name_fe = txt
    name = name_fc or name_fe  # some panels (AUO on Dell) only carry the 0xFE string descriptor
    return {
        "vendor": letters,
        "product_code": (b[11] << 8) | b[10],
        "serial": "<redacted>",
        "manufactured": f"week {b[16]}, {1990 + b[17]}",
        "edid_version": f"{b[18]}.{b[19]}",
        "size_cm": [b[21], b[22]],
        "preferred_mode": {
            "h_visible": hact, "v_visible": vact, "pixel_clock_khz": pclk_khz,
            "refresh_hz": refresh, "h_total": htotal, "v_total": vtotal,
        },
        "monitor_name": name,
    }


NO_DRIVER = "none — no macOS driver exists for Gen12 iGPUs"
KNOWN_INTEL_DISPLAY = {
    0x9A49: ("Iris Xe Graphics (Tiger Lake-UP3 GT2)", 12),
    0x9A40: ("Iris Xe Graphics (Tiger Lake-UP3 GT2)", 12),
    0x9A59: ("Iris Xe Graphics (Tiger Lake-UP3 GT2)", 12),
    0x9A60: ("UHD Graphics (Tiger Lake-H GT1)", 12),
    0x9A68: ("UHD Graphics (Tiger Lake-H GT1)", 12),
    0x9A70: ("UHD Graphics (Tiger Lake-H GT1)", 12),
}


def atoi_or_none(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- analyze

def analyze(data: dict) -> dict:
    a: dict = {"target": {}, "components": [], "warnings": []}
    pci = data.get("pci", {})
    locs = {e.get("InstanceId"): e.get("Location") for e in data.get("locations", [])}

    # iGPU: Intel display-class device
    for d in pci:
        ids = parse_pnp(d.get("PNPDeviceID", ""))
        if ids.get("vendor_id") != 0x8086:
            continue
        if (d.get("PNPClass") or "") != "Display":
            continue
        dev = ids["device_id"]
        name, disp_ver = KNOWN_INTEL_DISPLAY.get(dev, ("Intel display device", None))
        loc = parse_location(locs.get(d.get("PNPDeviceID", "")) or "")
        a["target"] = {
            "igpu_name": d.get("Name") or name,
            "igpu_device_id": f"0x{dev:04X}",
            "igpu_subsystem_id": f"0x{ids.get('subsystem_id', 0):04X}",
            "igpu_subsystem_vendor_id": f"0x{ids.get('subsystem_vendor_id', 0):04X}",
            "family": name,
            "display_version": disp_ver,
            "pci_location": f"{loc[0]:04d}:{loc[1]:02d}.{loc[2]}" if loc else None,
            "opencore_path": f"PciRoot(0x{loc[0]//16})/Pci(0x{loc[1]:X},0x{loc[2]:X})" if loc else None,
            "macos_driver": NO_DRIVER,
        }
        break

    # components worth a macOS-support verdict
    for d in pci:
        ids = parse_pnp(d.get("PNPDeviceID", ""))
        ven, dev = ids.get("vendor_id"), ids.get("device_id")
        if ven is None:
            continue
        name = d.get("Name") or ""
        cls = d.get("PNPClass") or ""
        nl = name.lower()
        verdict = None
        if ven == 0x8086 and dev in KNOWN_INTEL_DISPLAY:
            verdict = "iGPU — this project's target (display Phase 1 first; acceleration is research)"
        elif "wi-fi" in nl or "wireless" in nl:
            verdict = "works with itlwm + HeliPort (OpenIntelWireless)" if ven == 0x8086 else "check chipset support"
        elif "bluetooth" in nl:
            verdict = "works with IntelBluetoothFirmware + BlueToolFixup" if ven == 0x8086 else "check support"
        elif cls == "Net" or "ethernet" in nl:
            verdict = "IntelMausi kext" if ven == 0x8086 else ("RealtekRTL8111 kext" if ven == 0x10EC else "check support")
        elif "thunderbolt" in nl or "usb4" in nl:
            verdict = "not supported on macOS (basic USB behind it may work)"
        elif cls == "Media" or "audio" in nl or "smart sound" in nl:
            verdict = "AppleALC (find the working layout-id by testing); shows as HDEF in macOS"
        elif "card reader" in nl or "sd host" in nl:
            verdict = "usually unsupported"
        elif cls == "HDC" or "nvme" in nl:
            verdict = "native"
        if verdict:
            a["components"].append({"name": name, "device": f"{ven:04X}:{dev:04X}", "verdict": verdict})

    for b in data.get("bluetooth", []):
        nm = b.get("Name") or ""
        vid = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", b.get("PNPDeviceID", ""), re.I)
        dev = f"{vid.group(1)}:{vid.group(2)}" if vid else "?"
        verdict = ("IntelBluetoothFirmware + BlueToolFixup" if "intel" in nm.lower()
                   else "check support (may need firmware kext)")
        a["components"].append({"name": nm, "device": f"USB {dev}", "verdict": verdict})

    # panel(s)
    for m in data.get("monitors", []):
        conn = m.get("connection", {})
        tech = conn.get("VideoOutputTechnology")
        m["internal"] = tech in (0x80000000, 11)  # INTERNAL flag / embedded DisplayPort
    if not any(m.get("internal") for m in data.get("monitors", [])):
        a["warnings"].append("no monitor reported as internal/eDP — check edid parsing")

    a["smbios_suggestion"] = "MacBookPro16,2"
    a["plan"] = {
        "phase_c": "boot macOS via OpenCore, then build IXFB display Phase 1 (firmware-lit pipe takeover)",
        "phase_d": "IXRM kernel driver + Mesa ANV port + IXMTLDriver.bundle (research)",
    }
    return a


# --------------------------------------------------------------------------- outputs

def pci_root_from_location(location: tuple) -> str:
    bus, dev, fn = location
    return f"PciRoot(0x{bus // 16})/Pci(0x{dev:X},0x{fn:X})"


def write_plist(data: dict) -> str:
    t = data["analysis"]["target"]
    cfg = {"DeviceProperties": {"Add": {}}}
    if t.get("pci_location"):
        loc = tuple(int(x) for x in re.split(r"[:.]", t["pci_location"]))
        dev_id = int(t["igpu_device_id"], 16)
        subsys = int(t["igpu_subsystem_id"], 16)
        subsys_ven = int(t["igpu_subsystem_vendor_id"], 16)
        cfg["DeviceProperties"]["Add"][pci_root_from_location(loc)] = {
            "device-id": dev_id.to_bytes(4, "little"),
            "subsystem-id": subsys.to_bytes(4, "little"),
            "subsystem-vendor-id": subsys_ven.to_bytes(4, "little"),
            "model": t["igpu_name"],
        }
    cfg["NVRAM"] = {"Add": {"7C436110-AB2A-4BBB-A880-FE41995C9F82": {
        "boot-args": "-v debug=0x100 keepsyms=1",
    }}}
    path = os.path.join(OUTDIR, "iris-config.plist")
    with open(path, "wb") as f:
        plistlib.dump(cfg, f, fmt=plistlib.FMT_XML, sort_keys=False)
    return path


def write_notes(data: dict) -> str:
    t = data["analysis"]["target"]
    sysinfo = data.get("system", {})
    lines = [
        "# iris-config-notes — generated by IrisProbe",
        "",
        f"Machine: **{sysinfo.get('Manufacturer', '?')} {sysinfo.get('Model', '?')}**, "
        f"CPU: **{(data.get('cpu') or [{}])[0].get('Name', '?')}**, "
        f"iGPU: **{t.get('igpu_name', '?')}** (`{t.get('igpu_device_id', '?')}`, "
        f"subsys `{t.get('igpu_subsystem_id', '?')}`/`{t.get('igpu_subsystem_vendor_id', '?')}`)",
        "",
        "## Merging `iris-config.plist` into OpenCore",
        "",
        "1. Back up your `EFI/OC/config.plist`.",
        "2. In ProperTree (or any plist editor), copy:",
        "   - `DeviceProperties > Add` entries into your config's same section,",
        "   - `NVRAM > Add > 7C436110-…` values into your config's same section.",
        "3. Add `boot-args` to `NVRAM > Delete` as well so the value is rewritten each boot.",
        "4. This fragment contains **no driver flags yet** — `iris=1 …` flags will appear here",
        "   once the project's kexts exist (see `docs/ROADMAP.md`).",
        "",
        "## BIOS settings for a Latitude 5420 (enable macOS)",
        "",
        "| Setting | Value |",
        "|---|---|",
        "| Secure Boot | **Disabled** (required) |",
        "| SATA Operation | AHCI |",
        "| TPM / PTT | Disabled (recommended) |",
        "| CFG Lock | Disable if the BIOS offers it, else keep AppleXcpmCfgLock quirk |",
        "| VT-d | may stay on with `DisableIoMapper` quirk |",
        "| Fast Boot | Thorough / off |",
        "",
        "## What works on macOS for this machine (today)",
        "",
        "| Component | Status |",
        "|---|---|",
    ]
    for c in data["analysis"]["components"]:
        lines.append(f"| {c['name']} (`{c['device']}`) | {c['verdict']} |")
    lines += [
        "",
        "## The big two",
        "",
        "- **Display**: no native driver. Plan: `IXFB` Phase 1 (take over the firmware-lit pipe —",
        "  NullMoth's `NMIntelFB` already targets display v12 = Tiger Lake; ours follows the same method).",
        "- **Metal acceleration**: does not exist anywhere for Gen12 iGPUs on macOS. This project",
        "  mirrors the NullMoth stack (translator → Mesa **ANV** → new `IXRM` kernel driver → `IXMTLDriver.bundle`).",
        "  Research horizon, not a weekend. See `docs/ROADMAP.md`.",
        "",
        f"Suggested SMBIOS: `{data['analysis'].get('smbios_suggestion', 'MacBookPro16,2')}`.",
        "",
        "## Redaction",
        "",
        "No serial numbers, UUIDs or MAC addresses were collected by IrisProbe. The EDID serial is",
        "redacted in the parsed monitor data; the raw EDID hex stays local in this report only.",
        "",
    ]
    path = os.path.join(OUTDIR, "iris-config-notes.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def write_text_report(data: dict) -> str:
    t = data["analysis"]["target"]
    out = [
        "IrisProbe report",
        f"tool {VERSION} · {data['probe']['timestamp']} · host {data['probe']['host']}",
        "=" * 72, "",
        f"Machine : {data.get('system', {}).get('Manufacturer')} {data.get('system', {}).get('Model')}",
        f"CPU     : {(data.get('cpu') or [{}])[0].get('Name')}",
        f"RAM     : {int(data.get('system', {}).get('TotalPhysicalMemory') or 0) / 2**30:.1f} GiB",
        f"BIOS    : {data.get('bios', {}).get('SMBIOSBIOSVersion')}",
        "",
        "iGPU target",
        "-" * 72,
        f"  name            : {t.get('igpu_name')}",
        f"  device id       : {t.get('igpu_device_id')}   (subsys {t.get('igpu_subsystem_id')} / vendor {t.get('igpu_subsystem_vendor_id')})",
        f"  family          : {t.get('family')}   display version {t.get('display_version')}",
        f"  PCI location    : {t.get('pci_location')}",
        f"  OpenCore path   : {t.get('opencore_path')}",
        f"  macOS driver    : {t.get('macos_driver')}",
        "",
        "Displays",
        "-" * 72,
    ]
    for m in data.get("monitors", []):
        edid = m.get("edid") or {}
        pm = edid.get("preferred_mode") or {}
        pc = edid.get("product_code") or 0
        size = edid.get("size_cm") or [0, 0]
        out.append(f"  {edid.get('monitor_name') or '?'} · {edid.get('vendor', '?')} {pc:04X} · "
                   f"{pm.get('h_visible')}x{pm.get('v_visible')} @ {pm.get('refresh_hz')} Hz · "
                   f"{'internal/eDP' if m.get('internal') else 'external'} · {size[0]}x{size[1]} cm")
    out += ["", "PCI components and macOS verdicts", "-" * 72]
    for c in data["analysis"]["components"]:
        out.append(f"  {c['device']}  {c['name']}")
        out.append(f"           -> {c['verdict']}")
    out += ["", "Storage", "-" * 72]
    for d in data.get("disks", []):
        out.append(f"  {d.get('FriendlyName')} · {d.get('BusType')} · {int(d.get('Size') or 0) / 2**30:.0f} GB")
    out += ["", "Battery", "-" * 72]
    for b in data.get("battery", []):
        out.append(f"  {b.get('Name')} · design {b.get('DesignCapacity')} · full {b.get('FullChargeCapacity')}")
    bw = data.get("battery_wmi") or {}
    extra = ", ".join(f"{k}={v}" for k, v in bw.items() if v)
    if extra:
        out.append(f"  (root\\wmi: {extra})")
    out += ["", "Bluetooth", "-" * 72]
    for b in data.get("bluetooth", []):
        out.append(f"  {b.get('Name')} · {b.get('PNPDeviceID')}")
    out += ["", "Audio", "-" * 72]
    for s in data.get("sound", []):
        out.append(f"  {s.get('Name')} · {s.get('Manufacturer')}")
    out += ["", "Next: docs/ROADMAP.md (Phase C: boot macOS, IXFB display; Phase D: acceleration research)", ""]
    path = os.path.join(OUTDIR, "irisprobe-report.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return path


# --------------------------------------------------------------------------- main

def main() -> int:
    os.makedirs(OUTDIR, exist_ok=True)
    data: dict = {"probe": {"tool": "irisprobe", "version": VERSION,
                            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                            "host": socket.gethostname()}}
    log("irisprobe: reading machine...")

    log("  system / bios / board...")
    s = sniff_system() or {}
    data.update(system=one(s.get("system"))[0] if s.get("system") else {},
                bios=one(s.get("bios"))[0] if s.get("bios") else {},
                board=one(s.get("board"))[0] if s.get("board") else {},
                enclosure=one(s.get("enclosure"))[0] if s.get("enclosure") else {})

    log("  cpu / memory...")
    cm = sniff_cpu_mem() or {}
    data.update(cpu=one(cm.get("cpu")), memory=one(cm.get("memory")))

    log("  gpus / pci tree...")
    gp = sniff_gpus_pci() or {}
    data.update(gpus=one(gp.get("gpus")), pci=one(gp.get("pci")), locations=one(gp.get("locations")))

    log("  monitors...")
    mo = sniff_monitors() or {}
    monitors = one(mo.get("monitors"))
    conns = {c.get("InstanceName"): c for c in one(mo.get("connections"))}
    sizes = {c.get("InstanceName"): c for c in one(mo.get("sizes"))}
    for m in monitors:
        m["connection"] = conns.get(m.get("InstanceName"), {})
        m["size"] = sizes.get(m.get("InstanceName"), {})

    log("  edid (registry)...")
    edids = one(sniff_edids())
    for m in monitors:
        key = (m.get("InstanceName") or "")
        code = key.split("\\")[1] if "\\" in key else None
        for e in edids:
            if code and e.get("Monitor") == code:
                try:
                    m["edid"] = parse_edid(bytes.fromhex(e.get("EdidHex") or ""))
                    m["edid_hex"] = e.get("EdidHex")
                except ValueError:
                    pass
                break
    data["monitors"] = monitors

    log("  battery / sound / disks...")
    misc = sniff_misc() or {}
    data.update(battery=one(misc.get("battery")), sound=one(misc.get("sound")),
                disks=one(misc.get("disks")), bluetooth=one(misc.get("bluetooth")),
                battery_wmi=misc.get("battery_wmi") or {})

    log("analyzing...")
    data["analysis"] = analyze(data)

    rj = os.path.join(OUTDIR, "irisprobe-report.json")
    with open(rj, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    rt = write_text_report(data)
    rp = write_plist(data)
    rn = write_notes(data)
    log("")
    for p in (rj, rt, rp, rn):
        log(f"wrote {p}")
    t = data["analysis"]["target"]
    log("")
    log(f"target: {t.get('igpu_name')} {t.get('igpu_device_id')} at {t.get('pci_location')} "
        f"(display v{t.get('display_version')}), panel: "
        + ", ".join((m.get('edid') or {}).get('monitor_name') or '?' for m in monitors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
