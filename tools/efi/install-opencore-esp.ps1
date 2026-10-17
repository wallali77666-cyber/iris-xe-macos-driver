# install-opencore-esp.ps1 — put OpenCore on the internal ESP and register a
# firmware boot entry, with no USB stick involved (docs/PHASE-C-OPENCORE.md §2b).
#
# Run via tools/efi/install-opencore-esp.cmd (self-elevating) or from an
# elevated PowerShell:
#   powershell -ExecutionPolicy Bypass -File .\install-opencore-esp.ps1
#
# It only ever writes S:\EFI\OC and adds one NVRAM boot entry. It never touches
# S:\EFI\Microsoft or S:\EFI\BOOT. Undo instructions are printed at the end.

param(
    [string]$Source = "$env:TEMP\opencode\efi-stage\EFI\OC",
    [string]$Mount  = 'S:',
    [string]$Label  = 'OpenCore'
)

$ErrorActionPreference = 'Stop'
$letter = $Mount.TrimEnd(':')

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Host 'ERROR: run this in an elevated PowerShell (right-click > Run as administrator).'; exit 1 }

if (-not (Test-Path (Join-Path $Source 'OpenCore.efi'))) {
    Write-Host "ERROR: source not found: $Source\OpenCore.efi"
    Write-Host 'Stage the iris-xe-efi artifact first (gh run download ... -n iris-xe-efi).'
    exit 1
}

Write-Host "[1/4] mounting the ESP on ${Mount} ..."
mountvol $Mount /S | Out-Null
if ($LASTEXITCODE -ne 0) { throw "mountvol $Mount /S failed (is $Mount free?)" }
Start-Sleep 1
$vol = Get-Volume -DriveLetter $letter
$freeBefore = [math]::Round($vol.SizeRemaining / 1MB, 1)
Write-Host ("      ESP free before: {0} MB" -f $freeBefore)
if ($vol.SizeRemaining -lt 10MB) { throw 'ESP has less than 10 MB free - stop, do not copy.' }

Write-Host '[2/4] copying EFI\OC (EFI\Microsoft and EFI\BOOT are never touched) ...'
$dst = "$Mount\EFI\OC"
if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
robocopy $Source $dst /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }
$freeAfter = [math]::Round((Get-Volume -DriveLetter $letter).SizeRemaining / 1MB, 1)
Write-Host ("      ESP free after:  {0} MB" -f $freeAfter)
mountvol $Mount /D | Out-Null
Write-Host '      ESP unmounted again'

Write-Host '[3/4] registering the firmware boot entry ...'
$out = (bcdedit /copy '{bootmgr}' /d "$Label" | Out-String)
if ($out -notmatch '\{[0-9a-fA-F-]{36}\}') { throw "bcdedit /copy failed: $out" }
$guid = $Matches[0]
bcdedit /set $guid path '\EFI\OC\OpenCore.efi' | Out-Null
Write-Host "      entry $guid  ->  \EFI\OC\OpenCore.efi"

if (Test-Path 'G:\') { Write-Host '      note: the 1 GB FAT32 (G: TEST) stays free for the Recovery image' }

Write-Host '[4/4] done.'
Write-Host ''
Write-Host 'TEST: reboot, press F12, pick "OpenCore" (it will also appear in BIOS boot order).'
Write-Host 'OpenCore should show its menu even before macOS exists (auxiliary tools are visible).'
Write-Host ''
Write-Host 'UNDO anytime (elevated):'
Write-Host "  bcdedit /delete $guid"
Write-Host "  mountvol $Mount /S ; rmdir /s /q $Mount\EFI\OC ; mountvol $Mount /D"
