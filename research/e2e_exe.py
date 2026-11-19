"""用打包后的 AgentDeck-relay.exe 对正在运行的 AgentDeck.exe 走一遍批准 / 拒绝 / 高危二次确认。"""
import json, subprocess, sys, time, urllib.request
from pathlib import Path

RELAY = r"D:\desk\hardware\h1\dist\AgentDeck\AgentDeck-relay.exe"
TOKEN = (Path.home() / ".agentdeck" / "token").read_text().strip()
BASE = "http://127.0.0.1:47800"


def call(path, body=None):
    req = urllib.request.Request(BASE + path, method="POST" if body is not None else "GET",
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"X-AgentDeck-Token": TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def event(session, command):
    return {"hook_event_name": "PermissionRequest", "session_id": session,
            "cwd": r"D:\desk\hardware\h1\agentdeck-test", "tool_name": "Bash",
            "tool_input": {"command": command}}


def shown(rid):
    """等到这条请求成为当前显示的请求。"""
    for _ in range(100):
        st = call("/state")[1]
        req = st.get("input_request") or {}
        if req.get("request_id") == rid:
            return req
        time.sleep(0.1)
    raise SystemExit(f"request {rid} never displayed: {st.get('input_request')}")


def run(name, session, command, actions):
    proc = subprocess.Popen([RELAY, "--agent", "cc"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    proc.stdin.write(json.dumps(event(session, command)))
    proc.stdin.close()
    rid = None
    for _ in range(50):
        for p in call("/state")[1].get("pending", []):
            if p["session_id"] == session:
                rid = p["id"]
        if rid:
            break
        time.sleep(0.1)
    log = []
    for act in actions:
        for attempt in range(6):
            req = shown(rid)
            time.sleep(0.6)
            code, body = call("/action", {"action": act, "request_id": rid, "nonce": req["nonce"]})
            log.append((act, code, body.get("status") or body.get("error") or body.get("message")))
            if code != 409:
                break
            time.sleep(0.4)
        time.sleep(0.3)
    out, _ = proc.communicate(timeout=30)
    end = subprocess.run([RELAY, "--agent", "cc"], input=json.dumps(
        {"hook_event_name": "SessionEnd", "session_id": session, "cwd": r"D:\desk\hardware\h1\agentdeck-test"}),
        capture_output=True, text=True, timeout=10)
    print(f"[{name}] {log}\n    relay exit={proc.returncode} stdout={out.strip()[:200]}", flush=True)
    return out


tag = str(int(time.time()))
a = run("低风险批准", "e2e-low-" + tag, "ls", ["approve"])
b = run("拒绝", "e2e-deny-" + tag, "ls -la", ["deny"])
c = run("高危两次", "e2e-high-" + tag, "git push --force origin feature-x", ["approve", "approve"])
# 槽位泄漏回归：连开 8 个不发 SessionEnd 的会话，第 8 个的请求仍须被 hub 接住
for i in range(7):
    call("/event?agent=cc", {"hook_event_name": "UserPromptSubmit", "session_id": f"leak-{tag}-{i}",
                             "cwd": r"D:\desk\hardware\h1\agentdeck-test"})
d = run("槽满后第8个会话", "leak-new-" + tag, "ls", ["approve"])
for i in range(7):  # 自测完把假会话清掉，别占着用户的槽位
    call("/event?agent=cc", {"hook_event_name": "SessionEnd", "session_id": f"leak-{tag}-{i}"})
ok = '"allow"' in a and '"deny"' in b and '"allow"' in c and '"allow"' in d
print("RESULT", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
