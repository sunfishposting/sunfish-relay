"""
VPS Monitor - System resources (CPU, RAM, Disk, GPU)

Works on Windows Server with NVIDIA GPU.
"""

import subprocess
import platform
from .base import BaseMonitor


class VPSMonitor(BaseMonitor):
    name = "vps"

    def __init__(self, config: dict):
        super().__init__(config)
        self.is_windows = platform.system() == 'Windows'

    def get_status(self) -> dict:
        """Get VPS resource status."""
        status = {
            'healthy': True,
            'cpu_percent': self._get_cpu(),
            'memory_percent': self._get_memory(),
            'disk_percent': self._get_disk(),
            'gpu': self._get_gpu()
        }

        # Store before checking alerts to prevent recursion
        self._last_status = status

        # Check thresholds
        alerts = self.get_alerts()
        if alerts:
            status['healthy'] = False
            status['alerts'] = alerts
            self._last_status = status

        return status

    def get_alerts(self) -> list[str]:
        """Check resource thresholds."""
        alerts = []

        # Use cached status or fetch fresh (but _last_status should always exist after get_status runs once)
        if not self._last_status:
            # Fetch raw metrics without recursing through get_status
            status = {
                'cpu_percent': self._get_cpu(),
                'memory_percent': self._get_memory(),
                'disk_percent': self._get_disk(),
                'gpu': self._get_gpu()
            }
        else:
            status = self._last_status

        thresholds = self.alerts_config

        if status.get('cpu_percent', 0) > thresholds.get('cpu_pct_max', 95):
            alerts.append(f"CPU high: {status['cpu_percent']}%")

        if status.get('memory_percent', 0) > thresholds.get('memory_pct_max', 90):
            alerts.append(f"Memory high: {status['memory_percent']}%")

        if status.get('disk_percent', 0) > thresholds.get('disk_pct_max', 85):
            alerts.append(f"Disk high: {status['disk_percent']}%")

        gpu = status.get('gpu', {})
        if gpu.get('temp', 0) > thresholds.get('gpu_temp_max', 80):
            alerts.append(f"GPU temp high: {gpu['temp']}C")

        if gpu.get('utilization', 0) > thresholds.get('gpu_util_max', 95):
            alerts.append(f"GPU util high: {gpu['utilization']}%")

        return alerts

    def get_status_line(self) -> str:
        """One-line summary."""
        s = self.get_status()
        gpu = s.get('gpu', {})
        gpu_str = f"GPU {gpu.get('utilization', '?')}% @ {gpu.get('temp', '?')}C" if gpu else "GPU: N/A"
        return f"VPS: CPU {s.get('cpu_percent', '?')}%, RAM {s.get('memory_percent', '?')}%, Disk {s.get('disk_percent', '?')}%, {gpu_str}"

    def _get_cpu(self) -> float:
        """Get CPU usage percent."""
        try:
            if self.is_windows:
                # Use wmic on Windows
                result = subprocess.run(
                    ['wmic', 'cpu', 'get', 'loadpercentage'],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.strip().split('\n'):
                    line = line.strip()
                    if line.isdigit():
                        return float(line)
            else:
                # Use top on Unix
                result = subprocess.run(
                    ['top', '-bn1'],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.split('\n'):
                    if 'Cpu' in line or '%Cpu' in line:
                        # Parse CPU idle and calculate usage
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if 'id' in part or part == 'id,':
                                idle = float(parts[i-1].replace(',', '.'))
                                return round(100 - idle, 1)
        except Exception:
            pass
        return 0.0

    def _get_memory(self) -> float:
        """Get memory usage percent."""
        try:
            if self.is_windows:
                result = subprocess.run(
                    ['wmic', 'OS', 'get', 'FreePhysicalMemory,TotalVisibleMemorySize'],
                    capture_output=True, text=True, timeout=5
                )
                lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
                if len(lines) >= 2:
                    values = lines[1].split()
                    if len(values) >= 2:
                        free = int(values[0])
                        total = int(values[1])
                        return round((1 - free/total) * 100, 1)
            else:
                result = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=5)
                for line in result.stdout.split('\n'):
                    if line.startswith('Mem:'):
                        parts = line.split()
                        total = float(parts[1])
                        used = float(parts[2])
                        return round((used / total) * 100, 1)
        except Exception:
            pass
        return 0.0

    def _get_disk(self) -> float:
        """Get disk usage percent for main drive."""
        try:
            if self.is_windows:
                result = subprocess.run(
                    ['wmic', 'logicaldisk', 'where', 'DeviceID="C:"', 'get', 'Size,FreeSpace'],
                    capture_output=True, text=True, timeout=5
                )
                lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
                if len(lines) >= 2:
                    values = lines[1].split()
                    if len(values) >= 2:
                        free = int(values[0])
                        size = int(values[1])
                        return round((1 - free/size) * 100, 1)
            else:
                result = subprocess.run(['df', '/'], capture_output=True, text=True, timeout=5)
                for line in result.stdout.split('\n'):
                    if '/' in line and '%' in line:
                        parts = line.split()
                        for part in parts:
                            if '%' in part:
                                return float(part.replace('%', ''))
        except Exception:
            pass
        return 0.0

    def _get_gpu(self) -> dict:
        """Get NVIDIA GPU status."""
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                parts = [p.strip() for p in result.stdout.strip().split(',')]
                if len(parts) >= 5:
                    return {
                        'utilization': int(parts[0]),
                        'temp': int(parts[1]),
                        'memory_used_mb': int(parts[2]),
                        'memory_total_mb': int(parts[3]),
                        'power_watts': float(parts[4])
                    }
        except Exception:
            pass
        return {}
