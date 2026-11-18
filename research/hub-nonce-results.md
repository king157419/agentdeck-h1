# 审批 nonce 校验交付

已按 `research/brief-hub-nonce.md` 实现。改前快照保存在 `_rollback/hub-nonce/`，没有覆盖旧备份。没有修改固件、hook 协议、风险规则或真实用户配置，没有打开 COM4，也没有启停正在运行的 Hub。`pc/verify_real_session.py` 和 `pc/test_verify_real_session.py` 未读取、未修改。

## 改动文件

| 文件 | 改动 |
| --- | --- |
| `pc/hub.py` | 32 位随机 nonce、进程内碰撞重抽、状态公开、强制配置、校验/审计、接收时刻切换保护、LCD 回执与渲染快照、短名称 nonce 后缀 |
| `pc/hub_hotkey.py` | 捕获最后渲染的请求/nonce；保留 OS 事件的接收时刻，贯穿修饰键释放和锁等待 |
| `pc/hub_hotkey_mac.py` | 回调进入时保存渲染快照和接收时刻，随后才等待适配器锁或入队 |
| `pc/hub_overlay.py` | 显示 nonce 后四位；按钮按下时绑定 nonce；可见画面刷新成功后才记录渲染 |
| `pc/hub_virtual_device.py` | 显示 nonce 后四位；点击取最后成功绘制的请求，避免异步轮询抢先更新审批对象 |
| `pc/hub_README.md` | 配置、HTTP 错误、切换保护、后端渲染语义及审计说明 |
| `pc/test_hub_nonce.py` | 新增 33 项 nonce、过期、竞态、配置和 HTTP 验收测试 |
| `pc/test_hub.py` | 既有测试等待切换保护期结束；保持原审批断言 |
| `pc/test_hub_gate.py` | 既有闸门测试等待保护期结束 |
| `pc/test_hub_hotkey.py` | nonce 替身接口及 macOS 回调/排队/适配器锁回归 |
| `pc/test_hub_overlay.py` | 按下到释放的 nonce 绑定、渲染成功与不可见窗口回归 |
| `pc/test_hub_virtual_device.py` | nonce 显示、异步状态抢先更新和绘制失败回归 |
| `research/selftest_hub_replay.py` | 为离线回放显式提供冻结的模拟显示快照；等待 300 ms 保护期 |

保留统一的 `Hub.action` 审批路径、现有哈希链审计和 LCD `set`/`focus` 协议，没有增加依赖或另一套审批状态机。

## 要求与测试对应

以下名称除标注外均在 `pc/test_hub_nonce.py`。

| 要求 | 测试名 |
| --- | --- |
| 1. 随机 32 位 nonce 随请求公开到 `/state` | `test_nonce_is_random_32_bit_and_public`；`test_real_requests_resample_expired_nonce_collision_before_accepting_replay` |
| 2. 当前请求 nonce 一致放行 | `test_matching_nonce_approves` |
| 2. 不一致、其他待批请求、错误 ID 拒收且无状态变化 | `test_mismatch_rejects_without_mutation`；`test_non_displayed_pending_nonce_rejects`；`test_correct_nonce_wrong_request_id_rejects` |
| 2. 非整数、NaN 和嵌套无效值拒收 | `test_invalid_nonce_types_never_coerce`；`test_malformed_nan_and_nested_nonce_values_are_auditable` |
| 2. HTTP 409、原因和审计 | `test_http_stale_nonce_returns_409`；`test_rejected_nonce_and_guard_are_audited` |
| 2. 300 ms 切换保护，deny 豁免 | `test_initial_switch_guard_and_boundary`；`test_guard_allows_exact_300ms_boundary`；`test_queue_switch_restarts_guard_and_deny_is_exempt`；`test_deny_is_exempt_from_initial_guard` |
| 2. 到达保护期内，等锁到保护期外仍拒收 | `test_http_action_receipt_guard_survives_same_request_lock_contention`；`test_hotkey_modifier_wait_preserves_original_guard_receipt`；`test_usb_guard_uses_callback_receipt_before_same_request_lock_wait`；`test_json_received_at_cannot_bypass_switch_guard` |
| 2. 高危第二次 nonce 错误保持待确认状态 | `test_high_risk_second_wrong_nonce_preserves_armed_state`；`test_high_and_critical_gates_preserve_armed_state_on_wrong_second_nonce` |
| 2. 不改变 critical 的终端确认规则 | `test_locked_request_accepts_current_nonce_without_unlocking`；`test_locked_wrong_or_expired_nonce_rejects_without_mutation`；回放 critical 场景 |
| 3. 浮窗取按钮按下时画面的 nonce | `test_nonce_is_captured_at_press_before_refresh`（`test_hub_overlay.py`） |
| 3. 渲染成功才发布，启动不可见窗口不发布 | `test_render_snapshot_recorded_only_after_successful_idle_update`；`test_withdrawn_startup_does_not_acknowledge_invisible_render`（`test_hub_overlay.py`） |
| 3. 虚拟设备取最后成功绘制的 nonce | `test_worker_state_change_before_redraw_uses_drawn_nonce`；`test_failed_draw_does_not_publish_worker_nonce`（`test_hub_virtual_device.py`） |
| 3. 热键取最后渲染而非当前队首，锁等待不重绑 | `test_hotkey_uses_last_rendered_request_after_logical_switch`；`test_hotkey_snapshot_is_copy_and_survives_dispatch_lock_wait` |
| 3. USB 在回调入口取渲染快照 | `test_usb_captures_rendered_snapshot_before_lock_contention` |
| 3. macOS 回调在排队/适配器锁之前取快照与时刻 | `test_callback_snapshot_survives_display_change_before_queue_drain`；`test_callback_receipt_precedes_adapter_lock_contention`（`test_hub_hotkey.py`） |
| 3. 默认无 nonce HTTP 兼容、强制配置和类型校验 | `test_legacy_missing_nonce_works_after_guard`；`test_require_nonce_rejects_missing_approve_but_keeps_legacy_deny`；`test_require_nonce_constructor_requires_strict_boolean`；`test_main_forwards_require_nonce_from_explicit_config` |
| 4. nonce 后四位十六进制 | `test_short_lcd_name_displays_low_four_hex_digits`；`test_nonce_is_captured_at_press_before_refresh`（浮窗）；`test_actions_and_display_include_nonce`（虚拟设备） |
| 4. LCD 失败/空回执不冒充渲染成功 | `test_lcd_failed_send_preserves_rendered_snapshot_and_ack_publishes` |
| 5. 110 s 边界失效、维护之后也不能重放 | `test_expiry_boundary_rejects_without_expiring_or_arming`；`test_expired_nonce_cannot_replay_after_maintenance_and_new_request`；`test_real_requests_resample_expired_nonce_collision_before_accepting_replay` |

## 真实验证输出

Python 均为 `D:/conda/miniconda3/python.exe`。完整输出见 `research/hub-nonce-tests.txt`，汇总见 `research/hub-nonce-test-summary.json`。

| 命令 | 结果 |
| --- | --- |
| `python -m unittest discover -s pc -p "test_hub*.py"` | `Ran 403 tests in 10.147s` / `OK` |
| `python research/selftest_hub_replay.py` | `12 PASS / 0 FAIL` |
| `python pc/test_ui.py` | `UI: 7 groups passed` |
| `python pc/test_daemon.py` | `daemon offline tests: 10 groups passed` |
| `python pc/test_pc.py` | `PC and firmware loop: 4 groups passed` |
| `python pc/sim.py` | `Rendered 42 scenarios -> D:\desk\hardware\h1\lcd1602\preview-sim.png` |
| 改动的 12 个 Python 文件语法、缩进静态检查 | 全部通过 |

403 是实际测试执行次数；`test_hub.py` 会再次导入并运行其他测试模块，因此去重后是 **331 个唯一用例**。其中 nonce 专项 33 项、浮窗 22 项、虚拟设备 15 项、热键 36 项均通过。仓库没有配置 lint/typecheck 命令，本次未添加依赖来补装检查器。

## 兼容范围与剩余验证

- `require_nonce` 默认 `false`，HTTP 不带 nonce 仍可审批；切换后的 300 ms 保护对所有 approve 生效。开启后缺 nonce 的 approve 返回 409 `nonce_required`；deny 保持兼容。带错 nonce 无论开关如何都拒收。
- LCD 的“已渲染”使用现有命令完整回执确认；没有修改固件增加画面回执。真实 LCD 时序、物理 USB 输入以及 Windows/macOS 实际窗口仍需用户真机验证。此次全部使用替身、临时目录或独立临时 Hub。
- 没有 LCD 或可见浮窗渲染时，热键/USB 的 nonce 审批会拒收；独立虚拟设备点击和直接 HTTP 调用仍可用。离线报文回放使用显式模拟显示，不能代替真机渲染验证。
- 已发行 nonce 在本 Hub 进程生命周期内不再复用；此保留集合不跨 Hub 重启持久化。内置界面和输入后端同时携带请求 ID，旧请求 ID 在重启后也不匹配。

## PRD 第 337 行建议改写

> **为什么叫 Hardware 2FA**：第一因子是 agent 自己的判断（auto mode / 规则），第二因子是人手在一块独立设备上的物理确认。Hub 已实现请求 nonce 校验：浮窗和虚拟设备回传画面中的 nonce，热键和 USB 宏键盘绑定按键到达时最后渲染的请求 ID 与 nonce；错配、过期及切换后 300 ms 内的批准均拒收并审计。HTTP 默认兼容无 nonce 调用，可用 `require_nonce: true` 强制批准携带 nonce。焦点在哪个窗口都不影响审批对象；物理设备回报 nonce 的原生协议仍待后续固件实现。

PRD 第 338 行的“nonce 校验未做”也应同步替换成上述已实现范围及默认 HTTP 兼容限制。本次提供改写建议，没有直接改动 PRD。

## 审查状态

原生独立只读审查发现的“等锁跨过 300 ms 导致保护失效”和 macOS 适配器锁内打时间戳问题均已修复，最终回归包含对应接收时刻测试。

Carbon 没有给出有效审查结论，不能算审查通过。首次 `agy --model gemini-4-carbon-high --mode plan` 被 headless 自动权限审查拒绝了读取文件所需的 `command` 工具；随后改为把简报/差异直接放入提示词，避免要求工具权限，仍未获得有效结论。最后一次运行在 540 秒后退出，真实结果为 exit 3、`DEADLINE_EXCEEDED`、`response: ""`。完整输出保存在 `research/review-carbon-hub-nonce.md`。没有放宽权限，也没有为此修改用户配置。
