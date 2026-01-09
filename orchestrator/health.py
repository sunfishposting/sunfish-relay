"""
Health Aggregator - Collects status from all monitors and manages alerts.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from monitors import BaseMonitor, VPSMonitor, OBSMonitor, AgentMonitor, UnityMonitor

logger = logging.getLogger(__name__)

# Shared thread pool for monitor operations (prevents blocking event loop)
_monitor_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="monitor")


# Registry of available monitor classes
MONITOR_CLASSES = {
    'vps': VPSMonitor,
    'obs': OBSMonitor,
    'agent': AgentMonitor,
    'unity': UnityMonitor,
    # Add new monitors here
}


class HealthAggregator:
    """Aggregates health status from all configured monitors."""

    def __init__(self, config: dict):
        """
        Initialize with monitors config.

        Args:
            config: The 'monitors' section from settings.yaml
        """
        self.monitors: dict[str, BaseMonitor] = {}
        self._load_monitors(config)

    def _load_monitors(self, config: dict):
        """Load and initialize configured monitors."""
        monitors_config = config.get('monitors', {})

        for name, monitor_config in monitors_config.items():
            if not monitor_config.get('enabled', True):
                logger.info(f"Monitor '{name}' is disabled")
                continue

            if name in MONITOR_CLASSES:
                try:
                    self.monitors[name] = MONITOR_CLASSES[name](monitor_config)
                    logger.info(f"Loaded monitor: {name}")
                except Exception as e:
                    logger.error(f"Failed to load monitor '{name}': {e}")
            else:
                logger.warning(f"Unknown monitor type: {name}")

    def get_all_status(self) -> dict:
        """
        Get status from all monitors.

        Returns:
            Dict mapping monitor name to status dict
        """
        statuses = {}
        for name, monitor in self.monitors.items():
            try:
                logger.debug(f"[HEALTH] Checking {name}...")
                statuses[name] = monitor.get_status()
                logger.debug(f"[HEALTH] {name} done")
            except Exception as e:
                logger.error(f"Error getting status from {name}: {e}")
                statuses[name] = {'healthy': False, 'error': str(e)}
        return statuses

    def get_all_alerts(self) -> list[str]:
        """
        Collect alerts from all monitors.

        Returns:
            List of alert messages
        """
        alerts = []
        for name, monitor in self.monitors.items():
            try:
                monitor_alerts = monitor.get_alerts()
                alerts.extend(monitor_alerts)
            except Exception as e:
                logger.error(f"Error getting alerts from {name}: {e}")
        return alerts

    def get_status_summary(self) -> str:
        """
        Get a formatted status summary for Claude's context.

        Returns:
            Multi-line string with all monitor statuses
        """
        lines = ["## Current System Status"]

        for name, monitor in self.monitors.items():
            try:
                lines.append(f"- {monitor.get_status_line()}")
            except Exception as e:
                lines.append(f"- {name}: error ({e})")

        alerts = self.get_all_alerts()
        if alerts:
            lines.append("")
            lines.append("## Active Alerts")
            for alert in alerts:
                lines.append(f"- {alert}")
        else:
            lines.append("")
            lines.append("## Active Alerts: None")

        return "\n".join(lines)

    def is_healthy(self) -> bool:
        """Check if all monitors report healthy."""
        for name, monitor in self.monitors.items():
            try:
                status = monitor.get_status()
                if not status.get('healthy', True):
                    return False
            except Exception:
                return False
        return True

    def get_monitor(self, name: str) -> Optional[BaseMonitor]:
        """Get a specific monitor by name."""
        return self.monitors.get(name)

    def execute_command(self, monitor_name: str, command: str) -> dict:
        """
        Execute a command on a specific monitor.

        Args:
            monitor_name: Name of the monitor (e.g., 'obs')
            command: Command to execute (e.g., 'start_stream')

        Returns:
            Result dict with 'success' and 'message'
        """
        monitor = self.monitors.get(monitor_name)
        if not monitor:
            return {'success': False, 'message': f"Monitor '{monitor_name}' not found"}

        return monitor.execute(command)

    # =========================================================================
    # Async versions (non-blocking for event loop)
    # =========================================================================

    async def get_all_status_async(self) -> dict:
        """
        Get status from all monitors without blocking the event loop.

        Runs monitor checks in a thread pool to prevent blocking Signal polling.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_monitor_executor, self.get_all_status)

    async def get_all_alerts_async(self) -> list[str]:
        """Get alerts from all monitors without blocking the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_monitor_executor, self.get_all_alerts)

    async def get_status_summary_async(self) -> str:
        """Get formatted status summary without blocking the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_monitor_executor, self.get_status_summary)
