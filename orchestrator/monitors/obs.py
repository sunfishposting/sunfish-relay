"""
OBS Monitor - Stream status via WebSocket API

Requires OBS WebSocket plugin (built into OBS 28+).
"""

import json
import hashlib
import base64
from .base import BaseMonitor

# Optional import - graceful degradation if not installed
try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False


class OBSMonitor(BaseMonitor):
    name = "obs"

    def __init__(self, config: dict):
        super().__init__(config)
        self.host = config.get('host', 'localhost')
        self.port = config.get('port', 4455)
        self.password = config.get('password', '')
        self._ws = None
        self._connected = False
        self._message_id = 0

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        """Connect to OBS WebSocket."""
        if not HAS_WEBSOCKET:
            return False

        # Clean up any existing connection first
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

        try:
            self._ws = websocket.create_connection(
                f"ws://{self.host}:{self.port}",
                timeout=5
            )

            # Handle authentication
            hello = json.loads(self._ws.recv())
            if hello.get('op') == 0:  # Hello
                auth_required = hello.get('d', {}).get('authentication')

                if auth_required and self.password:
                    # Generate auth string
                    challenge = auth_required.get('challenge', '')
                    salt = auth_required.get('salt', '')

                    secret = base64.b64encode(
                        hashlib.sha256((self.password + salt).encode()).digest()
                    ).decode()
                    auth_string = base64.b64encode(
                        hashlib.sha256((secret + challenge).encode()).digest()
                    ).decode()

                    # Send Identify with auth
                    self._send({
                        'op': 1,
                        'd': {
                            'rpcVersion': 1,
                            'authentication': auth_string
                        }
                    })
                else:
                    # No auth needed
                    self._send({'op': 1, 'd': {'rpcVersion': 1}})

                response = json.loads(self._ws.recv())
                if response.get('op') == 2:  # Identified
                    self._connected = True
                    return True
        except Exception:
            # Clean up on failure to prevent socket leak
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None
            self._connected = False
        return False

    def disconnect(self):
        """Disconnect from OBS."""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._connected = False

    def get_status(self) -> dict:
        """Get OBS streaming status."""
        if not self._connected:
            if not self.connect():
                return {'healthy': False, 'error': 'Not connected to OBS'}

        try:
            # Get stream status
            stream_status = self._request('GetStreamStatus')

            # Get stats
            stats = self._request('GetStats')

            status = {
                'healthy': True,
                'streaming': stream_status.get('outputActive', False),
                'duration_sec': stream_status.get('outputDuration', 0) // 1000,
                'bytes_sent': stream_status.get('outputBytes', 0),
                'frames_dropped': stats.get('outputSkippedFrames', 0),
                'frames_total': stats.get('outputTotalFrames', 0),
                'fps': stats.get('activeFps', 0),
                'cpu_usage': stats.get('cpuUsage', 0),
                'memory_mb': stats.get('memoryUsage', 0)
            }

            # Calculate dropped frame percentage
            if status['frames_total'] > 0:
                status['dropped_pct'] = round(
                    (status['frames_dropped'] / status['frames_total']) * 100, 2
                )
            else:
                status['dropped_pct'] = 0

            # Check alerts
            alerts = self.get_alerts()
            if alerts:
                status['healthy'] = False
                status['alerts'] = alerts

            self._last_status = status
            return status

        except Exception as e:
            self._connected = False
            return {'healthy': False, 'error': str(e)}

    def get_alerts(self) -> list[str]:
        """Check OBS thresholds."""
        alerts = []
        status = self._last_status

        if not status or not status.get('streaming'):
            return alerts

        thresholds = self.alerts_config

        if status.get('dropped_pct', 0) > thresholds.get('dropped_frames_pct', 1):
            alerts.append(f"OBS dropped frames: {status['dropped_pct']}%")

        return alerts

    def get_status_line(self) -> str:
        """One-line summary."""
        s = self.get_status()
        if s.get('error'):
            return f"OBS: {s['error']}"

        if s.get('streaming'):
            duration = s.get('duration_sec', 0)
            hours = duration // 3600
            mins = (duration % 3600) // 60
            return f"OBS: LIVE {hours}h{mins:02d}m, {s.get('dropped_pct', 0)}% dropped, {round(s.get('fps', 0))} fps"
        else:
            return "OBS: Offline"

    def execute(self, command: str) -> dict:
        """Execute OBS commands."""
        if not self._connected:
            if not self.connect():
                return {'success': False, 'message': 'Not connected to OBS'}

        commands = {
            'start_stream': ('StartStream', {}),
            'stop_stream': ('StopStream', {}),
            'start_recording': ('StartRecord', {}),
            'stop_recording': ('StopRecord', {}),
            'toggle_stream': ('ToggleStream', {}),
        }

        if command not in commands:
            return {'success': False, 'message': f'Unknown command: {command}'}

        try:
            request_type, data = commands[command]
            self._request(request_type, data)
            return {'success': True, 'message': f'{command} executed'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def _send(self, data: dict):
        """Send raw message to OBS."""
        if self._ws:
            self._ws.send(json.dumps(data))

    def _request(self, request_type: str, data: dict = None, timeout: float = 10.0) -> dict:
        """Send request and get response with timeout protection."""
        self._message_id += 1

        request = {
            'op': 6,  # Request
            'd': {
                'requestType': request_type,
                'requestId': str(self._message_id),
                'requestData': data or {}
            }
        }

        self._send(request)

        # Set socket timeout for recv operations
        original_timeout = self._ws.gettimeout()
        self._ws.settimeout(timeout)

        try:
            max_attempts = 10  # Safety valve: don't loop forever
            for _ in range(max_attempts):
                response = json.loads(self._ws.recv())
                if response.get('op') == 7:  # RequestResponse
                    resp_data = response.get('d', {})
                    if resp_data.get('requestId') == str(self._message_id):
                        if resp_data.get('requestStatus', {}).get('result'):
                            return resp_data.get('responseData', {})
                        else:
                            raise Exception(resp_data.get('requestStatus', {}).get('comment', 'Unknown error'))
            raise Exception(f"No response after {max_attempts} messages")
        finally:
            # Restore original timeout
            try:
                self._ws.settimeout(original_timeout)
            except Exception:
                pass
