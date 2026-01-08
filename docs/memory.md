# Memory & Context Architecture

How Claude maintains context in this 24/7 system.

## Anthropic's Recommended Pattern

Reference: [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

Anthropic recommends for 24/7 agents:
1. **Sessions with auto-compaction** - context auto-summarizes at ~95% capacity
2. **File-based progress tracking** - `claude-progress.txt` that agents read at session start
3. **Git history** - for understanding what changed

Key quote: "compaction alone is insufficient for production-quality work across multiple sessions"

## How We Implement This

### Anthropic's Pattern → Our Implementation

| Anthropic | Ours | Purpose |
|-----------|------|---------|
| claude-progress.txt | ops-log.md | What's happening, what was done |
| Session continuity | --resume SESSION_ID | Conversational memory |
| Git history | Git history | Code change tracking |

**Why ops-log.md instead of claude-progress.txt?**

Anthropic's pattern is for coding agents doing feature work. Ours is a DevOps agent monitoring a livestream. ops-log.md tracks:
- Current system status (updated by monitors)
- Active issues
- Recent events (auto-trimmed to 6h)
- History summary
- Standing instructions

If Opus does significant code work, it should log that in ops-log.md too. We don't need a separate code.md - that's overcomplicating it.

## Session Management

Both Sonnet and Opus use persistent sessions:

```bash
# Capture session ID from first call
session_id=$(claude -p "prompt" --output-format json | jq -r '.session_id')

# Resume same session for subsequent calls
claude -p "prompt" --resume "$session_id" --output-format json
```

**Auto-compaction**: When context reaches ~95% capacity, Claude automatically summarizes and continues. Sessions can run indefinitely.

**When to restart sessions**: At logical breakpoints (major issue resolved, shift change, weekly reset). Not mid-task.

Orchestrator stores session IDs:
- `sonnet_session_id` - Sonnet's ongoing session
- `opus_session_id` - Opus's ongoing session

## What Each Model Receives

### Every Call (Injected by Orchestrator)

| Source | Contents |
|--------|----------|
| CLAUDE.md | System knowledge, personality, architecture |
| ops-log.md | Working memory (status, issues, events) |
| Live status | Current metrics from monitors |
| Recent messages | Last 5 Signal messages for context |

Plus session history (auto-compacted as needed).

### On-Demand (Via Tools)

- Sonnet: `Read`, `Glob`, `Grep` (observe only)
- Opus: All tools including `Edit`, `Write`, `Bash` (can act)

## Memory Files

### CLAUDE.md (Static)
- Role, personality, architecture
- Signal formatting rules
- Pointers to docs/
- Updated rarely

### ops-log.md (Dynamic)
- Current status (auto-updated)
- Active issues (Claude manages)
- Recent events (auto-trimmed)
- History summary (patterns learned)
- Standing instructions (user prefs)

This IS our claude-progress.txt equivalent.

### docs/ (Reference)
- signal-cli.md, operations.md, troubleshooting.md, monitors.md
- Read on-demand when needed
- Updated when we learn new patterns

## Key Behaviors

**Session startup**: Claude reads ops-log.md to understand current state, even with session continuity. File is the source of truth.

**After taking action**: Opus updates ops-log.md with what it did and why.

**On crash/restart**: Session may be lost, but ops-log.md persists. New session reads file and continues.

## References

- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) - Multi-context patterns
- [Claude Code Best Practices](https://www.anthropic.com/engineering/claude-code-best-practices) - CLAUDE.md, context management
- [Building Agents with Claude Agent SDK](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk) - Compaction, subagents
