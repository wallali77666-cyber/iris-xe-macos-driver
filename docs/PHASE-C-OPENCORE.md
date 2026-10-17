# Phase C — OpenCore EFI for the Latitude 5420 (and other Iris Xe laptops)

Status: **the EFI is produced and validated by CI** (workflow `efi`); first hardware
boot is the next step and is debugged from logs the machine writes to the USB stick.

Quick order of operations (everything cheap comes first):

```
1. download iris-xe-efi          ~4 MB   Actions -> efi -> latest run -> Artifacts
2. put EFI/ on a FAT32 USB       secs    section 2 below (Win+R -> diskpart)
   no USB stick?  section 2b: the internal disk does the same job
3. when YOU say go: Recovery    ~650-700 MB  macrecovery, section 2.4 (size confirmed first)
4. BIOS + boot + install                 sections 3-4; send back the ESP logs if off
5. later, validation: Linux live USB -> ixcheck -> compare   (docs/IXCHECK.md)
```

This document is the real-machine half of Phase C. Everything listed here is
built by `.github/workflows/efi.yml` — your laptop downloads nothing until the
step marked **⬇ big download** below.

## 1. What the CI artifact contains

Artifact `iris-xe-efi` (Actions → `efi` → the run → Artifacts) =
`iris-xe-efi.zip` — **~4 MB download**:

```
EFI/BOOT/BOOTx64.efi        OpenCore bootloader
EFI/OC/OpenCore.efi         OpenCore core
EFI/OC/Drivers/             OpenRuntime, OpenHfsPlus, ResetNvramEntry
EFI/OC/Kexts/               Lilu, VirtualSMC(+Processor+BatteryManager),
                            WhateverGreen, AppleALC, IntelMausi,
                            IXFB.kext, IXRM.kext   <- our kexts, injected by OpenCore
EFI/OC/ACPI/SSDT-PLUG.aml   CPU power management
EFI/OC/config.plist         generated from the OpenCore release's own Sample.plist
VERSIONS.txt                exact versions of every component in this build
```

`IXFB` being injected here matters: it claims the panel **during the installer**, so
the macOS UI has a display even though no Apple driver supports Tiger Lake.

## 2. Make the USB (Windows)

1. USB stick, 8 GB or more. It will be wiped.
2. `Win+R` → `cmd` → `diskpart`:

   ```
   list disk            (find your USB disk number)
   select disk N
   clean
   convert mbr
   create partition primary
   format fs=fat32 quick
   assign
   exit
   ```

3. Unzip `iris-xe-efi.zip`, copy the `EFI` folder to the USB root.
   Result: `USB:\EFI\BOOT\BOOTx64.efi` …
4. macOS Recovery (**⬇ ~650–700 MB download** — do this only when you are ready;
   exact size depends on Apple):
   - get `macrecovery.py` from OpenCorePkg (`Utilities/macrecovery/`) — a few KB;
   - run:

     ```
     python macrecovery.py -b Mac-27AD2F918AE68F61 -m 00000000000000000 download
     ```

     It creates `com.apple.recovery.boot\` (BaseSystem.dmg + .contentDetails).
   - copy that folder next to `EFI` on the USB.
   - If Apple rejects the board id (error instead of download), stop and tell me —
     the id is fixed in CI, not on your side.

Final USB layout:

```
USB:\EFI\...                              (from the CI zip)
USB:\com.apple.recovery.boot\...          (from macrecovery)
```

## 2b. No USB stick? Use the internal disk instead

Everything the stick would carry can live on the laptop's own disk, and every
piece of it is additive and removable:

- `EFI\OC` → the **EFI system partition** (ESP) Windows already has, with a
  dedicated *OpenCore* firmware entry (Windows Boot Manager stays untouched)
- `com.apple.recovery.boot` → the **SHARE** FAT32 partition made for ixcheck
  (needs ~1 GB free; only the recovery folder goes there)

**Shortcut:** `tools\efi\install-opencore-esp.cmd` (double-click, accept UAC)
performs 2b.1 and 2b.2 in one step — it mounts the ESP, refreshes `EFI\OC`,
registers the firmware entry, prints ESP free space and the undo commands, and
never touches `EFI\Microsoft` / `EFI\BOOT`. The manual steps below remain the
reference (and the fallback if the script's output shows anything unexpected).

### 2b.1 Copy OpenCore to the ESP

Get the artifact as in section 1 and unzip it somewhere convenient (Desktop is
fine). Then, in an **Administrator** cmd window:

```
mountvol S: /S                    & rem  mounts the ESP read/write at S: (any free letter)
xcopy /e /i "<unzipped>\EFI\OC" S:\EFI\OC
mountvol S: /D                    & rem  unmount when done
```

Rules that keep this safe:

- **only** `EFI\OC` goes to the ESP. Never touch `S:\EFI\Microsoft` (Windows)
  or `S:\EFI\BOOT` (the fallback loader). There is no reason to copy
  `EFI\BOOT` from the zip on this route.
- if `S:\EFI\OC` already exists from an earlier attempt, delete it first —
  it's ours and gets replaced wholesale every time.

### 2b.2 Add the "OpenCore" firmware entry (additive, reversible)

```
bcdedit /copy {bootmgr} /d "OpenCore"
```

It prints a brand-new `{guid}`; feed that guid back:

```
bcdedit /set {guid} path \EFI\OC\OpenCore.efi
bcdedit /enum firmware        & rem  verify: "OpenCore" -> \EFI\OC\OpenCore.efi
```

Boot it via `F12` → boot menu → **OpenCore**. (Optional:
`bcdedit /set {fwbootmgr} displayorder {guid} /addfirst` makes it first in the
firmware order — I'd wait with that; F12 keeps Windows in charge until macOS
actually boots. If F12 doesn't list it yet, one clean Windows shutdown +
power-on usually syncs the firmware variables.)

Fully uninstallable any time: `bcdedit /delete {guid}` plus deleting
`S:\EFI\OC`.

### 2b.3 Recovery onto SHARE

Download it exactly as in section 2 step 4 (**⬇ ~650–700 MB — only when you
say go; nothing above has pulled a byte yet**) and copy the resulting folder
`com.apple.recovery.boot` to the root of the SHARE partition. Explorer gives
the partition its own drive letter; open it and drop the folder next to the
existing `ixcheck` files. Leave the partition FAT32.

### 2b.4 Boot, and where the logs land

As in section 4: `F12` → OpenCore → pick **macOS Base System** (the picker
lists it because a plain FAT32 volume carries the recovery folder — no stick
involved). OpenCore's and the installer's logs now land on the internal ESP;
`mountvol S: /S` again and read `S:\EFI\opencore-*.txt` and `S:\SysReport\`,
then send those over as usual.

## 3. BIOS (Latitude 5420)

| Setting | Value |
|---|---|
| Secure Boot | Disabled (required) |
| SATA Operation | AHCI |
| TPM / PTT | Disabled (recommended) |
| CFG Lock | Disable if offered, otherwise the config's AppleXcpmCfgLock covers it |
| VT-d | may stay on (config sets DisableIoMapper) |
| Fast Boot | Thorough / off |

Recommended: update the BIOS to the latest Dell release first — display
bring-up depends on the firmware leaving the panel lit when it hands off.

## 4. Boot

1. Plug in the USB, power on, `F12` → boot menu → the USB.
2. OpenCore text picker appears. Pick **macOS Base System**.
3. Verbose text scrolls. The installer UI should appear (slowly — no
   acceleration). If the screen goes black after the Apple logo phase,
   **the machine is still running**: see §5.

## 5. If something goes wrong (it will be debugged from logs)

The config writes its logs to the ESP it booted from (stick or internal):

- `EFI\opencore-*.txt` — OpenCore's own log
- `SysReport\` — ACPI table dump (fixes SSDT names, EC/AWAC decisions)
- kernel-side: boot is already `-v debug=0x100 keepsyms=1`; the `IXFB:` and `IXRM:`
  lines are the interesting ones

- To boot with the panel left entirely to the firmware (IXFB disabled), add
  `-ixfboff` to `boot-args` — useful when bisecting a bad screen.

Send me those files after a failed attempt; every iteration happens in CI/config,
nothing on your side changes except the USB.

### Quirks we picked, and the fallbacks

| Where | Value | If boot stalls, try |
|---|---|---|
| Booter › SetupVirtualMap | true | very early hang (`OCB:` lines) → false |
| Booter › DevirtualiseMmio | false | early hang after memory map → true |
| Booter › RebuildAppleMemoryMap | true | keep |
| Booter › SyncRuntimePermissions | true | keep (needed on most TGL boards) |
| Booter › ProtectUefiServices | true | keep |
| Booter › EnableWriteUnprotector | false | keep |
| Kernel › AppleXcpmCfgLock | true | keep (Dell BIOS hides the toggle) |
| Kernel › DisableIoMapper | true | keep (VT-d stays enabled in BIOS) |
| Misc › SecureBootModel | Disabled | required — our kexts are unsigned |
| Misc › ScanPolicy | 0 | keep (shows every volume) |
| SMBIOS | MacBookPro16,2 | serials generated in CI when macserial is available |

Change one thing at a time and keep the log files — that is the whole loop.

## 6. After the installer finishes

1. Reboot into the installed system (the same EFI works — USB or the
   section 2b internal-disk entry).
2. That first boot is Phase C step 2: compare the `IXFB:` log lines against the
   `tools/ixplan` plan (expected for B140HAK: format 8 = XRGB8888, stride 0x78,
   HTOTAL/VTOTAL from `ixplan.py`). The log prints what the firmware left lit.
3. Nothing to install: the EFI already loads IXFB/IXRM on every boot.
   `package/install.sh` exists only for the optional /Library/Extensions route
   (see its header — the injected path is the supported one).
4. Optional, later, each with size reported first: Wi-Fi (`itlwm` + HeliPort),
   Bluetooth (`IntelBluetoothFirmware` + `BlueToolFixup`), USB map (USBToolBox).

## 7. Deliberately not in this EFI yet

- `SSDT-USBX`, `SSDT-AWAC`, `SSDT-PNLF` — they need the machine's real ACPI tables;
  they come out of the `SysReport\` dump of this first boot.
- OpenCanopy GUI picker/themes — the text picker is enough for bring-up.
- Serial numbers, if `macserial` was unavailable in the CI run — generate later
  with GenSMBIOS (Windows) and paste 3 values into `PlatformInfo › Generic`.

Sources of truth: `tools/efi/assemble.sh` (what gets downloaded/bundled),
`tools/efi/configure.py` (every config value we set, with reasons),
`VERSIONS.txt` inside the zip (what you actually got).
