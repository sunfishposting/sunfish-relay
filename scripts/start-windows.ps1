# Sunfish Relay Startup Script for Windows
# Features:
# - Auto-restart on crash
# - Logging to file
# - Pre-flight checks

$ErrorActionPreference = "Stop"

# Paths
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$OrchestratorPath = Join-Path $ProjectRoot "orchestrator"
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "orchestrator.log"

# Ensure log directory exists
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "$timestamp - $Message"
    Write-Host $logMessage
    Add-Content -Path $LogFile -Value $logMessage
}

Write-Log "=== Sunfish Relay Starting ==="
Write-Log "Project root: $ProjectRoot"

# Pre-flight checks
Write-Log "Running pre-flight checks..."

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Log "Python: $pythonVersion"
} catch {
    Write-Log "ERROR: Python not found"
    exit 1
}

# Check signal-cli
try {
    $signalVersion = signal-cli --version 2>&1
    Write-Log "signal-cli: $signalVersion"
} catch {
    Write-Log "ERROR: signal-cli not found in PATH"
    exit 1
}

# Check Claude Code
try {
    $claudeVersion = claude --version 2>&1
    Write-Log "Claude Code: $claudeVersion"
} catch {
    Write-Log "ERROR: Claude Code not found"
    exit 1
}

# Check config
$ConfigPath = Join-Path $ProjectRoot "config\settings.yaml"
if (-not (Test-Path $ConfigPath)) {
    Write-Log "ERROR: Config not found at $ConfigPath"
    Write-Log "Copy settings.example.yaml to settings.yaml and configure it"
    exit 1
}
Write-Log "Config: OK"

# Change to orchestrator directory
Set-Location $OrchestratorPath

Write-Log "Pre-flight checks passed. Starting orchestrator..."

# Main loop with auto-restart
$restartCount = 0
$maxRestarts = 10
$restartWindow = 3600  # Reset counter after 1 hour of stable running
$lastStart = Get-Date

while ($true) {
    $startTime = Get-Date

    try {
        Write-Log "Starting orchestrator (attempt $($restartCount + 1))..."

        # Run the orchestrator
        python main.py 2>&1 | ForEach-Object {
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            "$timestamp - $_" | Tee-Object -FilePath $LogFile -Append
        }

        $exitCode = $LASTEXITCODE
        Write-Log "Orchestrator exited with code: $exitCode"

    } catch {
        Write-Log "Orchestrator crashed: $_"
    }

    $runTime = (Get-Date) - $startTime

    # Reset restart counter if it ran for more than an hour
    if ($runTime.TotalSeconds -gt $restartWindow) {
        $restartCount = 0
        Write-Log "Ran for $($runTime.TotalMinutes) minutes, resetting restart counter"
    }

    $restartCount++

    # Check if we've hit max restarts
    if ($restartCount -ge $maxRestarts) {
        Write-Log "ERROR: Max restarts ($maxRestarts) reached. Stopping."
        Write-Log "Manual intervention required."
        exit 1
    }

    # Wait before restart (exponential backoff, max 60 seconds)
    $waitTime = [Math]::Min(5 * $restartCount, 60)
    Write-Log "Restarting in $waitTime seconds... (restart $restartCount of $maxRestarts)"
    Start-Sleep -Seconds $waitTime
}
