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

## Streaming for Observability

Use `stream-json` to see what Claude is doing in real-time:

```bash
claude -p "$prompt" \
  --output-format stream-json \
  --model opus \
  --resume "$SESSION_ID"
```

**Claude Code CLI event format** (different from raw API):
```json
{"type":"system","session_id":"...","model":"claude-sonnet-4-..."}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"file_path":"..."}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","content":"..."}]}}
{"type":"result","result":"final response text","session_id":"..."}
```

Parse in Python:
```python
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
for line in proc.stdout:
    evt = json.loads(line)

    # Tool use is in assistant message content
    if evt.get('type') == 'assistant':
        for block in evt.get('message', {}).get('content', []):
            if block.get('type') == 'tool_use':
                tool_name = block.get('name')
                tool_input = block.get('input', {})
                print(f"[TOOL] {tool_name}: {tool_input.get('file_path', '')}")

    # Final result
    if evt.get('type') == 'result':
        response = evt['result']
```

## Our Implementation

Sonnet (read-only observer, 5 turns max):
```bash
claude -p "$prompt" \
  --output-format stream-json \
  --model sonnet \
  --tools "Read,Glob,Grep" \
  --max-turns 5 \
  --resume "$SONNET_SESSION_ID"
```

Opus (full access actor, 10 turns max, 10 min timeout):
```bash
claude -p "$prompt" \
  --output-format stream-json \
  --model opus \
  --tools "Read,Edit,Write,Bash,Glob,Grep" \
  --max-turns 10 \
  --resume "$OPUS_SESSION_ID"
```

Tool usage is logged in real-time as `[TOOL] toolname` in orchestrator logs.

## References

- [Claude Code CLI Reference](https://docs.anthropic.com/en/docs/claude-code/cli-reference)
- [Claude Code Settings](https://docs.anthropic.com/en/docs/claude-code/settings)
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
