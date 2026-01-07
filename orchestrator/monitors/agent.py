"""
Agent Monitor - Track the streaming agent process and logs

Monitors the AI agent that runs the stream content.
"""

import os
import subprocess
import platform
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from .base import BaseMonitor


class AgentMonitor(BaseMonitor):
    name = "agent"

    def __init__(self, config: dict):
        super().__init__(config)
        self.log_path = Path(config.get('log_path', './agent/logs'))
        self.process_name = config.get('process_name', '')
        self.log_file = config.get('log_file', 'agent.log')
        self.is_windows = platform.system() == 'Windows'

    def get_status(self) -> dict:
        """Get agent status."""
        status = {
            'healthy': True,
            'process_running': self._check_process(),
            'last_log_age_sec': self._get_log_age(),
            'last_log_lines': self._get_recent_logs(5),
            'error_count_recent': self._count_recent_errors()
        }

        # Check if process is running
        if self.process_name and not status['process_running']:
            status['healthy'] = False

        # Check if logs are stale (no output in 5 minutes)
        max_log_age = self.alerts_config.get('max_log_age_sec', 300)
        if status['last_log_age_sec'] and status['last_log_age_sec'] > max_log_age:
            status['healthy'] = False

        # Check alerts
        alerts = self.get_alerts()
        if alerts:
            status['healthy'] = False
            status['alerts'] = alerts

        self._last_status = status
        return status

    def get_alerts(self) -> list[str]:
        """Check agent health."""
        alerts = []
        status = self._last_status or {}

        if self.process_name and not status.get('process_running'):
            alerts.append(f"Agent process '{self.process_name}' not running")

        max_log_age = self.alerts_config.get('max_log_age_sec', 300)
        log_age = status.get('last_log_age_sec')
        if log_age and log_age > max_log_age:
            alerts.append(f"Agent logs stale ({log_age}s since last output)")

        max_errors = self.alerts_config.get('max_errors_per_hour', 10)
        if status.get('error_count_recent', 0) > max_errors:
            alerts.append(f"Agent has {status['error_count_recent']} recent errors")

        return alerts

    def get_status_line(self) -> str:
        """One-line summary."""
        s = self.get_status()

        parts = []

        if self.process_name:
            parts.append("Running" if s.get('process_running') else "STOPPED")

        log_age = s.get('last_log_age_sec')
        if log_age is not None:
            if log_age < 60:
                parts.append(f"last output {log_age}s ago")
            else:
                parts.append(f"last output {log_age // 60}m ago")

        errors = s.get('error_count_recent', 0)
        if errors > 0:
            parts.append(f"{errors} recent errors")

        return f"Agent: {', '.join(parts)}" if parts else "Agent: No data"

    def _check_process(self) -> bool:
        """Check if agent process is running."""
        if not self.process_name:
            return True  # No process configured, skip check

        try:
            if self.is_windows:
                result = subprocess.run(
                    ['tasklist', '/FI', f'IMAGENAME eq {self.process_name}*'],
                    capture_output=True, text=True, timeout=5
                )
                return self.process_name.lower() in result.stdout.lower()
            else:
                result = subprocess.run(
                    ['pgrep', '-f', self.process_name],
                    capture_output=True, text=True, timeout=5
                )
                return result.returncode == 0
        except Exception:
            return False

    def _get_log_age(self) -> Optional[int]:
        """Get seconds since last log modification."""
        log_file = self.log_path / self.log_file

        if not log_file.exists():
            # Try to find any log file
            if self.log_path.exists():
                log_files = list(self.log_path.glob('*.log'))
                if log_files:
                    log_file = max(log_files, key=lambda f: f.stat().st_mtime)
                else:
                    return None
            else:
                return None

        try:
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            age = datetime.now() - mtime
            return int(age.total_seconds())
        except Exception:
            return None

    def _get_recent_logs(self, n: int = 10) -> list[str]:
        """Get last N lines from log file."""
        log_file = self.log_path / self.log_file

        if not log_file.exists():
            if self.log_path.exists():
                log_files = list(self.log_path.glob('*.log'))
                if log_files:
                    log_file = max(log_files, key=lambda f: f.stat().st_mtime)
                else:
                    return []
            else:
                return []

        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                return [l.strip() for l in lines[-n:]]
        except Exception:
            return []

    def _count_recent_errors(self, hours: int = 1) -> int:
        """Count error lines in recent logs."""
        log_file = self.log_path / self.log_file

        if not log_file.exists():
            return 0

        error_keywords = ['error', 'exception', 'failed', 'crash', 'fatal']
        count = 0

        try:
            # Simple approach: count error keywords in last 1000 lines
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()[-1000:]
                for line in lines:
                    if any(kw in line.lower() for kw in error_keywords):
                        count += 1
        except Exception:
            pass

        return count
