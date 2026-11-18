"""Offline mutex checks; no serial port, USB device or keyboard input."""
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import patch

import focus_lock as locking


class Kernel:
    def __init__(self, status=0, handle=0x123456789):
        self.status, self.handle = status, handle
        self.calls = []

    def CreateMutexW(self, attributes, owner, name):
        self.calls.append(("create", attributes, owner, name))
        return self.handle

    def WaitForSingleObject(self, handle, milliseconds):
        self.calls.append(("wait", handle, milliseconds))
        return self.status

    def ReleaseMutex(self, handle):
        self.calls.append(("release", handle))
        return True

    def CloseHandle(self, handle):
        self.calls.append(("close", handle))
        return True


def test_acquired_and_abandoned_mutex_release_and_close():
    for status in (0, 0x80):
        for fail_body in (False, True):
            kernel = Kernel(status)
            entered = []
            try:
                with locking.focus_lock(timeout=0.0011, kernel=kernel):
                    entered.append(True)
                    if fail_body:
                        raise RuntimeError("body failure")
            except RuntimeError as error:
                assert fail_body and str(error) == "body failure"
            assert entered == [True]
            assert kernel.calls == [
                ("create", None, False, r"Local\AgentDeckFocus"),
                ("wait", kernel.handle, 2), ("release", kernel.handle),
                ("close", kernel.handle)]


def test_timeout_and_failed_wait_never_enter_or_release():
    for status, expected in ((0x102, TimeoutError), (0xFFFFFFFF, OSError)):
        kernel = Kernel(status)
        try:
            with locking.focus_lock(timeout=0, kernel=kernel):
                raise AssertionError("must not enter")
        except expected:
            pass
        else:
            raise AssertionError("expected wait failure")
        assert kernel.calls == [("create", None, False, locking.MUTEX_NAME),
                                ("wait", kernel.handle, 0), ("close", kernel.handle)]
    kernel = Kernel(handle=0)
    try:
        with locking.focus_lock(kernel=kernel):
            raise AssertionError("must not enter")
    except OSError:
        pass
    assert kernel.calls == [("create", None, False, locking.MUTEX_NAME)]


def test_invalid_timeout_and_non_windows_fallback():
    for timeout in (-1, float("inf"), float("nan")):
        kernel = Kernel()
        try:
            with locking.focus_lock(timeout, kernel=kernel):
                raise AssertionError("invalid timeout entered")
        except ValueError:
            pass
        assert not kernel.calls
    result = []

    def contender():
        try:
            with locking.focus_lock(timeout=0):
                result.append("entered")
        except TimeoutError:
            result.append("timeout")

    with patch.object(locking.os, "name", "posix"):
        with locking.focus_lock():
            thread = threading.Thread(target=contender)
            thread.start()
            thread.join(timeout=2)
            assert not thread.is_alive()
        with locking.focus_lock(timeout=0):
            result.append("released")
    assert result == ["timeout", "released"]


def test_windows_named_mutex_excludes_other_process():
    if os.name != "nt":
        print("Windows cross-process case: SKIP (non-Windows)")
        return
    code = '''import sys
sys.path.insert(0, sys.argv[1])
from focus_lock import focus_lock
try:
    with focus_lock(timeout=0.05):
        print("acquired")
except TimeoutError:
    print("timeout")
'''
    command = [sys.executable, "-B", "-c", code, str(Path(__file__).resolve().parent)]

    def child():
        completed = subprocess.run(command, capture_output=True, text=True, timeout=10,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                   check=True)
        assert not completed.stderr, completed.stderr
        return completed.stdout.strip()

    with locking.focus_lock(timeout=1.0):
        assert child() == "timeout"
    assert child() == "acquired"


def main():
    tests = (test_acquired_and_abandoned_mutex_release_and_close,
             test_timeout_and_failed_wait_never_enter_or_release,
             test_invalid_timeout_and_non_windows_fallback,
             test_windows_named_mutex_excludes_other_process)
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("focus lock offline tests: %d groups passed" % len(tests))


if __name__ == "__main__":
    main()
