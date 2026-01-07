"""
Base monitor class - all monitors inherit from this.

To create a new monitor:
1. Create a new file in monitors/
2. Inherit from BaseMonitor
3. Implement get_status() and optionally get_alerts(), execute()
4. Add to monitors/__init__.py
5. Add config section in settings.yaml
"""

from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseMonitor(ABC):
    """Base class for all system monitors."""

    name: str = "base"  # Override in subclass

    def __init__(self, config: dict):
        """
        Initialize monitor with config from settings.yaml.

        Args:
            config: The monitor's section from settings.yaml
        """
        self.config = config
        self.enabled = config.get('enabled', True)
        self.alerts_config = config.get('alerts', {})
        self._last_status: dict = {}

    @abstractmethod
    def get_status(self) -> dict:
        """
        Get current status of the monitored system.

        Returns:
            Dict with status info. Keys vary by monitor type.
            Should include 'healthy': bool
        """
        pass

    def get_alerts(self) -> list[str]:
        """
        Check for any threshold violations.

        Returns:
            List of alert messages (empty if all good)
        """
        # Default implementation - override for custom logic
        return []

    def execute(self, command: str) -> dict:
        """
        Execute a command on this system (optional).

        Args:
            command: Command string (e.g., "restart", "stop")

        Returns:
            Dict with 'success': bool and 'message': str
        """
        return {
            'success': False,
            'message': f"Monitor '{self.name}' does not support commands"
        }

    def get_status_line(self) -> str:
        """
        Get a one-line status summary for Claude's context.
        Override for custom formatting.
        """
        status = self.get_status()
        if not status:
            return f"{self.name}: unavailable"
        return f"{self.name}: {status}"

    def __repr__(self):
        return f"<{self.__class__.__name__} enabled={self.enabled}>"
