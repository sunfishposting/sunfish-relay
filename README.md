# Sunfish Relay

Signal-to-Claude bridge for remote VPS and stream administration.

## What This Does

Connects a Signal group chat to Claude Code running on a VPS. Send a message, Claude responds with system-aware context. Built for managing a 24/7 AI livestream operation.

```
You (Signal) → signal-cli → Orchestrator → Claude Code → Response → Signal
```

## Features

- **Trigger-based responses** - Only responds to messages with trigger word (e.g., `@claude`)
- **System awareness** - Monitors VPS resources, OBS, agent processes
- **Proactive alerts** - Warns you when thresholds are exceeded
- **Operational memory** - Maintains rolling log of events and issues
- **Extensible monitors** - Add new system monitors as plugins

## Quick Start

1. Install signal-cli and link to your Signal account
2. Copy `config/settings.example.yaml` to `config/settings.yaml`
3. Fill in your phone number and group ID
4. `pip install -r orchestrator/requirements.txt`
5. `python orchestrator/main.py`

See [SETUP.md](SETUP.md) for detailed instructions.

## Architecture

See [CLAUDE.md](CLAUDE.md) for complete system documentation (also serves as context for Claude Code).

## Requirements

- Python 3.10+
- signal-cli 0.13+
- Java 21+ (for signal-cli)
- Claude Code CLI
- Windows Server 2022 / Linux / macOS

## License

Private repository.
