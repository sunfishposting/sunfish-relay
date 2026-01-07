"""
Operational Memory Manager

Maintains ops-log.md with optimized structure for LLM context:
- Current Status: Auto-updated, always fresh
- Active Issues: Things being tracked
- Recent Events: Last 6 hours, granular (auto-trimmed)
- History Summary: Compressed learnings, not raw logs
- Standing Instructions: User preferences

Designed to stay small (~50 lines) while preserving knowledge.
"""

import logging
from pathlib import Path
from datetime import datetime, timedelta
import re

logger = logging.getLogger(__name__)

DEFAULT_OPS_LOG = """# Ops Log

## Current Status
_Waiting for first health check..._

## Active Issues
_None currently_

## Recent Events (Last 6h)
- System initialized

## History Summary
Key patterns and learnings (compressed, not a full log):
- _No history yet_

## Standing Instructions
- Alert if GPU > 80°C
- Alert if dropped frames > 1%
- Alert if disk > 85%
- Keep responses concise (Signal/mobile)
- Restart OBS proactively if memory exceeds 8GB
"""


class MemoryManager:
    """
    Manages ops-log.md with context-optimized structure.

    Keeps the file small by:
    - Auto-trimming events older than 6 hours
    - Limiting recent events to 20 max
    - Compressing old events into history summary
    """

    # Section markers
    SECTIONS = {
        'status': '## Current Status',
        'issues': '## Active Issues',
        'events': '## Recent Events',
        'history': '## History Summary',
        'instructions': '## Standing Instructions'
    }

    def __init__(self, project_path: Path, max_recent_events: int = 20, max_event_age_hours: int = 6):
        self.project_path = Path(project_path)
        self.ops_log_path = self.project_path / "ops-log.md"
        self.max_recent_events = max_recent_events
        self.max_event_age_hours = max_event_age_hours
        self._ensure_exists()

    def _ensure_exists(self):
        """Create ops-log.md if it doesn't exist."""
        if not self.ops_log_path.exists():
            self.project_path.mkdir(parents=True, exist_ok=True)
            self.ops_log_path.write_text(DEFAULT_OPS_LOG)
            logger.info(f"Created ops-log.md at {self.ops_log_path}")

    def read(self) -> str:
        """Read the current ops log."""
        try:
            return self.ops_log_path.read_text()
        except Exception as e:
            logger.error(f"Failed to read ops-log: {e}")
            return DEFAULT_OPS_LOG

    def write(self, content: str):
        """Write the entire ops log."""
        try:
            self.ops_log_path.write_text(content)
        except Exception as e:
            logger.error(f"Failed to write ops-log: {e}")

    def get_context_for_claude(self) -> str:
        """Get the ops log, auto-trimming old events first."""
        self._trim_old_events()
        return self.read()

    # =========================================================================
    # Section Updates
    # =========================================================================

    def update_status_section(self, status_text: str):
        """Update the Current Status section."""
        self._update_section('status', status_text)

    def add_event(self, event: str):
        """
        Add an event to Recent Events.
        Auto-trims to max_recent_events.
        """
        timestamp = datetime.now().strftime("%m/%d %H:%M")
        event_line = f"- {timestamp} - {event}"

        content = self.read()
        lines = content.split('\n')
        new_lines = []
        in_events = False
        events_added = False
        event_count = 0

        for line in lines:
            if self.SECTIONS['events'] in line:
                in_events = True
                new_lines.append(line)
                new_lines.append(event_line)  # Add new event at top
                events_added = True
                continue

            if in_events:
                if line.startswith('## '):  # Next section
                    in_events = False
                    new_lines.append(line)
                elif line.startswith('- '):
                    event_count += 1
                    if event_count < self.max_recent_events:
                        new_lines.append(line)
                    # Skip if over limit
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        self.write('\n'.join(new_lines))

    def add_active_issue(self, issue: str):
        """Add an issue to Active Issues."""
        content = self.read()

        # Remove "None currently" placeholder if present
        content = content.replace('_None currently_\n', '')

        timestamp = datetime.now().strftime("%m/%d")
        issue_line = f"- [{timestamp}] {issue}"

        self._insert_after_section('issues', issue_line)

    def resolve_issue(self, issue_fragment: str):
        """Remove an issue containing the given text."""
        content = self.read()
        lines = content.split('\n')
        new_lines = []
        removed = False

        for line in lines:
            if issue_fragment.lower() in line.lower() and line.strip().startswith('- ['):
                removed = True
                continue
            new_lines.append(line)

        if removed:
            # Add placeholder if no issues left
            result = '\n'.join(new_lines)
            if '## Active Issues\n\n##' in result or '## Active Issues\n##' in result:
                result = result.replace(
                    '## Active Issues\n',
                    '## Active Issues\n_None currently_\n'
                )
            self.write(result)

    def add_to_history(self, learning: str):
        """Add a learning to History Summary."""
        content = self.read()

        # Remove placeholder if present
        content = content.replace('- _No history yet_\n', '')

        self._insert_after_section('history', f"- {learning}", after_description=True)

    # =========================================================================
    # Auto-Maintenance
    # =========================================================================

    def _trim_old_events(self):
        """Remove events older than max_event_age_hours."""
        content = self.read()
        lines = content.split('\n')
        new_lines = []
        in_events = False
        cutoff = datetime.now() - timedelta(hours=self.max_event_age_hours)

        for line in lines:
            if self.SECTIONS['events'] in line:
                in_events = True
                new_lines.append(line)
                continue

            if in_events:
                if line.startswith('## '):  # Next section
                    in_events = False
                    new_lines.append(line)
                elif line.startswith('- '):
                    # Try to parse timestamp
                    if self._is_event_recent(line, cutoff):
                        new_lines.append(line)
                    # Skip old events
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        self.write('\n'.join(new_lines))

    def _is_event_recent(self, line: str, cutoff: datetime) -> bool:
        """Check if an event line is more recent than cutoff."""
        # Format: "- MM/DD HH:MM - event text"
        match = re.match(r'- (\d{2}/\d{2}) (\d{2}:\d{2}) -', line)
        if not match:
            return True  # Keep if can't parse

        try:
            month_day = match.group(1)
            time_str = match.group(2)

            # Assume current year
            year = datetime.now().year
            event_time = datetime.strptime(f"{year}/{month_day} {time_str}", "%Y/%m/%d %H:%M")

            # Handle year boundary
            if event_time > datetime.now():
                event_time = event_time.replace(year=year - 1)

            return event_time > cutoff
        except ValueError:
            return True  # Keep if can't parse

    def compress_history(self) -> str:
        """
        Generate a compression prompt for Claude to summarize old events.
        Call this periodically (e.g., daily) to keep history summary fresh.

        Returns prompt for Claude, or empty string if nothing to compress.
        """
        content = self.read()

        # Extract recent events
        events = self._extract_section_content('events')
        if not events or len(events.strip().split('\n')) < 5:
            return ""  # Not enough events to compress

        history = self._extract_section_content('history')

        return f"""Review these recent events and update the history summary.

Current History Summary:
{history}

Recent Events to Review:
{events}

---
Extract any patterns, learnings, or important context worth remembering.
Keep the summary concise (max 10 bullet points total).
Don't duplicate what's already in history.
If nothing new worth adding, respond with just "No updates needed."

Format your response as bullet points starting with "- " """

    # =========================================================================
    # Helpers
    # =========================================================================

    def _update_section(self, section_key: str, content: str):
        """Replace content of a section."""
        marker = self.SECTIONS[section_key]
        full_content = self.read()
        lines = full_content.split('\n')
        new_lines = []
        in_section = False
        content_added = False

        for line in lines:
            if marker in line:
                in_section = True
                new_lines.append(line)
                new_lines.append(content)
                content_added = True
                continue

            if in_section:
                if line.startswith('## '):  # Next section
                    in_section = False
                    if not content_added:
                        new_lines.append(content)
                    new_lines.append('')  # Blank line before next section
                    new_lines.append(line)
                # Skip old content in this section
            else:
                new_lines.append(line)

        self.write('\n'.join(new_lines))

    def _insert_after_section(self, section_key: str, line: str, after_description: bool = False):
        """Insert a line at the start of a section's content."""
        marker = self.SECTIONS[section_key]
        content = self.read()
        lines = content.split('\n')
        new_lines = []
        inserted = False

        for i, current_line in enumerate(lines):
            new_lines.append(current_line)

            if marker in current_line and not inserted:
                # Skip description line if needed
                if after_description:
                    # Look for next non-empty line that's not a list item
                    for j in range(i + 1, min(i + 3, len(lines))):
                        if lines[j].strip() and not lines[j].startswith('- '):
                            new_lines.append(lines[j])
                            continue
                new_lines.append(line)
                inserted = True

        self.write('\n'.join(new_lines))

    def _extract_section_content(self, section_key: str) -> str:
        """Extract content between section header and next section."""
        marker = self.SECTIONS[section_key]
        content = self.read()
        lines = content.split('\n')
        section_lines = []
        in_section = False

        for line in lines:
            if marker in line:
                in_section = True
                continue

            if in_section:
                if line.startswith('## '):
                    break
                section_lines.append(line)

        return '\n'.join(section_lines).strip()
