# install-opencore-share.ps1 - turn the internal 1 GB FAT32 partition (SHARE,
# drive G:) into a self-contained OpenCore boot medium. The ESP and Windows
# Boot Manager are never touched.
#
#   1. formats it FAT32 (first run; skipped afterwards unless -ForceFormat)
#   2. installs the staged EFI: EFI\OC + EFI\BOOT\BOOTX64.EFI (= OpenCore.efi)
#   3. copies the staged macOS Recovery folder (com.apple.recovery.boot) if the
#      download has completed and the image is intact
#   4. registers firmware boot entry "OpenCore" pointing at
#      G:\EFI\OC\OpenCore.efi, appended to the boot order (Windows stays first)
#
# Run via install-opencore-share.cmd (self-elevating, double-click).

param(
    [string]$Volume   = 'G:',
    [string]$Label    = 'SHARE',
    [string]$EfiStage = "$env:TEMP\opencode\efi-stage",
    [string]$RecStage = "$env:TEMP\opencode\recovery",
    [switch]$ForceFormat
)

$ErrorActionPreference = 'Stop'
$letter = $Volume.TrimEnd(':')

function Test-RecoveryStaged {
    param([string]$Root)
    $dir = Join-Path $Root 'com.apple.recovery.boot'
    if (-not (Test-Path $dir)) { return $false }
    $dmg = Get-ChildItem $dir -Filter '*.dmg' | Select-Object -First 1
    $cnk = Get-ChildItem $dir -Filter '*.chunklist' | Select-Object -First 1
    if (-not $dmg -or -not $cnk) { return $false }
    try {
        $b = [System.IO.File]::ReadAllBytes($cnk.FullName)
        if ($b.Length -lt 0x24) { return $false }
        if ([System.Text.Encoding]::ASCII.GetString($b, 0, 4) -ne 'CNKL') { return $false }
        $count = [int][BitConverter]::ToUInt64($b, 12)
        [uint64]$sum = 0
        for ($i = 0; $i -lt $count; $i++) {
            $sum += [BitConverter]::ToUInt32($b, 0x24 + $i * 0x24)
        }
        return ([uint64](Get-Item $dmg.FullName).Length -eq $sum)
    } catch {
        return $false
    }
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host 'ERROR: run this in an elevated PowerShell (right-click > Run as administrator).'
    exit 1
}

$vol = Get-Volume -DriveLetter $letter -ErrorAction SilentlyContinue
if (-not $vol) { Write-Host "ERROR: volume $Volume not found."; exit 1 }
if ($vol.Size -gt 2GB) {
    Write-Host ("ERROR: {0} is {1} GB - that is not the 1 GB SHARE partition. Refusing." -f $Volume, [math]::Round($vol.Size / 1GB, 2))
    exit 1
}
if (-not (Test-Path (Join-Path $EfiStage 'EFI\OC\OpenCore.efi'))) {
    Write-Host "ERROR: no staged EFI at $EfiStage\EFI\OC\OpenCore.efi"
    Write-Host 'Stage it first: gh run download <run-id> -n iris-xe-efi -D <dir>, then unzip.'
    exit 1
}

Write-Host ("[1/5] volume {0}: {1} GB, label '{2}'" -f $Volume, [math]::Round($vol.Size / 1GB, 2), $vol.FileSystemLabel)
$ourLayout = Test-Path "${Volume}\EFI\OC\OpenCore.efi"
if ($ForceFormat -or -not $ourLayout) {
    Write-Host ("      formatting FAT32 (label {0}) ..." -f $Label)
    try {
        Format-Volume -DriveLetter $letter -FileSystem FAT32 -NewFileSystemLabel $Label -Confirm:$false | Out-Null
    } catch {
        Write-Host "ERROR: format failed: $($_.Exception.Message)"
        Write-Host 'Is Explorer or a terminal sitting inside G:? Close it and run again.'
        exit 1
    }
    Write-Host '      formatted.'
} else {
    Write-Host '      our layout already present - skipping format (use -ForceFormat to wipe).'
}

Write-Host '[2/5] EFI\OC ...'
robocopy (Join-Path $EfiStage 'EFI\OC') "${Volume}\EFI\OC" /E /NFL /NDL /NJH /NJS /NP /R:2 /W:2 | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy EFI\OC failed (exit $LASTEXITCODE)" }
if (Test-Path (Join-Path $EfiStage 'VERSIONS.txt')) {
    Copy-Item (Join-Path $EfiStage 'VERSIONS.txt') "${Volume}\VERSIONS.txt" -Force
}
Write-Host '      installed.'

Write-Host '[3/5] EFI\BOOT\BOOTX64.EFI (fallback boot path - a copy of OpenCore.efi) ...'
New-Item -ItemType Directory -Force "${Volume}\EFI\BOOT" | Out-Null
Copy-Item "${Volume}\EFI\OC\OpenCore.efi" "${Volume}\EFI\BOOT\BOOTX64.EFI" -Force
Write-Host '      installed.'

Write-Host '[4/5] macOS Recovery ...'
if (Test-RecoveryStaged -Root $RecStage) {
    $recDir = Join-Path $RecStage 'com.apple.recovery.boot'
    $recSize = (Get-ChildItem $recDir -File | Measure-Object -Property Length -Sum).Sum
    $free = (Get-Volume -DriveLetter $letter).SizeRemaining
    Write-Host ("      staged + verified: {0} MB   free on {1}: {2} MB" -f [math]::Round($recSize / 1MB, 1), $Volume, [math]::Round($free / 1MB, 1))
    if ($free -lt ($recSize + 5MB)) {
        Write-Host '      WARNING: it does not fit - NOT copied.'
        Write-Host '      (the boot test still works; tell Claude before installing)'
    } else {
        robocopy $recDir "${Volume}\com.apple.recovery.boot" /E /NFL /NDL /NJH /NJS /NP /R:2 /W:2 | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy recovery failed (exit $LASTEXITCODE)" }
        Write-Host ("      copied. free now: {0} MB" -f [math]::Round((Get-Volume -DriveLetter $letter).SizeRemaining / 1MB, 1))
    }
} else {
    Write-Host '      no complete staged recovery yet - skipping (run add-recovery.cmd later).'
}

Write-Host '[5/5] firmware boot entry ...'
$stateFile = Join-Path $env:TEMP 'opencode\opencore-entry.guid'
$guid = $null
if (Test-Path $stateFile) {
    $cand = (Get-Content $stateFile -Raw).Trim()
    if ($cand -match '^\{[0-9a-fA-F-]{36}\}$') {
        $probe = (bcdedit /enum $cand 2>&1 | Out-String)
        if ($probe -match 'identifier\s+\{') {
            $guid = $cand
            Write-Host "      reusing entry $guid"
        }
    }
}
if (-not $guid) {
    $out = (bcdedit /copy '{bootmgr}' /d 'OpenCore' 2>&1 | Out-String)
    if ($out -notmatch '\{[0-9a-fA-F-]{36}\}') { throw "bcdedit /copy failed: $out" }
    $guid = $Matches[0]
    New-Item -ItemType Directory -Force (Split-Path $stateFile) | Out-Null
    Set-Content -Path $stateFile -Value $guid -Encoding ascii
    Write-Host "      created entry $guid"
}

Write-Host ('      device: ' + (bcdedit /set $guid device partition=$Volume 2>&1 | Out-String).Trim())
Write-Host ('      path:   ' + (bcdedit /set $guid path '\EFI\OC\OpenCore.efi' 2>&1 | Out-String).Trim())
Write-Host ('      order:  ' + (bcdedit /set '{fwbootmgr}' displayorder $guid /addlast 2>&1 | Out-String).Trim())

$verify = (bcdedit /enum $guid | Out-String)
Write-Host '      entry now reads:'
$verify.Split("`n") | Where-Object { $_.Trim() -ne '' } | ForEach-Object { '        ' + $_.TrimEnd() }
if ($verify -match 'OpenCore\.efi' -and $verify -match 'partition=') {
    Write-Host '      verified: entry has a device and the OpenCore path.'
} else {
    Write-Host '      *** verification looks off - paste this output to Claude before rebooting. ***'
}

Write-Host ''
Write-Host 'READY.'
Write-Host 'BIOS (F2) check: Secure Boot = Disabled. Then reboot -> F12 -> "OpenCore" -> pick macOS Base System.'
Write-Host 'If F12 does not list it yet: full shutdown + power-on (not a plain reboot), then F12 again.'
Write-Host ''
Write-Host 'UNDO (elevated, any time):'
Write-Host ("  bcdedit /set {fwbootmgr} displayorder $guid /remove")
Write-Host ("  bcdedit /delete $guid /f")
Write-Host ("  (files: delete {0}\EFI and {0}\com.apple.recovery.boot)" -f $Volume)
