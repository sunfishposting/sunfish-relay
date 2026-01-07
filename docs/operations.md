# Operations Reference

Common commands and procedures for the Sunfish Relay system.

## Startup & Recovery

### On System Boot
Orchestrator auto-starts via Windows Task Scheduler:
1. Pre-flight checks (Python, signal-cli, Claude Code, config)
2. Checks all monitors
3. Sends startup notification to Signal
4. If issues + `auto_recovery: true` → Opus attempts fixes

### Crash Detection
Uses `.running` marker file:
- Created on start, deleted on clean shutdown
- Exists on startup = previous run crashed

### Crash Recovery
PowerShell wrapper auto-restarts on crash:
- Exponential backoff (5s → 60s max)
- Max 10 restarts before giving up
- Logs to `logs/orchestrator.log`

## Manual Commands

```powershell
# Task Scheduler
Get-ScheduledTask -TaskName "Sunfish-Relay"
Start-ScheduledTask -TaskName "Sunfish-Relay"
Stop-ScheduledTask -TaskName "Sunfish-Relay"

# View logs
Get-Content C:\Users\Administrator\sunfish-relay\logs\orchestrator.log -Tail 50
```

## Common Operations

### Check Status
Query monitors or check ops-log.md Current Status section.

### Restart OBS
```powershell
taskkill /IM obs64.exe /F
Start-Process "C:\Program Files\obs-studio\bin\64bit\obs64.exe"
```

### View Logs
- OBS: `%APPDATA%\obs-studio\logs\`
- Agent: Check `settings.yaml` for `agent.log_path`
- Orchestrator: stdout or Task Scheduler

### Edit Configuration
```powershell
notepad config/settings.yaml
# Then restart orchestrator
```

### Manual Signal Message
```bash
signal-cli -u +PHONE send -g GROUP_ID -m "message"
```

## Alert Thresholds (defaults)

| Metric | Threshold |
|--------|-----------|
| CPU | > 90% |
| Memory | > 85% |
| Disk | > 85% |
| GPU Temp | > 80C |
| GPU Util | > 95% |
| Dropped Frames | > 1% |
| Agent Log Age | > 5 min |

Configured in `settings.yaml` under each monitor's `alerts` section.
