#!/usr/bin/env python3
"""
Sunfish Relay Orchestrator
Bridges Signal messages to Claude Code for VPS/stream administration.

Supports two modes:
- Native: Uses signal-cli directly (for local Mac development)
- Docker: Uses signal-cli-rest-api (for containerized deployment)
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Protocol

import yaml

# Configure logging (minimal to avoid leaking sensitive data)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class SignalClientProtocol(Protocol):
    """Protocol for Signal clients."""
    def configure(self, phone_number: str, allowed_group_ids: list[str]) -> None: ...
    def receive_messages(self) -> list[dict]: ...
    def send_message(self, group_id: str, message: str) -> None: ...
    def extract_group_message(self, envelope: dict) -> Optional[tuple[str, str, str]]: ...


class SignalCLINative:
    """Native signal-cli client (for local development without Docker)."""

    def __init__(self):
        self.phone_number: Optional[str] = None
        self.allowed_group_ids: set[str] = set()

    def configure(self, phone_number: str, allowed_group_ids: list[str]):
        self.phone_number = phone_number
        self.allowed_group_ids = set(allowed_group_ids)

    def receive_messages(self) -> list[dict]:
        """Poll for new messages using signal-cli."""
        try:
            result = subprocess.run(
                ["signal-cli", "-u", self.phone_number, "receive", "--json"],
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
        """Send a message to a group using signal-cli."""
        try:
            if len(message) > 4000:
                message = message[:3900] + "\n\n[Message truncated]"

            subprocess.run(
                ["signal-cli", "-u", self.phone_number, "send", "-g", group_id, "-m", message],
                capture_output=True,
                text=True,
                timeout=30
            )
            logger.info("Message sent successfully")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    def extract_group_message(self, envelope: dict) -> Optional[tuple[str, str, str]]:
        """Extract group ID, sender, and message text from an envelope."""
        # Native signal-cli JSON format
        env = envelope.get('envelope', envelope)
        data_message = env.get('dataMessage', {})
        group_info = data_message.get('groupInfo', {})
        group_id = group_info.get('groupId')
        message = data_message.get('message')
        sender = env.get('source')

        if group_id and message and group_id in self.allowed_group_ids:
            return (group_id, sender, message)
        return None


class SignalRESTClient:
    """REST API client for signal-cli-rest-api (Docker deployment)."""

    def __init__(self, base_url: str):
        # Lazy import - only needed in Docker mode
        import requests
        self._requests = requests
        self.base_url = base_url.rstrip('/')
        self.phone_number: Optional[str] = None
        self.allowed_group_ids: set[str] = set()

    def configure(self, phone_number: str, allowed_group_ids: list[str]):
        self.phone_number = phone_number
        self.allowed_group_ids = set(allowed_group_ids)

    def receive_messages(self) -> list[dict]:
        try:
            resp = self._requests.get(
                f"{self.base_url}/v1/receive/{self.phone_number}",
                timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to receive messages: {e}")
            return []

    def send_message(self, group_id: str, message: str):
        try:
            if len(message) > 4000:
                message = message[:3900] + "\n\n[Message truncated]"

            resp = self._requests.post(
                f"{self.base_url}/v2/send",
                json={
                    "number": self.phone_number,
                    "recipients": [group_id],
                    "message": message
                },
                timeout=30
            )
            resp.raise_for_status()
            logger.info("Message sent successfully")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    def extract_group_message(self, envelope: dict) -> Optional[tuple[str, str, str]]:
        data_message = envelope.get('dataMessage', {})
        group_info = data_message.get('groupInfo', {})
        group_id = group_info.get('groupId')
        message = data_message.get('message')
        sender = envelope.get('source')

        if group_id and message and group_id in self.allowed_group_ids:
            return (group_id, sender, message)
        return None


def call_claude_code(prompt: str, working_dir: Path) -> str:
    """
    Execute Claude Code in headless mode and return the response.
    Uses your Claude subscription (Pro/Max) or API key if set.
    """
    try:
        result = subprocess.run(
            [
                "claude", "-p", prompt,
                "--output-format", "text",
                "--allowedTools", "Read,Edit,Write,Bash,Glob,Grep"
            ],
            capture_output=True,
            text=True,
            cwd=str(working_dir),
            timeout=120
        )

        if result.returncode != 0 and result.stderr:
            logger.error(f"Claude Code error: {result.stderr}")
            return f"Error: {result.stderr[:500]}"

        return result.stdout.strip() or "Task completed (no output)"

    except subprocess.TimeoutExpired:
        return "Request timed out after 2 minutes"
    except Exception as e:
        logger.error(f"Claude Code execution failed: {e}")
        return f"Failed to execute: {e}"


def load_config() -> dict:
    """Load configuration from file or environment."""
    # Check multiple config locations
    config_paths = [
        Path('./config/settings.yaml'),           # Local dev
        Path('/app/config/settings.yaml'),        # Docker
        Path.home() / '.config/sunfish/settings.yaml'  # User config
    ]

    for config_path in config_paths:
        if config_path.exists():
            logger.info(f"Loading config from {config_path}")
            with open(config_path) as f:
                return yaml.safe_load(f)

    logger.error("No config file found. Create config/settings.yaml")
    sys.exit(1)


def get_project_path(config: dict) -> Path:
    """Get the stream project path."""
    # Check config, then env, then defaults
    if 'project_path' in config:
        return Path(config['project_path'])
    if os.environ.get('STREAM_PROJECT_PATH'):
        return Path(os.environ['STREAM_PROJECT_PATH'])

    # Default locations
    for path in [Path('./stream-project'), Path('/app/stream-project')]:
        if path.exists():
            return path

    return Path('.')


async def main():
    """Main orchestrator loop."""
    logger.info("Starting Sunfish Relay Orchestrator")

    # Load configuration
    config = load_config()

    # Determine mode: native (local) or docker (REST API)
    mode = os.environ.get('SIGNAL_MODE', config.get('signal', {}).get('mode', 'native'))

    if mode == 'docker' or os.environ.get('SIGNAL_API_URL'):
        api_url = os.environ.get('SIGNAL_API_URL', 'http://signal-api:8080')
        signal: SignalClientProtocol = SignalRESTClient(api_url)
        logger.info(f"Using REST API mode: {api_url}")
    else:
        signal = SignalCLINative()
        logger.info("Using native signal-cli mode")

    signal.configure(
        phone_number=config['signal']['phone_number'],
        allowed_group_ids=config['signal']['allowed_group_ids']
    )

    # Get project path
    project_path = get_project_path(config)
    logger.info(f"Stream project path: {project_path}")

    # Optional OBS integration
    obs_client = None
    obs_config = config.get('obs', {})
    if obs_config.get('enabled', False):
        try:
            from obs_client import OBSClient
            obs_client = OBSClient(
                host=os.environ.get('OBS_HOST', obs_config.get('host', 'localhost')),
                port=int(os.environ.get('OBS_PORT', obs_config.get('port', 4455))),
                password=obs_config.get('password', '')
            )
            obs_client.connect()
            logger.info("Connected to OBS")
        except Exception as e:
            logger.warning(f"Could not connect to OBS: {e}")

    logger.info("Orchestrator ready, polling for messages...")

    # Main loop
    processed_timestamps = set()
    poll_interval = int(os.environ.get('POLL_INTERVAL', config.get('poll_interval', 2)))

    while True:
        try:
            messages = signal.receive_messages()

            for msg in messages:
                envelope = msg.get('envelope', msg)
                timestamp = envelope.get('timestamp')

                if timestamp in processed_timestamps:
                    continue
                processed_timestamps.add(timestamp)

                # Prevent unbounded growth
                if len(processed_timestamps) > 1000:
                    processed_timestamps = set(list(processed_timestamps)[-500:])

                parsed = signal.extract_group_message(msg)
                if not parsed:
                    continue

                group_id, sender, message_text = parsed
                logger.info("Received command from group")

                # Build context
                context_parts = []
                if obs_client and obs_client.connected:
                    try:
                        status = obs_client.get_stream_status()
                        context_parts.append(f"Stream: {'LIVE' if status.get('active') else 'OFF'}")
                    except Exception:
                        pass

                prompt = f"""You are a stream/VPS administrator. User command via Signal:

"{message_text}"

{f"Status: {' | '.join(context_parts)}" if context_parts else ""}

Project files at: {project_path}
Respond concisely for mobile chat. Execute clear requests, ask about ambiguous ones."""

                response = call_claude_code(prompt, project_path)
                signal.send_message(group_id, response)

        except Exception as e:
            logger.error(f"Error in main loop: {e}")

        await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    asyncio.run(main())
