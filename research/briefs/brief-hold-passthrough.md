# 简报：宏键盘没插时不拦权限请求 + 会话持久化 + relay 加固（hub 侧）

先读 `AGENTS.md`、`pc/hub_README.md`。Python 用 `D:\conda\miniconda3\python.exe -X utf8`。

## 硬规则（违反任何一条都算失败）

- 只改 `pc/` 下的文件，但**不许碰** `pc/agentdeck_app.py`、`pc/test_agentdeck_app.py`（另一个 agent 正在改），也不许碰 `research/acceptance/accept.py`。
- 不许读写真实的 `~/.claude/settings.json`、`~/.codex/hooks.json`、`~/.agentdeck/` 里的任何文件；测试一律用临时 home。
- 不许建/改/删计划任务或注册表 Run 值，测试里也不许碰真实的计划任务和注册表。
- 不许启动 `dist/` 里的 exe，不许 build，不许打开 COM4，不许向键盘发任何东西。
- 不许 git commit / checkout / reset / stash / clean。
- 现有 cx 钩子条目的字节不能变（Codex 按哈希信任钩子）。

## 共享接口（验收脚本按这个写，字段名和取值必须一模一样）

- `GET /state` 增加：`"deck_connected"`（bool：键盘读取器是 `usb` 或 `raw`，即 `input_reader()` 返回 `"usb"`/`"raw"` 时为 true；`"absent"`、None、没有读取器都是 false）、`"hold_mode"`（`"auto"|"always"|"never"`）、`"hold_active"`（= `hold_mode=="always" or (hold_mode=="auto" and deck_connected)`）。
- `POST /action {"action": "hold auto"|"hold always"|"hold never"}`：同样的 token 校验；只在运行时生效，不写盘；回复 200 `{"status":"ok","hold_mode":...}`。其它参数回 400。
- `hold_active` 为 false 时，PermissionRequest（以及 gate 请求）**不拦**：hub 立刻回 `{}`（relay 打印 `{}`、退出码 0，全程约 1 s 内），agent 弹自己的确认框。会话进 `"state": "wait"`、`"native_wait": true`、`"label": "在应用里批准"`；**不进** pending；写一条审计记录，`decision` 为 `"passthrough"`（source `"hold"`）。gate 请求只回 `{}` + 审计 passthrough，不改会话为 wait。critical 请求在不拦时也走 passthrough（不建 locked 记录）。`NEEDS_ANSWER_TOOLS` 的现有分支不变。
- 会话持久化到 `~/.agentdeck/sessions.json`（原子写：同目录临时文件 + `os.replace`；节流：最多每 2 s 写一次，退出时 `close()` 强制写一次；内容没变就不写）。每个会话存 `agent, session_id, slot, cwd, name, state, hwnd, window_exe, last_text, last_updated`（可以顺带存 `last_kind`、`last_text_at`）。启动时读回：`last_updated` 早于 `SESSION_IDLE_SECONDS` 的丢掉；`hwnd` 用 `IsWindow` 检查，失败就清掉 hwnd/window_exe（会话保留）；`wait`/`locked` 读回成 `wait` + `native_wait: true`；未知 state 读回成 `idle`；slot 必须是 1..6 且不重复，坏条目跳过；文件缺失/损坏只记 WARNING，绝不让 hub 起不来。
- Claude Code 事件 `StopFailure` 被接受：会话 state `"error"`，`label` 取自 `error` 字段（如 `"出错：rate_limit"`，error 截到 40 字符），`last_assistant_message`（此时是 API 错误文本）当作 last_text，kind 用 `"错误"`。`StopFailure` 加进安装器写的 cc 钩子集合（exec 形式，和其它 cc 条目同样的形状，timeout 10）。官方输入字段：`error`（rate_limit / authentication_failed / billing_error / server_error / unknown 等）、可选 `error_details`、可选 `last_assistant_message`。
- `Notification` 且 `notification_type == "idle_prompt"`：会话当前是 `tool`/`think` 且没有 pending/locked 时，改成 `idle`。
- relay.log 每行：`YYYY-mm-dd HH:MM:SS <agent> <event> <sid 前 8 位> <message>`，message 最多 300 字符、换行换成空格，**绝不写原始 stdin 字节**；缺的字段写 `-`；文件到 512 KB 时先轮转成 `relay.log.1`（覆盖旧的）再写。
- 开机自启的计划任务名是根目录的 `"AgentDeck"`（这一条本步骤不用改代码，别碰）。

## 要做的事

### 1. hub.py：hold 模式、passthrough、持久化、StopFailure、idle_prompt
- `Hub.__init__` 新参数：`hold_mode="always"`（直接构造 Hub 的现有测试保持原行为）、`sessions_path=None`（None = 不持久化）、`window_alive=None`（hwnd -> bool；默认 win32 用 `user32.IsWindow`，其它平台恒 True）。新方法 `deck_connected()`、`hold_active()`（调 `self.input_reader()`，异常当 false；不做 I/O）。
- `main()`：新增 `--hold-mode {auto,always,never}`，**默认 auto**；把 `sessions_path=home/".agentdeck"/"sessions.json"` 传给 Hub。托盘程序调用 `hub.main` 时不带这个参数，所以真机默认就是 auto。
- 切到不拦（`hold never`，或 `hold auto` 时键盘没连）时，把已挂着的非 gate pending 也按 passthrough 放掉（审计 passthrough、native_wait、wait、label），记一行 INFO。
- `maintain()` 在锁外做节流写盘；`close()` 放掉 pending 后强制写一次。写盘用单独的小锁，失败只记 WARNING（同一错误只记一次）。
- LCD：passthrough 会话的名字字段显示 `"APP: " + name`（ASCII）。
- 未知 `hook_event_name`（是字符串但不在 EVENTS）：仍回 400，但每个进程每个名字只记一条 WARNING 到日志（名字截 64 字符，记过的名字集合最多 256 个）。

### 2. 幽灵请求（用户已在应用里点了）
同一会话后来的任何事件（除 PermissionRequest / Notification 外：PreToolUse、PostToolUse、PostToolUseFailure、Stop、StopFailure、UserPromptSubmit、SessionEnd、Interrupt）把这个会话的 pending 请求以“无决定”放掉（等待中的 relay 打印 `{}` 退出），从浮窗清掉，`native_wait`/`label` 也清掉。审计 decision 用现有的 `"abandoned"`、source `"event"`、`moved_on=True`（不要设 native_wait）。每个事件放掉 ≥1 个时记**一行** INFO（含事件名、会话前 8 位、放掉的个数）。细节：
- gate 请求不能被 PreToolUse/PostToolUse/PostToolUseFailure/UserPromptSubmit 放掉（放掉 gate = 拒绝工具，而且 gate 自己那次调用的普通 PreToolUse 会同时到）。Stop/StopFailure/Interrupt/SessionEnd 照旧全放。
- 子代理：`Pending` 记下事件里的 `agent_id`（字符串，没有就 `""`）；PreToolUse/PostToolUse/PostToolUseFailure 只放掉 `agent_id` 相同的请求（避免并行子代理互相误放）。relay 的 slim body 要转发 `agent_id`。
- `SessionEnd` 走 `_remove_session`：会话结束时放掉的请求也用 abandoned/event/moved_on，并记那行 INFO；闲置过期和槽位淘汰保持原来的语义即可。
- 删掉 hub.py 里“PreToolUse 不用来取消”的旧注释，换成新规则的说明。

### 3. relay：每个事件都带窗口
实测 `research/time_relay_window.py`：查窗口的额外开销中位数约 7.5 ms（< 20 ms），所以：
- 所有事件都查 `agentdeck_window`（去掉 `WINDOW_EVENTS` 限制），继续在线程里和 import/connect 重叠；connect 之后 `join` 有上限：普通事件 0.05 s、PermissionRequest/gate 0.25 s，超时就不带窗口照常发。`AGENTDECK_NO_WINDOW=1` 仍可关掉。hub 已死（hub.json 指向死进程）的快速失败路径不能变慢。
- PermissionRequest / gate 现在按原始字节转发：在原始字节的开头 `{` 后面拼进 `"agentdeck_window":{...},`（空对象 `{}` 时不加逗号；先去掉前导空白），其余字节一个不改。拼不了（不是以 `{` 开头）就原样发。
- 改完后重跑 `research/time_relay_window.py`，把输出贴进最终回复。

### 4. hub 卡死时 relay 不能拖住 agent
- 普通事件（非 PermissionRequest、非 gate）：connect + send + read 总预算 ≤ 2 s（connect 前取 deadline；connect 超时取现有值和剩余预算的较小者；request 前、getresponse 前各按剩余预算重设 socket 超时）。
- PermissionRequest / gate：保持长读超时（现有逻辑），connect 超时保持短（现有 0.1 / 0.5 s）。

### 5. 风险：Codex apply_patch 删文件
`hub_risk.RISK_RULES` 加一条：输入里有一行以 `*** Delete File:` 开头 → `"high"`（和 rm -rf 同等处理）。只有 `*** Update File:` / `*** Add File:` 的仍是 low。加测试（tool_input 是 dict 的 command/patch/input 字段、或纯字符串都要覆盖）。

### 6. relay 记状态
hub 回非 200 时，relay.log 记 `hub status <code>: <error 字段，≤100 字符>`；异常记 `<异常类名>: <消息>`。按上面的 relay.log 格式和 512 KB 轮转。StopFailure 的 slim body 要带 `error`（≤64）、`error_details`（≤300）、`last_assistant_message`（尾部 TEXT_LIMIT）。

### 7. 浮窗（hub_overlay.py，只改 display_model 和已有的标签，不加动画、不加新控件）
- `state["deck_connected"] is False` 时顶部那行提示显示 `"宏键盘未连接 · 批准请在应用里点"`（读取器是 `raw` 时仍显示原来的 Zadig 提示）；快照里没有 `deck_connected` 键时保持旧行为。
- `state["hold_active"] is False` 且会话 `native_wait` 为真时，这一行的提示文字是 `"在应用里批准"`（代替“等你”）。会话 state 为 `error` 且有 `label` 时，行提示显示 label。

### 8. 安装器（hub_install.py）
- `EVENTS["cc"]` 加 `"StopFailure"`。
- `global_status()` 增加 `"missing_events": {"cc": [...], "cx": [...]}`（已启用的配置里缺哪些我们的非 gate 事件）。打包版（`expected is not None`）且 cc 缺事件时 `needs_repair` 为 true，这样托盘程序启动时的 repair 会把 StopFailure 补上；cx 缺事件**不**触发 repair。确认 `apply("install")` 对条目已一致的 cx 配置是 no-op（不写文件）——加一个测试：cx 配置已是安装器写的样子时，cc 补 StopFailure 的 install 不改 cx 文件的字节。

### 9. README（pc/hub_README.md）
- 修正“Selection, display, and actions”里的淘汰说明：第 7 个新会话会淘汰最久没更新、没有 pending/locked 请求、也不是语音目标的会话；全部都忙时才回 409。
- 新增一节说明：hold 模式（auto/always/never、`/action hold ...`、不写盘、默认 auto）、passthrough 行为、`/state` 新字段、幽灵请求、sessions.json、StopFailure 和 idle_prompt、relay.log 格式与轮转、relay 的 2 s 预算。中文为主，和现有风格一致，写短。

## 做完的标准
1. 新增 `pc/test_hub_hold.py`，覆盖 1、2、5、6 的 hub 侧逻辑（假时钟、假 input_reader、临时 home），并包含**一个真 socket 集成测试**：`HubServer(port=0)` + `hold_mode="auto"` + `input_reader=lambda: "absent"`，用子进程跑真实的 `pc/hub_relay.py`（临时 home 里放 token 和 hub.json）发 PermissionRequest，断言 stdout 是 `{}`、退出码 0、耗时 < 1.5 s、`/state` 里该会话 `native_wait` 为真、审计有 passthrough；再测幽灵：`hold always` 下子进程 relay 发 PermissionRequest 挂着，然后发同会话的 PostToolUse（另一个工具也行），断言挂着的 relay 很快打印 `{}` 退出、`/state` 的 pending 为空。
2. relay 测试加进 `pc/test_hub_relay.py`：日志格式/截断/不含 stdin/512 KB 轮转；假 hub 接受连接但永不回复时普通事件 ≤ 2.5 s 返回；PermissionRequest 拼窗口后仍是合法 JSON 且其余字节不变；PreToolUse 也带窗口；非 200 记状态；StopFailure 与 agent_id 字段转发。
3. 安装器测试加进 `pc/test_hub_install.py`，浮窗测试加进 `pc/test_hub_overlay.py`。
4. 因新行为失效的旧测试要改对（例如以前断言 PreToolUse 不取消 pending 的；通过 `hub.main` 起 hub 又期望请求被拦的，传 `--hold-mode always`）。改旧测试时在回复里逐条说明原因。
5. 逐个单独运行 `pc/` 下**除 `test_agentdeck_app.py` 以外**的每个 `test_*.py`（`D:\conda\miniconda3\python.exe -X utf8 pc/<file>`），全部退出码 0；桌面锁屏导致的 SKIP 不算失败。最终回复贴出每个文件的最后一行结果。
6. 最终回复写清：按 1–9 每项改了什么（文件 + 函数）、改了哪些旧测试及原因、时间测量结果、没做完的。
