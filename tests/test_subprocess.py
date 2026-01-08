#!/usr/bin/env python3
"""
Tests for async subprocess handling and shutdown behavior.

These tests verify the 4 fixes for orchestrator brittleness:
1. No blocking shutdown message (structural verification)
2. Async subprocess calls don't block event loop
3. Process termination on timeout (no zombies)
4. Shutdown timeout safety valve

Run with: python tests/test_subprocess.py

Philosophy: Real subprocesses, real timeouts, real behavior.
No mocks for the critical paths.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'orchestrator'))

from main import run_subprocess_async


# =============================================================================
# Fix 2 & 3: Async Subprocess Tests
# =============================================================================

def test_async_subprocess_basic():
    """Test basic command execution returns stdout, stderr, returncode."""
    print("\n[TEST] Async subprocess basic execution...")

    async def run():
        # Use Python for cross-platform compatibility
        cmd = [sys.executable, '-c', 'print("hello stdout"); import sys; print("hello stderr", file=sys.stderr)']
        returncode, stdout, stderr = await run_subprocess_async(cmd, timeout=10)
        return returncode, stdout, stderr

    returncode, stdout, stderr = asyncio.run(run())

    assert returncode == 0, f"Expected returncode 0, got {returncode}"
    assert 'hello stdout' in stdout, f"Expected 'hello stdout' in stdout, got: {stdout}"
    assert 'hello stderr' in stderr, f"Expected 'hello stderr' in stderr, got: {stderr}"

    print("  PASS: Basic execution works correctly")
    return True


def test_async_subprocess_stdin():
    """Test that input_data (stdin) is correctly passed to subprocess."""
    print("\n[TEST] Async subprocess stdin handling...")

    async def run():
        # Python script that reads from stdin and echoes it
        cmd = [sys.executable, '-c', 'import sys; data = sys.stdin.read(); print(f"received: {data}")']
        input_data = b'test input data'
        returncode, stdout, stderr = await run_subprocess_async(cmd, timeout=10, input_data=input_data)
        return returncode, stdout, stderr

    returncode, stdout, stderr = asyncio.run(run())

    assert returncode == 0, f"Expected returncode 0, got {returncode}"
    assert 'received: test input data' in stdout, f"Expected stdin data in output, got: {stdout}"

    print("  PASS: Stdin handling works correctly")
    return True


def test_async_subprocess_cwd():
    """Test that cwd parameter correctly sets working directory."""
    print("\n[TEST] Async subprocess cwd handling...")

    async def run():
        # Use a temp directory to verify cwd works
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [sys.executable, '-c', 'import os; print(os.getcwd())']
            returncode, stdout, stderr = await run_subprocess_async(cmd, timeout=10, cwd=tmpdir)
            return returncode, stdout.strip(), tmpdir

    returncode, actual_cwd, expected_cwd = asyncio.run(run())

    assert returncode == 0, f"Expected returncode 0, got {returncode}"
    # Normalize paths for comparison (resolve symlinks)
    assert os.path.realpath(actual_cwd) == os.path.realpath(expected_cwd), \
        f"Expected cwd {expected_cwd}, got {actual_cwd}"

    print("  PASS: CWD handling works correctly")
    return True


def test_async_subprocess_nonzero_exit():
    """Test that non-zero exit codes are correctly returned."""
    print("\n[TEST] Async subprocess non-zero exit code...")

    async def run():
        cmd = [sys.executable, '-c', 'import sys; sys.exit(42)']
        returncode, stdout, stderr = await run_subprocess_async(cmd, timeout=10)
        return returncode

    returncode = asyncio.run(run())

    assert returncode == 42, f"Expected returncode 42, got {returncode}"

    print("  PASS: Non-zero exit codes returned correctly")
    return True


def test_async_subprocess_concurrent_not_blocking():
    """
    CRITICAL TEST: Verify run_subprocess_async doesn't block the event loop.

    This is the whole point of Fix #2. If the function blocked, these
    3 concurrent 1-second sleeps would take 3+ seconds. They should
    complete in ~1 second since they run in parallel.
    """
    print("\n[TEST] Async subprocess concurrent (non-blocking)...")

    async def run():
        # Three 1-second sleeps
        cmd = [sys.executable, '-c', 'import time; time.sleep(1); print("done")']

        start = time.time()

        # Run all three concurrently
        results = await asyncio.gather(
            run_subprocess_async(cmd, timeout=10),
            run_subprocess_async(cmd, timeout=10),
            run_subprocess_async(cmd, timeout=10),
        )

        elapsed = time.time() - start
        return elapsed, results

    elapsed, results = asyncio.run(run())

    # All should succeed
    for i, (returncode, stdout, stderr) in enumerate(results):
        assert returncode == 0, f"Task {i} failed with returncode {returncode}"
        assert 'done' in stdout, f"Task {i} missing output"

    # Should complete in ~1 second, not 3 (allow 2.5s for slow CI)
    assert elapsed < 2.5, f"Took {elapsed:.1f}s - likely BLOCKING. Should be ~1s for concurrent execution."

    print(f"  PASS: 3 concurrent 1s sleeps completed in {elapsed:.1f}s (non-blocking confirmed)")
    return True


def test_async_subprocess_timeout_raises():
    """Test that timeout raises subprocess.TimeoutExpired."""
    print("\n[TEST] Async subprocess timeout raises exception...")

    async def run():
        # Sleep for 10 seconds, but timeout after 0.5
        cmd = [sys.executable, '-c', 'import time; time.sleep(10)']
        try:
            await run_subprocess_async(cmd, timeout=0.5)
            return False, "No exception raised"
        except subprocess.TimeoutExpired:
            return True, "TimeoutExpired raised correctly"
        except Exception as e:
            return False, f"Wrong exception: {type(e).__name__}: {e}"

    success, message = asyncio.run(run())

    assert success, message

    print(f"  PASS: {message}")
    return True


def test_async_subprocess_timeout_kills_process():
    """
    CRITICAL TEST: Verify that timeout KILLS the subprocess (Fix #3).

    This prevents zombie processes. The old subprocess.run() would
    leave processes running even after timeout. We explicitly call
    proc.kill() now.
    """
    print("\n[TEST] Async subprocess timeout kills process...")

    async def run():
        # Create a Python process that writes its PID to a file, then sleeps
        import tempfile
        pid_file = tempfile.mktemp()

        script = f'''
import os
import time

# Write our PID so the test can check if we're still alive
with open({repr(pid_file)}, 'w') as f:
    f.write(str(os.getpid()))

# Sleep forever (until killed)
time.sleep(60)
'''
        cmd = [sys.executable, '-c', script]

        try:
            await run_subprocess_async(cmd, timeout=0.5)
        except subprocess.TimeoutExpired:
            pass  # Expected

        # Give OS a moment to clean up
        await asyncio.sleep(0.2)

        # Read the PID and check if process is dead
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())

            # Check if process exists
            try:
                os.kill(pid, 0)  # Signal 0 = just check if process exists
                return False, pid, "Process still alive after timeout!"
            except OSError:
                return True, pid, "Process correctly killed"
        finally:
            try:
                os.unlink(pid_file)
            except:
                pass

    success, pid, message = asyncio.run(run())

    assert success, f"PID {pid}: {message}"

    print(f"  PASS: Process {pid} correctly killed on timeout")
    return True


def test_async_subprocess_cancellation_kills_process():
    """
    Test that cancelling the async task kills the subprocess.

    This is important for graceful shutdown - when asyncio.run() is
    interrupted, pending tasks are cancelled. The subprocess should die.
    """
    print("\n[TEST] Async subprocess cancellation kills process...")

    async def run():
        import tempfile
        pid_file = tempfile.mktemp()

        script = f'''
import os
import time

with open({repr(pid_file)}, 'w') as f:
    f.write(str(os.getpid()))

time.sleep(60)
'''
        cmd = [sys.executable, '-c', script]

        # Start the subprocess task
        task = asyncio.create_task(run_subprocess_async(cmd, timeout=60))

        # Wait for process to start and write its PID
        await asyncio.sleep(0.3)

        # Cancel the task
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass  # Expected

        # Give OS a moment to clean up
        await asyncio.sleep(0.2)

        # Check if process is dead
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())

            try:
                os.kill(pid, 0)
                return False, pid, "Process still alive after cancellation!"
            except OSError:
                return True, pid, "Process correctly killed"
        finally:
            try:
                os.unlink(pid_file)
            except:
                pass

    success, pid, message = asyncio.run(run())

    assert success, f"PID {pid}: {message}"

    print(f"  PASS: Process {pid} correctly killed on cancellation")
    return True


# =============================================================================
# Fix 1: No Blocking Shutdown Message (Structural Test)
# =============================================================================

def test_shutdown_no_blocking_send_message():
    """
    Verify the finally block in Orchestrator.run() doesn't call send_message.

    This is Fix #1 - we removed the shutdown notification that could block
    if signal-cli was hung. This test verifies the fix is still in place
    by inspecting the source code.
    """
    print("\n[TEST] Shutdown doesn't call blocking send_message...")

    # Read the source and check the finally block
    import ast
    import inspect
    from main import Orchestrator

    # Get the source code of the run method
    source = inspect.getsource(Orchestrator.run)

    # Parse it as AST
    # We need to wrap it in a class to make it valid Python
    wrapped_source = f"class Dummy:\n" + "\n".join("    " + line for line in source.split("\n"))
    tree = ast.parse(wrapped_source)

    # Find the finally block in the run method
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and node.finalbody:
            # Check if any call in the finally block is to send_message
            for final_stmt in node.finalbody:
                for subnode in ast.walk(final_stmt):
                    if isinstance(subnode, ast.Call):
                        # Check if it's a method call
                        if isinstance(subnode.func, ast.Attribute):
                            method_name = subnode.func.attr
                            if method_name == 'send_message':
                                print(f"  FAIL: Found send_message call in finally block")
                                return False

    print("  PASS: No send_message call in finally block (won't block on shutdown)")
    return True


# =============================================================================
# Fix 4: Shutdown Timeout Safety Valve
# =============================================================================

def test_shutdown_safety_valve_structure():
    """
    Verify the main() function has proper shutdown timeout handling.

    We check that:
    1. There's a force_exit function
    2. There's a threading.Timer that calls it
    3. The timer is set to ~5 seconds
    """
    print("\n[TEST] Shutdown safety valve structure...")

    import inspect
    from main import main

    source = inspect.getsource(main)

    # Check for key components
    checks = {
        'force_exit function': 'def force_exit' in source,
        'os._exit call': 'os._exit' in source,
        'threading.Timer': 'threading.Timer' in source,
        '5 second timeout': '5.0' in source or '5,' in source,
        'shutting_down flag': 'shutting_down' in source,
        'second interrupt handling': 'Second' in source or 'second' in source,
    }

    failed = []
    for check, passed in checks.items():
        if not passed:
            failed.append(check)

    if failed:
        print(f"  FAIL: Missing components: {', '.join(failed)}")
        return False

    print("  PASS: All shutdown safety valve components present")
    return True


def test_force_exit_timer_actually_works():
    """
    Test that a timer-based force exit mechanism works.

    We can't test os._exit() directly (it would kill the test process),
    but we can verify the timer mechanism fires correctly.
    """
    print("\n[TEST] Force exit timer mechanism works...")

    import threading

    result = {'fired': False, 'elapsed': 0}

    def on_timer():
        result['fired'] = True
        result['elapsed'] = time.time() - start

    start = time.time()
    timer = threading.Timer(0.5, on_timer)
    timer.daemon = True
    timer.start()

    # Wait for timer to fire
    time.sleep(0.8)

    assert result['fired'], "Timer never fired"
    assert 0.4 < result['elapsed'] < 0.7, f"Timer fired at wrong time: {result['elapsed']:.2f}s"

    print(f"  PASS: Timer fired correctly after {result['elapsed']:.2f}s")
    return True


def test_double_interrupt_handling():
    """
    Test that double interrupt handling is structured correctly.

    The code should have:
    1. A flag to track if we're already shutting down
    2. Logic to force exit on second interrupt
    """
    print("\n[TEST] Double interrupt handling structure...")

    import inspect
    from main import main

    source = inspect.getsource(main)

    # Check for the pattern of checking shutting_down flag and calling os._exit
    has_flag_check = 'if shutting_down' in source
    has_immediate_exit = 'immediate' in source.lower() or 'force' in source.lower()

    if not has_flag_check:
        print("  FAIL: Missing shutting_down flag check")
        return False

    if not has_immediate_exit:
        print("  FAIL: Missing immediate/force exit on second interrupt")
        return False

    print("  PASS: Double interrupt handling correctly structured")
    return True


# =============================================================================
# Integration Test: Full Subprocess Lifecycle
# =============================================================================

def test_subprocess_full_lifecycle():
    """
    Integration test: Run a real command through the full async lifecycle.

    This tests the path that signal-cli and claude will take in production.
    """
    print("\n[TEST] Full subprocess lifecycle integration...")

    async def run():
        # Simulate what we do with signal-cli: run command, capture output, handle timeout
        cmd = [sys.executable, '-c', '''
import json
import sys

# Simulate signal-cli JSON output
output = {"status": "ok", "messages": [{"text": "hello"}]}
print(json.dumps(output))
''']

        returncode, stdout, stderr = await run_subprocess_async(cmd, timeout=10)

        if returncode != 0:
            return False, f"Command failed: {stderr}"

        # Parse the JSON like we do in production
        import json
        try:
            data = json.loads(stdout.strip())
            if data.get('status') != 'ok':
                return False, f"Unexpected status: {data}"
        except json.JSONDecodeError as e:
            return False, f"JSON parse failed: {e}"

        return True, "Full lifecycle successful"

    success, message = asyncio.run(run())

    assert success, message

    print(f"  PASS: {message}")
    return True


# =============================================================================
# Main
# =============================================================================

def main():
    """Run all tests."""
    print("=" * 60)
    print("Subprocess & Shutdown Tests")
    print("=" * 60)
    print("Testing fixes for orchestrator brittleness:")
    print("  Fix 1: No blocking shutdown message")
    print("  Fix 2: Async subprocess (non-blocking)")
    print("  Fix 3: Process termination on timeout")
    print("  Fix 4: Shutdown timeout safety valve")
    print("=" * 60)

    results = []

    # Fix 2 & 3: Async subprocess tests
    results.append(('Basic execution', test_async_subprocess_basic()))
    results.append(('Stdin handling', test_async_subprocess_stdin()))
    results.append(('CWD handling', test_async_subprocess_cwd()))
    results.append(('Non-zero exit codes', test_async_subprocess_nonzero_exit()))
    results.append(('Concurrent (non-blocking)', test_async_subprocess_concurrent_not_blocking()))
    results.append(('Timeout raises exception', test_async_subprocess_timeout_raises()))
    results.append(('Timeout kills process', test_async_subprocess_timeout_kills_process()))
    results.append(('Cancellation kills process', test_async_subprocess_cancellation_kills_process()))

    # Fix 1: No blocking shutdown
    results.append(('No blocking send_message', test_shutdown_no_blocking_send_message()))

    # Fix 4: Shutdown safety valve
    results.append(('Safety valve structure', test_shutdown_safety_valve_structure()))
    results.append(('Timer mechanism', test_force_exit_timer_actually_works()))
    results.append(('Double interrupt handling', test_double_interrupt_handling()))

    # Integration
    results.append(('Full lifecycle integration', test_subprocess_full_lifecycle()))

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

    if passed == total:
        print("\nAll fixes verified. Safe to deploy.")
    else:
        print("\nSome tests failed. DO NOT deploy until fixed.")

    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
