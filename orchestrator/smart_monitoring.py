"""
Smart Monitoring System

Event-driven monitoring that only invokes Claude when something interesting happens.
Designed to be extensible - add new metrics and change detection rules via config.
"""

import time
import logging
from typing import Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MetricRule:
    """
    Defines how to detect significant changes for a metric.

    Add new metrics by creating new MetricRule instances in config or code.
    """
    name: str                           # Metric name (e.g., "gpu_temp")
    delta_threshold: float = 0          # Trigger if value changes by this much
    absolute_threshold: float = 0       # Trigger if value exceeds this
    trigger_on_state_change: bool = False  # Trigger on any change (for booleans)
    cooldown_seconds: int = 300         # Don't re-trigger within this window

    # Optional custom check function for complex logic
    # Signature: (current_value, previous_value, rule) -> bool
    custom_check: Optional[Callable] = None


# Default rules - override or extend via settings.yaml
DEFAULT_RULES = {
    # VPS metrics
    'cpu_percent': MetricRule(
        name='cpu_percent',
        delta_threshold=25,      # 25 point jump
        absolute_threshold=90,   # Or above 90%
    ),
    'memory_percent': MetricRule(
        name='memory_percent',
        delta_threshold=20,
        absolute_threshold=90,  # Raised from 85% - Windows servers often run higher
    ),
    'disk_percent': MetricRule(
        name='disk_percent',
        delta_threshold=10,
        absolute_threshold=85,
    ),
    'gpu_temp': MetricRule(
        name='gpu_temp',
        delta_threshold=10,      # 10 degree jump
        absolute_threshold=80,   # Or above 80C
    ),
    'gpu_utilization': MetricRule(
        name='gpu_utilization',
        delta_threshold=30,
        absolute_threshold=95,
    ),

    # OBS metrics
    'streaming': MetricRule(
        name='streaming',
        trigger_on_state_change=True,  # Any change in stream state
    ),
    'dropped_pct': MetricRule(
        name='dropped_pct',
        delta_threshold=0.5,     # 0.5% increase in dropped frames
        absolute_threshold=1,
    ),

    # Agent metrics
    'process_running': MetricRule(
        name='process_running',
        trigger_on_state_change=True,
    ),
    'last_log_age_sec': MetricRule(
        name='last_log_age_sec',
        absolute_threshold=300,  # 5 minutes without log output
    ),
    'error_count_recent': MetricRule(
        name='error_count_recent',
        delta_threshold=5,       # 5 new errors
        absolute_threshold=10,
    ),
}


class SmartMonitor:
    """
    Intelligent change detection for system metrics.

    Only triggers Claude when something meaningful changes.
    """

    def __init__(self, config: dict):
        """
        Initialize with config from settings.yaml.

        Config structure:
        smart_monitoring:
          enabled: true
          scheduled_check_interval: 1800  # 30 min deep check
          post_action_delay: 120          # 2 min after Opus acts
          rules:
            gpu_temp:
              delta_threshold: 15
              absolute_threshold: 75
            # Add custom metrics here
            unity_fps:
              delta_threshold: 10
              absolute_threshold: 30
        """
        self.config = config.get('smart_monitoring', {})
        self.enabled = self.config.get('enabled', True)

        # Timing
        self.scheduled_check_interval = self.config.get('scheduled_check_interval', 1800)
        self.post_action_delay = self.config.get('post_action_delay', 120)
        self.startup_grace_period = self.config.get('startup_grace_period', 300)  # 5 min default

        # State
        self.start_time: float = time.time()
        self.previous_status: dict = {}
        self.last_check: float = 0
        self.pending_verification: Optional[float] = None
        self.last_trigger_times: dict[str, float] = {}

        # Load rules (defaults + config overrides)
        self.rules = self._load_rules()

    def _load_rules(self) -> dict[str, MetricRule]:
        """Load metric rules from defaults + config."""
        rules = DEFAULT_RULES.copy()

        # Override/add from config
        config_rules = self.config.get('rules', {})
        for metric_name, rule_config in config_rules.items():
            if metric_name in rules:
                # Update existing rule
                for key, value in rule_config.items():
                    if hasattr(rules[metric_name], key):
                        setattr(rules[metric_name], key, value)
            else:
                # New metric from config
                rules[metric_name] = MetricRule(name=metric_name, **rule_config)
                logger.info(f"Added custom metric rule: {metric_name}")

        return rules

    def add_rule(self, rule: MetricRule):
        """Add a new metric rule at runtime."""
        self.rules[rule.name] = rule
        logger.info(f"Added metric rule: {rule.name}")

    def should_invoke_claude(self, current_status: dict) -> tuple[bool, str, list[str]]:
        """
        Determine if we should invoke Claude for observation.

        Args:
            current_status: Flattened dict of all current metric values

        Returns:
            (should_invoke, reason, changed_metrics)
        """
        if not self.enabled:
            return False, "disabled", []

        now = time.time()

        # Startup grace period - don't alert immediately after restart
        if now - self.start_time < self.startup_grace_period:
            return False, "startup_grace_period", []
        changed_metrics = []

        # 1. Check for significant changes
        for metric_name, rule in self.rules.items():
            current_value = self._get_nested_value(current_status, metric_name)
            previous_value = self._get_nested_value(self.previous_status, metric_name)

            if current_value is None:
                continue

            if self._is_significant_change(current_value, previous_value, rule, now):
                changed_metrics.append(metric_name)

        # Update previous status
        self.previous_status = current_status.copy()

        if changed_metrics:
            self.last_check = now
            return True, "significant_change", changed_metrics

        # 2. Post-action verification
        if self.pending_verification and now > self.pending_verification:
            self.pending_verification = None
            self.last_check = now
            return True, "verify_fix", []

        # 3. Scheduled deep check (disabled if interval is 0)
        if self.scheduled_check_interval > 0 and now - self.last_check > self.scheduled_check_interval:
            self.last_check = now
            return True, "scheduled_check", []

        return False, "no_change", []

    def _is_significant_change(
        self,
        current: any,
        previous: any,
        rule: MetricRule,
        now: float
    ) -> bool:
        """Check if a metric change is significant based on its rule."""

        # Check cooldown
        last_trigger = self.last_trigger_times.get(rule.name, 0)
        if now - last_trigger < rule.cooldown_seconds:
            return False

        # Custom check function
        if rule.custom_check:
            if rule.custom_check(current, previous, rule):
                self.last_trigger_times[rule.name] = now
                return True
            return False

        # State change detection (for booleans)
        if rule.trigger_on_state_change:
            if previous is not None and current != previous:
                self.last_trigger_times[rule.name] = now
                logger.info(f"State change detected: {rule.name} = {current}")
                return True
            return False

        # Numeric checks
        try:
            current_num = float(current)

            # Absolute threshold
            if rule.absolute_threshold and current_num > rule.absolute_threshold:
                self.last_trigger_times[rule.name] = now
                logger.info(f"Threshold exceeded: {rule.name} = {current_num}")
                return True

            # Delta threshold
            if rule.delta_threshold and previous is not None:
                previous_num = float(previous)
                delta = abs(current_num - previous_num)
                if delta > rule.delta_threshold:
                    self.last_trigger_times[rule.name] = now
                    logger.info(f"Delta exceeded: {rule.name} changed by {delta}")
                    return True
        except (TypeError, ValueError):
            pass

        return False

    def _get_nested_value(self, data: dict, key: str) -> any:
        """Get value from nested dict using dot notation (e.g., 'vps.gpu_temp')."""
        if not data:
            return None

        # Try direct key first
        if key in data:
            return data[key]

        # Try nested access
        parts = key.split('.')
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def schedule_verification(self, delay_seconds: int = None):
        """
        Schedule a verification check after Opus takes action.
        DISABLED: Relying on normal metric monitoring to detect if fixes work.
        The previous implementation caused hangs and was brittle.
        """
        # Disabled - monitoring will catch ongoing issues via metric changes
        # delay = delay_seconds or self.post_action_delay
        # self.pending_verification = time.time() + delay
        # logger.info(f"Scheduled verification check in {delay} seconds")
        pass

    def flatten_status(self, nested_status: dict) -> dict:
        """
        Flatten nested monitor status into dot-notation keys.

        Input: {'vps': {'gpu_temp': 65, 'cpu_percent': 30}}
        Output: {'vps.gpu_temp': 65, 'vps.cpu_percent': 30, 'gpu_temp': 65, ...}
        """
        flat = {}

        def _flatten(obj, prefix=''):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    new_key = f"{prefix}.{k}" if prefix else k
                    _flatten(v, new_key)
                    # Also store without prefix for convenience
                    if prefix:
                        flat[k] = v
            else:
                flat[prefix] = obj

        _flatten(nested_status)
        return flat

    def get_change_summary(self, changed_metrics: list[str]) -> str:
        """Generate a human-readable summary of what changed."""
        if not changed_metrics:
            return "No specific changes detected."

        lines = ["Detected changes:"]
        for metric in changed_metrics:
            current = self._get_nested_value(self.previous_status, metric)
            lines.append(f"  - {metric}: {current}")

        return "\n".join(lines)
