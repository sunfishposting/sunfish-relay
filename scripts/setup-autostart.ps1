# Sunfish Relay Auto-Start Setup
# Run this once (as Administrator) to configure auto-start on boot

$ErrorActionPreference = "Stop"

$TaskName = "Sunfish-Relay"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$StartScript = Join-Path $ProjectRoot "scripts\start-windows.ps1"

Write-Host "=== Sunfish Relay Auto-Start Setup ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project root: $ProjectRoot"
Write-Host "Start script: $StartScript"
Write-Host ""

# Check if running as admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: Run this script as Administrator" -ForegroundColor Red
    Write-Host "Right-click PowerShell -> Run as Administrator"
    exit 1
}

# Check if start script exists
if (-not (Test-Path $StartScript)) {
    Write-Host "ERROR: Start script not found at $StartScript" -ForegroundColor Red
    exit 1
}

# Remove existing task if present
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Removing existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create the scheduled task
Write-Host "Creating scheduled task..." -ForegroundColor Green

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartScript`"" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -AtStartup

$Principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)  # No time limit

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Sunfish Relay orchestrator - Signal to Claude bridge"

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Task '$TaskName' created successfully."
Write-Host ""
Write-Host "The orchestrator will now:"
Write-Host "  - Start automatically when Windows boots"
Write-Host "  - Run as SYSTEM (no login required)"
Write-Host "  - Restart automatically if it crashes"
Write-Host "  - Send startup notification to Signal"
Write-Host ""
Write-Host "To test, you can:"
Write-Host "  1. Run manually: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  2. Reboot the server"
Write-Host ""
Write-Host "To check status: Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "To remove: Unregister-ScheduledTask -TaskName '$TaskName'"
