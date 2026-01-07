# Monitor plugins
# Add new monitors here and they'll be auto-discovered

from .base import BaseMonitor
from .vps import VPSMonitor
from .obs import OBSMonitor
from .agent import AgentMonitor
from .unity import UnityMonitor

__all__ = ['BaseMonitor', 'VPSMonitor', 'OBSMonitor', 'AgentMonitor', 'UnityMonitor']
