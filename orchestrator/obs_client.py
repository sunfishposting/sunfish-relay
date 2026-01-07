#!/usr/bin/env python3
"""
Minimal OBS WebSocket client wrapper.
"""

from typing import Optional
import obsws_python as obs


class OBSClient:
    """Wrapper for OBS WebSocket operations."""

    def __init__(self, host: str = 'localhost', port: int = 4455, password: str = ''):
        self.host = host
        self.port = port
        self.password = password
        self._client: Optional[obs.ReqClient] = None
        self.connected = False

    def connect(self):
        """Connect to OBS WebSocket."""
        self._client = obs.ReqClient(
            host=self.host,
            port=self.port,
            password=self.password if self.password else None
        )
        self.connected = True

    def disconnect(self):
        """Disconnect from OBS."""
        if self._client:
            self._client.disconnect()
            self._client = None
            self.connected = False

    def get_stream_status(self) -> dict:
        """Get current streaming status."""
        if not self._client:
            return {'active': False, 'error': 'Not connected'}

        status = self._client.get_stream_status()
        return {
            'active': status.output_active,
            'reconnecting': status.output_reconnecting,
            'timecode': status.output_timecode,
            'duration_ms': status.output_duration,
            'congestion': status.output_congestion,
            'bytes': status.output_bytes,
            'skipped_frames': status.output_skipped_frames,
            'total_frames': status.output_total_frames
        }

    def start_stream(self) -> bool:
        """Start streaming."""
        if not self._client:
            return False
        self._client.start_stream()
        return True

    def stop_stream(self) -> bool:
        """Stop streaming."""
        if not self._client:
            return False
        self._client.stop_stream()
        return True

    def get_current_scene(self) -> str:
        """Get current program scene name."""
        if not self._client:
            return 'Unknown'
        return self._client.get_current_program_scene().current_program_scene_name

    def set_scene(self, scene_name: str) -> bool:
        """Switch to a scene."""
        if not self._client:
            return False
        self._client.set_current_program_scene(scene_name)
        return True

    def get_scenes(self) -> list[str]:
        """List all available scenes."""
        if not self._client:
            return []
        scenes = self._client.get_scene_list()
        return [s['sceneName'] for s in scenes.scenes]

    def get_stats(self) -> dict:
        """Get OBS performance stats."""
        if not self._client:
            return {}

        stats = self._client.get_stats()
        return {
            'cpu_usage': stats.cpu_usage,
            'memory_usage': stats.memory_usage,
            'disk_space_available': stats.available_disk_space,
            'fps': stats.active_fps,
            'avg_frame_render_time': stats.average_frame_render_time,
            'render_skipped_frames': stats.render_skipped_frames,
            'output_skipped_frames': stats.output_skipped_frames
        }
