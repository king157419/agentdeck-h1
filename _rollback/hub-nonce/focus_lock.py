"""Serialize deck/daemon focus ownership within the current Windows session."""
from contextlib import contextmanager
import ctypes
import math
import os
import threading


MUTEX_NAME = r"Local\AgentDeckFocus"
_fallback = threading.RLock()


def _kernel32():
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.ReleaseMutex.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _error(operation):
    if hasattr(ctypes, "WinError"):
        return ctypes.WinError(ctypes.get_last_error())
    return OSError(operation + " failed")


@contextmanager
def focus_lock(timeout=1.0, *, kernel=None):
    """Raise TimeoutError before entering the body if focus is still owned.

    ``kernel`` allows offline Win32 substitutes. Non-Windows callers share a
    process-local lock; Windows always uses the named, cross-process mutex.
    """
    timeout = float(timeout)
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("focus lock timeout must be finite and nonnegative")
    if kernel is None and os.name != "nt":
        if not _fallback.acquire(timeout=timeout):
            raise TimeoutError("focus lock timed out")
        try:
            yield
        finally:
            _fallback.release()
        return

    kernel = _kernel32() if kernel is None else kernel
    handle = kernel.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise _error("CreateMutexW")
    acquired = False
    try:
        # Never convert a finite timeout to Win32's INFINITE sentinel.
        milliseconds = math.ceil(min(timeout * 1000, 0xFFFFFFFE))
        status = kernel.WaitForSingleObject(handle, milliseconds)
        if status == 0x102:  # WAIT_TIMEOUT
            raise TimeoutError("focus lock timed out")
        if status not in (0, 0x80):  # WAIT_OBJECT_0 / WAIT_ABANDONED
            raise _error("WaitForSingleObject")
        acquired = True
        yield
    finally:
        try:
            if acquired and not kernel.ReleaseMutex(handle):
                raise _error("ReleaseMutex")
        finally:
            if not kernel.CloseHandle(handle):
                raise _error("CloseHandle")
