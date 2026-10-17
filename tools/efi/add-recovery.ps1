# add-recovery.ps1 - copy the staged macOS Recovery folder
# (com.apple.recovery.boot) onto the SHARE partition once macrecovery has
# finished. No admin rights needed. Run via add-recovery.cmd (double-click).

param(
    [string]$Volume   = 'G:',
    [string]$RecStage = "$env:TEMP\opencode\recovery"
)

$ErrorActionPreference = 'Stop'

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

$dir = Join-Path $RecStage 'com.apple.recovery.boot'
if (-not (Test-RecoveryStaged -Root $RecStage)) {
    Write-Host "ERROR: no complete staged recovery under $dir"
    Write-Host '(the download is either still running or it failed - tell Claude)'
    Write-Host ''
    Write-Host 'Press Enter to close.'
    [void][System.Console]::ReadLine()
    exit 1
}

$dmg = Get-ChildItem $dir -Filter '*.dmg' | Select-Object -First 1
$recSize = (Get-ChildItem $dir -File | Measure-Object -Property Length -Sum).Sum
$vol = Get-Volume -DriveLetter $Volume.TrimEnd(':')
$free = $vol.SizeRemaining
Write-Host ("recovery {0} ({1} MB)   free on {2}: {3} MB" -f $dmg.Name, [math]::Round($recSize / 1MB, 1), $Volume, [math]::Round($free / 1MB, 1))
if ($free -lt ($recSize + 5MB)) {
    Write-Host 'ERROR: it does not fit - stop and tell Claude before installing.'
    Write-Host ''
    Write-Host 'Press Enter to close.'
    [void][System.Console]::ReadLine()
    exit 1
}

robocopy $dir "${Volume}\com.apple.recovery.boot" /E /NFL /NDL /NJH /NJS /NP /R:2 /W:2 | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed (exit $LASTEXITCODE)" }

Write-Host ("copied. free now: {0} MB" -f [math]::Round((Get-Volume -DriveLetter $Volume.TrimEnd(':')).SizeRemaining / 1MB, 1))
Write-Host 'OpenCore picker will list "macOS Base System" on next boot.'
Write-Host ''
Write-Host 'Press Enter to close.'
[void][System.Console]::ReadLine()
