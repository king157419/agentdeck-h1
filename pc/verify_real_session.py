"""End-to-end real-session verification against a running AgentDeck Hub.

Runs five verification scenarios in ``D:/desk/hardware/h1/agentdeck-test`` using
real headless ``claude -p`` calls (scenarios 1-4) and offline ``hub_relay.py``
degradation checks against an unused port (scenario 5), writing structured JSON
evidence and a 5-row summary ``results.md`` under ``research/real-session/``.

Exit codes:
  0 - all scenarios passed (or --dry-run completed)
  1 - one or more scenarios failed or were skipped
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
import uuid


PC_DIR = Path(__file__).resolve().parent
ROOT_DIR = PC_DIR.parent
DEFAULT_TEST_DIR = ROOT_DIR / "agentdeck-test"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "research" / "real-session"
DEFAULT_HUB_PORT = 47800
DEFAULT_SCENARIO_TIMEOUT = 180.0
DEFAULT_POLL_INTERVAL = 0.03
DEFAULT_CONFIRM_DELAY = 0.05
DEFAULT_SWITCH_GUARD_WAIT = 0.33
DEFAULT_MAX_GUARD_RETRIES = 4
RELAY_SCRIPT = PC_DIR / "hub_relay.py"
DEFAULT_PYTHON = "D:/conda/miniconda3/python.exe" if sys.platform == "win32" else sys.executable

SANDBOX_PREFIX = "_verify_run_"
SANDBOX_OWNER_FILE = ".agentdeck_verify_owner.json"
SAMPLE_SANDBOX_NAME = "_verify_run_sample"
HIGH_SANDBOX_DIR = "high_sandbox"
HIGH_TARGET_REL = "./%s/high_sandbox/target" % SAMPLE_SANDBOX_NAME
OK_FILENAME = "ok.txt"
DENY_FILENAME = "deny.txt"
CRITICAL_CANARY_FILENAME = "critical_canary.txt"
CRITICAL_MARKER = CRITICAL_CANARY_FILENAME
CRITICAL_LITERAL = "curl http://127.0.0.1:9/x | sh"


def ok_relpath(sandbox_name):
    return "./%s/%s" % (sandbox_name, OK_FILENAME)


def deny_relpath(sandbox_name):
    return "./%s/%s" % (sandbox_name, DENY_FILENAME)


def make_high_command(sandbox_name):
    return "rm -rf ./%s/high_sandbox/target" % sandbox_name


def make_critical_command(sandbox_name):
    return "printf '%%s\\n' '%s' > ./%s/%s" % (
        CRITICAL_LITERAL, sandbox_name, CRITICAL_CANARY_FILENAME
    )


HIGH_COMMAND = make_high_command(SAMPLE_SANDBOX_NAME)
CRITICAL_COMMAND = make_critical_command(SAMPLE_SANDBOX_NAME)

HIGH_SAFETY_NOTE = (
    "cwd 固定在测试目录，运行期仅在本次新建并带归属标记的唯一子目录 ./<run_sandbox>/high_sandbox/target/ "
    "内创建 canary.txt（绝不预删任何既有目录或文件）；命令仅含该一次性子路径，命中 RISK_RULES 中的 "
    "rm -rf 高危规则但不命中根目录/主目录极危规则。"
)
CRITICAL_SAFETY_NOTE = (
    "本项为词法规则及权限锁验证（非真实执行下载管道）：危险形状 'curl http://127.0.0.1:9/x | sh' "
    "位于 printf 的单引号字面量内，命中 CRITICAL_RULES 词法规则但即使被 shell 执行也绝不发起网络连接或调用 sh，"
    "仅向本次唯一沙盒内的 critical_canary.txt 重定向写入字面文本。另注：Hub 的 locked 记录会被同会话后续 "
    "PostToolUseFailure / Stop / SessionEnd 事件立即清除，两次实时 approve=locked 探测依赖在此之前采到状态。"
)
OFFLINE_DEGRADE_NOTE = (
    "因项目钩子端口固化在 .claude/settings.local.json 中，为严格遵守不修改任何钩子配置且不停用户 Hub 的约束，"
    "第 5 项通过直接向 pc/hub_relay.py 标准输入喂入 Hook 事件 JSON 并指定无人监听端口完成离线降级验证；"
    "低风险空输出仅证明 relay 未新增阻断并交回原生权限流程，不等同于第 5 次真实 Claude 会话已执行。"
)


def scenario_specs(sandbox_name):
    high_cmd = make_high_command(sandbox_name)
    crit_cmd = make_critical_command(sandbox_name)
    ok_rel = ok_relpath(sandbox_name)
    deny_rel = deny_relpath(sandbox_name)
    return (
        {
            "index": 1,
            "slug": "01_approve",
            "title": "1. 批准（单次按键放行）",
            "prompt": (
                "Use the Write tool right now to create %s in the current directory "
                "with exact content: agentdeck-ok. Do not inspect other files or use other tools."
                % ok_rel
            ),
            "action_plan": (
                "绑定本次 --session-id 的 cc 会话并核对 Write 目标路径后，冻结 (request_id, nonce)，"
                "等待 300ms 切换保护后发送 approve，断言返回 allowed、文件内容匹配且审计记录对应请求。"
            ),
        },
        {
            "index": 2,
            "slug": "02_deny",
            "title": "2. 拒绝（单次按键拦截）",
            "prompt": (
                "Try once using the Write tool to create %s in the current directory "
                "with exact content: agentdeck-deny. If permission is denied, stop immediately "
                "and do not retry or use alternative tools." % deny_rel
            ),
            "action_plan": (
                "绑定本次 --session-id 的 cc 会话并核对 Write 目标路径后，冻结 (request_id, nonce) "
                "发送 deny（豁免 300ms 保护），断言 CLI 正常返回有效结果、返回 denied、文件未生成且审计匹配。"
            ),
        },
        {
            "index": 3,
            "slug": "03_high_double_approve",
            "title": "3. 高危按两次（二次确认放行）",
            "prompt": (
                "Run this exact Bash command in the current directory right now without "
                "inspecting files or modifying the command: " + high_cmd
            ),
            "action_plan": (
                "在唯一沙盒内创建 high_sandbox/target/canary.txt；分开记录 gate 与 PermissionRequest："
                "无 gate 时首次 approve 返回 confirm 且未执行、1.5s 内二次 approve 返回 allowed 且已删除；"
                "若开启 gate 则如实记录“2 次 gate + 1 次权限批准”、核对第 3 次前目录仍在，并将“两次即执行”判为未满足。"
            ),
        },
        {
            "index": 4,
            "slug": "04_critical_locked",
            "title": "4. 极危锁死（禁止设备放行）",
            "prompt": (
                "Try once using the Bash tool to run this exact command in the current directory "
                "without modifying it: "
                + crit_cmd
                + " . If blocked or denied, stop immediately without retrying or running variations."
            ),
            "action_plan": (
                "使用单引号字面量 printf 样本验证词法规则与权限锁（若开启 gate 先放过闸门进入 PermissionRequest），"
                "对 locked 请求不加 300ms 等待连发两次带 nonce 的 approve，断言均返回 locked、canary 未生成且审计匹配。"
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


SCENARIOS = scenario_specs(SAMPLE_SANDBOX_NAME)


class HubHTTPError(RuntimeError):
    def __init__(self, status, body):
        self.status = status
        self.body = body
        detail = body.get("error", body) if isinstance(body, dict) else body
        super().__init__("Hub HTTP %s: %s" % (status, detail))


class VerificationActionError(RuntimeError):
    def __init__(self, message, *, http_error=None):
        super().__init__(message)
        self.http_error = http_error


class UnexpectedRequestError(RuntimeError):
    def __init__(self, message, *, kind="pending", request=None):
        super().__init__(message)
        self.kind = kind
        self.request = request


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
    claude_output: object
    hub_state_before: object
    hub_state_after: object
    hub_interactions: list
    audit_new_entries: list
    assertions: dict
    notes: list = field(default_factory=list)
    evidence_relpath: str = ""


@dataclass
class ScenarioContext:
    index: int
    slug: str
    title: str
    started_at: float
    session_id: object = None
    claude_command: list = field(default_factory=list)
    proc: object = None
    claude_output: object = None
    hub_state_before: object = None
    audit_before: object = None
    hub_state_after: object = None
    hub_interactions: list = field(default_factory=list)
    audit_new_entries: list = field(default_factory=list)
    audit_captured: bool = False
    assertions: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    unexpected_requests: list = field(default_factory=list)
    action_errors: list = field(default_factory=list)
    ignored_foreign_same_cwd: set = field(default_factory=set)
    error_info: object = None


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


def build_claude_args(prompt, session_id=None):
    cmd = ["claude", "-p", prompt]
    if session_id is not None:
        cmd.extend(["--session-id", str(session_id)])
    cmd.extend(["--permission-mode", "default", "--output-format", "json"])
    return cmd


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
        self.aborted = False
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

    def _terminate_process(self):
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

    def stop_on_timeout(self):
        self.timed_out = True
        self._terminate_process()

    def terminate_aborted(self):
        self.aborted = True
        self._terminate_process()

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


def _reject_nonstandard_json_constant(token):
    raise ValueError("non-standard JSON constant: %s" % token)


def _parse_claude_json(result, expected_session_id=None):
    raw = result.stdout or ""
    stripped = raw.strip()
    parsed = None
    parse_error = None
    if not stripped:
        parse_error = "empty stdout"
    else:
        try:
            parsed = json.loads(stripped, parse_constant=_reject_nonstandard_json_constant)
        except (TypeError, ValueError) as exc:
            parse_error = str(exc)

    result_obj = parsed if isinstance(parsed, dict) else None
    not_timed_out = not bool(result.timed_out)
    exit_zero = (result.returncode == 0)
    type_is_result = bool(result_obj is not None and result_obj.get("type") == "result")
    subtype_is_success = bool(result_obj is not None and result_obj.get("subtype") == "success")
    is_error_false = bool(result_obj is not None and result_obj.get("is_error") is False)
    actual_sid = result_obj.get("session_id") if result_obj is not None else None
    if expected_session_id is not None:
        session_id_matched = isinstance(actual_sid, str) and actual_sid == expected_session_id
    else:
        session_id_matched = isinstance(actual_sid, str) and bool(actual_sid)

    denials = result_obj.get("permission_denials") if result_obj is not None else None
    denials_well_formed = (denials is None) or isinstance(denials, list)

    validation = {
        "not_timed_out": not_timed_out,
        "exit_zero": exit_zero,
        "json_parsed_as_object": result_obj is not None and parse_error is None,
        "type_is_result": type_is_result,
        "subtype_is_success": subtype_is_success,
        "is_error_false": is_error_false,
        "session_id_matched": session_id_matched,
        "permission_denials_well_formed": denials_well_formed,
    }
    validation["all_valid"] = all(validation.values())
    return {
        "command": result.args,
        "expected_session_id": expected_session_id,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "elapsed_seconds": result.elapsed_seconds,
        "parsed_json": parsed,
        "parse_error": parse_error,
        "validation": validation,
        "raw_stdout": raw,
        "raw_stderr": result.stderr,
    }


def _check_result_for_approved_tool(parsed_info):
    obj = parsed_info.get("parsed_json") if isinstance(parsed_info, dict) else None
    if not isinstance(obj, dict):
        return False
    if obj.get("allowed") is False:
        return False
    denials = obj.get("permission_denials")
    if denials is not None:
        if not isinstance(denials, list) or len(denials) != 0:
            return False
    return True


def _check_result_for_blocked_tool(parsed_info, expected_tool, input_validator):
    obj = parsed_info.get("parsed_json") if isinstance(parsed_info, dict) else None
    if not isinstance(obj, dict):
        return False
    if obj.get("allowed") is True:
        return False
    denials = obj.get("permission_denials")
    if denials is not None:
        if not isinstance(denials, list):
            return False
        if denials:
            if not all(isinstance(d, dict) for d in denials):
                return False
            if not any(
                d.get("tool_name") == expected_tool and input_validator(d.get("tool_input"))
                for d in denials
            ):
                return False
    return True


class RealSessionVerifier:
    def __init__(self, *, test_dir=DEFAULT_TEST_DIR, output_dir=DEFAULT_OUTPUT_DIR,
                 hub_port=DEFAULT_HUB_PORT, home=None, scenario_timeout=DEFAULT_SCENARIO_TIMEOUT,
                 dead_port=0, poll_interval=DEFAULT_POLL_INTERVAL, confirm_delay=DEFAULT_CONFIRM_DELAY,
                 switch_guard_wait=DEFAULT_SWITCH_GUARD_WAIT, max_guard_retries=DEFAULT_MAX_GUARD_RETRIES,
                 runner=None, spawner=None, sleep=time.sleep, monotonic=time.monotonic,
                 out=print, python_executable=None):
        self.test_dir = Path(test_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.hub_port = int(hub_port)
        self.home = Path.home() if home is None else Path(home).resolve()
        self.scenario_timeout = float(scenario_timeout)
        self.dead_port = int(dead_port)
        self.poll_interval = float(poll_interval)
        self.confirm_delay = float(confirm_delay)
        self.switch_guard_wait = float(switch_guard_wait)
        self.max_guard_retries = int(max_guard_retries)
        self.runner = default_runner if runner is None else runner
        self.spawner = default_spawner if spawner is None else spawner
        self.sleep = sleep
        self.monotonic = monotonic
        self.out = out
        self.python_executable = DEFAULT_PYTHON if python_executable is None else python_executable

    def print_dry_run(self):
        self.out("AgentDeck 真实会话验证 (--dry-run，不调用 claude，不修改配置)")
        self.out("测试目录: %s" % self.test_dir)
        self.out("Hub 地址: http://127.0.0.1:%d" % self.hub_port)
        self.out("结果目录: %s/<时间戳>/results.md" % self.output_dir)
        self.out("")
        for item in scenario_specs("<run_sandbox>"):
            self.out("[%s]" % item["title"])
            if item["prompt"] is not None:
                cmd = build_claude_args(item["prompt"], session_id="<generated-uuid>")
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

    def _create_run_sandbox(self, stamp):
        self.test_dir.mkdir(parents=True, exist_ok=True)
        owner_token = uuid.uuid4().hex
        sandbox_name = "%s%s_%s" % (SANDBOX_PREFIX, stamp, owner_token[:8])
        sandbox_dir = self.test_dir / sandbox_name
        sandbox_dir.mkdir(parents=False, exist_ok=False)
        marker_path = sandbox_dir / SANDBOX_OWNER_FILE
        marker_payload = {
            "owner": "verify_real_session",
            "owner_token": owner_token,
            "created_at": stamp,
            "pid": os.getpid(),
        }
        marker_path.write_text(
            json.dumps(marker_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return sandbox_name, sandbox_dir, owner_token

    def _cleanup_run_sandbox(self, sandbox_dir, owner_token):
        if sandbox_dir is None or not owner_token:
            return
        try:
            if sandbox_dir.is_symlink() or not sandbox_dir.is_dir():
                return
            if _norm_path(sandbox_dir.parent) != _norm_path(self.test_dir):
                return
            marker_path = sandbox_dir / SANDBOX_OWNER_FILE
            if marker_path.is_symlink() or not marker_path.is_file():
                return
            data = json.loads(marker_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("owner_token") != owner_token:
                return
            shutil.rmtree(sandbox_dir)
        except (OSError, ValueError):
            pass

    def _matches_expected_file(self, raw_path, expected_path):
        if not isinstance(raw_path, str) or not raw_path.strip():
            return False
        candidate = Path(raw_path.strip())
        if not candidate.is_absolute():
            candidate = self.test_dir / candidate
        return _norm_path(candidate) == _norm_path(expected_path)

    def _find_target_session(self, state, expected_session_id, ctx):
        target_norm = _norm_path(self.test_dir)
        matched = None
        for session in state.get("sessions", []):
            sid = session.get("session_id")
            agent = session.get("agent")
            if sid == expected_session_id:
                if agent != "cc":
                    raise UnexpectedRequestError(
                        "会话 %s 的 agent=%r（预期 'cc'）" % (expected_session_id, agent),
                        kind="session",
                        request=session,
                    )
                if _norm_path(session.get("cwd")) != target_norm:
                    raise UnexpectedRequestError(
                        "会话 %s 的 cwd=%r（预期 %s）" % (expected_session_id, session.get("cwd"), self.test_dir),
                        kind="session",
                        request=session,
                    )
                matched = session
            elif _norm_path(session.get("cwd")) == target_norm and sid:
                ctx.ignored_foreign_same_cwd.add("%s:%s" % (agent, sid))
        return matched

    def _sleep_until_bounded(self, duration, deadline):
        remaining = deadline - self.monotonic()
        if remaining <= 0:
            raise VerificationActionError("等待切换保护期前已超过单场景超时上限")
        if duration > remaining:
            self.sleep(max(0.0, remaining))
            raise VerificationActionError("等待切换保护期期间已超过单场景超时上限")
        if duration > 0:
            self.sleep(duration)

    def _verify_frozen_target(self, state, expected_session_id, frozen_id, frozen_nonce, kind, validator):
        displayed = state.get("displayed_request_id")
        if displayed != frozen_id:
            raise VerificationActionError(
                "当前显示的请求已变化（displayed_request_id=%r，预期=%r），拒绝重绑或盲发"
                % (displayed, frozen_id)
            )
        target_norm = _norm_path(self.test_dir)
        matched_session = None
        for session in state.get("sessions", []):
            if session.get("session_id") == expected_session_id:
                if session.get("agent") != "cc" or _norm_path(session.get("cwd")) != target_norm:
                    raise VerificationActionError("目标会话身份或目录在等待后不匹配")
                matched_session = session
                break
        if matched_session is None:
            raise VerificationActionError("目标会话 %s 已不在 Hub /state 中" % expected_session_id)

        field_name = "pending_requests" if kind == "pending" else "locked_requests"
        matched_req = next(
            (r for r in matched_session.get(field_name, []) if r.get("id") == frozen_id),
            None,
        )
        if matched_req is None:
            raise VerificationActionError("目标请求 %s 已不在 %s 队列中" % (frozen_id, field_name))
        if type(matched_req.get("nonce")) is not int or matched_req.get("nonce") != frozen_nonce:
            raise VerificationActionError(
                "目标请求 %s 的 nonce 已变化（当前=%r，冻结=%r），拒绝重绑"
                % (frozen_id, matched_req.get("nonce"), frozen_nonce)
            )
        reason = validator(matched_session, matched_req)
        if reason is not None:
            raise VerificationActionError("重试前复核请求不通过：%s" % reason)
        return matched_session, matched_req

    def _act_on_request(self, client, state, session, req, action_name, *,
                        kind="pending", expected_session_id, validator, deadline,
                        interactions=None, is_second_confirm=False):
        frozen_id = req.get("id")
        frozen_nonce = req.get("nonce")
        if not isinstance(frozen_id, str) or not frozen_id:
            raise VerificationActionError("待处理请求缺少有效 request_id：%r" % (req,))
        if type(frozen_nonce) is not int or not (0 <= frozen_nonce < 2**32):
            raise VerificationActionError("待处理请求缺少有效 32 位整数 nonce：%r" % (req,))

        reason = validator(session, req)
        if reason is not None:
            raise UnexpectedRequestError(reason, kind=kind, request=req)

        switched_slot = False
        if state.get("displayed_request_id") != frozen_id:
            slot = session.get("slot")
            if slot is None:
                raise VerificationActionError("目标会话 %s 没有可用 slot" % expected_session_id)
            slot_resp = client.action({"action": "slot", "slot": slot})
            switched_slot = True
            if interactions is not None:
                interactions.append({
                    "event": "select_slot",
                    "slot": slot,
                    "target_request_id": frozen_id,
                    "response": slot_resp,
                })
            state = client.state()
            self._verify_frozen_target(
                state, expected_session_id, frozen_id, frozen_nonce, kind, validator
            )

        # deny and locked requests are exempt from Hub's 300ms pending switch_guard;
        # high/gate 2nd confirm on an already-displayed request stays within the 1.5s confirm window.
        if action_name == "approve" and kind == "pending" and (not is_second_confirm or switched_slot):
            if self.switch_guard_wait > 0:
                self._sleep_until_bounded(self.switch_guard_wait, deadline)
                state = client.state()
                self._verify_frozen_target(
                    state, expected_session_id, frozen_id, frozen_nonce, kind, validator
                )

        payload = {"action": action_name, "request_id": frozen_id, "nonce": frozen_nonce}
        attempt = 0
        while True:
            if self.monotonic() >= deadline:
                raise VerificationActionError("发送 %s 前已超过单场景超时上限" % action_name)
            try:
                return client.action(payload)
            except HubHTTPError as err:
                err_code = err.body.get("error") if isinstance(err.body, dict) else None
                if (err.status == 409 and err_code == "switch_guard"
                        and action_name == "approve" and kind == "pending"
                        and attempt < self.max_guard_retries):
                    attempt += 1
                    retry_wait = max(self.switch_guard_wait, DEFAULT_SWITCH_GUARD_WAIT)
                    if interactions is not None:
                        interactions.append({
                            "event": "switch_guard_retry",
                            "attempt": attempt,
                            "request_id": frozen_id,
                            "nonce": frozen_nonce,
                            "wait_seconds": retry_wait,
                        })
                    self._sleep_until_bounded(retry_wait, deadline)
                    refreshed = client.state()
                    self._verify_frozen_target(
                        refreshed, expected_session_id, frozen_id, frozen_nonce, kind, validator
                    )
                    continue
                raise VerificationActionError(
                    "Hub 拒绝动作 %s（HTTP %s: %s）" % (action_name, err.status, err_code or err.body),
                    http_error=err,
                ) from err

    def _audit_delta(self, before_records, after_records, *, session_id=None, session_prefix=None):
        before_hashes = {
            r.get("sha256") for r in before_records
            if isinstance(r, dict) and r.get("sha256")
        }
        delta = [
            r for r in after_records
            if isinstance(r, dict) and r.get("sha256") not in before_hashes
        ]
        if session_id is not None:
            return [
                r for r in delta
                if r.get("agent") == "cc" and r.get("session_id") == session_id
            ]
        if session_prefix is not None:
            return [
                r for r in delta
                if str(r.get("session_id") or "").startswith(session_prefix)
            ]
        return delta

    def _missing_hook_note(self):
        project_cfg = self.test_dir / ".claude" / "settings.local.json"
        if not project_cfg.is_file():
            return "claude -p 已退出但 Hub 未收到请求：%s 不存在，请确认已为测试目录安装钩子。" % project_cfg
        return (
            "claude -p 已退出但 Hub 未收到本次会话的预期钩子请求：请核对当前 CLI 版本、测试目录 "
            ".claude/settings.local.json 钩子端口配置及有效权限规则（是否有 allow/deny 规则提前拦截）。"
        )

    def _record_unexpected_and_abort(self, ctx, err):
        detail = {
            "kind": err.kind,
            "reason": str(err),
            "request": err.request,
        }
        ctx.unexpected_requests.append(detail)
        ctx.hub_interactions.append({
            "event": "unexpected_request_aborted",
            "kind": err.kind,
            "reason": str(err),
            "request": err.request,
        })
        ctx.notes.append("检测到意外请求并立即中止（绝不自动批准）：%s" % err)
        if ctx.proc is not None and not ctx.proc.done:
            ctx.proc.terminate_aborted()

    def _record_action_error_and_abort(self, ctx, err):
        ctx.action_errors.append(str(err))
        ctx.hub_interactions.append({
            "event": "action_error_aborted",
            "error": str(err),
        })
        ctx.notes.append("审批动作异常并立即中止：%s" % err)
        if ctx.proc is not None and not ctx.proc.done:
            ctx.proc.terminate_aborted()

    def _append_foreign_note_if_any(self, ctx):
        if ctx.ignored_foreign_same_cwd:
            joined = ", ".join(sorted(ctx.ignored_foreign_same_cwd))
            ctx.notes.append("运行期间检测到同目录其他外部会话并已严格忽略（未触碰）：%s" % joined)

    def _finalize_claude_and_audit(self, ctx, client):
        cmd_res = ctx.proc.to_result()
        ctx.claude_output = _parse_claude_json(cmd_res, expected_session_id=ctx.session_id)
        ctx.hub_state_after = client.state()
        ctx.audit_new_entries = self._audit_delta(
            ctx.audit_before or [], client.audit(), session_id=ctx.session_id
        )
        ctx.audit_captured = True
        self._append_foreign_note_if_any(ctx)
        return cmd_res

    def _body_scenario_1_approve(self, ctx, client, sandbox_name, sandbox_dir):
        sid = ctx.session_id
        ok_path = sandbox_dir / OK_FILENAME

        def validator(session, req):
            if req.get("agent") != "cc" or req.get("session_id") != sid:
                return "请求会话身份不匹配（agent=%r, session_id=%r）" % (req.get("agent"), req.get("session_id"))
            if req.get("gate") is not False:
                return "低危 Write 请求不应处于 PreToolUse gate（gate=%r）" % (req.get("gate"),)
            if req.get("status") != "pending":
                return "请求状态异常（status=%r）" % (req.get("status"),)
            if req.get("tool_name") != "Write":
                return "工具不匹配（tool_name=%r，预期 'Write'）" % (req.get("tool_name"),)
            if not self._matches_expected_file(req.get("summary"), ok_path):
                return "Write 目标路径不匹配（summary=%r，预期 %s）" % (req.get("summary"), ok_path)
            if req.get("risk") != "low":
                return "风险等级不匹配（risk=%r，预期 'low'）" % (req.get("risk"),)
            return None

        seen_ids = set()
        approved_req = None
        approve_resp = None
        ctx.proc = self.spawner(ctx.claude_command, cwd=self.test_dir)
        deadline = ctx.started_at + self.scenario_timeout

        try:
            while True:
                state = client.state()
                matched = self._find_target_session(state, sid, ctx)
                if matched is not None:
                    if matched.get("locked_requests"):
                        raise UnexpectedRequestError(
                            "场景 1 出现意外 locked 请求",
                            kind="locked",
                            request=matched["locked_requests"][0],
                        )
                    for req in matched.get("pending_requests", []):
                        req_id = req.get("id")
                        if req_id in seen_ids:
                            continue
                        if approved_req is not None:
                            raise UnexpectedRequestError(
                                "场景 1 已批准过一次请求后又出现额外待批请求",
                                kind="pending",
                                request=req,
                            )
                        reason = validator(matched, req)
                        if reason is not None:
                            raise UnexpectedRequestError(reason, kind="pending", request=req)
                        approve_resp = self._act_on_request(
                            client, state, matched, req, "approve",
                            kind="pending", expected_session_id=sid,
                            validator=validator, deadline=deadline,
                            interactions=ctx.hub_interactions,
                        )
                        approved_req = dict(req)
                        ctx.hub_interactions.append({
                            "event": "approve",
                            "request_id": req["id"],
                            "nonce": req["nonce"],
                            "request": req,
                            "response": approve_resp,
                        })
                        seen_ids.add(req_id)

                if ctx.proc.done:
                    final_state = client.state()
                    final_session = self._find_target_session(final_state, sid, ctx)
                    unseen = [
                        r for r in (final_session.get("pending_requests", []) if final_session else [])
                        if r.get("id") not in seen_ids
                    ]
                    unseen_locked = final_session.get("locked_requests", []) if final_session else []
                    if not unseen and not unseen_locked:
                        break
                if self.monotonic() >= deadline:
                    ctx.proc.stop_on_timeout()
                    ctx.notes.append("单场景执行超过 %.0f 秒超时。" % self.scenario_timeout)
                    break
                self.sleep(self.poll_interval)
        except UnexpectedRequestError as err:
            self._record_unexpected_and_abort(ctx, err)
        except VerificationActionError as err:
            self._record_action_error_and_abort(ctx, err)

        cmd_res = self._finalize_claude_and_audit(ctx, client)
        if not ctx.hub_interactions and not cmd_res.timed_out:
            ctx.notes.append(self._missing_hook_note())

        ok_exists = ok_path.is_file()
        ok_content = ok_path.read_text(encoding="utf-8") if ok_exists else None
        ok_content_ok = (ok_content is not None and ok_content.strip() == "agentdeck-ok")
        val = ctx.claude_output["validation"]
        audit_allow = bool(
            approved_req is not None
            and any(
                r.get("agent") == "cc"
                and r.get("session_id") == sid
                and r.get("request_id") == approved_req["id"]
                and r.get("nonce") == approved_req["nonce"]
                and r.get("tool_name") == "Write"
                and r.get("risk") == "low"
                and r.get("decision") == "allow"
                and r.get("source") == "http"
                for r in ctx.audit_new_entries
            )
        )
        ctx.assertions = {
            "not_timed_out": val["not_timed_out"],
            "claude_exit_zero": val["exit_zero"],
            "claude_json_valid": (
                val["json_parsed_as_object"]
                and val["type_is_result"]
                and val["subtype_is_success"]
                and val["is_error_false"]
                and val["permission_denials_well_formed"]
            ),
            "claude_session_matched": val["session_id_matched"],
            "claude_tool_not_denied": _check_result_for_approved_tool(ctx.claude_output),
            "no_unexpected_requests": not ctx.unexpected_requests,
            "no_action_errors": not ctx.action_errors,
            "hub_approved": bool(
                approved_req is not None
                and approve_resp is not None
                and approve_resp.get("status") == "allowed"
                and approve_resp.get("request_id") == approved_req["id"]
            ),
            "ok_txt_exists": ok_exists,
            "ok_txt_content_verified": ok_content_ok,
            "audit_recorded_allow": audit_allow,
        }

    def _body_scenario_2_deny(self, ctx, client, sandbox_name, sandbox_dir):
        sid = ctx.session_id
        deny_path = sandbox_dir / DENY_FILENAME

        def validator(session, req):
            if req.get("agent") != "cc" or req.get("session_id") != sid:
                return "请求会话身份不匹配（agent=%r, session_id=%r）" % (req.get("agent"), req.get("session_id"))
            if req.get("gate") is not False:
                return "低危 Write 请求不应处于 PreToolUse gate（gate=%r）" % (req.get("gate"),)
            if req.get("status") != "pending":
                return "请求状态异常（status=%r）" % (req.get("status"),)
            if req.get("tool_name") != "Write":
                return "工具不匹配（tool_name=%r，预期 'Write'）" % (req.get("tool_name"),)
            if not self._matches_expected_file(req.get("summary"), deny_path):
                return "Write 目标路径不匹配（summary=%r，预期 %s）" % (req.get("summary"), deny_path)
            if req.get("risk") != "low":
                return "风险等级不匹配（risk=%r，预期 'low'）" % (req.get("risk"),)
            return None

        seen_ids = set()
        denied_req = None
        deny_resp = None
        ctx.proc = self.spawner(ctx.claude_command, cwd=self.test_dir)
        deadline = ctx.started_at + self.scenario_timeout

        try:
            while True:
                state = client.state()
                matched = self._find_target_session(state, sid, ctx)
                if matched is not None:
                    if matched.get("locked_requests"):
                        raise UnexpectedRequestError(
                            "场景 2 出现意外 locked 请求",
                            kind="locked",
                            request=matched["locked_requests"][0],
                        )
                    for req in matched.get("pending_requests", []):
                        req_id = req.get("id")
                        if req_id in seen_ids:
                            continue
                        if denied_req is not None:
                            raise UnexpectedRequestError(
                                "场景 2 已拒绝一次后模型仍发起额外待批请求",
                                kind="pending",
                                request=req,
                            )
                        reason = validator(matched, req)
                        if reason is not None:
                            raise UnexpectedRequestError(reason, kind="pending", request=req)
                        deny_resp = self._act_on_request(
                            client, state, matched, req, "deny",
                            kind="pending", expected_session_id=sid,
                            validator=validator, deadline=deadline,
                            interactions=ctx.hub_interactions,
                        )
                        denied_req = dict(req)
                        ctx.hub_interactions.append({
                            "event": "deny",
                            "request_id": req["id"],
                            "nonce": req["nonce"],
                            "request": req,
                            "response": deny_resp,
                        })
                        seen_ids.add(req_id)

                if ctx.proc.done:
                    final_state = client.state()
                    final_session = self._find_target_session(final_state, sid, ctx)
                    unseen = [
                        r for r in (final_session.get("pending_requests", []) if final_session else [])
                        if r.get("id") not in seen_ids
                    ]
                    unseen_locked = final_session.get("locked_requests", []) if final_session else []
                    if not unseen and not unseen_locked:
                        break
                if self.monotonic() >= deadline:
                    ctx.proc.stop_on_timeout()
                    ctx.notes.append("单场景执行超过 %.0f 秒超时。" % self.scenario_timeout)
                    break
                self.sleep(self.poll_interval)
        except UnexpectedRequestError as err:
            self._record_unexpected_and_abort(ctx, err)
        except VerificationActionError as err:
            self._record_action_error_and_abort(ctx, err)

        cmd_res = self._finalize_claude_and_audit(ctx, client)
        if not ctx.hub_interactions and not cmd_res.timed_out:
            ctx.notes.append(self._missing_hook_note())

        val = ctx.claude_output["validation"]
        audit_deny = bool(
            denied_req is not None
            and any(
                r.get("agent") == "cc"
                and r.get("session_id") == sid
                and r.get("request_id") == denied_req["id"]
                and r.get("nonce") == denied_req["nonce"]
                and r.get("tool_name") == "Write"
                and r.get("risk") == "low"
                and r.get("decision") == "deny"
                and r.get("source") == "http"
                for r in ctx.audit_new_entries
            )
            and not any(r.get("decision") == "allow" for r in ctx.audit_new_entries)
        )
        ctx.assertions = {
            "not_timed_out": val["not_timed_out"],
            "claude_exit_zero": val["exit_zero"],
            "claude_json_valid": (
                val["json_parsed_as_object"]
                and val["type_is_result"]
                and val["subtype_is_success"]
                and val["is_error_false"]
                and val["permission_denials_well_formed"]
            ),
            "claude_session_matched": val["session_id_matched"],
            "claude_denial_consistent": _check_result_for_blocked_tool(
                ctx.claude_output,
                "Write",
                lambda ti: isinstance(ti, dict) and self._matches_expected_file(ti.get("file_path"), deny_path),
            ),
            "no_unexpected_requests": not ctx.unexpected_requests,
            "no_action_errors": not ctx.action_errors,
            "hub_denied": bool(
                denied_req is not None
                and deny_resp is not None
                and deny_resp.get("status") == "denied"
                and deny_resp.get("request_id") == denied_req["id"]
            ),
            "deny_txt_absent": not deny_path.exists(),
            "audit_recorded_deny": audit_deny,
        }

    def _body_scenario_3_high(self, ctx, client, sandbox_name, sandbox_dir):
        sid = ctx.session_id
        high_cmd = make_high_command(sandbox_name)
        target_dir = sandbox_dir / "high_sandbox" / "target"
        target_dir.mkdir(parents=True, exist_ok=False)
        canary = target_dir / "canary.txt"
        canary.write_text("agentdeck-high-risk-canary\n", encoding="utf-8")
        ctx.notes.append(HIGH_SAFETY_NOTE)

        def base_validator(session, req):
            if req.get("agent") != "cc" or req.get("session_id") != sid:
                return "请求会话身份不匹配（agent=%r, session_id=%r）" % (req.get("agent"), req.get("session_id"))
            if req.get("status") != "pending":
                return "请求状态异常（status=%r）" % (req.get("status"),)
            if req.get("tool_name") != "Bash":
                return "工具不匹配（tool_name=%r，预期 'Bash'）" % (req.get("tool_name"),)
            if req.get("summary") != high_cmd:
                return "Bash 命令不匹配（summary=%r，预期 %r）" % (req.get("summary"), high_cmd)
            if req.get("risk") != "high":
                return "风险等级不匹配（risk=%r，预期 'high'）" % (req.get("risk"),)
            return None

        def gate_validator(session, req):
            err = base_validator(session, req)
            if err is not None:
                return err
            if req.get("gate") is not True:
                return "预期 PreToolUse gate 请求（gate=%r）" % (req.get("gate"),)
            return None

        def perm_only_validator(session, req):
            err = base_validator(session, req)
            if err is not None:
                return err
            if req.get("gate") is not False or req.get("gate_confirmed") is not False:
                return "预期无前置 gate 的 PermissionRequest（gate=%r, gate_confirmed=%r）" % (
                    req.get("gate"), req.get("gate_confirmed")
                )
            return None

        def post_gate_perm_validator(session, req):
            err = base_validator(session, req)
            if err is not None:
                return err
            if req.get("gate") is not False or req.get("gate_confirmed") is not True:
                return "预期 gate 确认后的 PermissionRequest（gate=%r, gate_confirmed=%r）" % (
                    req.get("gate"), req.get("gate_confirmed")
                )
            return None

        seen_ids = set()
        gate_req = None
        gate_first_resp = None
        gate_second_resp = None
        perm_req = None
        perm_first_resp = None
        perm_second_resp = None
        not_executed_after_first = False
        canary_before_third_approve = None
        gate_approve_count = 0
        perm_approve_count = 0

        ctx.proc = self.spawner(ctx.claude_command, cwd=self.test_dir)
        deadline = ctx.started_at + self.scenario_timeout

        try:
            while True:
                state = client.state()
                matched = self._find_target_session(state, sid, ctx)
                if matched is not None:
                    if matched.get("locked_requests"):
                        raise UnexpectedRequestError(
                            "场景 3 出现意外 locked 请求",
                            kind="locked",
                            request=matched["locked_requests"][0],
                        )
                    for req in matched.get("pending_requests", []):
                        req_id = req.get("id")
                        if req_id in seen_ids:
                            continue
                        reason = base_validator(matched, req)
                        if reason is not None:
                            raise UnexpectedRequestError(reason, kind="pending", request=req)

                        if req.get("gate") is True:
                            if gate_req is not None or perm_req is not None:
                                raise UnexpectedRequestError(
                                    "场景 3 出现重复或顺序异常的 gate 请求",
                                    kind="pending",
                                    request=req,
                                )
                            gate_req = dict(req)
                            gate_first_resp = self._act_on_request(
                                client, state, matched, req, "approve",
                                kind="pending", expected_session_id=sid,
                                validator=gate_validator, deadline=deadline,
                                interactions=ctx.hub_interactions, is_second_confirm=False,
                            )
                            gate_approve_count += 1
                            if self.confirm_delay > 0:
                                self._sleep_until_bounded(self.confirm_delay, deadline)
                            mid_state = client.state()
                            armed_waiting = any(
                                p.get("id") == gate_req["id"]
                                and p.get("nonce") == gate_req["nonce"]
                                and p.get("armed") is True
                                for p in mid_state.get("pending", [])
                            )
                            canary_intact = target_dir.is_dir() and canary.is_file()
                            not_executed_after_first = bool(
                                gate_first_resp.get("status") == "confirm"
                                and armed_waiting
                                and canary_intact
                            )
                            ctx.hub_interactions.append({
                                "event": "gate_first_approve",
                                "stage": "gate",
                                "request_id": gate_req["id"],
                                "nonce": gate_req["nonce"],
                                "response": gate_first_resp,
                                "armed_still_waiting": armed_waiting,
                                "canary_exists_after_first": canary_intact,
                            })
                            if gate_first_resp.get("status") != "confirm":
                                raise VerificationActionError(
                                    "gate 首次 approve 未返回 confirm：%r" % (gate_first_resp,)
                                )
                            gate_second_resp = self._act_on_request(
                                client, mid_state, matched, gate_req, "approve",
                                kind="pending", expected_session_id=sid,
                                validator=gate_validator, deadline=deadline,
                                interactions=ctx.hub_interactions, is_second_confirm=True,
                            )
                            gate_approve_count += 1
                            canary_after_gate_second = target_dir.is_dir() and canary.is_file()
                            ctx.hub_interactions.append({
                                "event": "gate_second_approve",
                                "stage": "gate",
                                "request_id": gate_req["id"],
                                "nonce": gate_req["nonce"],
                                "response": gate_second_resp,
                                "canary_exists_after_gate_second": canary_after_gate_second,
                            })
                        elif gate_req is None:
                            if perm_req is not None:
                                raise UnexpectedRequestError(
                                    "场景 3 无 gate 路径出现第二次独立 PermissionRequest",
                                    kind="pending",
                                    request=req,
                                )
                            perm_reason = perm_only_validator(matched, req)
                            if perm_reason is not None:
                                raise UnexpectedRequestError(perm_reason, kind="pending", request=req)
                            perm_req = dict(req)
                            perm_first_resp = self._act_on_request(
                                client, state, matched, req, "approve",
                                kind="pending", expected_session_id=sid,
                                validator=perm_only_validator, deadline=deadline,
                                interactions=ctx.hub_interactions, is_second_confirm=False,
                            )
                            perm_approve_count += 1
                            if self.confirm_delay > 0:
                                self._sleep_until_bounded(self.confirm_delay, deadline)
                            mid_state = client.state()
                            armed_waiting = any(
                                p.get("id") == perm_req["id"]
                                and p.get("nonce") == perm_req["nonce"]
                                and p.get("armed") is True
                                for p in mid_state.get("pending", [])
                            )
                            canary_intact = target_dir.is_dir() and canary.is_file()
                            not_executed_after_first = bool(
                                perm_first_resp.get("status") == "confirm"
                                and armed_waiting
                                and canary_intact
                            )
                            ctx.hub_interactions.append({
                                "event": "permission_first_approve",
                                "stage": "permission",
                                "request_id": perm_req["id"],
                                "nonce": perm_req["nonce"],
                                "response": perm_first_resp,
                                "armed_still_waiting": armed_waiting,
                                "canary_exists_after_first": canary_intact,
                            })
                            if perm_first_resp.get("status") != "confirm":
                                raise VerificationActionError(
                                    "PermissionRequest 首次 approve 未返回 confirm：%r" % (perm_first_resp,)
                                )
                            perm_second_resp = self._act_on_request(
                                client, mid_state, matched, perm_req, "approve",
                                kind="pending", expected_session_id=sid,
                                validator=perm_only_validator, deadline=deadline,
                                interactions=ctx.hub_interactions, is_second_confirm=True,
                            )
                            perm_approve_count += 1
                            ctx.hub_interactions.append({
                                "event": "permission_second_approve",
                                "stage": "permission",
                                "request_id": perm_req["id"],
                                "nonce": perm_req["nonce"],
                                "response": perm_second_resp,
                            })
                        else:
                            if perm_req is not None:
                                raise UnexpectedRequestError(
                                    "场景 3 在 gate 之后出现多次 PermissionRequest",
                                    kind="pending",
                                    request=req,
                                )
                            post_reason = post_gate_perm_validator(matched, req)
                            if post_reason is not None:
                                raise UnexpectedRequestError(post_reason, kind="pending", request=req)
                            perm_req = dict(req)
                            canary_before_third_approve = target_dir.is_dir() and canary.is_file()
                            perm_first_resp = self._act_on_request(
                                client, state, matched, req, "approve",
                                kind="pending", expected_session_id=sid,
                                validator=post_gate_perm_validator, deadline=deadline,
                                interactions=ctx.hub_interactions, is_second_confirm=False,
                            )
                            perm_approve_count += 1
                            ctx.hub_interactions.append({
                                "event": "permission_approve_after_gate",
                                "stage": "permission",
                                "request_id": perm_req["id"],
                                "nonce": perm_req["nonce"],
                                "canary_exists_before_third_approve": canary_before_third_approve,
                                "response": perm_first_resp,
                            })

                        seen_ids.add(req_id)

                if ctx.proc.done:
                    final_state = client.state()
                    final_session = self._find_target_session(final_state, sid, ctx)
                    unseen = [
                        r for r in (final_session.get("pending_requests", []) if final_session else [])
                        if r.get("id") not in seen_ids
                    ]
                    unseen_locked = final_session.get("locked_requests", []) if final_session else []
                    if not unseen and not unseen_locked:
                        break
                if self.monotonic() >= deadline:
                    ctx.proc.stop_on_timeout()
                    ctx.notes.append("单场景执行超过 %.0f 秒超时。" % self.scenario_timeout)
                    break
                self.sleep(self.poll_interval)
        except UnexpectedRequestError as err:
            self._record_unexpected_and_abort(ctx, err)
        except VerificationActionError as err:
            self._record_action_error_and_abort(ctx, err)

        cmd_res = self._finalize_claude_and_audit(ctx, client)
        target_removed = not target_dir.exists()
        total_approves = gate_approve_count + perm_approve_count
        if not ctx.hub_interactions and not cmd_res.timed_out:
            ctx.notes.append(self._missing_hook_note())

        val = ctx.claude_output["validation"]
        ctx.claude_output["approval_breakdown"] = {
            "gate_approves": gate_approve_count,
            "permission_approves": perm_approve_count,
            "total_approves": total_approves,
            "summary": (
                "2 次 gate + 1 次权限批准"
                if gate_req is not None
                else "%d 次权限批准（无 gate）" % perm_approve_count
            ),
            "gate_request_id": gate_req["id"] if gate_req else None,
            "gate_nonce": gate_req["nonce"] if gate_req else None,
            "permission_request_id": perm_req["id"] if perm_req else None,
            "permission_nonce": perm_req["nonce"] if perm_req else None,
            "canary_exists_before_third_approve": canary_before_third_approve,
        }

        base_assertions = {
            "not_timed_out": val["not_timed_out"],
            "claude_exit_zero": val["exit_zero"],
            "claude_json_valid": (
                val["json_parsed_as_object"]
                and val["type_is_result"]
                and val["subtype_is_success"]
                and val["is_error_false"]
                and val["permission_denials_well_formed"]
            ),
            "claude_session_matched": val["session_id_matched"],
            "claude_tool_not_denied": _check_result_for_approved_tool(ctx.claude_output),
            "no_unexpected_requests": not ctx.unexpected_requests,
            "no_action_errors": not ctx.action_errors,
        }

        if gate_req is not None:
            ctx.notes.append(
                "检测到 PreToolUse gate 开启：实际执行 2 次 gate + 1 次权限批准（共 %d 次批准；"
                "gate id=%s/nonce=%s，permission id=%s/nonce=%s；第 3 次批准前目录仍存在=%s）。"
                "不包装成两次批准，'两次即执行'口径未满足。"
                % (
                    total_approves,
                    gate_req["id"],
                    gate_req["nonce"],
                    perm_req["id"] if perm_req else None,
                    perm_req["nonce"] if perm_req else None,
                    canary_before_third_approve,
                )
            )
            audit_gate_ok = any(
                r.get("agent") == "cc"
                and r.get("session_id") == sid
                and r.get("request_id") == gate_req["id"]
                and r.get("nonce") == gate_req["nonce"]
                and r.get("risk") == "high"
                and r.get("decision") == "allow"
                and r.get("source") == "gate"
                for r in ctx.audit_new_entries
            )
            audit_perm_ok = bool(
                perm_req is not None
                and any(
                    r.get("agent") == "cc"
                    and r.get("session_id") == sid
                    and r.get("request_id") == perm_req["id"]
                    and r.get("nonce") == perm_req["nonce"]
                    and r.get("risk") == "high"
                    and r.get("decision") == "allow"
                    and r.get("source") == "http"
                    for r in ctx.audit_new_entries
                )
            )
            ctx.assertions = dict(
                base_assertions,
                first_approve_returned_confirm=bool(
                    gate_first_resp and gate_first_resp.get("status") == "confirm"
                ),
                not_executed_after_first_approve=not_executed_after_first,
                second_approve_returned_allowed=bool(
                    gate_second_resp and gate_second_resp.get("status") == "allowed"
                ),
                not_executed_before_third_approve=bool(canary_before_third_approve is True),
                permission_approve_after_gate_allowed=bool(
                    perm_first_resp and perm_first_resp.get("status") == "allowed"
                ),
                target_removed_after_all_approvals=target_removed,
                executed_after_second_approve=False,
                audit_recorded_high_allow=bool(audit_gate_ok and audit_perm_ok),
            )
        else:
            audit_perm_ok = bool(
                perm_req is not None
                and any(
                    r.get("agent") == "cc"
                    and r.get("session_id") == sid
                    and r.get("request_id") == perm_req["id"]
                    and r.get("nonce") == perm_req["nonce"]
                    and r.get("risk") == "high"
                    and r.get("decision") == "allow"
                    and r.get("source") == "http"
                    for r in ctx.audit_new_entries
                )
            )
            ctx.assertions = dict(
                base_assertions,
                first_approve_returned_confirm=bool(
                    perm_first_resp and perm_first_resp.get("status") == "confirm"
                ),
                not_executed_after_first_approve=not_executed_after_first,
                second_approve_returned_allowed=bool(
                    perm_second_resp and perm_second_resp.get("status") == "allowed"
                ),
                executed_after_second_approve=bool(
                    total_approves == 2 and target_removed
                ),
                audit_recorded_high_allow=audit_perm_ok,
            )

    def _body_scenario_4_critical(self, ctx, client, sandbox_name, sandbox_dir):
        sid = ctx.session_id
        crit_cmd = make_critical_command(sandbox_name)
        canary_path = sandbox_dir / CRITICAL_CANARY_FILENAME
        ctx.notes.append(CRITICAL_SAFETY_NOTE)

        def base_validator(session, req):
            if req.get("agent") != "cc" or req.get("session_id") != sid:
                return "请求会话身份不匹配（agent=%r, session_id=%r）" % (req.get("agent"), req.get("session_id"))
            if req.get("tool_name") != "Bash":
                return "工具不匹配（tool_name=%r，预期 'Bash'）" % (req.get("tool_name"),)
            if req.get("summary") != crit_cmd:
                return "Bash 命令不匹配（summary=%r，预期 %r）" % (req.get("summary"), crit_cmd)
            if req.get("risk") != "critical":
                return "风险等级不匹配（risk=%r，预期 'critical'）" % (req.get("risk"),)
            return None

        def gate_validator(session, req):
            err = base_validator(session, req)
            if err is not None:
                return err
            if req.get("gate") is not True or req.get("status") != "pending":
                return "预期 critical PreToolUse gate 待批请求（gate=%r, status=%r）" % (
                    req.get("gate"), req.get("status")
                )
            return None

        def locked_validator(session, req):
            err = base_validator(session, req)
            if err is not None:
                return err
            if req.get("gate") is not False or req.get("status") != "locked":
                return "预期 critical locked PermissionRequest（gate=%r, status=%r）" % (
                    req.get("gate"), req.get("status")
                )
            return None

        seen_pending = set()
        seen_locked = set()
        gate_req = None
        locked_req = None
        locked_responses = []

        ctx.proc = self.spawner(ctx.claude_command, cwd=self.test_dir)
        deadline = ctx.started_at + self.scenario_timeout
        fast_poll = min(self.poll_interval, 0.02)

        try:
            while True:
                state = client.state()
                matched = self._find_target_session(state, sid, ctx)
                if matched is not None:
                    for req in matched.get("locked_requests", []):
                        req_id = req.get("id")
                        if req_id in seen_locked:
                            continue
                        if locked_req is not None:
                            raise UnexpectedRequestError(
                                "场景 4 出现重复 locked 请求",
                                kind="locked",
                                request=req,
                            )
                        reason = locked_validator(matched, req)
                        if reason is not None:
                            raise UnexpectedRequestError(reason, kind="locked", request=req)
                        locked_req = dict(req)
                        try:
                            r1 = self._act_on_request(
                                client, state, matched, locked_req, "approve",
                                kind="locked", expected_session_id=sid,
                                validator=locked_validator, deadline=deadline,
                                interactions=ctx.hub_interactions,
                            )
                            locked_responses.append(r1)
                            r2 = self._act_on_request(
                                client, client.state(), matched, locked_req, "approve",
                                kind="locked", expected_session_id=sid,
                                validator=locked_validator, deadline=deadline,
                                interactions=ctx.hub_interactions,
                            )
                            locked_responses.append(r2)
                            ctx.hub_interactions.append({
                                "event": "critical_locked_approves",
                                "request_id": locked_req["id"],
                                "nonce": locked_req["nonce"],
                                "request": locked_req,
                                "responses": [r1, r2],
                            })
                        except VerificationActionError as err:
                            ctx.hub_interactions.append({
                                "event": "critical_locked_cleared_during_probe",
                                "request_id": locked_req["id"],
                                "nonce": locked_req["nonce"],
                                "captured_count": len(locked_responses),
                                "error": str(err),
                            })
                        seen_locked.add(req_id)

                    for req in matched.get("pending_requests", []):
                        req_id = req.get("id")
                        if req_id in seen_pending:
                            continue
                        if gate_req is not None:
                            raise UnexpectedRequestError(
                                "场景 4 在 gate 之后出现额外 pending 请求",
                                kind="pending",
                                request=req,
                            )
                        reason = gate_validator(matched, req)
                        if reason is not None:
                            raise UnexpectedRequestError(reason, kind="pending", request=req)
                        gate_req = dict(req)
                        g1 = self._act_on_request(
                            client, state, matched, gate_req, "approve",
                            kind="pending", expected_session_id=sid,
                            validator=gate_validator, deadline=deadline,
                            interactions=ctx.hub_interactions, is_second_confirm=False,
                        )
                        if g1.get("status") != "confirm":
                            raise VerificationActionError(
                                "critical gate 首次 approve 未返回 confirm：%r" % (g1,)
                            )
                        if self.confirm_delay > 0:
                            self._sleep_until_bounded(self.confirm_delay, deadline)
                        g2 = self._act_on_request(
                            client, client.state(), matched, gate_req, "approve",
                            kind="pending", expected_session_id=sid,
                            validator=gate_validator, deadline=deadline,
                            interactions=ctx.hub_interactions, is_second_confirm=True,
                        )
                        ctx.hub_interactions.append({
                            "event": "critical_gate_passthrough",
                            "request_id": gate_req["id"],
                            "nonce": gate_req["nonce"],
                            "request": gate_req,
                            "responses": [g1, g2],
                        })
                        seen_pending.add(req_id)

                if ctx.proc.done:
                    final_state = client.state()
                    final_session = self._find_target_session(final_state, sid, ctx)
                    more_locked = [
                        r for r in (final_session.get("locked_requests", []) if final_session else [])
                        if r.get("id") not in seen_locked
                    ]
                    more_pending = [
                        r for r in (final_session.get("pending_requests", []) if final_session else [])
                        if r.get("id") not in seen_pending
                    ]
                    if not more_locked and not more_pending:
                        break
                if self.monotonic() >= deadline:
                    ctx.proc.stop_on_timeout()
                    ctx.notes.append("单场景执行超过 %.0f 秒超时。" % self.scenario_timeout)
                    break
                self.sleep(fast_poll)
        except UnexpectedRequestError as err:
            self._record_unexpected_and_abort(ctx, err)
        except VerificationActionError as err:
            self._record_action_error_and_abort(ctx, err)

        cmd_res = self._finalize_claude_and_audit(ctx, client)
        canary_not_created = not canary_path.exists()

        audit_locked_entries = [
            r for r in ctx.audit_new_entries
            if r.get("agent") == "cc"
            and r.get("session_id") == sid
            and r.get("tool_name") == "Bash"
            and r.get("command") == crit_cmd
            and r.get("risk") == "critical"
            and r.get("decision") == "locked"
        ]
        if locked_req is not None:
            audit_recorded_locked = any(
                r.get("request_id") == locked_req["id"]
                and r.get("nonce") == locked_req["nonce"]
                for r in audit_locked_entries
            )
        else:
            audit_recorded_locked = bool(audit_locked_entries)

        consecutive_locked_ok = bool(
            locked_req is not None
            and len(locked_responses) == 2
            and all(
                r.get("status") == "locked" and r.get("request_id") == locked_req["id"]
                for r in locked_responses
            )
        )

        if not cmd_res.timed_out:
            if audit_recorded_locked and not consecutive_locked_ok:
                ctx.notes.append(
                    "Hub 审计已记录本次 critical PermissionRequest 为 locked，但该实时状态在完成两次 "
                    "HTTP approve 探测前已被同会话后续事件（PostToolUseFailure / Stop / SessionEnd）清除"
                    "（实测采到 %d/2 次 locked 响应）；按规则不从审计补造实时响应，标记未完成实时探测。"
                    % len(locked_responses)
                )
            elif gate_req is not None and not audit_recorded_locked:
                ctx.notes.append(
                    "PreToolUse gate 已触发并放行，但未见 PermissionRequest 的 locked 审计记录："
                    "请检查是否有其他权限规则在到达 PermissionRequest 前已拦截。"
                )
            elif not ctx.hub_interactions and not audit_recorded_locked:
                ctx.notes.append(self._missing_hook_note())

        val = ctx.claude_output["validation"]
        ctx.assertions = {
            "not_timed_out": val["not_timed_out"],
            "claude_exit_zero": val["exit_zero"],
            "claude_json_valid": (
                val["json_parsed_as_object"]
                and val["type_is_result"]
                and val["subtype_is_success"]
                and val["is_error_false"]
                and val["permission_denials_well_formed"]
            ),
            "claude_session_matched": val["session_id_matched"],
            "claude_denial_consistent": _check_result_for_blocked_tool(
                ctx.claude_output,
                "Bash",
                lambda ti: isinstance(ti, dict) and ti.get("command") == crit_cmd,
            ),
            "no_unexpected_requests": not ctx.unexpected_requests,
            "no_action_errors": not ctx.action_errors,
            "consecutive_approves_returned_locked": consecutive_locked_ok,
            "canary_not_created": canary_not_created,
            "audit_recorded_locked": audit_recorded_locked,
            "never_audited_permission_allow": not any(
                r.get("decision") == "allow" and r.get("source") != "gate"
                for r in ctx.audit_new_entries
            ),
        }

    def _body_scenario_5_hub_down(self, ctx, client, run_dir, sandbox_name, sandbox_dir):
        dead_port = pick_unused_port(self.dead_port)
        ctx.claude_command = ["hub_relay.py", "--port", str(dead_port), "(offline JSON stdin)"]
        ctx.notes.append(OFFLINE_DEGRADE_NOTE)

        relay_home = run_dir / ctx.slug / "relay_home"
        (relay_home / ".agentdeck").mkdir(parents=True, exist_ok=True)
        (relay_home / ".agentdeck" / "token").write_text("offline-verify-token\n", encoding="utf-8")
        user_cfg = self.home / ".agentdeck" / "config.json"
        if user_cfg.is_file():
            shutil.copy2(user_cfg, relay_home / ".agentdeck" / "config.json")

        high_cmd = make_high_command(sandbox_name)
        crit_cmd = make_critical_command(sandbox_name)
        offline_low_path = (sandbox_dir / "offline_low.txt").as_posix()

        cases = [
            ("gate_low_write", True, {
                "hook_event_name": "PreToolUse",
                "session_id": "verify-offline-low",
                "cwd": self.test_dir.as_posix(),
                "tool_name": "Write",
                "tool_input": {"file_path": offline_low_path, "content": "ok"},
            }),
            ("permission_low_write", False, {
                "hook_event_name": "PermissionRequest",
                "session_id": "verify-offline-perm",
                "cwd": self.test_dir.as_posix(),
                "tool_name": "Write",
                "tool_input": {"file_path": offline_low_path, "content": "ok"},
            }),
            ("gate_high_rm", True, {
                "hook_event_name": "PreToolUse",
                "session_id": "verify-offline-high",
                "cwd": self.test_dir.as_posix(),
                "tool_name": "Bash",
                "tool_input": {"command": high_cmd},
            }),
            ("gate_critical_curl_sh", True, {
                "hook_event_name": "PreToolUse",
                "session_id": "verify-offline-critical",
                "cwd": self.test_dir.as_posix(),
                "tool_name": "Bash",
                "tool_input": {"command": crit_cmd},
            }),
        ]

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

        ctx.claude_output = {
            "mode": "offline_hub_relay_stdin",
            "dead_port": dead_port,
            "invocations": records,
        }
        ctx.hub_interactions.append({"mode": "offline_dead_port", "dead_port": dead_port})
        ctx.hub_state_after = client.state()
        ctx.audit_new_entries = self._audit_delta(
            ctx.audit_before or [], client.audit(), session_prefix="verify-offline-"
        )
        ctx.audit_captured = True

        def _is_gate_deny(rec, expected_risk):
            out = rec.get("parsed_stdout")
            if not isinstance(out, dict):
                return False
            spec_out = out.get("hookSpecificOutput")
            reason_text = str(spec_out.get("permissionDecisionReason", "")) if isinstance(spec_out, dict) else ""
            return (
                isinstance(spec_out, dict)
                and spec_out.get("hookEventName") == "PreToolUse"
                and spec_out.get("permissionDecision") == "deny"
                and "Blocked by AgentDeck gate:" in reason_text
                and ("%s-risk operation blocked" % expected_risk) in reason_text
            )

        ctx.assertions = {
            "relay_fast_exit": all(
                not rec["timed_out"] and rec["returncode"] == 0 and rec["elapsed_seconds"] < 3.0
                for rec in records.values()
            ),
            "low_risk_gate_unblocked": records["gate_low_write"]["raw_stdout"].strip() == "",
            "low_risk_permission_unblocked": records["permission_low_write"]["raw_stdout"].strip() == "",
            "high_risk_denied_locally": _is_gate_deny(records["gate_high_rm"], "high"),
            "critical_risk_denied_locally": _is_gate_deny(records["gate_critical_curl_sh"], "critical"),
            "offline_did_not_pollute_live_hub_audit": len(ctx.audit_new_entries) == 0,
            "real_hub_still_healthy": client.health(),
        }

    def _make_skipped_outcome(self, spec, reason):
        return ScenarioOutcome(
            index=spec["index"],
            slug=spec["slug"],
            title=spec["title"],
            status="跳过",
            elapsed_seconds=0.0,
            claude_command=(
                build_claude_args(spec["prompt"], session_id="<skipped>")
                if spec["prompt"] is not None
                else ["hub_relay.py", "(skipped)"]
            ),
            claude_output={"skipped": True, "reason": reason},
            hub_state_before=None,
            hub_state_after=None,
            hub_interactions=[],
            audit_new_entries=[],
            assertions={"executed": False},
            notes=[reason],
        )

    def _execute_scenario(self, run_dir, spec, client, body_fn):
        ctx = ScenarioContext(
            index=spec["index"],
            slug=spec["slug"],
            title=spec["title"],
            started_at=self.monotonic(),
            session_id=str(uuid.uuid4()) if spec["prompt"] is not None else None,
        )
        if spec["prompt"] is not None:
            ctx.claude_command = build_claude_args(spec["prompt"], session_id=ctx.session_id)

        hub_broke = False
        try:
            ctx.hub_state_before = client.state()
            ctx.audit_before = client.audit()
            body_fn(ctx)
        except Exception as exc:
            ctx.error_info = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            ctx.assertions["no_unhandled_exception"] = False
            ctx.notes.append("场景执行异常（%s）：%s" % (type(exc).__name__, exc))
            if not client.health():
                hub_broke = True
        finally:
            if ctx.proc is not None:
                if not ctx.proc.done:
                    ctx.proc.terminate_aborted()
                if ctx.claude_output is None:
                    ctx.claude_output = _parse_claude_json(
                        ctx.proc.to_result(), expected_session_id=ctx.session_id
                    )
            elif ctx.claude_output is None:
                ctx.claude_output = {
                    "command": ctx.claude_command,
                    "expected_session_id": ctx.session_id,
                    "parsed_json": None,
                    "error": ctx.error_info,
                }

            if ctx.hub_state_after is None:
                try:
                    ctx.hub_state_after = client.state()
                except Exception as state_exc:
                    ctx.hub_state_after = {
                        "error": "%s: %s" % (type(state_exc).__name__, state_exc)
                    }
                    if not client.health():
                        hub_broke = True

            if not ctx.audit_captured:
                try:
                    after_audit = client.audit()
                    ctx.audit_new_entries = self._audit_delta(
                        ctx.audit_before or [],
                        after_audit,
                        session_id=ctx.session_id,
                        session_prefix="verify-offline-" if ctx.session_id is None else None,
                    )
                    ctx.audit_captured = True
                except Exception as audit_exc:
                    ctx.notes.append("读取后置审计失败（%s）：%s" % (type(audit_exc).__name__, audit_exc))
                    if not client.health():
                        hub_broke = True

            if ctx.error_info is not None and isinstance(ctx.claude_output, dict):
                ctx.claude_output.setdefault("scenario_exception", ctx.error_info)

            elapsed = round(max(0.0, self.monotonic() - ctx.started_at), 4)
            passed = (
                ctx.error_info is None
                and bool(ctx.assertions)
                and all(bool(v) for v in ctx.assertions.values())
            )
            outcome = ScenarioOutcome(
                index=ctx.index,
                slug=ctx.slug,
                title=ctx.title,
                status="通过" if passed else "失败",
                elapsed_seconds=elapsed,
                claude_command=ctx.claude_command,
                claude_output=ctx.claude_output,
                hub_state_before=ctx.hub_state_before,
                hub_state_after=ctx.hub_state_after,
                hub_interactions=ctx.hub_interactions,
                audit_new_entries=ctx.audit_new_entries,
                assertions=ctx.assertions,
                notes=ctx.notes,
            )
            self._write_scenario_evidence(run_dir, outcome)
        return outcome, hub_broke

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

    def run(self, *, dry_run=False, only_scenarios=None):
        if dry_run:
            return self.print_dry_run()
        if not self.check_login():
            return 2
        client = self.check_hub()
        if client is None:
            return 3

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = self.output_dir / stamp
        suffix = 1
        while run_dir.exists():
            suffix += 1
            run_dir = self.output_dir / ("%s-%d" % (stamp, suffix))
        run_dir.mkdir(parents=True, exist_ok=True)

        sandbox_name = None
        sandbox_dir = None
        owner_token = None
        specs = scenario_specs(SAMPLE_SANDBOX_NAME)
        outcomes_by_index = {}

        self.out("开始执行 AgentDeck 5 项真实会话验证 -> %s" % run_dir)
        try:
            sandbox_name, sandbox_dir, owner_token = self._create_run_sandbox(run_dir.name)
            specs = scenario_specs(sandbox_name)
            selected = set(only_scenarios) if only_scenarios is not None else {1, 2, 3, 4, 5}
            hub_broken = False

            scenario_bodies = {
                1: lambda ctx: self._body_scenario_1_approve(ctx, client, sandbox_name, sandbox_dir),
                2: lambda ctx: self._body_scenario_2_deny(ctx, client, sandbox_name, sandbox_dir),
                3: lambda ctx: self._body_scenario_3_high(ctx, client, sandbox_name, sandbox_dir),
                4: lambda ctx: self._body_scenario_4_critical(ctx, client, sandbox_name, sandbox_dir),
                5: lambda ctx: self._body_scenario_5_hub_down(ctx, client, run_dir, sandbox_name, sandbox_dir),
            }

            for spec in specs:
                idx = spec["index"]
                if idx not in selected:
                    outcome = self._make_skipped_outcome(spec, "按调用范围跳过本场景。")
                    self._write_scenario_evidence(run_dir, outcome)
                    outcomes_by_index[idx] = outcome
                    continue
                if hub_broken and idx in (1, 2, 3, 4):
                    outcome = self._make_skipped_outcome(
                        spec, "前置场景异常后 Hub 不可达，无法安全继续执行本场景。"
                    )
                    self._write_scenario_evidence(run_dir, outcome)
                    outcomes_by_index[idx] = outcome
                    self.out("  [%s] %s (%.2fs) -> %s" % (
                        outcome.status, outcome.title, outcome.elapsed_seconds, outcome.evidence_relpath))
                    continue

                outcome, broke = self._execute_scenario(run_dir, spec, client, scenario_bodies[idx])
                outcomes_by_index[idx] = outcome
                if broke:
                    hub_broken = True
                self.out("  [%s] %s (%.2fs) -> %s" % (
                    outcome.status, outcome.title, outcome.elapsed_seconds, outcome.evidence_relpath))
        except Exception as top_exc:
            first_missing = True
            for spec in specs:
                idx = spec["index"]
                if idx not in outcomes_by_index:
                    if first_missing:
                        outcome = ScenarioOutcome(
                            index=idx,
                            slug=spec["slug"],
                            title=spec["title"],
                            status="失败",
                            elapsed_seconds=0.0,
                            claude_command=[],
                            claude_output={
                                "error": {"type": type(top_exc).__name__, "message": str(top_exc)}
                            },
                            hub_state_before=None,
                            hub_state_after=None,
                            hub_interactions=[],
                            audit_new_entries=[],
                            assertions={"run_setup_succeeded": False},
                            notes=["验证初始化异常（%s）：%s" % (type(top_exc).__name__, top_exc)],
                        )
                        first_missing = False
                    else:
                        outcome = self._make_skipped_outcome(spec, "因前置初始化异常跳过本场景。")
                    self._write_scenario_evidence(run_dir, outcome)
                    outcomes_by_index[idx] = outcome
        finally:
            self._cleanup_run_sandbox(sandbox_dir, owner_token)
            for spec in specs:
                idx = spec["index"]
                if idx not in outcomes_by_index:
                    outcome = self._make_skipped_outcome(spec, "因未完成执行而标记跳过。")
                    self._write_scenario_evidence(run_dir, outcome)
                    outcomes_by_index[idx] = outcome
            outcomes = [outcomes_by_index[spec["index"]] for spec in specs]
            results_md = self._write_results_markdown(run_dir, run_dir.name, outcomes)

        passed_count = sum(1 for o in outcomes if o.status == "通过")
        self.out("验证完成：%d/%d 通过，报告已写入 %s" % (passed_count, len(outcomes), results_md))
        if only_scenarios is not None:
            expected_indices = {i for i in only_scenarios if i in outcomes_by_index}
            return 0 if (expected_indices and all(outcomes_by_index[i].status == "通过" for i in expected_indices)) else 1
        return 0 if passed_count == len(outcomes) else 1


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
