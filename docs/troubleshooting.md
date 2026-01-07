# Troubleshooting

Common issues and fixes.

## Orchestrator won't start

1. Check Python: `python --version`
2. Check dependencies: `pip install -r requirements.txt`
3. Check config: Does `config/settings.yaml` exist?
4. Check signal-cli: `signal-cli --version`

## Not receiving messages

1. Is signal-cli linked? `signal-cli -u +PHONE receive`
2. Phone number correct in settings?
3. Group ID correct? `signal-cli -u +PHONE listGroups`

## Claude not responding

1. Check trigger word in settings
2. Claude Code installed? `claude --version`
3. Check orchestrator logs for errors

## OBS monitor failing

1. Is OBS running?
2. WebSocket enabled? (Tools → WebSocket Server Settings)
3. Password correct in settings?

## signal-cli issues

See `docs/signal-cli.md` for detailed patterns and gotchas.

Key points:
- `--output json` goes BEFORE subcommand
- Mentions use U+FFFC placeholder, check `mentions` array
- Windows may need `--message-from-stdin` for newlines
