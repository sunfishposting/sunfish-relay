#!/usr/bin/env python3
"""
Sunfish Relay Orchestrator
Bridges Signal messages to Claude Code for VPS/stream administration.

Architecture:
- Signal listener (reactive): Responds to messages when triggered
- Smart monitor (proactive): Event-driven Claude invocation
- Memory manager: Maintains ops-log.md for persistent context
- Monitor plugins: Extensible system monitoring (VPS, OBS, Agent, etc.)
- Tiered models: Haiku observes, Opus acts
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from health import HealthAggregator
from memory import MemoryManager
from smart_monitoring import SmartMonitor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# =============================================================================
# Signal Client
# =============================================================================

class SignalCLINative:
    """Native signal-cli client."""

    def __init__(self, signal_cli_path: str = "signal-cli"):
        self.phone_number: Optional[str] = None
        self.allowed_group_ids: set[str] = set()
        self.signal_cli_path = signal_cli_path

    def configure(self, phone_number: str, allowed_group_ids: list[str]):
        self.phone_number = phone_number
        self.allowed_group_ids = set(allowed_group_ids)

    def receive_messages(self) -> list[dict]:
        """Poll for new messages using signal-cli."""
        try:
            result = subprocess.run(
                [self.signal_cli_path, "-u", self.phone_number, "receive", "--json"],
                capture_output=True,
                text=True,
                timeout=30
            )
            messages = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return messages
        except subprocess.TimeoutExpired:
            return []
        except Exception as e:
            logger.error(f"Failed to receive messages: {e}")
            return []

    def send_message(self, group_id: str, message: str):
        """Send a message to a group."""
        try:
            if len(message) > 4000:
                message = message[:3900] + "\n\n[truncated]"

            subprocess.run(
                [self.signal_cli_path, "-u", self.phone_number, "send", "-g", group_id, "-m", message],
                capture_output=True,
                text=True,
                timeout=30
            )
            logger.info("Message sent")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    def extract_group_message(self, envelope: dict) -> Optional[tuple[str, str, str]]:
        """Extract group ID, sender, and message text."""
        env = envelope.get('envelope', envelope)
        data_message = env.get('dataMessage', {})
        group_info = data_message.get('groupInfo', {})
        group_id = group_info.get('groupId')
        message = data_message.get('message')
        sender = env.get('source')

        if group_id and message and group_id in self.allowed_group_ids:
            return (group_id, sender, message)
        return None


# =============================================================================
# Claude Code Integration (Tiered Models)
# =============================================================================

# Global claude path (set by Orchestrator on init)
_claude_path = "claude"


def call_claude_code(
    prompt: str,
    working_dir: Path,
    model: str = 'opus',
    allowed_tools: str = 'Read,Edit,Write,Bash,Glob,Grep',
    timeout: int = 120
) -> str:
    """
    Execute Claude Code in headless mode.

    Args:
        prompt: The prompt to send
        working_dir: Directory to run from (for CLAUDE.md context)
        model: Model to use ('haiku', 'sonnet', 'opus')
        allowed_tools: Comma-separated list of allowed tools
        timeout: Max seconds to wait

    Returns:
        Claude's response text
    """
    try:
        cmd = [
            _claude_path, "-p", prompt,
            "--output-format", "text",
            "--allowedTools", allowed_tools,
        ]

        # Add model flag if not default
        if model and model != 'opus':
            cmd.extend(["--model", model])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(working_dir),
            timeout=timeout
        )

        if result.returncode != 0 and result.stderr:
            logger.error(f"Claude Code error: {result.stderr}")
            return f"Error: {result.stderr[:500]}"

        return result.stdout.strip() or "Done (no output)"

    except subprocess.TimeoutExpired:
        return "Request timed out"
    except Exception as e:
        logger.error(f"Claude Code failed: {e}")
        return f"Failed: {e}"


def handle_message_tiered(
    message: str,
    context: str,
    project_path: Path
) -> tuple[str, str]:
    """
    Handle a message using tiered model approach.

    1. Try Haiku with read-only tools
    2. If Haiku needs action, escalate to Opus

    Returns:
        (response, model_used)
    """
    # Signal formatting instructions
    signal_format = """FORMAT FOR SIGNAL (mobile phone):
- Short lines, no markdown (no **bold** or `code`)
- No ASCII art or tables
- Use emoji sparingly for status (✓ ✗ ⚠️)
- Lead with the answer, details after
- If listing items, use simple bullets (•)
- Max 3-4 short paragraphs"""

    # Build prompt for Haiku (read-only observation)
    haiku_prompt = f"""{context}

## Request
"{message}"

---
You are in READ-ONLY mode. You can observe, check status, read logs, and report.
If this request requires ACTION (editing files, restarting services, fixing issues),
respond with exactly: "ESCALATE: <reason>"

Otherwise, answer the question using only read operations.

{signal_format}"""

    # Try Haiku first
    response = call_claude_code(
        prompt=haiku_prompt,
        working_dir=project_path,
        model='haiku',
        allowed_tools='Read,Glob,Grep',
        timeout=60
    )

    # Check for escalation
    if response.strip().upper().startswith('ESCALATE:'):
        reason = response.split(':', 1)[1].strip() if ':' in response else 'Action required'
        logger.info(f"Escalating to Opus: {reason}")

        # Build prompt for Opus (full access)
        opus_prompt = f"""{context}

## Request
"{message}"

---
You have full system access. Execute the requested action.

{signal_format}"""

        response = call_claude_code(
            prompt=opus_prompt,
            working_dir=project_path,
            model='opus',
            allowed_tools='Read,Edit,Write,Bash,Glob,Grep',
            timeout=120
        )
        return response, 'opus'

    return response, 'haiku'


# =============================================================================
# Configuration
# =============================================================================

def load_config() -> dict:
    """Load configuration from settings.yaml."""
    config_paths = [
        Path('./config/settings.yaml'),
        Path('../config/settings.yaml'),
        Path.home() / '.config/sunfish/settings.yaml'
    ]

    for path in config_paths:
        if path.exists():
            logger.info(f"Loading config: {path}")
            with open(path) as f:
                return yaml.safe_load(f)

    logger.error("No config found. Create config/settings.yaml")
    sys.exit(1)


def get_project_path(config: dict) -> Path:
    """Get the project path from config."""
    if 'project_path' in config:
        path = Path(config['project_path'])
        if not path.is_absolute():
            path = Path(__file__).parent.parent / config['project_path']
        return path
    return Path(__file__).parent.parent


# =============================================================================
# Main Orchestrator
# =============================================================================

class Orchestrator:
    """Main orchestrator that ties everything together."""

    def __init__(self, config: dict):
        global _claude_path

        self.config = config
        self.project_path = get_project_path(config)

        # Set executable paths from config (for Windows)
        paths = config.get('paths', {})
        signal_cli_path = paths.get('signal_cli', 'signal-cli')
        _claude_path = paths.get('claude', 'claude')

        # Initialize components
        self.signal = SignalCLINative(signal_cli_path=signal_cli_path)
        self.signal.configure(
            phone_number=config['signal']['phone_number'],
            allowed_group_ids=config['signal']['allowed_group_ids']
        )

        self.health = HealthAggregator(config)
        self.memory = MemoryManager(self.project_path)
        self.smart_monitor = SmartMonitor(config)

        # Settings
        self.trigger_word = config.get('trigger_word', '').lower()
        self.poll_interval = config.get('poll_interval', 2)
        self.proactive_alerts = config.get('proactive_alerts', True)
        self.use_tiered_models = config.get('use_tiered_models', True)

        # State
        self.processed_timestamps: set = set()
        self.message_buffer: list[dict] = []
        self.buffer_size = config.get('context_buffer_size', 30)

    async def run(self):
        """Main run loop."""
        logger.info("Starting Sunfish Relay Orchestrator")
        logger.info(f"Project path: {self.project_path}")
        logger.info(f"Trigger word: '{self.trigger_word}' (empty = all messages)")
        logger.info(f"Monitors loaded: {list(self.health.monitors.keys())}")
        logger.info(f"Tiered models: {'enabled' if self.use_tiered_models else 'disabled'}")

        # Initial status update
        self._update_status_in_memory()

        # Startup notification (checks for crash before setting marker)
        await self._startup_check()

        # Set running marker AFTER crash detection
        self._set_running_marker()

        try:
            while True:
                try:
                    # Process incoming messages
                    await self._process_messages()

                    # Smart monitoring check
                    await self._smart_monitoring_check()

                except Exception as e:
                    logger.error(f"Error in main loop: {e}")

                await asyncio.sleep(self.poll_interval)
        finally:
            # Clean shutdown - remove marker
            logger.info("Shutting down...")
            self._clear_running_marker()
            self.memory.add_event("Clean shutdown")

    async def _process_messages(self):
        """Process incoming Signal messages."""
        messages = self.signal.receive_messages()

        for msg in messages:
            envelope = msg.get('envelope', msg)
            timestamp = envelope.get('timestamp')

            if timestamp in self.processed_timestamps:
                continue
            self.processed_timestamps.add(timestamp)

            # Trim processed set
            if len(self.processed_timestamps) > 1000:
                self.processed_timestamps = set(list(self.processed_timestamps)[-500:])

            parsed = self.signal.extract_group_message(msg)
            if not parsed:
                continue

            group_id, sender, message_text = parsed

            # Buffer all messages for context
            self.message_buffer.append({'sender': sender, 'text': message_text})
            if len(self.message_buffer) > self.buffer_size:
                self.message_buffer = self.message_buffer[-self.buffer_size:]

            # Check trigger word
            if self.trigger_word and self.trigger_word not in message_text.lower():
                continue

            logger.info("Processing triggered message")

            # Build context
            context = self._build_context()

            # Handle with tiered models or Opus only
            if self.use_tiered_models:
                response, model_used = handle_message_tiered(
                    message_text, context, self.project_path
                )
                logger.info(f"Handled by {model_used}")

                # If Opus acted, schedule verification
                if model_used == 'opus':
                    self.smart_monitor.schedule_verification()
            else:
                # Legacy: always use Opus
                prompt = f"{context}\n\n## Request\n\"{message_text}\""
                response = call_claude_code(prompt, self.project_path)
                model_used = 'opus'

            # Log event
            self.memory.add_event(f"Responded to: {message_text[:50]}...")

            # Send response with model attribution
            model_tag = "🔵" if model_used == 'haiku' else "🟣"
            tagged_response = f"{response}\n\n{model_tag} {model_used}"
            self.signal.send_message(group_id, tagged_response)

    async def _smart_monitoring_check(self):
        """Event-driven monitoring - only invoke Claude when interesting."""
        # Get current status from all monitors
        raw_status = self.health.get_all_status()
        flat_status = self.smart_monitor.flatten_status(raw_status)

        # Check if we should invoke Claude
        should_invoke, reason, changed_metrics = self.smart_monitor.should_invoke_claude(flat_status)

        if not should_invoke:
            return

        logger.info(f"Smart monitor triggered: {reason}")

        # Update status in memory
        self._update_status_in_memory()

        if reason == "verify_fix":
            # Verification check after Opus action
            await self._verification_check(flat_status)

        elif reason in ("significant_change", "scheduled_check"):
            # Let Haiku observe and report if needed
            await self._haiku_observation(reason, changed_metrics, flat_status)

    async def _haiku_observation(self, reason: str, changed_metrics: list[str], status: dict):
        """Have Haiku observe the system and report if needed."""
        change_summary = self.smart_monitor.get_change_summary(changed_metrics)
        ops_log = self.memory.get_context_for_claude()

        prompt = f"""You are monitoring a livestream system. A check was triggered.

Trigger reason: {reason}
{change_summary}

Current status:
{self.health.get_status_summary()}

Ops log:
{ops_log}

---
Review the system state. Is everything okay?
- If all clear, respond with just: "All clear."
- If there's a concern worth flagging, explain briefly (2-3 lines max).
- If immediate action is needed, say "ALERT: <issue>"

FORMAT: This goes to Signal on a phone. Short lines, no markdown, no tables."""

        response = call_claude_code(
            prompt=prompt,
            working_dir=self.project_path,
            model='haiku',
            allowed_tools='Read,Glob,Grep',
            timeout=60
        )

        response_lower = response.lower().strip()

        # Log observation
        if 'all clear' in response_lower:
            logger.debug("Haiku: All clear")
            return

        # Alert or concern - notify humans
        if response_lower.startswith('alert:'):
            self.memory.add_event(f"Haiku alert: {response[:200]}")
            for group_id in self.signal.allowed_group_ids:
                self.signal.send_message(group_id, f"⚠️ {response}\n\n🔵 haiku")
        else:
            # Non-critical observation
            self.memory.add_event(f"Haiku observation: {response[:200]}")
            logger.info(f"Haiku observation: {response}")

    async def _verification_check(self, status: dict):
        """Verify that a recent Opus fix worked."""
        ops_log = self.memory.get_context_for_claude()

        prompt = f"""A fix was recently applied. Verify if it worked.

Current status:
{self.health.get_status_summary()}

Recent ops log:
{ops_log}

---
Check if the recent fix resolved the issue.
- If fixed, respond: "Fix verified: <brief summary>"
- If issue persists, respond: "ALERT: Fix did not hold - <details>"

FORMAT: This goes to Signal on a phone. Short lines, no markdown."""

        response = call_claude_code(
            prompt=prompt,
            working_dir=self.project_path,
            model='haiku',
            allowed_tools='Read,Glob,Grep',
            timeout=60
        )

        self.memory.add_event(f"Verification: {response[:200]}")

        # Alert if fix failed
        if 'alert:' in response.lower():
            for group_id in self.signal.allowed_group_ids:
                self.signal.send_message(group_id, f"⚠️ {response}\n\n🔵 haiku")

    async def _startup_check(self):
        """
        Run on orchestrator startup.
        Checks system state, detects crash recovery, and notifies team.
        """
        if not self.config.get('startup_notification', True):
            return

        logger.info("Running startup check...")

        # Check if this is a crash recovery by looking at ops-log
        ops_log = self.memory.read()
        is_crash_recovery = self._detect_crash_recovery(ops_log)

        # Get current system status
        status = self.health.get_all_status()
        alerts = self.health.get_all_alerts()

        # Build startup message (plain text - Signal doesn't render markdown)
        if is_crash_recovery:
            lines = ["🔄 SUNFISH RELAY BACK ONLINE (crash recovery)\n"]
        else:
            lines = ["🔄 SUNFISH RELAY ONLINE\n"]

        # Check each monitor
        for name, monitor in self.health.monitors.items():
            try:
                line = monitor.get_status_line()
                monitor_status = status.get(name, {})
                if monitor_status.get('healthy', True):
                    lines.append(f"✓ {line}")
                else:
                    lines.append(f"✗ {line}")
            except Exception as e:
                lines.append(f"✗ {name}: error ({e})")

        # Add any alerts
        if alerts:
            lines.append("\n⚠️ Issues detected:")
            for alert in alerts:
                lines.append(f"  • {alert}")

        message = "\n".join(lines)

        # Send to all groups
        for group_id in self.signal.allowed_group_ids:
            self.signal.send_message(group_id, message)

        # Log the startup appropriately
        if is_crash_recovery:
            self.memory.add_event("CRASH RECOVERY - orchestrator restarted after unexpected shutdown")
            self.memory.add_active_issue("Investigate recent crash - check logs/orchestrator.log")

            # Have Haiku analyze what might have caused the crash
            await self._analyze_crash()
        else:
            self.memory.add_event("System startup - orchestrator online")

        # If there are critical issues, ask Opus what to do
        if alerts and self.config.get('auto_recovery', False):
            await self._attempt_auto_recovery(alerts)

    def _detect_crash_recovery(self, ops_log: str) -> bool:
        """
        Detect if this startup is recovering from a crash.

        Uses a marker file approach:
        - .running file exists on startup = previous instance didn't shut down cleanly
        - Clean shutdown removes the file
        """
        marker_file = self.project_path / ".running"

        if marker_file.exists():
            # Previous instance didn't clean up - was a crash
            logger.info("Crash marker found - previous instance didn't shut down cleanly")
            return True

        return False

    def _set_running_marker(self):
        """Create marker file indicating we're running."""
        marker_file = self.project_path / ".running"
        try:
            marker_file.write_text(f"Started: {datetime.now().isoformat()}")
        except Exception as e:
            logger.warning(f"Could not create running marker: {e}")

    def _clear_running_marker(self):
        """Remove marker file on clean shutdown."""
        marker_file = self.project_path / ".running"
        try:
            if marker_file.exists():
                marker_file.unlink()
        except Exception as e:
            logger.warning(f"Could not remove running marker: {e}")

    async def _analyze_crash(self):
        """Have Haiku analyze what might have caused the crash."""
        logger.info("Analyzing potential crash cause...")

        # Read orchestrator log if it exists
        log_path = self.project_path / "logs" / "orchestrator.log"
        log_tail = ""
        if log_path.exists():
            try:
                with open(log_path, 'r') as f:
                    lines = f.readlines()
                    log_tail = ''.join(lines[-50:])  # Last 50 lines
            except Exception:
                pass

        ops_log = self.memory.get_context_for_claude()

        prompt = f"""The system just restarted after what appears to be a crash or unexpected shutdown.

## Recent Ops Log
{ops_log}

## Orchestrator Log (last 50 lines)
{log_tail if log_tail else "Log file not available"}

---
Analyze what might have caused the crash:
1. Look for errors or warnings in the logs
2. Check if any monitors showed problems before shutdown
3. Note any patterns or suspicious activity

Respond concisely with:
- Likely cause (if identifiable)
- Recommended action (if any)
- "Unknown cause" if can't determine

This will be logged to ops-log.md for reference."""

        response = call_claude_code(
            prompt=prompt,
            working_dir=self.project_path,
            model='haiku',
            allowed_tools='Read,Glob,Grep',
            timeout=60
        )

        # Log the analysis
        logger.info(f"Crash analysis result: {response}")
        self.memory.add_event(f"Crash analysis: {response[:250]}")

        # If Haiku found something actionable, add to history
        if 'unknown' not in response.lower():
            self.memory.add_to_history(f"Crash on {datetime.now().strftime('%m/%d')}: {response[:150]}")

    async def _attempt_auto_recovery(self, alerts: list[str]):
        """
        Let Opus attempt to recover from startup issues.
        Only runs if auto_recovery is enabled in config.
        """
        logger.info("Attempting auto-recovery...")

        context = self._build_context()
        prompt = f"""{context}

## Startup Recovery

The system just restarted and detected these issues:
{chr(10).join(f'• {a}' for a in alerts)}

Assess the situation and attempt to fix critical issues.

FORMAT FOR SIGNAL (phone):
- Short lines, no markdown
- Lead with what you did
- Then brief status
- Max 3-4 lines"""

        response = call_claude_code(
            prompt=prompt,
            working_dir=self.project_path,
            model='opus',
            allowed_tools='Read,Edit,Write,Bash,Glob,Grep',
            timeout=120
        )

        # Log and notify
        self.memory.add_event(f"Auto-recovery attempted: {response[:200]}")

        for group_id in self.signal.allowed_group_ids:
            self.signal.send_message(group_id, f"🔧 Auto-recovery:\n{response}\n\n🟣 opus")

        # Schedule verification
        self.smart_monitor.schedule_verification()

    def _build_context(self) -> str:
        """Build context string for Claude."""
        status_summary = self.health.get_status_summary()
        ops_log = self.memory.get_context_for_claude()

        conversation = ""
        if self.message_buffer:
            recent = self.message_buffer[-10:]
            conversation = "\n".join([f"- {m['text']}" for m in recent])

        return f"""You are the DevOps administrator for a 24/7 AI livestream.

{status_summary}

---
## Operational Memory
{ops_log}
---

## Recent Conversation
{conversation}"""

    def _update_status_in_memory(self):
        """Update the status section in ops-log.md."""
        try:
            status_lines = []
            for name, monitor in self.health.monitors.items():
                status_lines.append(monitor.get_status_line())

            status_text = "\n".join(f"- {line}" for line in status_lines)
            self.memory.update_status_section(status_text)
        except Exception as e:
            logger.error(f"Failed to update status: {e}")


# =============================================================================
# Entry Point
# =============================================================================

def main():
    config = load_config()
    orchestrator = Orchestrator(config)
    asyncio.run(orchestrator.run())


if __name__ == "__main__":
    main()
