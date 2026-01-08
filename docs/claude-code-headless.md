# Claude Code Headless Deployment

Reference for running Claude Code CLI in automated/headless mode (verified January 2026).

## Tool Restriction Flags

**Critical distinction:**

| Flag | Purpose | Effect |
|------|---------|--------|
| `--tools "Read,Glob"` | Restrict available tools | Only these tools exist |
| `--allowedTools "Read,Glob"` | Pre-approve tools | These run without prompting, but ALL tools still available |
| `--disallowedTools "Bash"` | Block specific tools | These tools removed entirely |

**For read-only agents, use `--tools` not `--allowedTools`.**

## Core Headless Flags

```bash
claude -p "prompt" \                    # Print mode (non-interactive, required)
  --output-format json \                # Structured output with session_id
  --model sonnet \                      # Model: haiku, sonnet, opus
  --tools "Read,Glob,Grep" \            # Restrict available tools
  --resume SESSION_ID \                 # Continue existing session
  --max-turns 3                         # Limit agentic loops (cost control)
```

## Session Management

```bash
# Capture session ID from first call
response=$(claude -p "Start monitoring" --output-format json)
session_id=$(echo "$response" | jq -r '.session_id')

# Resume same session
claude -p "Check status" --resume "$session_id" --output-format json
```

**Auto-compaction**: At ~95% context capacity, Claude automatically summarizes and continues. Sessions can run indefinitely.

**When to restart sessions**: Logical breakpoints (issue resolved, shift change). Not mid-task.

## JSON Output Structure

```json
[
  {"type": "system", "session_id": "uuid-here"},
  {"type": "assistant", "message": {"content": [...]}},
  {"type": "result", "result": "response text", "session_id": "uuid-here"}
]
```

Parse with:
```python
data_list = json.loads(output)
for item in data_list:
    if item.get('type') == 'result':
        response = item['result']
    if 'session_id' in item:
        session_id = item['session_id']
```

## Permission Modes

| Mode | Behavior |
|------|----------|
| `default` | Prompt on first tool use |
| `acceptEdits` | Auto-accept file edits |
| `plan` | Read-only, no execution |
| `dontAsk` | Auto-deny unless pre-approved |

```bash
claude -p "..." --permission-mode dontAsk
```

## Tool Patterns

Bash uses prefix matching (not regex):
```bash
--allowedTools "Bash(git:*)"      # Matches: git log, git diff, git commit
--allowedTools "Bash(npm run:*)"  # Matches: npm run test, npm run build
```

Read/Edit use gitignore patterns:
```bash
--allowedTools "Read(src/**/*.ts)"
--disallowedTools "Read(.env*)"
```

## Settings Precedence

1. Managed settings (`/etc/claude-code/managed-settings.json`)
2. CLI arguments
3. Local project (`.claude/settings.local.json`)
4. Shared project (`.claude/settings.json`)
5. User (`~/.claude/settings.json`)

**Deny always wins over allow.**

## Error Handling

| Exit Code | Meaning |
|-----------|---------|
| 0 | Success |
| 1 | User/permission error |
| 2 | Tool execution failed |
| 124 | Timeout |

```bash
timeout 60s claude -p "prompt" --max-turns 3 --output-format json
```

## Environment Variables

```bash
export ANTHROPIC_API_KEY="sk-..."
export CLAUDE_CODE_MAX_OUTPUT_TOKENS="8000"
export BASH_MAX_TIMEOUT_MS="30000"
export DISABLE_AUTOUPDATER="1"  # Production stability
```

## Python Integration

Use `subprocess.run()` with `--output-format json` for reliable output:

```python
result = subprocess.run(
    [
        'claude', '-p', prompt,
        '--output-format', 'json',
        '--model', 'sonnet',
        '--tools', 'Read,Glob,Grep',
        '--max-turns', '5',
        '--resume', session_id,  # optional
    ],
    capture_output=True,
    text=True,
    timeout=120,
    cwd=project_path
)

# Parse JSON array output
response_text = ""
new_session_id = None

if result.returncode == 0:
    try:
        data_list = json.loads(result.stdout)
        for item in data_list:
            if 'session_id' in item:
                new_session_id = item['session_id']
            if item.get('type') == 'result':
                response_text = item['result']
    except json.JSONDecodeError:
        # Plain text fallback
        response_text = result.stdout
```

**Note**: `--output-format stream-json` exists for real-time streaming but has Windows compatibility issues. Use `json` format for reliability.

## Our Implementation

Sonnet (read-only observer, 5 turns max, 60s timeout):
```bash
claude -p "$prompt" \
  --output-format json \
  --model sonnet \
  --tools "Read,Glob,Grep" \
  --max-turns 5 \
  --resume "$SONNET_SESSION_ID"
```

Opus (full access actor, 10 turns max, 10 min timeout):
```bash
claude -p "$prompt" \
  --output-format json \
  --model opus \
  --tools "Read,Edit,Write,Bash,Glob,Grep" \
  --max-turns 10 \
  --resume "$OPUS_SESSION_ID"
```

## References

- [Claude Code CLI Reference](https://docs.anthropic.com/en/docs/claude-code/cli-reference)
- [Claude Code Headless Mode](https://docs.anthropic.com/en/docs/claude-code/headless)
- [Claude Code Settings](https://docs.anthropic.com/en/docs/claude-code/settings)
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [GitHub #1920 - Missing result event](https://github.com/anthropics/claude-code/issues/1920)
