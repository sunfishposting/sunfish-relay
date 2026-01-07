@echo off
REM Sunfish Relay Launcher
REM Double-click this or add to Task Scheduler for auto-start

cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "start-windows.ps1"
pause
