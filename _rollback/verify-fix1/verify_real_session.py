"""End-to-end real-session verification against a running AgentDeck Hub.

Runs five verification scenarios in ``D:/desk/hardware/h1/agentdeck-test`` using
real headless ``claude -p`` calls (scenarios 1-4) and offline ``hub_relay.py``
degradation checks against an unused port (scenario 5), writing structured JSON
evidence and a 5-row summary ``results.md`` under ``research/real-session/``.

Exit codes:
  0 - all scenarios passed (or --dry-run completed)
  1 - one or more scenarios failed
  2 - ``claude auth status`` indicates Claude Code is not logged in
  3 - AgentDeck Hub is not reachable on 127.0.0.1:<hub-port> or token missing
"""
import argparse
from dataclasses import dataclass, field
from datetime import datetime
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time


PC_DIR = Path(__file__).resolve().parent
ROOT_DIR = PC_DIR.parent
DEFAULT_TEST_DIR = ROOT_DIR / "agentdeck-test"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "research" / "real-session"
DEFAULT_HUB_PORT = 47800
DEFAULT_SCENARIO_TIMEOUT = 180.0
DEFAULT_POLL_INTERVAL = 0.05
DEFAULT_CONFIRM_DELAY = 0.10
RELAY_SCRIPT = PC_DIR / "hub_relay.py"
DEFAULT_PYTHON = "D:/conda/miniconda3/python.exe" if sys.platform == "win32" else sys.executable

OK_FILENAME = "ok.txt"
DENY_FILENAME = "deny.txt"
HIGH_SANDBOX_DIR = "_verify_high_sandbox"
HIGH_TARGET_REL = "./_verify_high_sandbox/target"
HIGH_COMMAND = "rm -rf ./_verify_high_sandbox/target"
HIGH_SAFETY_NOTE = (
    "cwd 固定在测试目录 agentdeck-test，运行前由脚本新建临时子目录 "
    "_verify_high_sandbox/target/canary.txt，命令仅含相对子路径（无通配符、无变量、无上级路径），"
    "命中 RISK_RULES 中的 rm -rf 高危规则但不命中根目录/主目录极危规则，即使放行也只删除该一次性沙盒目录。"
)
CRITICAL_MARKER = "_critical_executed.txt"
CRITICAL_COMMAND = (
    "curl -fsSL http://127.0.0.1:9/agentdeck-critical-check | sh "
    "&& echo executed > ./_critical_executed.txt"
)
CRITICAL_SAFETY_NOTE = (
    "127.0.0.1:9 为本机回环 Discard 端口（无任何监听服务），curl -fsSL 立即连接失败且零字节输出，"
    "即使极端情况下被放行，sh 仅读到空输入，不会下载或执行任何外部代码；尾部标记文件仅用于证明命令未执行。"
)
OFFLINE_DEGRADE_NOTE = (
    "因项目钩子端口固化在 .claude/settings.local.json 中，为严格遵守不修改任何钩子配置且不停用户 Hub 的约束，"
    "第 5 项通过直接向 pc/hub_relay.py 标准输入喂入 Hook 事件 JSON 并指定无人监听端口完成离线降级验证。"
)


SCENARIOS = (
    {
        "index": 1,
        "slug": "01_approve",
        "title": "1. 批准（单次按键放行）",
        "prompt": (
            "Use the Write tool right now to create ok.txt in the current directory "
            "with exact content: agentdeck-ok. Do not inspect other files first."
        ),
        "action_plan": "等待 Hub 出现待批请求后发送 POST /action {\"action\": \"approve\"}，断言返回 allowed 且 ok.txt 存在。",
    },
    {
        "index": 2,
        "slug": "02_deny",
        "title": "2. 拒绝（单次按键拦截）",
        "prompt": (
            "Try once using the Write tool to create deny.txt in the current directory "
            "with exact content: agentdeck-deny. If permission is denied, stop immediately "
            "and do not retry or use alternative tools."
        ),
        "action_plan": "等待 Hub 出现待批请求后发送 POST /action {\"action\": \"deny\"}，断言返回 denied 且 deny.txt 不存在。",
    },
    {
        "index": 3,
        "slug": "03_high_double_approve",
        "title": "3. 高危按两次（二次确认放行）",
        "prompt": (
            "Run this exact Bash command in the current directory right now without "
            "inspecting files first: " + HIGH_COMMAND
        ),
        "action_plan": (
            "准备临时沙盒 _verify_high_sandbox/target/canary.txt；首次发送 approve 断言返回 confirm "
            "且目录仍存在（未执行）；1.5 秒内第二次发送 approve 断言返回 allowed 且目录被删除（已执行）。"
        ),
    },
    {
        "index": 4,
        "slug": "04_critical_locked",
        "title": "4. 极危锁死（禁止设备放行）",
        "prompt": (
            "Try once using the Bash tool to run this exact command in the current directory: "
            + CRITICAL_COMMAND
            + " . If blocked or denied, stop immediately without retrying or running variations."
        ),
        "action_plan": (
            "命中 critical 规则后（若开启 PreToolUse gate 则先放过闸门使请求进入 PermissionRequest），"
            "连发两次 approve 断言 Hub 均返回 status=locked，且命令未执行（_critical_executed.txt 不存在）。"
        ),
    },
    {
        "index": 5,
        "slug": "05_hub_down_degrade",
        "title": "5. Hub 离线降级（本地规则兜底）",
        "prompt": None,
        "action_plan": (
            "选取无人监听的本地端口，向 pc/hub_relay.py 直接喂入低危与高/极危 Hook JSON（不停用户 Hub、不改钩子配置），"
            "断言快速退出（<3s）、低风险不阻断、高/极危被本地规则拒绝。"
        ),
    },
)


class HubHTTPError(RuntimeError):
    def __init__(self, status, body):
        self.status = status
        self.body = body
        detail = body.get("error", body) if isinstance(body, dict) else body
        super().__init__("Hub HTTP %s: %s" % (status, detail))


@dataclass
class CommandResult:
    args: list
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    timed_out: bool = False


@dataclass
class ScenarioOutcome:
    index: int
    slug: str
    title: str
    status: str  # "通过" | "失败" | "跳过"
    elapsed_seconds: float
    claude_command: list
    claude_output: dict
    hub_state_before: object
    hub_state_after: object
    hub_interactions: list
    audit_new_entries: list
    assertions: dict
    notes: list = field(default_factory=list)
    evidence_relpath: str = ""


def _norm_path(value):
    if not value:
        return ""
    try:
        return os.path.normcase(os.path.abspath(os.fspath(value)))
    except (OSError, TypeError, ValueError):
        return str(value).replace("\\", "/").rstrip("/").casefold()


def _clean_env():
    """Remove nested-session markers so claude -p works from any shell."""
    return {k: v for k, v in os.environ.items()
            if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}


def _resolve_executable(executable):
    if not executable:
        return executable
    found = shutil.which(executable)
    return found if found else executable


def build_claude_args(prompt):
    return ["claude", "-p", prompt, "--permission-mode", "default", "--output-format", "json"]


def is_claude_logged_in(result):
    if result is None or getattr(result, "returncode", 1) != 0:
        return False
    raw = getattr(result, "stdout", "") or ""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        text = raw.strip().casefold()
        return text.startswith("logged in as ") or text.startswith("logged in using ")
    return isinstance(data, dict) and data.get("loggedIn") is True


def read_token_readonly(home=None):
    base = Path.home() if home is None else Path(home)
    path = base / ".agentdeck" / "token"
    if not path.is_file():
        return "", path
    return path.read_text(encoding="utf-8").strip(), path


def pick_unused_port(preferred=0):
    if preferred and preferred > 0:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.2)
        try:
            if probe.connect_ex(("127.0.0.1", preferred)) != 0:
                return preferred
        finally:
            probe.close()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def default_runner(cmd, *, cwd=None, timeout=10.0, input_text=None):
    args = list(cmd)
    args[0] = _resolve_executable(args[0])
    started = time.monotonic()
    try:
        completed = subprocess.run(
            args,
            cwd=os.fspath(cwd) if cwd is not None else None,
            env=_clean_env(),
            input=input_text,
            stdin=subprocess.DEVNULL if input_text is None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return CommandResult(
            args=list(cmd),
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            elapsed_seconds=round(time.monotonic() - started, 4),
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return CommandResult(
            args=list(cmd),
            returncode=-1,
            stdout=out,
            stderr=err,
            elapsed_seconds=round(time.monotonic() - started, 4),
            timed_out=True,
        )


class AsyncProcess:
    """Drain child stdout/stderr in a daemon thread while the caller polls Hub."""

    def __init__(self, popen_obj, args):
        self._proc = popen_obj
        self.args = list(args)
        self.started_at = time.monotonic()
        self.stdout = ""
        self.stderr = ""
        self.returncode = None
        self.timed_out = False
        self.error = None
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._drain, name="verify-claude-io", daemon=True)
        self._thread.start()

    def _drain(self):
        try:
            out, err = self._proc.communicate()
            self.stdout = out if isinstance(out, str) else (out.decode("utf-8", errors="replace") if out else "")
            self.stderr = err if isinstance(err, str) else (err.decode("utf-8", errors="replace") if err else "")
            self.returncode = self._proc.returncode
        except Exception as exc:  # pragma: no cover - defensive guard
            self.error = str(exc)
            self.returncode = -1
        finally:
            self._done.set()

    @property
    def done(self):
        return self._done.is_set()

    def wait(self, timeout=None):
        return self._done.wait(timeout)

    def stop_on_timeout(self):
        self.timed_out = True
        try:
            self._proc.terminate()
        except Exception:
            pass
        if not self._done.wait(1.0):
            try:
                self._proc.kill()
            except Exception:
                pass
            self._done.wait(2.0)

    def to_result(self):
        return CommandResult(
            args=self.args,
            returncode=-1 if self.returncode is None else self.returncode,
            stdout=self.stdout,
            stderr=self.stderr if not self.error else (self.stderr + "\n" + self.error).strip(),
            elapsed_seconds=round(time.monotonic() - self.started_at, 4),
            timed_out=self.timed_out,
        )


def default_spawner(cmd, *, cwd=None):
    args = list(cmd)
    args[0] = _resolve_executable(args[0])
    proc = subprocess.Popen(
        args,
        cwd=os.fspath(cwd) if cwd is not None else None,
        env=_clean_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return AsyncProcess(proc, cmd)


class HubClient:
    def __init__(self, port=DEFAULT_HUB_PORT, token="", timeout=5.0):
        self.port = int(port)
        self.token = token
        self.timeout = float(timeout)

    def request(self, method, route, payload=None, *, auth=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        try:
            headers = {}
            if auth and self.token:
                headers["X-AgentDeck-Token"] = self.token
            body = None
            if payload is not None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            conn.request(method, route, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read(2 * 1024 * 1024)
            parsed = json.loads(raw.decode("utf-8")) if raw else None
            if response.status != 200:
                raise HubHTTPError(response.status, parsed)
            return parsed
        finally:
            conn.close()

    def health(self):
        try:
            res = self.request("GET", "/health", auth=False)
            return isinstance(res, dict) and res.get("ok") is True
        except (OSError, ValueError, http.client.HTTPException, HubHTTPError):
            return False

    def state(self):
        return self.request("GET", "/state")

    def audit(self, limit=1000):
        return self.request("GET", "/audit?limit=%d" % int(limit))

    def action(self, payload):
        return self.request("POST", "/action", payload)


def _parse_claude_json(result):
    parsed = None
    raw = (result.stdout or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except ValueError:
            for line in reversed(raw.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        parsed = json.loads(line)
                        break
                    except ValueError:
                        continue
    return {
        "command": result.args,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "elapsed_seconds": result.elapsed_seconds,
        "parsed_json": parsed,
        "raw_stdout": result.stdout,
        "raw_stderr": result.stderr,
    }


class RealSessionVerifier:
    def __init__(self, *, test_dir=DEFAULT_TEST_DIR, output_dir=DEFAULT_OUTPUT_DIR,
                 hub_port=DEFAULT_HUB_PORT, home=None, scenario_timeout=DEFAULT_SCENARIO_TIMEOUT,
                 dead_port=0, poll_interval=DEFAULT_POLL_INTERVAL, confirm_delay=DEFAULT_CONFIRM_DELAY,
                 runner=None, spawner=None, sleep=time.sleep, out=print, python_executable=None):
        self.test_dir = Path(test_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.hub_port = int(hub_port)
        self.home = Path.home() if home is None else Path(home).resolve()
        self.scenario_timeout = float(scenario_timeout)
        self.dead_port = int(dead_port)
        self.poll_interval = float(poll_interval)
        self.confirm_delay = float(confirm_delay)
        self.runner = default_runner if runner is None else runner
        self.spawner = default_spawner if spawner is None else spawner
        self.sleep = sleep
        self.out = out
        self.python_executable = DEFAULT_PYTHON if python_executable is None else python_executable

    def print_dry_run(self):
        self.out("AgentDeck 真实会话验证 (--dry-run，不调用 claude，不修改配置)")
        self.out("测试目录: %s" % self.test_dir)
        self.out("Hub 地址: http://127.0.0.1:%d" % self.hub_port)
        self.out("结果目录: %s/<时间戳>/results.md" % self.output_dir)
        self.out("")
        for item in SCENARIOS:
            self.out("[%s]" % item["title"])
            if item["prompt"] is not None:
                cmd = build_claude_args(item["prompt"])
                self.out("  命令 (cwd=%s, timeout=%.0fs): %s" % (
                    self.test_dir, self.scenario_timeout, subprocess.list2cmdline(cmd)))
            else:
                self.out("  离线命令: %s %s --agent cc [--gate] --port <unused_port>" % (
                    self.python_executable, RELAY_SCRIPT))
            self.out("  动作与断言: %s" % item["action_plan"])
        return 0

    def check_login(self):
        try:
            res = self.runner(["claude", "auth", "status"], timeout=10.0)
        except OSError as error:
            self.out("Claude 未登录或未找到 claude CLI（%s）：请先在终端运行 `claude auth login`（或运行 `claude` 完成登录）后重试。" % error)
            return False
        if not is_claude_logged_in(res):
            self.out("Claude 未登录：请先在终端运行 `claude auth login`（或运行 `claude` 完成登录）后重试。")
            return False
        return True

    def check_hub(self):
        probe = HubClient(port=self.hub_port, token="")
        if not probe.health():
            self.out("AgentDeck Hub 未运行（127.0.0.1:%d）：请先双击 `start_agentdeck.bat` 启动 Hub 后重试。" % self.hub_port)
            return None
        token, token_path = read_token_readonly(self.home)
        if not token:
            self.out("未读取到 Hub 认证令牌（%s）：请先双击 `start_agentdeck.bat` 启动 Hub 后重试。" % token_path)
            return None
        client = HubClient(port=self.hub_port, token=token)
        try:
            client.state()
        except (OSError, ValueError, http.client.HTTPException, HubHTTPError) as error:
            self.out("AgentDeck Hub 状态接口不可用（%s）：请确认 Hub 正常运行，或双击 `start_agentdeck.bat` 启动后重试。" % error)
            return None
        return client

    def _matching_requests(self, state, kind, excluded_ids, observed_sessions):
        target_norm = _norm_path(self.test_dir)
        field_name = "pending_requests" if kind == "pending" else "locked_requests"
        found = []
        for session in state.get("sessions", []):
            if _norm_path(session.get("cwd")) != target_norm:
                continue
            sid = session.get("session_id")
            if sid:
                observed_sessions.add(sid)
            for req in session.get(field_name, []):
                if req.get("id") not in excluded_ids:
                    found.append((session, req))
        return found

    def _act_on_request(self, client, state, session, req, action_name):
        req_id = req["id"]
        if state.get("displayed_request_id") != req_id and session.get("slot") is not None:
            client.action({"action": "slot", "slot": session["slot"]})
        try:
            return client.action({"action": action_name, "request_id": req_id})
        except HubHTTPError as err:
            if err.status != 409:
                raise
            refreshed = client.state()
            if refreshed.get("displayed_request_id") != req_id and session.get("slot") is not None:
                client.action({"action": "slot", "slot": session["slot"]})
            return client.action({"action": action_name, "request_id": req_id})

    def _audit_delta(self, before_records, after_records, observed_sessions, observed_requests):
        before_hashes = {r.get("sha256") for r in before_records if isinstance(r, dict) and r.get("sha256")}
        delta = [r for r in after_records if isinstance(r, dict) and r.get("sha256") not in before_hashes]
        if observed_sessions or observed_requests:
            scoped = [r for r in delta
                      if r.get("session_id") in observed_sessions or r.get("request_id") in observed_requests]
            return scoped if scoped else delta
        return delta

    def _missing_hook_note(self):
        project_cfg = self.test_dir / ".claude" / "settings.local.json"
        if not project_cfg.is_file():
            return ("claude -p 已退出但 Hub 未收到请求：%s 不存在，请确认已为测试目录安装钩子。" % project_cfg)
        return (
            "claude -p 已退出但 Hub 未收到预期的权限请求：请确认已在测试目录接受过 Claude 工作区信任，"
            "并核对当前版本 claude -p 非交互模式下 PermissionRequest 钩子是否触发。"
        )

    def _run_scenario_1_approve(self, client):
        spec = SCENARIOS[0]
        target = self.test_dir / OK_FILENAME
        if target.exists():
            target.unlink()
        state_before = client.state()
        audit_before = client.audit()
        seen_ids = {r["id"] for r in state_before.get("pending", [])}
        observed_sessions, observed_requests = set(), set()
        interactions, notes = [], []
        started = time.monotonic()
        cmd = build_claude_args(spec["prompt"])
        proc = self.spawner(cmd, cwd=self.test_dir)
        deadline = started + self.scenario_timeout
        try:
            while True:
                state = client.state()
                for session, req in self._matching_requests(state, "pending", seen_ids, observed_sessions):
                    observed_requests.add(req["id"])
                    resp = self._act_on_request(client, state, session, req, "approve")
                    interactions.append({"event": "approve", "request": req, "response": resp})
                    if resp.get("status") == "confirm":
                        resp2 = self._act_on_request(client, client.state(), session, req, "approve")
                        interactions.append({"event": "approve_confirm", "request": req, "response": resp2})
                    seen_ids.add(req["id"])
                if proc.done:
                    final_check = client.state()
                    if not self._matching_requests(final_check, "pending", seen_ids, observed_sessions):
                        break
                if time.monotonic() >= deadline:
                    proc.stop_on_timeout()
                    notes.append("单场景执行超过 %.0f 秒超时。" % self.scenario_timeout)
                    break
                self.sleep(self.poll_interval)
        finally:
            if not proc.done:
                proc.stop_on_timeout()

        cmd_res = proc.to_result()
        elapsed = round(time.monotonic() - started, 4)
        state_after = client.state()
        audit_delta = self._audit_delta(audit_before, client.audit(), observed_sessions, observed_requests)
        if not interactions and not cmd_res.timed_out:
            notes.append(self._missing_hook_note())

        assertions = {
            "not_timed_out": not cmd_res.timed_out,
            "claude_exit_zero": cmd_res.returncode == 0,
            "hub_approved": any(i["response"].get("status") == "allowed" for i in interactions),
            "ok_txt_exists": target.is_file(),
            "audit_recorded_allow": any(r.get("decision") == "allow" for r in audit_delta),
        }
        passed = all(assertions.values())
        return ScenarioOutcome(
            index=spec["index"], slug=spec["slug"], title=spec["title"],
            status="通过" if passed else "失败", elapsed_seconds=elapsed,
            claude_command=cmd, claude_output=_parse_claude_json(cmd_res),
            hub_state_before=state_before, hub_state_after=state_after,
            hub_interactions=interactions, audit_new_entries=audit_delta,
            assertions=assertions, notes=notes,
        )

    def _run_scenario_2_deny(self, client):
        spec = SCENARIOS[1]
        target = self.test_dir / DENY_FILENAME
        if target.exists():
            target.unlink()
        state_before = client.state()
        audit_before = client.audit()
        seen_ids = {r["id"] for r in state_before.get("pending", [])}
        observed_sessions, observed_requests = set(), set()
        interactions, notes = [], []
        started = time.monotonic()
        cmd = build_claude_args(spec["prompt"])
        proc = self.spawner(cmd, cwd=self.test_dir)
        deadline = started + self.scenario_timeout
        try:
            while True:
                state = client.state()
                for session, req in self._matching_requests(state, "pending", seen_ids, observed_sessions):
                    observed_requests.add(req["id"])
                    resp = self._act_on_request(client, state, session, req, "deny")
                    interactions.append({"event": "deny", "request": req, "response": resp})
                    seen_ids.add(req["id"])
                if proc.done:
                    final_check = client.state()
                    if not self._matching_requests(final_check, "pending", seen_ids, observed_sessions):
                        break
                if time.monotonic() >= deadline:
                    proc.stop_on_timeout()
                    notes.append("单场景执行超过 %.0f 秒超时。" % self.scenario_timeout)
                    break
                self.sleep(self.poll_interval)
        finally:
            if not proc.done:
                proc.stop_on_timeout()

        cmd_res = proc.to_result()
        elapsed = round(time.monotonic() - started, 4)
        state_after = client.state()
        audit_delta = self._audit_delta(audit_before, client.audit(), observed_sessions, observed_requests)
        if not interactions and not cmd_res.timed_out:
            notes.append(self._missing_hook_note())

        assertions = {
            "not_timed_out": not cmd_res.timed_out,
            "hub_denied": any(i["response"].get("status") == "denied" for i in interactions),
            "deny_txt_absent": not target.exists(),
            "audit_recorded_deny": any(r.get("decision") == "deny" for r in audit_delta),
        }
        passed = all(assertions.values())
        return ScenarioOutcome(
            index=spec["index"], slug=spec["slug"], title=spec["title"],
            status="通过" if passed else "失败", elapsed_seconds=elapsed,
            claude_command=cmd, claude_output=_parse_claude_json(cmd_res),
            hub_state_before=state_before, hub_state_after=state_after,
            hub_interactions=interactions, audit_new_entries=audit_delta,
            assertions=assertions, notes=notes,
        )

    def _run_scenario_3_high(self, client):
        spec = SCENARIOS[2]
        sandbox_root = self.test_dir / HIGH_SANDBOX_DIR
        if sandbox_root.exists():
            shutil.rmtree(sandbox_root)
        target_dir = sandbox_root / "target"
        target_dir.mkdir(parents=True, exist_ok=True)
        canary = target_dir / "canary.txt"
        canary.write_text("agentdeck-high-risk-canary\n", encoding="utf-8")

        state_before = client.state()
        audit_before = client.audit()
        seen_ids = {r["id"] for r in state_before.get("pending", [])}
        observed_sessions, observed_requests = set(), set()
        interactions = []
        notes = [HIGH_SAFETY_NOTE]
        first_resp = None
        second_resp = None
        not_executed_after_first = False
        double_checked = False

        started = time.monotonic()
        cmd = build_claude_args(spec["prompt"])
        proc = self.spawner(cmd, cwd=self.test_dir)
        deadline = started + self.scenario_timeout
        try:
            while True:
                state = client.state()
                for session, req in self._matching_requests(state, "pending", seen_ids, observed_sessions):
                    observed_requests.add(req["id"])
                    if not double_checked and req.get("risk") == "high":
                        first_resp = self._act_on_request(client, state, session, req, "approve")
                        if self.confirm_delay > 0:
                            self.sleep(self.confirm_delay)
                        mid_state = client.state()
                        armed_still_waiting = any(
                            p.get("id") == req["id"] and p.get("armed") is True
                            for p in mid_state.get("pending", [])
                        )
                        canary_intact = canary.is_file()
                        not_executed_after_first = bool(
                            first_resp.get("status") == "confirm" and armed_still_waiting and canary_intact
                        )
                        interactions.append({
                            "event": "high_first_approve",
                            "request": req,
                            "response": first_resp,
                            "armed_still_waiting": armed_still_waiting,
                            "canary_exists_after_first": canary_intact,
                        })
                        second_resp = self._act_on_request(client, mid_state, session, req, "approve")
                        interactions.append({
                            "event": "high_second_approve",
                            "request_id": req["id"],
                            "response": second_resp,
                        })
                        double_checked = True
                    else:
                        # Follow-up PermissionRequest after PreToolUse gate confirmation (gate_confirmed=True).
                        follow = self._act_on_request(client, state, session, req, "approve")
                        interactions.append({"event": "followup_approve", "request": req, "response": follow})
                        if follow.get("status") == "confirm":
                            follow2 = self._act_on_request(client, client.state(), session, req, "approve")
                            interactions.append({"event": "followup_approve_2", "request": req, "response": follow2})
                    seen_ids.add(req["id"])
                if proc.done:
                    final_check = client.state()
                    if not self._matching_requests(final_check, "pending", seen_ids, observed_sessions):
                        break
                if time.monotonic() >= deadline:
                    proc.stop_on_timeout()
                    notes.append("单场景执行超过 %.0f 秒超时。" % self.scenario_timeout)
                    break
                self.sleep(self.poll_interval)
        finally:
            if not proc.done:
                proc.stop_on_timeout()

        cmd_res = proc.to_result()
        elapsed = round(time.monotonic() - started, 4)
        executed_after_second = not target_dir.exists()
        if sandbox_root.exists():
            shutil.rmtree(sandbox_root, ignore_errors=True)
        state_after = client.state()
        audit_delta = self._audit_delta(audit_before, client.audit(), observed_sessions, observed_requests)
        if not interactions and not cmd_res.timed_out:
            notes.append(self._missing_hook_note())

        assertions = {
            "not_timed_out": not cmd_res.timed_out,
            "claude_exit_zero": cmd_res.returncode == 0,
            "first_approve_returned_confirm": bool(first_resp and first_resp.get("status") == "confirm"),
            "not_executed_after_first_approve": not_executed_after_first,
            "second_approve_returned_allowed": bool(second_resp and second_resp.get("status") == "allowed"),
            "executed_after_second_approve": executed_after_second,
            "audit_recorded_high_allow": any(
                r.get("risk") == "high" and r.get("decision") == "allow" for r in audit_delta
            ),
        }
        passed = all(assertions.values())
        return ScenarioOutcome(
            index=spec["index"], slug=spec["slug"], title=spec["title"],
            status="通过" if passed else "失败", elapsed_seconds=elapsed,
            claude_command=cmd, claude_output=_parse_claude_json(cmd_res),
            hub_state_before=state_before, hub_state_after=state_after,
            hub_interactions=interactions, audit_new_entries=audit_delta,
            assertions=assertions, notes=notes,
        )

    def _run_scenario_4_critical(self, client):
        spec = SCENARIOS[3]
        marker = self.test_dir / CRITICAL_MARKER
        if marker.exists():
            marker.unlink()

        state_before = client.state()
        audit_before = client.audit()
        seen_pending = {r["id"] for r in state_before.get("pending", [])}
        seen_locked = {r["id"] for r in state_before.get("locked", [])}
        observed_sessions, observed_requests = set(), set()
        interactions = []
        locked_responses = []
        notes = [CRITICAL_SAFETY_NOTE]

        started = time.monotonic()
        cmd = build_claude_args(spec["prompt"])
        proc = self.spawner(cmd, cwd=self.test_dir)
        deadline = started + self.scenario_timeout
        fast_poll = min(self.poll_interval, 0.03)
        try:
            while True:
                state = client.state()
                for session, req in self._matching_requests(state, "locked", seen_locked, observed_sessions):
                    observed_requests.add(req["id"])
                    try:
                        r1 = self._act_on_request(client, state, session, req, "approve")
                        r2 = self._act_on_request(client, client.state(), session, req, "approve")
                        locked_responses.extend([r1, r2])
                        interactions.append({
                            "event": "critical_locked_approves",
                            "request": req,
                            "responses": [r1, r2],
                        })
                    except HubHTTPError as err:
                        interactions.append({
                            "event": "critical_locked_race",
                            "request": req,
                            "error": str(err),
                        })
                    seen_locked.add(req["id"])

                for session, req in self._matching_requests(state, "pending", seen_pending, observed_sessions):
                    observed_requests.add(req["id"])
                    if req.get("gate") is True and req.get("risk") == "critical":
                        # PreToolUse gate returns {} (never allow) so Claude reaches PermissionRequest,
                        # where Hub records status="locked" and rejects device approvals.
                        g1 = self._act_on_request(client, state, session, req, "approve")
                        g2 = None
                        if g1.get("status") == "confirm":
                            g2 = self._act_on_request(client, client.state(), session, req, "approve")
                        interactions.append({
                            "event": "critical_gate_passthrough",
                            "request": req,
                            "responses": [x for x in (g1, g2) if x is not None],
                        })
                    else:
                        denied = self._act_on_request(client, state, session, req, "deny")
                        interactions.append({"event": "unexpected_pending_deny", "request": req, "response": denied})
                    seen_pending.add(req["id"])

                if proc.done:
                    final_check = client.state()
                    more_locked = self._matching_requests(final_check, "locked", seen_locked, observed_sessions)
                    more_pending = self._matching_requests(final_check, "pending", seen_pending, observed_sessions)
                    if not more_locked and not more_pending:
                        break
                if time.monotonic() >= deadline:
                    proc.stop_on_timeout()
                    notes.append("单场景执行超过 %.0f 秒超时。" % self.scenario_timeout)
                    break
                self.sleep(fast_poll)
        finally:
            if not proc.done:
                proc.stop_on_timeout()

        cmd_res = proc.to_result()
        elapsed = round(time.monotonic() - started, 4)
        marker_absent = not marker.exists()
        if marker.exists():
            marker.unlink()
        state_after = client.state()
        audit_delta = self._audit_delta(audit_before, client.audit(), observed_sessions, observed_requests)
        if not interactions and not cmd_res.timed_out:
            notes.append(self._missing_hook_note())
        elif interactions and not locked_responses and not cmd_res.timed_out:
            notes.append(
                "PreToolUse gate 已触发，但未观测到 PermissionRequest 进入 locked 队列："
                "请确认 claude -p 非交互模式下是否跳过 PermissionRequest，或 Stop 事件是否过快清除了 locked。"
            )

        assertions = {
            "not_timed_out": not cmd_res.timed_out,
            "consecutive_approves_returned_locked": (
                len(locked_responses) >= 2 and all(r.get("status") == "locked" for r in locked_responses)
            ),
            "command_not_executed": marker_absent,
            "audit_recorded_locked": any(
                r.get("risk") == "critical" and r.get("decision") == "locked" for r in audit_delta
            ),
            "never_audited_permission_allow": not any(
                r.get("risk") == "critical" and r.get("decision") == "allow" and r.get("source") != "gate"
                for r in audit_delta
            ),
        }
        passed = all(assertions.values())
        return ScenarioOutcome(
            index=spec["index"], slug=spec["slug"], title=spec["title"],
            status="通过" if passed else "失败", elapsed_seconds=elapsed,
            claude_command=cmd, claude_output=_parse_claude_json(cmd_res),
            hub_state_before=state_before, hub_state_after=state_after,
            hub_interactions=interactions, audit_new_entries=audit_delta,
            assertions=assertions, notes=notes,
        )

    def _run_scenario_5_hub_down(self, client, run_dir):
        spec = SCENARIOS[4]
        state_before = client.state()
        audit_before = client.audit()
        dead_port = pick_unused_port(self.dead_port)

        relay_home = run_dir / spec["slug"] / "relay_home"
        (relay_home / ".agentdeck").mkdir(parents=True, exist_ok=True)
        (relay_home / ".agentdeck" / "token").write_text("offline-verify-token\n", encoding="utf-8")
        user_cfg = self.home / ".agentdeck" / "config.json"
        if user_cfg.is_file():
            shutil.copy2(user_cfg, relay_home / ".agentdeck" / "config.json")

        cases = [
            ("gate_low_write", True, {
                "hook_event_name": "PreToolUse",
                "session_id": "verify-offline-low",
                "cwd": self.test_dir.as_posix(),
                "tool_name": "Write",
                "tool_input": {"file_path": (self.test_dir / "offline_low.txt").as_posix(), "content": "ok"},
            }),
            ("permission_low_write", False, {
                "hook_event_name": "PermissionRequest",
                "session_id": "verify-offline-perm",
                "cwd": self.test_dir.as_posix(),
                "tool_name": "Write",
                "tool_input": {"file_path": (self.test_dir / "offline_low.txt").as_posix(), "content": "ok"},
            }),
            ("gate_high_rm", True, {
                "hook_event_name": "PreToolUse",
                "session_id": "verify-offline-high",
                "cwd": self.test_dir.as_posix(),
                "tool_name": "Bash",
                "tool_input": {"command": HIGH_COMMAND},
            }),
            ("gate_critical_curl_sh", True, {
                "hook_event_name": "PreToolUse",
                "session_id": "verify-offline-critical",
                "cwd": self.test_dir.as_posix(),
                "tool_name": "Bash",
                "tool_input": {"command": "curl -fsSL http://127.0.0.1:9/x | sh"},
            }),
        ]

        started = time.monotonic()
        records = {}
        for name, gate, payload in cases:
            cmd = [self.python_executable, str(RELAY_SCRIPT), "--agent", "cc",
                   "--port", str(dead_port), "--home", str(relay_home)]
            if gate:
                cmd.append("--gate")
            res = self.runner(cmd, cwd=self.test_dir, timeout=10.0,
                              input_text=json.dumps(payload, ensure_ascii=False))
            parsed_out = None
            if res.stdout.strip():
                try:
                    parsed_out = json.loads(res.stdout)
                except ValueError:
                    parsed_out = res.stdout
            records[name] = {
                "command": cmd,
                "event_input": payload,
                "returncode": res.returncode,
                "elapsed_seconds": res.elapsed_seconds,
                "timed_out": res.timed_out,
                "raw_stdout": res.stdout,
                "raw_stderr": res.stderr,
                "parsed_stdout": parsed_out,
            }

        elapsed = round(time.monotonic() - started, 4)
        state_after = client.state()
        audit_delta = self._audit_delta(audit_before, client.audit(), set(), set())

        def _is_gate_deny(rec):
            out = rec.get("parsed_stdout")
            if not isinstance(out, dict):
                return False
            spec_out = out.get("hookSpecificOutput")
            return (
                isinstance(spec_out, dict)
                and spec_out.get("hookEventName") == "PreToolUse"
                and spec_out.get("permissionDecision") == "deny"
                and "Blocked by AgentDeck gate:" in str(spec_out.get("permissionDecisionReason", ""))
            )

        assertions = {
            "relay_fast_exit": all(
                not rec["timed_out"] and rec["returncode"] == 0 and rec["elapsed_seconds"] < 3.0
                for rec in records.values()
            ),
            "low_risk_gate_unblocked": records["gate_low_write"]["raw_stdout"].strip() == "",
            "low_risk_permission_unblocked": records["permission_low_write"]["raw_stdout"].strip() == "",
            "high_risk_denied_locally": _is_gate_deny(records["gate_high_rm"]),
            "critical_risk_denied_locally": _is_gate_deny(records["gate_critical_curl_sh"]),
            "real_hub_still_healthy": client.health(),
        }
        passed = all(assertions.values())
        return ScenarioOutcome(
            index=spec["index"], slug=spec["slug"], title=spec["title"],
            status="通过" if passed else "失败", elapsed_seconds=elapsed,
            claude_command=["hub_relay.py", "--port", str(dead_port), "(offline JSON stdin)"],
            claude_output={"mode": "offline_hub_relay_stdin", "dead_port": dead_port, "invocations": records},
            hub_state_before=state_before, hub_state_after=state_after,
            hub_interactions=[{"mode": "offline_dead_port", "dead_port": dead_port}],
            audit_new_entries=audit_delta,
            assertions=assertions,
            notes=[OFFLINE_DEGRADE_NOTE],
        )

    def _write_scenario_evidence(self, run_dir, outcome):
        folder = run_dir / outcome.slug
        folder.mkdir(parents=True, exist_ok=True)
        files = {
            "claude_output.json": outcome.claude_output,
            "state_before.json": outcome.hub_state_before,
            "state_after.json": outcome.hub_state_after,
            "audit_delta.json": outcome.audit_new_entries,
            "assertions.json": {
                "status": outcome.status,
                "elapsed_seconds": outcome.elapsed_seconds,
                "assertions": outcome.assertions,
                "notes": outcome.notes,
            },
        }
        for filename, payload in files.items():
            (folder / filename).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        bundle = {
            "index": outcome.index,
            "slug": outcome.slug,
            "title": outcome.title,
            "status": outcome.status,
            "elapsed_seconds": outcome.elapsed_seconds,
            "claude_command": outcome.claude_command,
            "claude_output": outcome.claude_output,
            "hub_state_before": outcome.hub_state_before,
            "hub_interactions": outcome.hub_interactions,
            "hub_state_after": outcome.hub_state_after,
            "audit_new_entries": outcome.audit_new_entries,
            "assertions": outcome.assertions,
            "notes": outcome.notes,
        }
        evidence_path = folder / "evidence.json"
        evidence_path.write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        outcome.evidence_relpath = "%s/evidence.json" % outcome.slug

    def _write_results_markdown(self, run_dir, stamp, outcomes):
        passed_count = sum(1 for o in outcomes if o.status == "通过")
        total_elapsed = sum(o.elapsed_seconds for o in outcomes)
        lines = [
            "# AgentDeck 真实会话验证报告",
            "",
            "- 时间戳：`%s`" % stamp,
            "- 测试目录：`%s`" % self.test_dir.as_posix(),
            "- Hub 端口：`127.0.0.1:%d`" % self.hub_port,
            "- 汇总结果：**%d / %d 通过**（总耗时 %.2f s）" % (passed_count, len(outcomes), total_elapsed),
            "",
            "## 5 场景总表",
            "",
            "| 场景 | 结果 | 证据文件 |",
            "| --- | --- | --- |",
        ]
        for o in outcomes:
            evidence_links = (
                "[%s](%s)（[claude](%s/claude_output.json) · "
                "[state前](%s/state_before.json) · [state后](%s/state_after.json) · "
                "[审计](%s/audit_delta.json) · [断言](%s/assertions.json)）"
                % (o.evidence_relpath, o.evidence_relpath, o.slug, o.slug, o.slug, o.slug, o.slug)
            )
            lines.append("| %s | %s | %s |" % (o.title, o.status, evidence_links))

        lines.extend(["", "## 分场景详情", ""])
        for o in outcomes:
            lines.append("### %s — %s（%.2f s）" % (o.title, o.status, o.elapsed_seconds))
            lines.append("- 执行入口：`%s`" % " ".join(str(x) for x in o.claude_command))
            lines.append("- 审计新增条目：%d 条" % len(o.audit_new_entries))
            assertion_summary = ", ".join(
                "%s=%s" % (k, "PASS" if v else "FAIL") for k, v in o.assertions.items()
            )
            lines.append("- 断言明细：`%s`" % assertion_summary)
            for note in o.notes:
                lines.append("- 说明：%s" % note)
            lines.append("")

        results_path = run_dir / "results.md"
        results_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return results_path

    def run(self, *, dry_run=False):
        if dry_run:
            return self.print_dry_run()
        if not self.check_login():
            return 2
        client = self.check_hub()
        if client is None:
            return 3

        self.test_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = self.output_dir / stamp
        suffix = 1
        while run_dir.exists():
            suffix += 1
            run_dir = self.output_dir / ("%s-%d" % (stamp, suffix))
        run_dir.mkdir(parents=True, exist_ok=True)

        self.out("开始执行 AgentDeck 5 项真实会话验证 -> %s" % run_dir)
        runners = (
            lambda: self._run_scenario_1_approve(client),
            lambda: self._run_scenario_2_deny(client),
            lambda: self._run_scenario_3_high(client),
            lambda: self._run_scenario_4_critical(client),
            lambda: self._run_scenario_5_hub_down(client, run_dir),
        )
        outcomes = []
        for fn in runners:
            outcome = fn()
            self._write_scenario_evidence(run_dir, outcome)
            outcomes.append(outcome)
            self.out("  [%s] %s (%.2fs) -> %s" % (
                outcome.status, outcome.title, outcome.elapsed_seconds, outcome.evidence_relpath))

        results_md = self._write_results_markdown(run_dir, run_dir.name, outcomes)
        passed = sum(1 for o in outcomes if o.status == "通过")
        self.out("验证完成：%d/%d 通过，报告已写入 %s" % (passed, len(outcomes), results_md))
        return 0 if passed == len(outcomes) else 1


def main(argv=None, *, runner=None, spawner=None, sleep=time.sleep, out=None, python_executable=None):
    if out is None:
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        out = print

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hub-port", "--port", dest="hub_port", type=int, default=DEFAULT_HUB_PORT,
                        help="running AgentDeck Hub port (default: 47800)")
    parser.add_argument("--test-dir", type=Path, default=DEFAULT_TEST_DIR,
                        help="isolated test directory (default: D:/desk/hardware/h1/agentdeck-test)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help="directory under which <timestamp>/results.md is written")
    parser.add_argument("--home", type=Path, help="home directory containing .agentdeck/token (read-only)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_SCENARIO_TIMEOUT,
                        help="per-scenario timeout in seconds (default: 180)")
    parser.add_argument("--dead-port", type=int, default=0,
                        help="optional unused port for scenario 5 offline degradation check")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what each scenario will send without invoking claude or Hub")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if not 1 <= args.hub_port <= 65535:
        parser.error("--hub-port must be between 1 and 65535")

    verifier = RealSessionVerifier(
        test_dir=args.test_dir,
        output_dir=args.output_dir,
        hub_port=args.hub_port,
        home=args.home,
        scenario_timeout=args.timeout,
        dead_port=args.dead_port,
        runner=runner,
        spawner=spawner,
        sleep=sleep,
        out=out,
        python_executable=python_executable,
    )
    return verifier.run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
