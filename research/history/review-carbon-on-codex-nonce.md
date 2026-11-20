# 审批 Nonce 校验独立代码审查报告

审查范围：[brief-hub-nonce.md](file:///D:/desk/hardware/h1/research/briefs/brief-hub-nonce.md)、[review-input-nonce.diff](file:///D:/desk/hardware/h1/research/review-input-nonce.diff)、[hub-nonce-results.md](file:///D:/desk/hardware/h1/research/hub-nonce-results.md)，以及 `pc/`、`lcd1602/`、`research/` 下相关完整源码与测试文件（只读静态审查）。

---

## 一、四个核心维度结论速览

### 1. 安全性核查
* **架构级事实（真假“设备回传 nonce”）**：固件与 USB HID 报文协议**未做任何改动**。USB 宏键盘与全局热键依然只发裸按键，所谓“带 nonce”实际是 Hub 在 PC 进程内存中读取 `self.rendered_request` 代填（[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L854)、[hub_hotkey.py](file:///D:/desk/hardware/h1/pc/hub_hotkey.py#L63)），并非 PRD/BP 所述的“物理设备保存当时显示的 nonce 并随按键回传”；仅浮窗（`Overlay`）和虚拟设备（`VirtualDevice`）是从自身 UI 状态回传 `nonce`。
* **不带 nonce 的路径**：
  * `require_nonce` 默认为 `False`（[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L134)，[start_agentdeck.bat](file:///D:/desk/hardware/h1/start_agentdeck.bat#L8) 和 [start_agentdeck_demo.bat](file:///D:/desk/hardware/h1/start_agentdeck_demo.bat#L17) 均未开启，CLI 也无 `--require-nonce` 参数），本机任何能读 `~/.agentdeck/token` 的进程发 `POST /action {"action": "approve"}` 可完全跳过 nonce 校验（含直接完成高危第二次确认）。
  * 开启 `require_nonce: true` 后，无 `nonce` 的 `approve` 会被 `409 nonce_required` 拦住；无 `nonce` 的 `deny`（[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L537-L538)）与 `interrupt`（[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L596-L615)、虚拟设备 `Ctrl+✗` [hub_virtual_device.py](file:///D:/desk/hardware/h1/pc/hub_virtual_device.py#L98-L99)）仍可无 nonce 拒绝请求，但不能放行。
* **热键/USB 取的是不是“最后渲染”而非队首**：
  * 存储上确实与 `displayed_request_id` 分离，读 `/state` 不会更新 `rendered_request`；**但存在三处破口**：① **LCD 与浮窗共用单一 `self.rendered_request` 后写覆盖**（见 **P0-2**，一屏卡死/滞后在旧请求时另一屏刷新会导致“看 A 批 B”）；② **Windows 全局热键在消息出队时才调 `snapshot()` 而非按键发生时**（见 **P1-1**）；③ **LCD 所谓“已渲染”只校验串口回显 `ok set ...`**，当项目名 > 3 字符时 LCD 屏上既无命令摘要也无 nonce，同一会话连续两条请求在 LCD 上画面完全相同却会被更新为新 nonce 已渲染。
* **并发竞态**：
  * **浮窗 `<ButtonPress-1>` 抓新请求 nonce 但 `<ButtonRelease-1>` 才取接收时间，正常点击即可直接绕过 300ms `switch_guard`**（见 **P0-1**）；
  * **虚拟设备不汇报渲染时刻 + 异步 `_jobs` 队列排队，可跨过 300ms `switch_guard`**（见 **P0-1**）；
  * **USB 同报文多键变迁（如松开语音 `H` 同时按下 `G`/`Ctrl+F`）在回调入口现取时间和渲染快照而非用读包时刻**（见 **P1-2**）。
* **高危二次确认第二次能否换请求**：
  * `armed_at` 绑定在具体 `Pending` 实例上（[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L607-L614)），切槽会清零 `armed_at`（[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L639-L641)）。第二次若带旧 nonce 必返 `409 stale_nonce` 且原请求保持 `armed`；若切到另一条**高危**请求且带新 nonce，只会重新进入第 1 次 `confirm`。
  * **但若第 1 次确认后原高危请求被 `Stop`/超时取消，队列切到另一条低危请求且已过 380ms**，用户在 1.5s 窗口内按第 2 下物理键（本意确认刚才的高危请求）时，USB/热键会重新取当前 `rendered_request` 的新 nonce，**把第 2 条低危请求当场单击放行**（见 **P1-3**）。
* **过期 nonce 能否复活**：
  * 单次 Hub 进程内**不能复活**：`_new_nonce()`（[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L244-L251)）用 `self.issued_nonces` 记录所有已发出的 nonce 并在碰撞时重抽，`_validate_decision` 在 `_expire()` 前先判 `self.monotonic() >= request.deadline`（[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L533)）。仅需注意 `Pending` 默认工厂（[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L117)）未走 `_new_nonce()`，且 `issued_nonces` 重启清空、长跑无上限（见 **P2-3**）。
* **`switch_guard` 计时用的是什么时钟**：
  * Hub 核心使用可注入单调时钟 `self.monotonic`（默认 `time.monotonic`，不受系统时间跳变影响，且忽略 HTTP JSON 传入的 `received_at`）。
  * **但输入端混用了不同时钟和错误采样点**：① Windows `Win32Hotkeys` 用 32 位 `GetTickCount() - message.time`（约 **15.6ms 粗粒度**系统滴答）算 `age`，再与 `time.monotonic()` 相减合成 `received_at`（[hub_hotkey.py](file:///D:/desk/hardware/h1/pc/hub_hotkey.py#L135,L191,L207)）；② `HotkeyInput` 和 `USBKeys` 默认各自绑 `time.monotonic` 而未继承 `hub.monotonic`（[hub_hotkey.py](file:///D:/desk/hardware/h1/pc/hub_hotkey.py#L153)、[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L850,L987)）；③ 浮窗取的是松开鼠标时刻、虚拟设备/HTTP 取的是服务端收完包时刻（见 **P0-1**、**P1-2**）。

### 2. 行为回归核查
1. **无浮窗 + 无/坏 LCD（含仅开虚拟设备）时，USB 与热键的批准和拒绝 100% 失效**（见 **P0-3**，直接破坏 `hub_README.md` 明文支持的 `--backend hotkey --no-lcd` 与无 LCD 容错承诺）。
2. **空闲无待批请求时按物理键/热键从返回 `200 {"status": "no_request"}` 退化为抛 `409 stale_nonce` 并写入缺字段的残缺审计记录，导致下游读 `audit["risk"]` 直接 `KeyError` 崩溃**（见 **P0-4**）。
3. **每次 `_show()` 在持有 `Hub.lock` 期间硬阻塞至少 150ms（`wait_reply=0.15`），且 `retry_for=0.0` 撞上 `agent_lcd.py hook` / `daemon.py` 占口时把物理审批锁死 20 秒**（见 **P1-4**）。
4. **USB `interrupt` 丢失了“空闲按下期间新请求到达”的防误拒校验**（见 **P2-1**）。
5. **所有不带 nonce 的旧 HTTP `approve` 及切槽后立即 `approve` 均新增 300ms `switch_guard` 拒绝**（现有测试因此改了 11 处加 `0.31s` 等待）。

### 3. 简报要求 vs 测试真实覆盖度逐条核对

| 简报要求 | 现有测试 | 真实覆盖评价 |
| :--- | :--- | :--- |
| 1. 每条请求生成 32 位随机 nonce 进 `/state` | `test_nonce_is_random_32_bit_and_public` 等 | **半覆盖**：`test_hub_nonce.py` 33 个用例里有 **32 个**调的是手搓 `Pending` 塞字典的 `self.request()`（测的是 dataclass 默认工厂而非 `Hub.event` -> `_new_nonce()`，连 `session["state"]="wait"` 都没设）；仅碰撞重抽那 1 个用例跑了真 `Hub.event`。 |
| 2a. 一致放行 / 不一致拒收（409 `stale_nonce` 不改状态） | `test_matching_nonce_approves`、`test_mismatch_rejects_without_mutation`、`test_http_stale_nonce_returns_409` 等 | **真覆盖**：含 `bool`/`str`/`float`/`NaN`/非当前显示请求/HTTP 409。 |
| 2b. 300 ms `switch_guard`，`deny` 豁免 | `test_initial_switch_guard_and_boundary`、`test_queue_switch_restarts_guard_and_deny_is_exempt` 等 | **漏掉 GUI 真实链路**：只测了直接调 `Hub.action`、手动喂 `received_at=.1` 的 `HotkeyKeys.dispatch` 和单事件 `USBKeys`；**未拿真 `Hub` 测 `Overlay` 和 `VirtualDevice`**，直接漏掉 **P0-1** 绕过漏洞。 |
| 2c. 高危二次确认第二次带错 nonce | `test_high_risk_second_wrong_nonce_preserves_armed_state`、`test_high_and_critical_gates_preserve_armed_state_on_wrong_second_nonce` | **真覆盖**（同一请求保持 `armed`）；未测第一次确认后请求切为低危时物理键误放行（**P1-3**）。 |
| 3a. 浮窗、虚拟设备带画面当时显示的 nonce | `test_hub_overlay.py`、`test_hub_virtual_device.py` | **只测了 Mock**：`test_hub_overlay.py` 全程用 `Mock()` 冒充 `Hub`，第 97、162 行甚至断言传 `"nonce": None` 返回 `"allowed"`（真 `Hub` 必抛 `409 stale_nonce`！）。 |
| 3b. 热键、USB 取“最后渲染”的 nonce（模拟渲染后队首变化） | `test_hotkey_uses_last_rendered_request_after_logical_switch`、`selftest_hub_replay.py` 等 | **严重失真**：① Windows 主平台只测了 `HotkeyKeys`，**从未跑过 `HotkeyInput.run()` 消息队列**（漏掉 **P1-1**）；② `selftest_hub_replay.py` [第 211 行](file:///D:/desk/hardware/h1/research/selftest_hub_replay.py#L211)直接把 `/state` 队首赋给 `target.rendered_request`，用队首假冒渲染；③ LCD 回执测试手拼 `'ok set %s idle...'` 假字符串，未接 `lcd1602/ui.py`。 |
| 3c. HTTP 无 nonce 兼容 + `require_nonce` 开关 | `test_legacy_missing_nonce_works_after_guard`、`test_require_nonce_*` | **真覆盖**。 |
| 4. LCD 与浮窗显示后 4 位十六进制 | `test_short_lcd_name_displays_low_four_hex_digits` | **纯断言自己写的字符串**：只把名字设成 `'abc'` 断言 `_display_name == 'abc abcd'`，根本没送进 `lcd1602/ui.py` 渲染，也没测 ≥4 字符项目名或多会话溢出（漏掉 **P1-5**）。 |
| 5. 110 s 过期永久作废 | `test_expiry_boundary_*`、`test_expired_nonce_cannot_replay_*` | **真覆盖**。 |
| 6. 审计日志条目 | `test_rejected_nonce_and_guard_are_audited` | **漏掉空请求分支与 `nonce_required`**：未测 `displayed_request_id is None` 时的拒收审计，漏掉缺字段导致下游 `KeyError: 'risk'`（**P0-4**）。 |

### 4. 1602 LCD 显示 nonce 后 4 位是否会挤掉原有内容
* **95% 以上的正常场景（含整个 `hub_demo.py` 路演脚本）根本不会显示 nonce，因此不挤占但也完全看不见**：`width = 13 - max(5, len(self.sessions) + 1)`（[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L258-L261)）在 1～4 会话时要求 `len(name) <= 3`，5 会话（`hub_demo.py`）要求 `len(name) <= 2`，6 会话要求 `len(name) <= 1`，所有 `GATE:` / `HOLD! press again` / `LOCKED:` 全不显示。
* **但在短项目名（≤3 字符）且 1602 板上有 Hub 之外的会话（如 `dsh_watch.py` 上报的 DeepSeek 会话或旧残留会话，板上最多 8 个）时，真的会挤掉原有内容！** 因为 `hub.py` 只按 `len(self.sessions)` 算宽度，而板子 `ui.py` 按板上总会话数画右侧小图标条 `tail`，超出后触发跑马灯：前 2 秒截断 nonce 末两位，2 秒后把原项目名从左侧挤出屏幕（详见 **P1-5**）。

---

## 二、问题分级清单（P0 / P1 / P2）

### P0（可被绕过或会坏）

#### [P0-1] 浮窗鼠标“按下抓新 nonce、松开算接收时刻”及虚拟设备未报渲染时刻，可直接绕过 300ms `switch_guard`
* **文件与位置**：
  * [hub_overlay.py](file:///D:/desk/hardware/h1/pc/hub_overlay.py#L168-L182)（`Overlay.dispatch`）、[hub_overlay.py](file:///D:/desk/hardware/h1/pc/hub_overlay.py#L219-L226)（`Overlay._decision_press` / `_decision_release`）
  * [hub_virtual_device.py](file:///D:/desk/hardware/h1/pc/hub_virtual_device.py#L323-L342)（`VirtualDevice._worker`）、[hub_virtual_device.py](file:///D:/desk/hardware/h1/pc/hub_virtual_device.py#L361-L368)（`VirtualDevice._press`）、[hub_virtual_device.py](file:///D:/desk/hardware/h1/pc/hub_virtual_device.py#L420-L431)（`VirtualDevice._tick`）
* **问题**：
  1. `Overlay._decision_press` 在鼠标按下（`<ButtonPress-1>`）时捕获画面上的 `(id, can_approve, nonce)`，却**没有记录按下时刻**；直到鼠标松开（`<ButtonRelease-1>`）调 `self.hub.action(payload, source="overlay")` 时未传 `received_at`，由 `Hub.action`（[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L561)）按**松开时刻**取 `monotonic()`。
  2. `VirtualDevice` 只轮询 `/state`（200ms 周期 + 40ms 绘制周期），从不通知 Hub 何时真正画上屏幕，`Hub.display_switched_at` 从请求进入 Hub 内存时就开始计时；且点击先入 `_jobs` 队列，若 `_worker` 正在等慢 `/state` 响应，送达 `/action` 时更晚。
* **复现方式**：
  1. 浮窗：请求 A 刚被请求 B 替换并渲染（`t = 0.00s`，`display_switched_at = 0.00s`），用户原本去点 A 的手指在 `t = 0.05s`（切换后仅 **50ms**，正处于 `switch_guard` 要防的误触窗口）按下 `✓`，`_decision_press` 抓到 B 的 `id` 和 `nonce`；用户按常规点击习惯 260ms 后在 `t = 0.31s` 松开鼠标，`received_at = 0.31s >= 0.30s`，请求 B 被直接批准放行。
  2. 虚拟设备：无浮窗/无 LCD 下，请求 B 在 `t = 0.00s` 进 Hub，虚拟设备在 `t = 0.23s` 才首次画出 B，用户在 `t = 0.31s`（看到 B 仅 **80ms**）点击 `✓`，Hub 算得 `0.31 - 0.00 >= 0.30`，直接放行。
* **建议改法**：
  * `Overlay._decision_press` 同时保存 `pressed_at = self.hub.monotonic()`，`_decision_release` -> `dispatch` 把 `received_at=pressed_at` 传给 `self.hub.action(...)`。
  * 为虚拟设备等独立前端增加渲染上报接口（如 `POST /rendered` 携带 `{request_id, nonce}` 更新对应前端的渲染时间戳），并在前端按下时校验本地首次绘制该 nonce 已满 300ms 才允许发出 `approve`。

#### [P0-2] LCD 与浮窗共用单一 `self.rendered_request`（后写覆盖），双屏不同步时会“看旧请求批掉新请求”
* **文件与位置**：
  * [hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L174-L175)（`Hub.__init__`）、[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L209-L220)（`Hub.record_rendered`）、[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L227-L240)（`Hub._show`）
  * [hub_overlay.py](file:///D:/desk/hardware/h1/pc/hub_overlay.py#L318-L324)（`Overlay._poll`）
* **问题**：
  `start_agentdeck.bat --usb` 默认同时启用 LCD、USB、热键和浮窗，但 Hub 只维护一个全局 `self.rendered_request`，`lcd` 与 `overlay` 谁后调 `record_rendered` 就覆盖谁。
  * 若物理 LCD 因串口瞬时争用（`retry_for=0.0`）写入失败，物理屏仍冻结在请求 A（`#1111`），而后台/副屏的浮窗轮询成功，就会把 `rendered_request` 覆盖为请求 B（`#2222`）；
  * 反之，若物理 LCD 先在 20ms 内回执把 `rendered_request` 更新成请求 B（且项目名 > 3 字符时 LCD 上根本不显示命令与 nonce），而用户正在拖动浮窗标题栏或 Tk 主线程卡顿 > 300ms 导致浮窗仍显示请求 A（`#1111`），热键 `F19` 也会取走 LCD 写入的请求 B nonce。
* **复现方式**：
  1. 同时开启 LCD 与 `--overlay`，请求 A（`#1111`）已上屏；
  2. 请求 A 结束、请求 B（`#2222`）入队，令本次串口 `_send` 失败（如 `agent_lcd.py hook` 正占用 COM4），物理 1602 屏仍停在 A；
  3. 300ms 后浮窗 `_poll` 调 `record_rendered(B.id, B.nonce, "overlay")`；再过 300ms 用户看着物理 1602 屏上的 A 按下 USB 键 `G`，请求 B 被直接放行。
* **建议改法**：
  按显示源分开记录 `rendered_by_source = {"lcd": ..., "overlay": ..., "virtual": ...}`；当启用了多个输出端时，要求所有当前活跃显示源均已渲染同一 `(request_id, nonce)`（或按输入后端绑定的显示源核对，且 `display_switched_at` 取最晚完成渲染的那个源的时刻）才允许放行。

#### [P0-3] 无浮窗且无/坏 LCD（含官方 `--backend hotkey --no-lcd` 及仅开虚拟设备模式）时，USB 与热键的批准和拒绝 100% 瘫痪
* **文件与位置**：
  * [hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L183-L208)（`Hub._send`）、[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L529-L536)（`Hub._validate_decision`）、[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L854,L895-L896)（`USBKeys`）
  * [hub_hotkey.py](file:///D:/desk/hardware/h1/pc/hub_hotkey.py#L62-L77)（`HotkeyKeys`）
  * [hub_README.md](file:///D:/desk/hardware/h1/pc/hub_README.md#L224,L412-L413)
* **问题**：
  `self.rendered_request` 初始为 `{"request_id": None, "nonce": None}`，只在 LCD 串口回执成功或 `Overlay._poll` 可见刷新后更新；`VirtualDevice` 也不更新它。一旦用户：
  1. 运行 README 第 224 行明文给出的 `python pc/hub.py --backend hotkey --no-lcd`；
  2. 运行 `python pc/hub.py --backend usb -v` 但没插 1602 屏（README 第 412 行仍承诺 *“Missing LCD hardware logs a warning and does not prevent decisions”*）；
  3. 运行 `hub.py --backend usb --no-lcd` 搭配 `hub_virtual_device.py`（看虚拟设备屏幕、按实体宏键盘/热键）；
  `USBKeys` 和 `HotkeyKeys` 都会附带 `nonce: None`，触发 `type(nonce) is not int`，导致**不仅 `approve` 全挂，连紧急拒绝 `deny` 也 100% 报 `409 stale_nonce` 失效**！（`test_hub.py:546` 之所以没发现，是因为它的假 `sender` 返回 `None` 被当成已回执，且测试里调的是无 nonce 的 `action({"action": "approve"})`；`selftest_hub_replay.py:211` 也是靠手动塞 `target.rendered_request` 才绕过。）
* **复现方式**：
  启动 `python pc/hub.py --backend hotkey --no-lcd`，发一条 `PermissionRequest`，等 0.5 秒后按 `F19`（批准）或 `F20`（拒绝），全部被 `409 stale_nonce` 拒收。
* **建议改法**：
  1. **`deny` 绝不应因无渲染回执而锁死**（至少在 `rendered_request["nonce"] is None` 且无活跃屏或串口离线时允许拒绝当前请求，或明确区分拒绝策略）；
  2. 让 `VirtualDevice` 绘制完成后上报 `rendered` 快照，使“虚拟设备屏 + 实体键盘/热键”可用；
  3. 若设计上确实决定彻底废弃无屏热键/无 LCD 降级模式，必须删除 `hub_README.md:224` 的 `--backend hotkey --no-lcd` 示例与 `hub_README.md:412` 的冲突描述，并在启动 `--backend usb|hotkey --no-lcd`（未带 `--overlay`）时直接报错提示，而不是静默启动后按键全挂。

#### [P0-4] 空闲无待批请求时按物理键/热键会写入缺字段的残缺审计记录，导致 `GET /audit` 消费方（如 `selftest_hub_replay.py`）`KeyError: 'risk'` 崩溃
* **文件与位置**：
  * [hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L323-L331)（`Hub._audit`）、[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L526-L555)（`Hub._validate_decision`）
  * [selftest_hub_replay.py](file:///D:/desk/hardware/h1/research/selftest_hub_replay.py#L313-L320)
  * [hub_README.md](file:///D:/desk/hardware/h1/pc/hub_README.md#L530-L533)
* **问题**：
  旧版在无待批请求（`displayed_request_id is None`）时按 USB `G`/`Ctrl+F` 或热键 `F19`/`F20`，返回 `200 {"status": "no_request"}` 且不写审计。新版 `USBKeys`/`HotkeyKeys` 会传 `{"request_id": None, "nonce": None}`，进入 `_validate_decision` 被判为 `409 stale_nonce` 并调用 `self._audit(None, "stale_nonce", ...)`。
  而 `Hub._audit` 在 `request is None` 时只写 `{"request_id": None, "nonce": None, ...}`，**缺失了文档规定的 `agent`、`session_id`、`project`、`tool_name`、`command`、`risk` 六个字段**！同时即便 `request` 存在，向同一审计链混入 `decision: "stale_nonce" / "switch_guard"` 也会改变按 `risk` 计数的语义。
* **复现方式**：
  在 `selftest_hub_replay.py` 跑 `audit()` 前（比如刚启动完 6 个空闲会话时）按一下 `G`（`replay.tap(G)`），或发一次无当前请求时的带 nonce `/action`，随后调 `GET /audit` 跑 `selftest_hub_replay.py:313`（`item["risk"] == "low"`），当场抛出 `KeyError: 'risk'`；或在 `critical` 锁死期间触发一次 `stale_nonce`，第 319 行 `sum(item["risk"] == "critical" ...) == 1` 断言立即失败。
* **建议改法**：
  1. 当 `displayed_request_id is None` 且输入快照也是 `{"request_id": None, "nonce": None}`（即按键时屏幕本来就没有显示任何请求、当前也没有请求）时，保持原有 `{"status": "no_request"}` 行为，不要判成 `stale_nonce` 污染审计日志；
  2. 在 `Hub._audit` 中即使 `request is None`，也补齐 `"agent": None, "session_id": None, "project": None, "tool_name": None, "command": "", "risk": None` 固定 Schema，避免任何下游消费方 `KeyError`。

---

### P1（高风险竞态、真机卡顿/锁死回归、测试严重盲区）

#### [P1-1] Windows `Win32Hotkeys` 在消息出队时而非按键时取 `rendered_request`，且前序动作失败不更新 `last_dispatch_finished`，可误拒新请求
* **文件与位置**：
  * [hub_hotkey.py](file:///D:/desk/hardware/h1/pc/hub_hotkey.py#L128-L137)（`Win32Hotkeys.next_event`）、[hub_hotkey.py](file:///D:/desk/hardware/h1/pc/hub_hotkey.py#L184-L208)（`HotkeyInput.run`）
* **问题**：
  macOS `PynputHotkeys._press` 在监听线程回调入口抓取 `shown` 快照，但 Windows 主平台 `HotkeyInput.run` 是单线程串行 `GetMessageW` -> 等修饰键释放（最长 1s） -> `dispatch`。阻塞期间用户按下的热键躺在系统消息队列里，直到上一条处理完出队时才执行第 198 行 `shown = self.keys.snapshot()`（**取到了出队时刻的新渲染请求，而非按键时刻看到的旧请求！**）。更糟的是第 207–208 行只在 `dispatch` 返回 `True` 时更新 `self.last_dispatch_finished`；一旦前序动作失败返回 `False`（如 `Ctrl+F13` 模板粘贴无匹配窗口），队列里积压的 `F20`（`deny` 免除 `switch_guard`）不会被第 193 行丢弃，而是直接带上新请求的 nonce 把新请求误拒！（`approve` 仅靠 `received_at - age < display_switched_at` 被 `switch_guard` 侥幸兜住。）
* **复现方式**：
  Windows 下请求 1 在屏上；按 `Ctrl+F13`（无匹配终端窗口）并按住 `Ctrl` 0.4s，在 `0.1s` 时看着请求 1 按 `F20`（拒绝），`0.2s` 时请求 1 自行结束、请求 2 上屏渲染，`0.4s` 松开 `Ctrl` 后 `Ctrl+F13` 返回 `False`，紧接着循环取出刚才的 `F20`，`snapshot()` 读到请求 2 的 nonce 并把请求 2 拒绝。
* **建议改法**：
  1. 无论 `dispatch` 成功或失败，在 `finally` 中更新 `self.last_dispatch_finished = self.monotonic()`（或者记录 `busy_since` 丢弃阻塞期间入队的决策键）；
  2. 将 Win32 `GetMessageW` 拆为像 `PynputHotkeys` 一样的轻量泵线程：收到 `WM_HOTKEY` 立即抓取 `(identity, monotonic(), keys.snapshot())` 放进内存队列，工作线程再做修饰键等待与分发，顺便消除 `GetTickCount` 15.6ms 粗粒度时钟混用。

#### [P1-2] `USBKeys` 丢弃读包时刻 `event["t"]` 改取回调当前时间，且 `USBKeys` / `HotkeyInput` 未继承 `Hub.monotonic` 时钟
* **文件与位置**：
  * [hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L850-L855,L987-L990)（`USBKeys.__init__` / `__call__`、`main`）
  * [hub_hotkey.py](file:///D:/desk/hardware/h1/pc/hub_hotkey.py#L149-L154)（`HotkeyInput.__init__`）
  * [deck_usb.py](file:///D:/desk/hardware/h1/pc/deck_usb.py#L221-L227,L254-L256)（`USBInput`）
* **问题**：
  1. `USBInput` 在 `endpoint.read()` 拿到 USB 中断包时已记录了单调时钟 `event["t"]`，但 `USBKeys.__call__` 第 853–854 行却重新调 `self.monotonic()` 和 `dict(self.hub.rendered_request)`。同一 8 字节 HID 报文可拆出多个事件（例如松开 `H` 触发 `voice_up` 的同时按下 `G` 或 `Ctrl+F`）：第 1 个事件持锁等待期间若刚跨过 300ms 保护期或刷新了 `rendered_request`，第 2 个事件就会拿到滞后的时间和新快照。
  2. `hub.py:987` 和 `990` 创建 `USBKeys`、`HotkeyInput` 时均未传 `monotonic=hub.monotonic`，与 `Hub` 注入时钟脱节。
* **复现方式**：
  新请求刚渲染 100ms 时，一帧 HID 报文同时松开 `H` 并按下 `G`；若 `voice_up` 耗时 220ms，随后处理的 `G` 事件会取到 `320ms` 作为 `received_at`，绕过 300ms `switch_guard`。
* **建议改法**：
  在 `USBInput` 读出报文生成 `context` 时一次性抓取 `t`（或把快照回调交给 `USBInput._report_context`），`USBKeys.__call__` 优先使用 `event.get("t")`（校验类型为数值后）作为 `received_at`；`USBKeys` 和 `HotkeyInput` 默认使用 `hub.monotonic`。

#### [P1-3] 高危二次确认期间若原请求取消并切到低危请求，超过 300ms 后的“第二次物理按键”会直接放行新低危请求
* **文件与位置**：
  * [hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L607-L615)（`Hub.action`）、[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L854,L895-L896)（`USBKeys`）、[hub_hotkey.py](file:///D:/desk/hardware/h1/pc/hub_hotkey.py#L63,L74)（`HotkeyKeys`）
* **问题**：
  L2 二次确认允许 1.5s 窗口，而 `switch_guard` 只有 0.3s。物理按键/热键本身无状态，第 1 下按完显示 `HOLD! press again` 后，若原高危请求在 `t = 0.4s` 因会话 `Stop`/超时撤下、队列切到另一会话的低危请求并在 `t = 0.42s` 完成渲染，用户在 `t = 0.85s`（距第 1 下仅 0.45s，属正常连按节奏，且距切换已过 0.43s > 0.3s）按下“第 2 下确认键”时，`USBKeys`/`HotkeyKeys` 会自动填入新低危请求的 nonce，一次按键直接将其放行。
* **复现方式**：
  入队高危请求 A 和低危请求 B；按第 1 下 `approve` 使 A 进入 `confirm`；立即向 A 所属会话发 `Stop` 事件使 A 取消、B 上屏渲染；等 0.35s（仍在 1.5s 二次确认心理预期内）按第 2 下物理 `approve` 键，B 被直接 `allowed`。
* **建议改法**：
  在 Hub 记录最近一次高危 `armed` 的 `(request_id, armed_at)`；若该请求在 `CONFIRM_SECONDS`（1.5s）内未经该用户主动切槽而消失/切换，则在这 1.5s 剩余窗口内对新顶上来的请求延长 `switch_guard`（或要求物理端绑定上次 armed 请求失配时先拦截一次提示已切换）。

#### [P1-4] `Hub._send(..., focus=True)` 在持有 `Hub.lock` 内死等 150ms，且 `retry_for=0.0` 遇串口争用失败后会锁死硬件审批长达 20 秒
* **文件与位置**：
  * [hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L183-L208)（`Hub._send`）、[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L474-L476)（`Hub.event`）、[hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L716-L721)（`Hub.maintain`）
  * [agent_lcd.py](file:///D:/desk/hardware/h1/pc/agent_lcd.py#L43-L68,L160)（`send`、`ensure_watcher`）
  * [daemon.py](file:///D:/desk/hardware/h1/pc/daemon.py#L168-L169)（`ForegroundWatcher.tick`）
* **问题**：
  1. `agent_lcd.send` 的读循环 `while time.time() - t1 < wait_reply: reply += s.read(256)` 不会因收齐回显提前退出。`hub.py:190` 新增 `wait_reply=0.15` 后，每次 `_show()`（新请求、切槽、高危首按、请求结束、心跳）都在持有全局 `Hub.lock` 的状态下硬睡 **150ms+**，阻塞所有 `/state`、`/action`、`/event`。
  2. 真实环境中 `agent_lcd.py hook` 与 `hub_relay.py` 并存（[hub_README.md](file:///D:/desk/hardware/h1/pc/hub_README.md#L24-L25)），且 `agent_lcd.py` 会拉起 `daemon.py`（其 `list` 查询在 `focus_lock` 外占串口 200ms），外加 `Hub.event` 第 474 行刚调完 `_publish()` 开关一次 COM4，第 476 行紧接着 `_show()` 又以 **`retry_for=0.0`（零重试）** 重开 COM4。一旦撞上串口忙抛异常，第 206 行仍把 `self.last_focus` 设为当前时间，`maintain()` 要等 `daemon.HEARTBEAT`（**20 秒**）后才重试 `_show()`！这 20 秒内若没开浮窗，物理按键全部报 `409 stale_nonce`。
* **复现方式**：
  真机连接 COM4，保留 `agent_lcd.py` hook 与 `daemon.py`，不加 `--overlay` 启动 `hub.py --backend usb`；触发 `PermissionRequest` 时若 `agent_lcd.py` 或 `daemon.py` 正占着 COM4，`Hub._show()` 打一条 `LCD unavailable` 警告，随后 20 秒内按宏键盘 `G`/`Ctrl+F` 全部失败。
* **建议改法**：
  1. 串口收发移出 `Hub.lock`（锁内只生成待发快照与版本号，回执回来再对比版本号调 `record_rendered`），并在收齐预期行数后立即退出读循环，消除 150ms 持锁卡顿；
  2. `Hub.event` 中即将 `_next_request()` 时不要先重复调一次无回执的 `_publish()`；
  3. 发送失败且 `rendered_request["request_id"] != displayed_request_id` 时，不要把下次重试推迟 20 秒，应在 `maintain()`（每 0.2s）按短退避（如 0.5～1s）重发 `_show()`。

#### [P1-5] 1602 LCD 宽度计算未考虑板上非 Hub 会话（如 DeepSeek），短名拼上 nonce 后会触发跑马灯截断 nonce 并挤走原项目名；且常规项目名与路演 Demo 在 LCD 上完全不显示 nonce
* **文件与位置**：
  * [hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L253-L262)（`Hub._display_name`）
  * [ui.py](file:///D:/desk/hardware/h1/lcd1602/ui.py#L299-L305,L350-L360)（`UI.ribbon`、`UI.render`）
  * [hub_virtual_device.py](file:///D:/desk/hardware/h1/pc/hub_virtual_device.py#L177-L188)（`request_line`）
* **问题**：
  1. `hub.py:258` 用 `width = 13 - max(5, len(self.sessions) + 1)` 计算剩余格数，只算了 Hub 内部的 `cc`/`cx` 会话数，而 1602 固件 `ui.py:304` 的小图标条 `tail` 按板上**全部会话数**（含 `dsh_watch.py` 写入的 `ds-*` 及未过期旧会话，最多 8 个）占用右侧列。当 Hub 有 ≤4 个会话、项目名为 3 字符 `"app"` 时，`hub.py` 算得 `width=8` 发出 `"app abcd"`（8 字符）；若板上共有 6～8 个会话，`ui.py` 实际 `width` 只有 **4～6 格**，前 2 秒截掉末尾 `"cd"` 只显示 `"app ab"`（看错/看不全 nonce），2 秒后跑马灯右滚把原项目名 `"app"` 挤出左边界！
  2. 反过来，由于 `len(name) + 5 <= width` 过于苛刻，1～4 会话只允许 ≤3 字符项目名，5 会话（`hub_demo.py` 全部 5 个会话）只允许 ≤2 字符，6 会话只允许 ≤1 字符，且 `GATE:` / `HOLD! press again` / `LOCKED:` 全不显示——**实际路演 Demo 中 1602 屏一次都不会出现 nonce**。
  3. 虚拟设备 `request_line` 在 60 字摘要上限后直接追加 `" #%04x"`（共可达 82 字符），未缩减摘要截断长度，宽字符下会向右溢出 640px 黑色条屏画到银色机身上。
* **复现方式**：
  在 `test_ui.py` 的 `make_ui()` 中先注入 4 个 `ds-*` 会话，再注入 Hub 对 3 字符项目 `"app"` 生成的 `set cc-a1 wait app abcd` 和 `set cx-b2 idle x`（共 6 个板上会话），调 `ui.render(0)` 可见第二行变成 `\x02\x03 app ab ......`（`cd` 被截断），`ui.render(2800)` 变成 `\x02\x03 p abcd ......`（`ap` 被挤掉）。
* **建议改法**：
  * 若坚持不改动静态布局不滚动，不能假设板上只有 `len(self.sessions)` 个会话（或应在连接时结合 `list` 会话数保守按 `MAXSESS` 留空，但这会让静态空间只剩 4 格根本放不下），建议在文档和简报交付中明确说明“1602 仅在极短名且板上总会话 ≤4 时静态显示，其余以浮窗/虚拟设备为准”，并补跑真实 `ui.UI.render()` 测试；
  * `hub_virtual_device.py:178` 将 `summary` 截断上限从 `60` 缩至 `54`（预留 `" #abcd"` 的 6 字符）。

#### [P1-6] 测试套件大量依赖手工注入状态与 Mock，漏测真实组件集成
* **文件与位置**：
  * [test_hub_nonce.py](file:///D:/desk/hardware/h1/pc/test_hub_nonce.py#L29-L41,L408-L428)
  * [test_hub_overlay.py](file:///D:/desk/hardware/h1/pc/test_hub_overlay.py#L87-L101,L155-L164)
  * [test_hub_hotkey.py](file:///D:/desk/hardware/h1/pc/test_hub_hotkey.py#L15-L36)
  * [selftest_hub_replay.py](file:///D:/desk/hardware/h1/research/selftest_hub_replay.py#L210-L212)
* **问题**：
  1. `test_hub_overlay.py` 用 `Mock()` 代替真 `Hub`，甚至把真 `Hub` 必抛 `409 stale_nonce` 的 `nonce: None` 断言为 `"allowed"`；
  2. `test_hub_nonce.py` 33 项中有 32 项绕过 `Hub.event` 手塞 `Pending`，LCD 回执测试手写错误的 `'ok set %s idle'` 假回显，LCD 后四位测试只断言 Python 字符串未过 `lcd1602/ui.py`；
  3. `selftest_hub_replay.py` 手动把 `/state` 队首抄进 `target.rendered_request`；
  4. Windows `HotkeyInput.run()` 从未与真 `Hub` 联测。
* **复现方式**：
  把 `test_hub_overlay.py:93` 的 `self.hub = Mock()` 换成真实 `hub.Hub(...)`，该测试立即因 `HubError('stale_nonce', 409)` 失败。
* **建议改法**：
  补充真实 `Hub` + `Overlay`（测按下/松开 `switch_guard`）、真实 `Hub` + `VirtualDevice`、真实 `Hub` + Windows `HotkeyInput.run()`、以及真实 `Hub` + `lcd1602/ui.UI` 的端到端离线集成测试。

---

### P2（边界退化与实现瑕疵）

#### [P2-1] USB `interrupt` 在空闲按下遭遇新请求并发到达时会误拒新请求（与热键行为不一致）
* **文件与位置**：
  * [hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L600-L602,L897-L898) vs [hub_hotkey.py](file:///D:/desk/hardware/h1/pc/hub_hotkey.py#L78-L83)
* **问题**：
  `HotkeyKeys.dispatch` 专门保留了 `if self.hub.displayed_request_id != request_id: return False` 防止 `request_id=None`（按键时无请求，用户本意发 Esc 中断终端）被 `Hub.action` 当成“未传 `request_id`”而拒绝刚到达的新请求；但 `USBKeys._dispatch` 删掉了锁内比对，直接发 `payload["request_id"] = shown["request_id"]`（为 `None`），`Hub.action` 第 601 行 `if expected is not None` 放过，导致新到达的待批请求被静默 `deny`。
* **复现方式**：
  `rendered_request` 为 `{None, None}` 时按下 USB `interrupt` 键，若进锁前恰好有 `PermissionRequest` 入队，该请求直接返回 `status: "denied"` 而非报请求已变化。
* **建议改法**：
  在 `Hub.action` 中用 `"request_id" in payload` 区分“显式传了 `request_id: None`（断言当前无请求）”与“未传 `request_id` 字段”，当 `"request_id" in payload and payload["request_id"] != self.displayed_request_id` 时统一返回 409。

#### [P2-2] 默认启动脚本与 CLI 未提供开启 `require_nonce` 的入口，且 `locked` 记录超过 110s 后按键从返回 `locked` 变为狂写 `stale_nonce` 审计
* **文件与位置**：
  * [hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L134,L531-L536,L916-L952)
  * [start_agentdeck.bat](file:///D:/desk/hardware/h1/start_agentdeck.bat#L8)、[start_agentdeck_demo.bat](file:///D:/desk/hardware/h1/start_agentdeck_demo.bat#L17)
* **问题**：
  1. `hub.py` CLI 没有 `--require-nonce` 参数，演示/启动脚本也未开启 `require_nonce`，线上实际运行处于不强制校验 nonce 的兼容态；
  2. `critical` 请求进入 `self.locked` 后不会随 110s `_expire()` 清除（要等会话下一条普通事件才清除），110s 内按硬件键返回 `200 {"status": "locked"}` 不记审计，110s 后按硬件键却因 `monotonic() >= request.deadline` 每次抛 `409 stale_nonce` 并写审计。
* **复现方式**：
  触发一条 `critical` `PermissionRequest`，等 111 秒后按浮窗/热键/USB 键，返回变为 `409 stale_nonce` 并不断往 `audit.jsonl` 追加记录。
* **建议改法**：
  在 `hub.py` 增加 `--require-nonce` 并在 `start_agentdeck*.bat` 中启用；`_validate_decision` 中对 `request.status == "locked"` 且 `nonce == request.nonce` 的当前显示记录跳过 `deadline` 报错，保持一致的 `status: "locked"` 响应。

#### [P2-3] `Pending` 默认工厂绕过 `issued_nonces`，且 `issued_nonces` 常驻内存无上限
* **文件与位置**：
  * [hub.py](file:///D:/desk/hardware/h1/pc/hub.py#L117,L167,L244-L251)
* **问题**：
  `Pending` 的 `default_factory=lambda: secrets.randbits(32)` 未注册进 `issued_nonces`；同时 `issued_nonces` 集合在长生命周期进程中只增不减。
* **复现方式**：
  直接构造 `Pending(...)` 不会写入 `engine.issued_nonces`；持续运行产生百万级请求时集合常驻增长。
* **建议改法**：
  将 `Pending.nonce` 改为必填或统一由 `Hub` 工厂函数构造；`issued_nonces` 可用定长 FIFO/OrderedDict（如保留最近 10 万个）兼顾防碰撞与有界内存。

---

## 三、一句话总结

目前**不能**直接按 BP/PRD 原话对投资人说“已实现设备端 nonce 校验”——因为硬件固件与 USB 协议并未回传 nonce（只是 PC 端 Hub 代填渲染快照，且路演时 1602 屏根本不显示 nonce），同时软件层还存在浮窗按下/松开绕过 300ms 切换保护、双屏覆盖串单、无浮窗无 LCD 模式按键全挂及空闲按键写坏审计字段四个 P0 缺陷，必须先修完 P0 并在演示环境开启 `require_nonce: true`，对外也只能严谨表述为“已在 Hub 中枢与桌面端实现请求 nonce 绑定和切换防误触校验，v2 量产固件再落地设备原生回传”。
