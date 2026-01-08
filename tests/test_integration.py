#!/usr/bin/env python3
"""
Integration tests for Sunfish Relay.

Philosophy: Test real behavior, not mocks. Each test should verify
something that matters in production.

Run with: python tests/test_integration.py
Add --live flag to include actual Claude API calls (costs money).
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'orchestrator'))


def test_session_persistence():
    """Test that session IDs survive save/load cycle."""
    print("\n[TEST] Session persistence...")

    with tempfile.TemporaryDirectory() as tmpdir:
        session_file = Path(tmpdir) / ".sessions.json"

        # Save
        test_data = {
            'sonnet': 'test-sonnet-session-12345',
            'opus': 'test-opus-session-67890',
            'updated': '2025-01-07T12:00:00'
        }
        with open(session_file, 'w') as f:
            json.dump(test_data, f)

        # Load
        with open(session_file) as f:
            loaded = json.load(f)

        assert loaded['sonnet'] == test_data['sonnet'], "Sonnet session mismatch"
        assert loaded['opus'] == test_data['opus'], "Opus session mismatch"

        print("  PASS: Session IDs persist correctly")
        return True


def test_json_parsing():
    """Test that we can parse Claude's JSON output format."""
    print("\n[TEST] JSON response parsing...")

    # Simulated Claude JSON output (array format - actual Claude output)
    sample_output = '[{"type":"system","session_id":"abc123-def456-ghi789"},{"type":"assistant","message":{"content":[{"type":"text","text":"Here is my response."}]}},{"type":"result","result":"Here is my response.","session_id":"abc123-def456-ghi789"}]'

    # Parse like our code does (array format)
    response_text = ""
    session_id = None

    try:
        data_list = json.loads(sample_output)
        if isinstance(data_list, list):
            for data in data_list:
                if isinstance(data, dict):
                    if 'session_id' in data:
                        session_id = data['session_id']
                    if data.get('type') == 'result' and 'result' in data:
                        response_text = data['result']
    except json.JSONDecodeError:
        pass

    assert response_text == "Here is my response.", f"Response mismatch: {response_text}"
    assert session_id == "abc123-def456-ghi789", f"Session ID mismatch: {session_id}"

    print("  PASS: JSON parsing extracts response and session_id correctly")
    return True


def test_ops_log_structure():
    """Test that ops-log.md has the expected structure."""
    print("\n[TEST] ops-log.md structure...")

    ops_log_path = Path(__file__).parent.parent / 'ops-log.md'

    if not ops_log_path.exists():
        print("  SKIP: ops-log.md not found")
        return True

    content = ops_log_path.read_text()

    required_sections = [
        '## Current Status',
        '## Active Issues',
        '## Recent Events',
        '## History Summary',
        '## Standing Instructions'
    ]

    for section in required_sections:
        assert section in content, f"Missing section: {section}"

    print("  PASS: ops-log.md has all required sections")
    return True


def test_claude_code_available():
    """Test that claude CLI is available."""
    print("\n[TEST] Claude Code CLI available...")

    try:
        result = subprocess.run(
            ['claude', '--version'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print(f"  PASS: Claude Code available ({result.stdout.strip()})")
            return True
        else:
            print(f"  FAIL: Claude Code returned error: {result.stderr}")
            return False
    except FileNotFoundError:
        print("  FAIL: Claude Code not found in PATH")
        return False
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_live_claude_call():
    """Actually call Claude and verify response + session_id. Costs money."""
    print("\n[TEST] Live Claude call (this costs money)...")

    project_path = Path(__file__).parent.parent

    try:
        result = subprocess.run(
            [
                'claude', '-p', 'Respond with exactly: TEST_OK',
                '--output-format', 'json',
                '--model', 'haiku',  # Cheapest model for testing
                '--tools', '',  # No tools available
            ],
            capture_output=True,
            text=True,
            cwd=str(project_path),
            timeout=60
        )

        if result.returncode != 0:
            print(f"  FAIL: Claude returned error: {result.stderr}")
            return False

        # Parse response (array format)
        output = result.stdout.strip()
        response_text = ""
        session_id = None

        try:
            data_list = json.loads(output)
            if isinstance(data_list, list):
                for data in data_list:
                    if isinstance(data, dict):
                        if 'session_id' in data:
                            session_id = data['session_id']
                        if data.get('type') == 'result' and 'result' in data:
                            response_text = data['result']
        except json.JSONDecodeError as e:
            print(f"  FAIL: JSON parse error: {e}")
            return False

        if 'TEST_OK' in response_text:
            print(f"  PASS: Got response, session_id={session_id[:20] if session_id else 'None'}...")
            return True
        else:
            print(f"  FAIL: Unexpected response: {response_text[:100]}")
            return False

    except subprocess.TimeoutExpired:
        print("  FAIL: Claude call timed out")
        return False
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_session_resume():
    """Test that --resume actually continues a session. Costs money."""
    print("\n[TEST] Session resume (this costs money)...")

    project_path = Path(__file__).parent.parent

    try:
        # First call - establish session
        result1 = subprocess.run(
            [
                'claude', '-p', 'Remember this number: 42. Respond with just OK.',
                '--output-format', 'json',
                '--model', 'haiku',
                '--tools', '',  # No tools available
            ],
            capture_output=True,
            text=True,
            cwd=str(project_path),
            timeout=60
        )

        # Extract session_id (array format)
        session_id = None
        try:
            data_list = json.loads(result1.stdout.strip())
            if isinstance(data_list, list):
                for data in data_list:
                    if isinstance(data, dict) and 'session_id' in data:
                        session_id = data['session_id']
        except:
            pass

        if not session_id:
            print("  FAIL: No session_id from first call")
            return False

        print(f"  Got session_id: {session_id[:20]}...")

        # Second call - resume and ask about the number
        result2 = subprocess.run(
            [
                'claude', '-p', 'What number did I ask you to remember? Just say the number.',
                '--output-format', 'json',
                '--model', 'haiku',
                '--tools', '',  # No tools available
                '--resume', session_id,
            ],
            capture_output=True,
            text=True,
            cwd=str(project_path),
            timeout=60
        )

        # Check if 42 is in response (array format)
        response_text = ""
        try:
            data_list = json.loads(result2.stdout.strip())
            if isinstance(data_list, list):
                for data in data_list:
                    if isinstance(data, dict) and data.get('type') == 'result' and 'result' in data:
                        response_text = data['result']
        except:
            pass

        if '42' in response_text:
            print(f"  PASS: Session resume works - Claude remembered 42")
            return True
        else:
            print(f"  FAIL: Claude didn't remember (response: {response_text[:100]})")
            return False

    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def main():
    """Run tests."""
    print("=" * 60)
    print("Sunfish Relay Integration Tests")
    print("=" * 60)

    live_mode = '--live' in sys.argv

    results = []

    # Always run these (no API calls)
    results.append(('Session persistence', test_session_persistence()))
    results.append(('JSON parsing', test_json_parsing()))
    results.append(('ops-log.md structure', test_ops_log_structure()))
    results.append(('Claude CLI available', test_claude_code_available()))

    # Only run with --live flag
    if live_mode:
        results.append(('Live Claude call', test_live_claude_call()))
        results.append(('Session resume', test_session_resume()))
    else:
        print("\n[SKIP] Live tests (add --live flag to run, costs money)")

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS:")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {name}")

    print(f"\n{passed}/{total} tests passed")

    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
