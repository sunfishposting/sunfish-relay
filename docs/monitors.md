# Monitor System

Monitors are plugins that track different systems.

## Interface

Each monitor provides:
- `get_status()` - Current state dict
- `get_alerts()` - Threshold violations list
- `get_status_line()` - One-liner for prompts
- `execute(command)` - Actions (optional)

## Available Monitors

| Monitor | Tracks | Key metrics |
|---------|--------|-------------|
| `vps` | System resources | CPU%, RAM%, Disk%, GPU temp/util |
| `obs` | OBS Studio | Stream status, dropped frames |
| `agent` | AI agent process | Running state, log freshness, errors |
| `unity` | Unity engine | (Placeholder) |

## Adding a New Monitor

1. Create `orchestrator/monitors/newmonitor.py`
2. Inherit from `BaseMonitor`
3. Implement `get_status()` at minimum
4. Add to `monitors/__init__.py`
5. Add to `MONITOR_CLASSES` in `health.py`
6. Add config section in `settings.yaml`

## Smart Monitoring Rules

Add custom metrics to `settings.yaml`:

```yaml
smart_monitoring:
  rules:
    unity_fps:
      delta_threshold: 15       # Alert if changes by 15+
      absolute_threshold: 25    # Alert if drops below 25
      cooldown_seconds: 60      # Don't re-alert for 1 min
```

Metric name must match what monitor returns in `get_status()`.

### Rule Options

- `delta_threshold` - Trigger if value changes by this much
- `absolute_threshold` - Trigger if value exceeds this
- `trigger_on_state_change` - For booleans (like `streaming`)
- `cooldown_seconds` - Minimum time between triggers
