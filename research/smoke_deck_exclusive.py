"""Ten-second Windows smoke: real deck hook, tagged SendInput, normal WM_CLOSE.

The probe hook is installed before the deck, so it sits downstream. It consumes
only its own tagged letters after the deck forwards them, keeping the foreground
application free of test text. No serial commands or HID reports are sent.
"""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pc"))
import deck_input as raw
from deck_windows import INPUT

TAG = 0xA6D3C5EA
LOG = ROOT / "research" / "history" / "deck-exclusive-smoke.log"
RESULT = LOG.with_suffix(".json")


def main():
    if os.name != "nt":
        raise OSError("This smoke requires a Windows desktop")
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    hook_proc = raw.WINFUNCTYPE(raw.IPTR, ctypes.c_int, raw.UPTR, raw.IPTR)
    enum_proc = raw.WINFUNCTYPE(raw.BOOL, raw.PTR, raw.IPTR)
    for name, result, arguments in (
            ("SetWindowsHookExW", raw.PTR, [ctypes.c_int, hook_proc, raw.PTR, raw.U32]),
            ("UnhookWindowsHookEx", raw.BOOL, [raw.PTR]),
            ("CallNextHookEx", raw.IPTR, [raw.PTR, ctypes.c_int, raw.UPTR, raw.IPTR]),
            ("PeekMessageW", raw.BOOL, [ctypes.POINTER(raw.MSG), raw.PTR, raw.U32, raw.U32, raw.U32]),
            ("TranslateMessage", raw.BOOL, [ctypes.POINTER(raw.MSG)]),
            ("DispatchMessageW", raw.IPTR, [ctypes.POINTER(raw.MSG)]),
            ("SendInput", raw.U32, [raw.U32, ctypes.POINTER(INPUT), ctypes.c_int]),
            ("EnumWindows", raw.BOOL, [enum_proc, raw.IPTR]),
            ("GetWindowThreadProcessId", raw.U32, [raw.PTR, ctypes.POINTER(raw.U32)]),
            ("GetWindowTextW", ctypes.c_int, [raw.PTR, ctypes.c_wchar_p, ctypes.c_int]),
            ("GetThreadDesktop", raw.PTR, [raw.U32]),
            ("OpenInputDesktop", raw.PTR, [raw.U32, raw.BOOL, raw.U32]),
            ("CloseDesktop", raw.BOOL, [raw.PTR]),
            ("GetUserObjectInformationW", raw.BOOL,
             [raw.PTR, ctypes.c_int, raw.PTR, raw.U32, ctypes.POINTER(raw.U32)]),
            ("PostMessageW", raw.BOOL, [raw.PTR, raw.U32, raw.UPTR, raw.IPTR])):
        raw._signature(user, name, result, arguments)
    raw._signature(kernel, "GetModuleHandleW", raw.PTR, [ctypes.c_wchar_p])
    raw._signature(kernel, "GetCurrentThreadId", raw.U32, [])

    def desktop_name(desktop):
        name, needed = ctypes.create_unicode_buffer(256), raw.U32()
        if desktop and user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)):
            return name.value
        return "unavailable"

    current_desktop = desktop_name(user.GetThreadDesktop(kernel.GetCurrentThreadId()))
    input_desktop = user.OpenInputDesktop(0, False, 1)
    try:
        input_name = desktop_name(input_desktop)
    finally:
        if input_desktop:
            user.CloseDesktop(input_desktop)

    class Keyboard(ctypes.Structure):
        _fields_ = [("vkCode", raw.U32), ("scanCode", raw.U32), ("flags", raw.U32),
                    ("time", raw.U32), ("dwExtraInfo", raw.UPTR)]

    observed = []

    @hook_proc
    def downstream(code, message, pointer):
        if code == 0 and pointer:
            key = ctypes.cast(pointer, ctypes.POINTER(Keyboard)).contents
            if key.dwExtraInfo == TAG and key.flags & 0x10:
                observed.append((key.vkCode, bool(key.flags & 0x80)))
                return 1
        return user.CallNextHookEx(None, code, message, pointer)

    def pump():
        message = raw.MSG()
        for _ in range(100):
            if not user.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                break
            user.TranslateMessage(ctypes.byref(message))
            user.DispatchMessageW(ctypes.byref(message))

    def child_window(pid):
        windows = []

        @enum_proc
        def collect(hwnd, unused):
            owner = raw.U32()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            title = ctypes.create_unicode_buffer(256)
            if owner.value == pid:
                user.GetWindowTextW(hwnd, title, len(title))
                if title.value == "AgentDeck input":
                    windows.append(hwnd)
            return 1

        user.EnumWindows(collect, 0)
        return windows[0] if len(windows) == 1 else None

    hook = user.SetWindowsHookExW(13, downstream, kernel.GetModuleHandleW(None), 0)
    if not hook:
        raise ctypes.WinError()
    process, hwnd = None, None
    normal_exit = False
    sent = []
    results = []
    try:
        with LOG.open("w", encoding="utf-8", buffering=1) as output:
            output.write("SMOKE: deck run -v; 10 seconds; no serial/HID commands\n")
            output.write("SMOKE: preinstalled downstream hook captures only tagged test letters\n")
            output.write("SMOKE: current desktop=%s; input desktop=%s\n" % (current_desktop, input_name))
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "pc" / "deck.py"), "run", "-v"],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                creationflags=0x08000000)
            started = time.monotonic()
            expected = [(vk, up) for vk in (0x51, 0x57, 0x52) for up in (False, True)]
            while time.monotonic() - started < 10:
                pump()
                if process.poll() is not None:
                    raise RuntimeError("deck exited before the ten-second smoke completed")
                hwnd = hwnd or child_window(process.pid)
                ready = "hook installed" in LOG.read_text(encoding="utf-8")
                elapsed = time.monotonic() - started
                if not ready and elapsed > 4:
                    raise RuntimeError("deck did not report that its exclusive hook was installed")
                if ready and len(sent) < 3 and elapsed >= 2 + 2 * len(sent):
                    vk = (0x51, 0x57, 0x52)[len(sent)]
                    inputs = (INPUT * 2)()
                    for index, flags in enumerate((0, 2)):
                        inputs[index].type = 1
                        inputs[index].ki.wVk = vk
                        inputs[index].ki.dwFlags = flags
                        inputs[index].ki.dwExtraInfo = TAG
                    ctypes.set_last_error(0)
                    inserted = user.SendInput(2, inputs, ctypes.sizeof(INPUT))
                    error = ctypes.get_last_error()
                    results.append({"vkey": vk, "requested": 2, "inserted": inserted, "error": error})
                    sent.append(vk)
                time.sleep(0.005)
            if not hwnd or not user.PostMessageW(hwnd, raw.WM_CLOSE, 0, 0):
                raise RuntimeError("could not request normal shutdown of the smoke child window")
            closing = time.monotonic()
            while process.poll() is None and time.monotonic() - closing < 4:
                pump()
                time.sleep(0.005)
            if process.poll() != 0:
                raise RuntimeError("deck failed to exit normally with status zero")
            normal_exit = True
            text = LOG.read_text(encoding="utf-8")
            assert "hook suppressed" not in text, text
            assert "AgentDeck stopped; action thread joined" in text, text
            verified = observed == expected and text.count("hook injected") == 6
            summary = {"duration_seconds": round(closing - started, 3), "sent_letters": "QWR",
                       "sendinput_attempts": results, "downstream_observed": len(observed),
                       "deck_injected_passes": text.count("hook injected"),
                       "suppressed_events": text.count("hook suppressed"),
                       "current_desktop": current_desktop, "input_desktop": input_name,
                       "normal_exit": True, "exit_code": process.returncode, "injection_verified": verified}
            if not verified:
                summary["limitation"] = "SendInput pass-through was not verified; the process desktop differs from the input desktop" if (
                    current_desktop != input_name) else "SendInput pass-through was not observed; see injection return counts"
            output.write(("SMOKE PASS: " if verified else "SMOKE INCOMPLETE: ") + json.dumps(summary, ensure_ascii=False) + "\n")
            RESULT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            return 0 if verified else 1
    finally:
        if process is not None and process.poll() is None:
            hwnd = hwnd or child_window(process.pid)
            if hwnd:
                user.PostMessageW(hwnd, raw.WM_CLOSE, 0, 0)
            closing = time.monotonic()
            while process.poll() is None and time.monotonic() - closing < 3:
                pump()
                time.sleep(0.005)
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)
        user.UnhookWindowsHookEx(hook)
        print(LOG.read_text(encoding="utf-8"), end="", flush=True)
        if not normal_exit:
            print("SMOKE FAILED; the child was cleaned up", flush=True)


if __name__ == "__main__":
    sys.exit(main())
