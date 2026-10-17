@echo off
rem install-opencore-share.cmd - turn the 1 GB SHARE partition (G:) into the
rem OpenCore boot medium: format on first run, EFI layout, staged Recovery if
rem ready, and its own firmware boot entry. Double-click; accept the UAC
rem prompt. The console window stays open so you can read the result.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = '%~dp0install-opencore-share.ps1'; Start-Process powershell -Verb RunAs -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -NoExit -File ' + [char]34 + $p + [char]34)"
