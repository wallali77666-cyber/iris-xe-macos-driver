@echo off
rem install-opencore-esp.cmd - self-elevating launcher for the no-USB OpenCore
rem install to the internal ESP (docs/PHASE-C-OPENCORE.md section 2b).
rem Double-click this file and accept the UAC prompt.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = '%~dp0install-opencore-esp.ps1'; Start-Process powershell -Verb RunAs -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -NoExit -File ' + [char]34 + $p + [char]34)"
