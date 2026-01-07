# signal-cli Reference

Quick reference for signal-cli patterns used in this project.

## Key Insight

`--output json` is a **GLOBAL flag** - it goes BEFORE the subcommand, not after.

```bash
# CORRECT
signal-cli -u +PHONE --output json receive

# WRONG - will error "unrecognized argument"
signal-cli -u +PHONE receive --json
signal-cli -u +PHONE receive --output json
```

## Receive Messages

```bash
# Basic (with 5 second timeout)
signal-cli -u +PHONE --output json receive -t 5

# Infinite wait (blocks until message arrives)
signal-cli -u +PHONE --output json receive -t -1
```

Options (these go AFTER `receive`):
- `-t TIMEOUT` - seconds to wait (default 5, use -1 for infinite)
- `--max-messages N` - return after N messages
- `--ignore-attachments` - don't download attachments

Output format (one JSON object per line):
```json
{"envelope":{"source":"+1234567890","timestamp":1234567890,"dataMessage":{"message":"Hello","groupInfo":{"groupId":"base64..."}}}}
```

## Send Messages

To a group (with newlines on Windows, use stdin):
```bash
signal-cli -u +PHONE send -g GROUP_ID --message-from-stdin
```

Then pipe the message to stdin as UTF-8 bytes.

## List Groups

```bash
signal-cli -u +PHONE listGroups
```

## Check Version

```bash
signal-cli --version
```

Requires Java 21+.

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `unrecognized argument: --json` | Flag in wrong position | Use `--output json` BEFORE subcommand |
| `Config file is in use` | Another signal-cli running | Kill other instance or use daemon mode |
| `java.lang.UnsupportedClassVersionError` | Java too old | Install Java 21+ |

## Links

- [GitHub](https://github.com/AsamK/signal-cli)
- [Man page](https://github.com/AsamK/signal-cli/blob/master/man/signal-cli.1.adoc)
