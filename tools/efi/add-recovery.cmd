@echo off
rem add-recovery.cmd - copy the staged macOS Recovery folder to the SHARE
rem partition (G:). No admin needed. Double-click after macrecovery finished.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0add-recovery.ps1"
