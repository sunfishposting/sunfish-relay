#!/usr/bin/env python3
"""
Sunfish Relay Orchestrator
Bridges Signal messages to Claude Code for VPS/stream administration.

Architecture:
- Signal listener (reactive): Responds to messages when triggered
- Smart monitor (proactive): Event-driven Claude invocation
- Memory manager: Maintains ops-log.md for persistent context
- Monitor plugins: Extensible system monitoring (VPS, OBS, Agent, etc.)
- Tiered models: Sonnet observes, Opus acts
"""

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
import yaml


# =============================================================================
# Async Subprocess Helper
# =============================================================================

async def run_subprocess_async(
    cmd: list[str],
    timeout: float,
    input_data: bytes = None,
    cwd: str = None
) -> tuple[int, str, str]:
    """
    Run a subprocess asynchronously with proper timeout and cleanup.

    Unlike subprocess.run(), this:
    1. Doesn't block the asyncio event loop
    2. Properly kills the process on timeout (no zombies)
    3. Handles Windows Ctrl+C gracefully

    Args:
        cmd: Command and arguments
        timeout: Timeout in seconds
        input_data: Optional bytes to send to stdin
        cwd: Working directory

    Returns:
        (returncode, stdout, stderr)
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if input_data else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=input_data),
                timeout=timeout
            )
            return proc.returncode, stdout.decode('utf-8', errors='replace'), stderr.decode('utf-8', errors='replace')

        except asyncio.TimeoutError:
            # Kill the process on timeout - don't leave zombies
            try:
                proc.kill()
                await proc.wait()  # Clean up process resources
            except ProcessLookupError:
                pass  # Already dead
            raise subprocess.TimeoutExpired(cmd, timeout)

    except asyncio.CancelledError:
        # Task was cancelled (e.g., shutdown) - kill subprocess
        try:
            proc.kill()
            await proc.wait()
        except (ProcessLookupError, UnboundLocalError):
            pass
        raise


# =============================================================================
# Response Style (included in all prompts)
# =============================================================================

# No hints needed - CLAUDE.md already explains roles and ESCALATE pattern

# Module-level API key (set by Orchestrator from config)
_openrouter_api_key: Optional[str] = None


def check_openrouter_balance() -> Optional[float]:
    """Check OpenRouter credit balance. Returns remaining credits or None on error."""
    # Use module-level key (from config) or env var
    api_key = _openrouter_api_key or os.environ.get('OPENROUTER_API_KEY')
    if not api_key:
        logger.debug("[OPENROUTER] No API key configured")
        return None

    # Log key format for debugging (first 10 chars only)
    key_preview = api_key[:10] + "..." if len(api_key) > 10 else api_key
    logger.debug(f"[OPENROUTER] Using key: {key_preview}")

    try:
        resp = requests.get(
            'https://openrouter.ai/api/v1/credits',
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=(2, 5)
        )
        if resp.status_code == 200:
            data = resp.json().get('data', {})
            total = data.get('total_credits', 0)
            used = data.get('total_usage', 0)
            return total - used
        else:
            logger.warning(f"[OPENROUTER] API returned {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        logger.debug(f"[OPENROUTER] Error: {e}")
    return None


def strip_markdown(text: str) -> str:
    """Remove markdown formatting for plain text output."""
    # Bold: **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    # Italic: *text* or _text_
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'\1', text)
    # Code: `text`
    text = re.sub(r'`(.+?)`', r'\1', text)
    # Headers: ### text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    return text


# =============================================================================
# Temp Folder Cleanup (libsignal leak prevention)
# =============================================================================

# Pattern: "libsignal" followed by ONLY digits (the random ID format)
# This is very specific to avoid accidentally matching anything else
LIBSIGNAL_PATTERN = re.compile(r'^libsignal\d+$')


def cleanup_libsignal_temp_folders(max_age_seconds: int = 300) -> dict:
    """
    Clean up orphaned libsignal temp folders on Windows.

    libsignal-client extracts native DLLs to randomly-named temp folders
    (e.g., libsignal4521685467174493703) on each invocation. On Windows,
    these can't be deleted while loaded, so they accumulate.

    We have a permanent fix (pre-extracted DLL with java.library.path),
    but this serves as a safety net in case that fix fails.

    Safety measures:
    1. Only matches folders named "libsignal" + digits (nothing else)
    2. Only deletes folders older than max_age_seconds (default 5 min)
    3. Only operates in system TEMP directory
    4. Catches permission errors gracefully (folder in use = skip it)
    5. Logs warnings if ANY folders are found (early warning the fix isn't working)

    Returns:
        dict with keys: checked, deleted, failed, warning
    """
    result = {'checked': 0, 'deleted': 0, 'failed': 0, 'warning': False}

    # Only run on Windows (this issue doesn't affect Linux/Mac)
    if sys.platform != 'win32':
        return result

    try:
        temp_dir = Path(tempfile.gettempdir())
    except Exception as e:
        logger.debug(f"[CLEANUP] Could not get temp dir: {e}")
        return result

    now = time.time()
    folders_found = []

    # Search TEMP and one level of subdirs (folders appeared in TEMP\2\ on VPS)
    search_paths = [temp_dir]
    try:
        for subdir in temp_dir.iterdir():
            if subdir.is_dir() and subdir.name.isdigit():
                search_paths.append(subdir)
    except Exception:
        pass  # Permission issues reading temp dir

    for search_path in search_paths:
        try:
            for item in search_path.iterdir():
                if not item.is_dir():
                    continue

                # CRITICAL: Only match exact pattern "libsignal" + digits
                if not LIBSIGNAL_PATTERN.match(item.name):
                    continue

                result['checked'] += 1
                folders_found.append(item)

                # Check age
                try:
                    mtime = item.stat().st_mtime
                    age_seconds = now - mtime

                    if age_seconds < max_age_seconds:
                        # Too recent - might be in use, skip
                        continue

                    # Safe to delete - old enough
                    shutil.rmtree(item, ignore_errors=False)
                    result['deleted'] += 1
                    logger.info(f"[CLEANUP] Deleted old libsignal folder: {item.name} (age: {int(age_seconds)}s)")

                except PermissionError:
                    # Folder is locked (DLL in use) - this is expected, skip silently
                    result['failed'] += 1
                except Exception as e:
                    result['failed'] += 1
                    logger.debug(f"[CLEANUP] Could not delete {item.name}: {e}")

        except Exception as e:
            logger.debug(f"[CLEANUP] Error scanning {search_path}: {e}")

    # If we found ANY libsignal folders, warn - the permanent fix might not be working
    if folders_found:
        result['warning'] = True
        logger.warning(
            f"[CLEANUP] Found {len(folders_found)} libsignal temp folder(s). "
            f"Deleted {result['deleted']}, skipped {result['failed']} (in use). "
            f"If this persists, check the java.library.path fix in signal-cli.bat"
        )

    return result


from health import HealthAggregator
from memory import MemoryManager
from smart_monitoring import SmartMonitor

# Configure logging - DEBUG level shows poll details
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
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

    async def receive_messages(self) -> list[dict]:
        """Poll for new messages using signal-cli (async)."""
        try:
            cmd = [self.signal_cli_path, "-u", self.phone_number, "--output", "json", "receive"]
            logger.debug("[POLL] Starting receive...")

            returncode, stdout, stderr = await run_subprocess_async(cmd, timeout=15)

            if stderr:
                logger.warning(f"[POLL] signal-cli stderr: {stderr[:200]}")

            if returncode != 0:
                logger.warning(f"[POLL] signal-cli returned {returncode}")

            messages = []
            raw_output = stdout.strip()

            if raw_output:
                logger.debug(f"[POLL] Received {len(raw_output)} bytes")

            for line in raw_output.split('\n'):
                if line:
                    try:
                        msg = json.loads(line)
                        messages.append(msg)
                        env = msg.get('envelope', msg)
                        data_msg = env.get('dataMessage', {})
                        text = data_msg.get('message', '')
                        group_info = data_msg.get('groupInfo', {})
                        group = group_info.get('groupId', 'DM')
                        sender = env.get('source', 'unknown')

                        if text:
                            logger.info(f"[RAW MSG] from={sender} group={group[:20] if group != 'DM' else 'DM'}... text={text[:100]}")
                        else:
                            msg_type = 'receipt' if env.get('receiptMessage') else 'typing' if env.get('typingMessage') else 'other'
                            logger.debug(f"[RAW {msg_type.upper()}] from={sender}")
                    except json.JSONDecodeError as e:
                        logger.warning(f"[POLL] JSON decode error: {e} - line: {line[:100]}")
                        continue

            logger.debug(f"[POLL] Parsed {len(messages)} messages")
            return messages
        except subprocess.TimeoutExpired:
            logger.warning("[POLL] signal-cli timed out (killed) - will retry next cycle")
            return []
        except Exception as e:
            logger.error(f"[POLL] Failed to receive messages: {e}")
            return []

    async def send_message(self, group_id: str, message: str):
        """Send a message to a group via stdin (async)."""
        try:
            message = strip_markdown(message)

            balance = check_openrouter_balance()
            if balance is not None and balance < 10:
                message += f"\n\n⚠️ LOW BALANCE: ${balance:.2f} remaining"

            if len(message) > 4000:
                message = message[:3900] + "\n\n[truncated]"

            cmd = [self.signal_cli_path, "-u", self.phone_number, "send", "-g", group_id, "--message-from-stdin"]
            returncode, stdout, stderr = await run_subprocess_async(
                cmd, timeout=30, input_data=message.encode('utf-8')
            )

            if returncode == 0:
                logger.info(f"[-> SIGNAL]\n{message}")
            else:
                logger.error(f"[-> SIGNAL FAILED] {stderr}")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    def extract_group_message(self, envelope: dict) -> Optional[tuple[str, str, str, list]]:
        """Extract group ID, sender, message text, and mentions."""
        env = envelope.get('envelope', envelope)
        data_message = env.get('dataMessage', {})
        group_info = data_message.get('groupInfo', {})
        group_id = group_info.get('groupId')
        message = data_message.get('message')
        sender = env.get('source')
        mentions = data_message.get('mentions', [])

        if group_id and message and group_id in self.allowed_group_ids:
            return (group_id, sender, message, mentions)
        return None


# =============================================================================
# Claude Code Integration (Tiered Models)
# =============================================================================

# Global claude path (set by Orchestrator on init)
_claude_path = "claude"


async def call_claude_code(
    prompt: str,
    working_dir: Path,
    model: str = 'opus',
    allowed_tools: str = 'Read,Edit,Write,Bash,Glob,Grep',
    timeout: int = 600,
    session_id: Optional[str] = None,
    max_turns: int = 10
) -> tuple[str, Optional[str]]:
    """
    Execute Claude Code in headless mode (async).

    Uses --output-format json for reliable structured output.

    Args:
        prompt: The prompt to send
        working_dir: Directory to run from (for CLAUDE.md context)
        model: Model to use ('haiku', 'sonnet', 'opus')
        allowed_tools: Comma-separated tools
        timeout: Max seconds to wait
        session_id: Optional session ID to resume
        max_turns: Max agentic turns (cost control)

    Returns:
        (response_text, session_id)
    """
    if model == 'opus':
        logger.warning(f"[$$$ OPUS $$$] Calling Opus (tools: {allowed_tools})")
    else:
        logger.info(f"[CLAUDE] Calling {model}...")

    cmd = [
        _claude_path,
        "-p", prompt,
        "--output-format", "json",
        "--model", model,
        "--max-turns", str(max_turns),
    ]

    if allowed_tools:
        cmd.extend(["--tools", allowed_tools])

    if session_id:
        cmd.extend(["--resume", session_id])

    try:
        returncode, stdout, stderr = await run_subprocess_async(
            cmd, timeout=timeout, cwd=str(working_dir)
        )

        logger.info(f"[CLAUDE] {model} finished (rc={returncode})")

        if returncode != 0:
            logger.error(f"[CLAUDE ERROR] {stderr[:500] if stderr else 'No stderr'}")
            return f"Error (rc={returncode}): {stderr[:200] if stderr else 'Unknown error'}", session_id

        output = stdout.strip()
        if not output:
            logger.warning("[CLAUDE] Empty output")
            return "No response from Claude", session_id

        response_text = ""
        new_session_id = session_id

        try:
            data_list = json.loads(output)
            if isinstance(data_list, list):
                for item in data_list:
                    if isinstance(item, dict):
                        if 'session_id' in item:
                            new_session_id = item['session_id']
                        if item.get('type') == 'result' and 'result' in item:
                            response_text = item['result']
            else:
                if 'session_id' in data_list:
                    new_session_id = data_list['session_id']
                if 'result' in data_list:
                    response_text = data_list['result']

        except json.JSONDecodeError:
            logger.warning("[CLAUDE] Output not JSON, using as plain text")
            response_text = output

        if new_session_id and new_session_id != session_id:
            logger.info(f"[SESSION] {new_session_id[:20]}...")

        return response_text or "No response from Claude", new_session_id

    except subprocess.TimeoutExpired:
        logger.error(f"[TIMEOUT] Claude exceeded {timeout}s (killed)")
        return f"Request timed out after {timeout}s", session_id

    except Exception as e:
        logger.error(f"[CLAUDE] Failed: {e}")
        return f"Error: {e}", session_id


async def handle_message_tiered(
    message: str,
    status_lines: list[str],
    conversation: list[dict],
    ops_log: str,
    project_path: Path,
    sonnet_session_id: Optional[str] = None,
    opus_session_id: Optional[str] = None
) -> tuple[str, str, Optional[str], Optional[str]]:
    """
    Handle a message using tiered model approach (async).

    1. Try Sonnet with read-only tools
    2. If Sonnet needs action, escalate to Opus

    Returns:
        (response, model_used, sonnet_session_id, opus_session_id)
    """
    sonnet_prompt = message

    response, sonnet_session_id = await call_claude_code(
        prompt=sonnet_prompt,
        working_dir=project_path,
        model='sonnet',
        allowed_tools='Read,Glob,Grep',
        timeout=60,
        session_id=sonnet_session_id,
        max_turns=5
    )

    # Check for escalation
    logger.info(f"[SONNET] {response[:200]}...")
    if response.strip().upper().startswith('ESCALATE:'):
        reason = response.split(':', 1)[1].strip() if ':' in response else 'Action required'
        logger.info(f"[$$$ OPUS $$$] Escalating: {reason}")

        response, opus_session_id = await call_claude_code(
            prompt=message,
            working_dir=project_path,
            model='opus',
            allowed_tools='Read,Edit,Write,Bash,Glob,Grep',
            timeout=120,
            session_id=opus_session_id
        )
        return response, 'opus', sonnet_session_id, opus_session_id

    return response, 'sonnet', sonnet_session_id, opus_session_id


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

        # Set module-level OpenRouter API key for balance checking
        global _openrouter_api_key
        _openrouter_api_key = config.get('openrouter', {}).get('api_key')

        # State
        self.processed_timestamps: set = set()
        self.message_buffer: list[dict] = []
        self.buffer_size = config.get('context_buffer_size', 30)

        # Session IDs for persistent context (auto-compaction enabled)
        self.session_file = self.project_path / ".sessions.json"
        self.sonnet_session_id, self.opus_session_id = self._load_sessions()
        logger.info(f"[SESSION] Loaded - Sonnet: {self.sonnet_session_id[:20] if self.sonnet_session_id else 'None'}..., Opus: {self.opus_session_id[:20] if self.opus_session_id else 'None'}...")

    def _load_sessions(self) -> tuple[Optional[str], Optional[str]]:
        """Load session IDs from disk."""
        try:
            if self.session_file.exists():
                with open(self.session_file) as f:
                    data = json.load(f)
                    return data.get('sonnet'), data.get('opus')
        except Exception as e:
            logger.warning(f"Could not load sessions: {e}")
        return None, None

    def _save_sessions(self):
        """Persist session IDs to disk."""
        try:
            with open(self.session_file, 'w') as f:
                json.dump({
                    'sonnet': self.sonnet_session_id,
                    'opus': self.opus_session_id,
                    'updated': datetime.now().isoformat()
                }, f)
        except Exception as e:
            logger.warning(f"Could not save sessions: {e}")

    async def run(self):
        """Main entry point - runs signal and monitoring as independent tasks."""
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
            # Run signal polling, health monitoring, and cleanup as INDEPENDENT tasks
            # They don't block each other
            await asyncio.gather(
                self._signal_loop(),
                self._monitoring_loop(),
                self._cleanup_loop(),
            )
        finally:
            # Clean shutdown - remove marker, skip message (can block if signal-cli hung)
            logger.info("Shutting down...")
            self._clear_running_marker()
            self.memory.add_event("Clean shutdown")

    async def _signal_loop(self):
        """Independent loop for Signal message polling."""
        logger.info("[SIGNAL LOOP] Started")
        while True:
            try:
                await self._process_messages()
            except Exception as e:
                logger.error(f"[SIGNAL LOOP] Error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def _monitoring_loop(self):
        """Independent loop for health monitoring."""
        logger.info("[MONITOR LOOP] Started")
        # Now independent from signal polling - can run frequently
        health_check_interval = self.config.get('health_check_interval', 10)
        while True:
            try:
                await self._smart_monitoring_check()
            except Exception as e:
                logger.error(f"[MONITOR LOOP] Error: {e}")
            await asyncio.sleep(health_check_interval)

    async def _cleanup_loop(self):
        """
        Independent loop for temp folder cleanup (Windows only).

        Cleans up orphaned libsignal temp folders that can accumulate
        if the java.library.path fix stops working.

        Runs hourly by default. If folders are found, logs a warning
        as early detection that the permanent fix needs attention.
        """
        # Configurable interval (default 1 hour)
        cleanup_interval = self.config.get('temp_cleanup_interval', 3600)

        # Skip if disabled (interval <= 0)
        if cleanup_interval <= 0:
            logger.info("[CLEANUP LOOP] Disabled (temp_cleanup_interval <= 0)")
            return

        logger.info(f"[CLEANUP LOOP] Started (interval: {cleanup_interval}s)")

        # Run once at startup to catch any existing accumulation
        cleanup_libsignal_temp_folders()

        while True:
            await asyncio.sleep(cleanup_interval)
            try:
                result = cleanup_libsignal_temp_folders()
                if result['warning']:
                    # Also log to memory for visibility
                    self.memory.add_event(
                        f"Cleanup warning: found {result['checked']} libsignal temp folders, "
                        f"deleted {result['deleted']}. Check java.library.path fix."
                    )
            except Exception as e:
                logger.error(f"[CLEANUP LOOP] Error: {e}")

    async def _process_messages(self):
        """Process incoming Signal messages."""
        messages = await self.signal.receive_messages()

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
                # Log why it was skipped
                data_msg = envelope.get('dataMessage', {})
                group_info = data_msg.get('groupInfo', {})
                group_id = group_info.get('groupId', 'none')
                text = data_msg.get('message', '')
                if text:
                    logger.debug(f"[SKIP] group={group_id[:20] if group_id else 'DM'}... not in allowed list or no text")
                continue

            group_id, sender, message_text, mentions = parsed
            logger.info(f"[<- SIGNAL] from {sender}: {message_text}")
            if mentions:
                logger.info(f"[MENTIONS] {len(mentions)} mention(s) detected")

            # Buffer all messages for context
            self.message_buffer.append({'sender': sender, 'text': message_text})
            if len(self.message_buffer) > self.buffer_size:
                self.message_buffer = self.message_buffer[-self.buffer_size:]

            # Check for @opus direct trigger (bypasses Sonnet)
            direct_opus = 'opus' in message_text.lower()

            # Check trigger: mentions array OR literal trigger word
            has_mention = len(mentions) > 0
            has_trigger_word = self.trigger_word and self.trigger_word in message_text.lower()

            if not has_mention and not has_trigger_word:
                logger.debug(f"[SKIP] no mention and no trigger word '{self.trigger_word}'")
                continue

            logger.info(f"[TRIGGERED] {'@opus direct' if direct_opus else 'via ' + ('mention' if has_mention else 'trigger word')}")

            # Get context for prompt
            status_lines = self._get_status_lines()
            ops_log = self.memory.get_context_for_claude()

            # Route to appropriate model
            if direct_opus:
                # Direct Opus access - bypass Sonnet entirely
                logger.info("[$$$ OPUS $$$] Direct Opus request")

                response, self.opus_session_id = await call_claude_code(
                    prompt=message_text,
                    working_dir=self.project_path,
                    model='opus',
                    allowed_tools='Read,Edit,Write,Bash,Glob,Grep',
                    timeout=120,
                    session_id=self.opus_session_id
                )
                self._save_sessions()
                model_used = 'opus'

            elif self.use_tiered_models:
                # Tiered: Sonnet first, escalate to Opus if needed
                response, model_used, self.sonnet_session_id, self.opus_session_id = await handle_message_tiered(
                    message_text, status_lines, self.message_buffer, ops_log, self.project_path,
                    sonnet_session_id=self.sonnet_session_id,
                    opus_session_id=self.opus_session_id
                )
                self._save_sessions()
                logger.info(f"Handled by {model_used}")
            else:
                # Legacy: always use Opus
                response, self.opus_session_id = await call_claude_code(
                    message_text, self.project_path, session_id=self.opus_session_id
                )
                self._save_sessions()
                model_used = 'opus'

            # Log event
            self.memory.add_event(f"Responded to: {message_text[:50]}...")

            # Send response with model attribution
            tagged_response = f"{response}\n\n— {model_used}"
            await self.signal.send_message(group_id, tagged_response)

    async def _smart_monitoring_check(self):
        """Event-driven monitoring - only invoke Claude when interesting."""
        # Get current status from all monitors
        logger.debug("[MONITOR] Health check running...")
        raw_status = self.health.get_all_status()
        logger.debug("[MONITOR] Health check complete")
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
            # Let Sonnet observe and report if needed
            await self._sonnet_observation(reason, changed_metrics)

    async def _sonnet_observation(self, reason: str, changed_metrics: list[str]):
        """Have Sonnet observe the system and report if needed."""
        change_summary = self.smart_monitor.get_change_summary(changed_metrics)

        prompt = f"""System check-in. Changes: {change_summary}

If all good, say "All clear." Only message if something's off."""

        response, self.sonnet_session_id = await call_claude_code(
            prompt=prompt,
            working_dir=self.project_path,
            model='sonnet',
            allowed_tools='Read,Glob,Grep',
            timeout=60,
            session_id=self.sonnet_session_id,
            max_turns=5
        )
        self._save_sessions()

        response_lower = response.lower().strip()

        if 'all clear' in response_lower:
            logger.info("Sonnet: All clear")
            return

        # Alert - high priority
        if response_lower.startswith('alert:'):
            self.memory.add_event(f"Alert: {response[:200]}")
            for group_id in self.signal.allowed_group_ids:
                await self.signal.send_message(group_id, f"🚨 {response}\n\n— sonnet")
        else:
            self.memory.add_event(f"Observation: {response[:200]}")
            logger.info(f"Sonnet observation: {response}")
            for group_id in self.signal.allowed_group_ids:
                await self.signal.send_message(group_id, f"{response}\n\n— sonnet")

    async def _verification_check(self, status: dict):
        """Verify that a recent Opus fix worked."""
        prompt = """Opus just made a fix. Did it work? Say "Fix verified" or "ALERT: still broken"."""

        response, self.sonnet_session_id = await call_claude_code(
            prompt=prompt,
            working_dir=self.project_path,
            model='sonnet',
            allowed_tools='Read,Glob,Grep',
            timeout=60,
            session_id=self.sonnet_session_id,
            max_turns=5
        )
        self._save_sessions()

        self.memory.add_event(f"Verification: {response[:200]}")

        if 'alert:' in response.lower():
            for group_id in self.signal.allowed_group_ids:
                await self.signal.send_message(group_id, f"🚨 {response}\n\n— sonnet")

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

        # Build startup message
        if is_crash_recovery:
            lines = ["SUNFISH back online (crash recovery)\n"]
        else:
            lines = ["SUNFISH online\n"]

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
            lines.append("\n🚨 Issues detected:")
            for alert in alerts:
                lines.append(f"  - {alert}")

        message = "\n".join(lines)

        # Send to all groups
        for group_id in self.signal.allowed_group_ids:
            await self.signal.send_message(group_id, message)

        # Log the startup appropriately
        if is_crash_recovery:
            self.memory.add_event("CRASH RECOVERY - orchestrator restarted after unexpected shutdown")
            self.memory.add_active_issue("Investigate recent crash - check logs/orchestrator.log")

            # Have Sonnet analyze what might have caused the crash
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
        """Have Sonnet analyze what might have caused the crash."""
        logger.info("Analyzing potential crash cause...")

        prompt = """System crashed and restarted. Quick take - what happened?"""

        response, self.sonnet_session_id = await call_claude_code(
            prompt=prompt,
            working_dir=self.project_path,
            model='sonnet',
            allowed_tools='Read,Glob,Grep',
            timeout=60,
            session_id=self.sonnet_session_id,
            max_turns=5
        )
        self._save_sessions()

        logger.info(f"Crash analysis: {response}")
        self.memory.add_event(f"Crash analysis: {response[:250]}")

        if 'unknown' not in response.lower():
            self.memory.add_to_history(f"Crash on {datetime.now().strftime('%m/%d')}: {response[:150]}")

    async def _attempt_auto_recovery(self, alerts: list[str]):
        """
        Let Opus attempt to recover from startup issues.
        Only runs if auto_recovery is enabled in config.
        """
        logger.info("Attempting auto-recovery...")

        alerts_text = "\n".join([f"- {a}" for a in alerts])

        prompt = f"""System restarted with issues: {alerts_text}

Fix what you can and let us know what you did."""

        response, self.opus_session_id = await call_claude_code(
            prompt=prompt,
            working_dir=self.project_path,
            model='opus',
            allowed_tools='Read,Edit,Write,Bash,Glob,Grep',
            timeout=120,
            session_id=self.opus_session_id
        )
        self._save_sessions()

        self.memory.add_event(f"Auto-recovery: {response[:200]}")

        for group_id in self.signal.allowed_group_ids:
            await self.signal.send_message(group_id, f"🔧 Auto-recovery:\n{response}\n\n— opus")

        self.smart_monitor.schedule_verification()

    def _get_status_lines(self) -> list[str]:
        """Get current status as a list of one-liner strings."""
        lines = []
        for name, monitor in self.health.monitors.items():
            try:
                lines.append(monitor.get_status_line())
            except Exception as e:
                lines.append(f"{name}: error ({e})")

        # Add OpenRouter balance
        balance = check_openrouter_balance()
        if balance is not None:
            lines.append(f"OpenRouter: ${balance:.2f} remaining")
            logger.info(f"[BALANCE] OpenRouter: ${balance:.2f}")

        return lines

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
    """
    Main entry point with graceful shutdown handling.

    - First Ctrl+C: Attempts graceful shutdown (5 second timeout)
    - Second Ctrl+C or timeout: Forces immediate exit
    """
    config = load_config()
    orchestrator = Orchestrator(config)

    # Track if we're already shutting down
    shutting_down = False

    def force_exit():
        """Force exit after timeout."""
        logger.warning("Shutdown timeout - forcing exit")
        os._exit(1)

    def handle_interrupt():
        """Handle Ctrl+C with timeout."""
        nonlocal shutting_down
        if shutting_down:
            # Second interrupt - force exit
            logger.warning("Second interrupt - forcing immediate exit")
            os._exit(1)

        shutting_down = True
        logger.info("Shutting down (Ctrl+C again to force)...")

        # Schedule force exit after 5 seconds
        import threading
        timer = threading.Timer(5.0, force_exit)
        timer.daemon = True
        timer.start()

    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        handle_interrupt()
        # Give the finally block a chance to run
        try:
            # Brief pause for cleanup
            pass
        except KeyboardInterrupt:
            force_exit()


if __name__ == "__main__":
    main()
