# Hub nonce-fix1 结果

2026-11-18，按用户要求先完成独立只读审查，再完整读取 Carbon nonce 审查后修复。第一件报告为 [review-codex-on-carbon-overlay.md](review-codex-on-carbon-overlay.md)，保留修复前结论和基线行号；第二件实施计划为 [nonce-fix1-plan.md](nonce-fix1-plan.md)。已有 `_rollback/nonce-fix1/` 未覆盖。没有打开 COM4、USB 设备、系统热键或真实浮窗，没有操作运行中的 Hub，没有修改固件。

全部 P0、P1-1～P1-6 的软件问题已处理并验证；P2-1、P2-2 已处理，P2-3 强制显式 nonce 已处理，内存淘汰建议未采用，理由和剩余风险见下。

## 逐条回应 Carbon nonce 审查

下列测试均来自最终真实执行的套件；没有把 Mock.action 的 `allowed` 当成实际审批证据。`NI` 指 `pc/test_hub_nonce_integration.py`，`IC` 指 `pc/test_hub_input_capture.py`，`VI` 指 `pc/test_hub_virtual_nonce_integration.py`。

| 编号 | 意见 | 修复与验证 |
| --- | --- | --- |
| P0-1 | 同意 | 浮窗在 ButtonPress 入口保存 Hub 单调时间，在 ButtonRelease 传入内部 `received_at`；服务端按 overlay 自己的渲染时刻再检查。虚拟设备在绘制完成后经认证 `/rendered` 上报，按下时本地检查300ms，未满足时根本不进入异步动作队列；服务端再核对 `display_source: virtual`。测试：NI.`test_overlay_press_in_guard_cannot_become_valid_at_release`、`test_delayed_overlay_render_has_own_guard_while_lcd_stale`；VI.`test_delayed_first_draw_has_its_own_guard_and_worker_delay_cannot_approve`、`test_press_time_precedes_window_callback_delay`。 |
| P0-2 | 同意 | `rendered_by_source`、各源渲染时间与活跃集合分开保存，USB/热键只有各活跃源一致才使用共同快照；冲突生成不可审批的空绑定。一屏的刷新不会覆盖另一屏的证据。首次迟到的实际渲染也重新开始物理输入保护。窗口自身点击按自己的显示来源校验。测试：NI.`test_lcd_cannot_overwrite_stale_overlay_and_reverse`、`test_async_old_lcd_ack_does_not_retarget_approval`、`test_first_late_render_restarts_physical_guard_even_same_headless_binding`；IC.`test_real_hub_queued_deny_uses_original_render_history`。 |
| P0-3 | 同意功能回归；明确降级语义 | 无任何成功显示回执时，采用终端 `headless` 当前请求绑定，USB/热键仍能批准/拒绝；`/state.input_mode` 与 `input_request` 明示该策略，不能把它称为“最后实际渲染”。虚拟设备成功绘制后成为独立显示来源。隐藏浮窗时保留已见请求的绑定，后继未显示请求不能继承；新请求使浮窗重现。已成功显示的 LCD 后来失败时，保留其旧快照并拒绝串单，不盲目切到 headless。测试：NI.`test_headless_hotkey_and_usb_approve_and_deny`、`test_hide_keeps_seen_request_usable_and_hub_http_alive`、`test_hidden_snapshot_cannot_bind_new_unseen_request_then_reappears`；VI.`test_render_http_auth_and_source_publication`。 |
| P0-4 | 同意 | 当前和按键快照均为空时返回 `no_request`，不写审计；异常 nonce 拒收仍写审计，无请求时补齐固定字段，`risk/agent/...` 使用 null、command为空。文档要求统计最终决定时过滤 `decision`，不能把拒收记录计为执行次数。测试：NI.`test_idle_key_is_no_request_without_audit_and_bad_nonce_has_full_schema`（同时验证完整哈希链）；replay 审计检查。 |
| P1-1 | 同意缺陷；采用历史快照与积压屏障 | Windows消息按 `received_at-age` 查询不可变快照历史，而非出队时的新快照；前序动作成功、失败、修饰键等待超时均在 finally 更新完成屏障，丢弃忙碌期间排队的决定。未额外引入泵线程：历史查找已能还原旧绑定，且减少线程生命周期复杂度。Win32 age 加16ms保守余量；过旧/历史不可用时拒收。测试：IC.`test_real_hub_failed_action_cannot_retarget_queued_deny`、`test_real_hub_queued_deny_uses_original_render_history`；原热键套件。 |
| P1-2 | 同意 | USBInput 在读包后先一次捕获 `t` 与 `USBKeys.snapshot()`，再查前台；同包全部按下/松开共用此 context。USBKeys 使用事件原时间，校验有限数值；USBKeys、HotkeyInput 默认继承 Hub 时钟，CLI也向 USBInput传相同时钟。测试：IC.`test_usb_same_report_shares_timestamp_and_snapshot`、`test_usb_report_context_captures_before_foreground_query`、`test_hotkey_default_clock_is_hub_clock`；NI.`test_usb_voice_release_delay_cannot_age_same_packet_approval`（真USBInput/ReportState/USBKeys/Hub，语音释放耗时跨过保护期仍拒绝）。 |
| P1-3 | 同意 | Hub 记录最近的高危确认目标和1.5秒窗口；原请求取消后，USB/热键在剩余窗口内不能单击批准后继低危请求。后继高危仍有自己的第一次确认；主动切槽清除旧意图。测试：NI.`test_cancelled_high_confirmation_cannot_approve_next_low_request`；原高危/闸门二次确认测试仍通过。 |
| P1-4 | 同意 | 生产串口发送使用后台队列，锁内只提交命令及不可变请求快照；锁外收发，完整回执后回锁登记对应LCD快照。旧回执只登记旧目标，不能改批新目标。失败约0.5秒退避重试，不等20秒心跳。`agent_lcd.send(expected_replies=...)` 收齐预期行立即退出读循环。注入的同步 sender默认保留，便于纯协议测试；异步回归显式启用同一生产队列。测试：NI.`test_async_lcd_does_not_hold_hub_lock_and_retries_failure`、`test_async_old_lcd_ack_does_not_retarget_approval`、`test_serial_ack_reader_returns_as_soon_as_complete_reply_arrives`。 |
| P1-5 | 同意实际宽度/截断问题；不采纳无实测依据的“95%以上”比例 | 不再按 Hub 会话数猜板上剩余宽度。旧固件可能同时有8个会话，保证只余4格，放不下项目名加5字符后缀，因此保守省略LCD名称nonce后缀，恢复原标签；浮窗与虚拟设备负责末4位核对。这项取舍在README中明确，不再宣称1602显示了nonce。虚拟设备摘要预留后缀，并按宽字符和Tk真实字体测量限制像素宽度，保留风险/nonce。测试：NI.`test_lcd_actual_protocol_ack_and_external_sessions_preserve_name`（真 `UI.handle/render`，7个外部会话+1个Hub会话，多时间点检查LCD字节）；VI.`test_request_line_reserves_nonce_and_bounds_wide_summary`、`test_canvas_font_measurement_keeps_wide_line_and_nonce_inside_strip`。 |
| P1-6 | 同意 | 新增真 Hub.event 请求线程，连接真实 Overlay、VirtualDevice/HubClient/HTTPServer、HotkeyInput.run消息队列、USBInput/ReportState/USBKeys、固件UI；只替换Tk/操作系统/设备边界。replay删除手工抄队首到rendered_request的做法，改读真实Hub公开的headless输入绑定，并打开 `--require-nonce`。测试：NI16项、IC5项、VI7项，另有位置测试10项；完整发现套件451项通过。原Mock展示单测保留为展示/回调接线测试，已更新按下时间和隐藏语义，不将其当成审批证明。 |
| P2-1 | 同意 | 统一按 `"request_id" in payload` 区分显式空目标与省略目标，空闲按下的interrupt不能拒绝之后出现的新请求。虚拟设备Ctrl+拒绝也携带绘制目标。测试：NI.`test_explicit_empty_interrupt_cannot_deny_new_request`；replay interrupt链路。 |
| P2-2 | 同意 | 新增CLI `--require-nonce`，两个启动bat启用；已运行进程不受此次文件修改影响。当前critical locked条目匹配nonce时，过原审批deadline仍稳定返回locked，不放行也不反复写拒收审计；错误nonce仍拒绝。测试：`test_hub_nonce.py::test_locked_wrong_nonce_rejects_but_matching_locked_stays_locked_after_deadline`、既有配置开关测试；开启严格模式的真实进程replay。 |
| P2-3 | 部分同意，拒绝FIFO建议 | `Pending.nonce` 改为必填关键字，Hub.event统一从 `_new_nonce()` 分配；单测构造也走Hub工厂。保留进程生命周期 `issued_nonces`，不做FIFO淘汰：淘汰过期值后，32位随机碰撞可能重用旧值，违背“本进程过期nonce不复活”的约定。测试：`test_hub_nonce.py::test_real_requests_resample_expired_nonce_collision_before_accepting_replay`、`test_nonce_is_random_32_bit_and_public`。剩余风险：集合内存随请求数增长；跨重启也不保证数值永不重复。 |

## 第一件独立审查的重叠修复

| 原审查项 | 处理 | 证据 |
| --- | --- | --- |
| overlay P1-1 隐藏后输入失效 | 同意并修复；仅撤销overlay活跃状态，保留已见目标，阻止后继未显示请求继承 | NI隐藏/HTTP存活与新请求重现测试；P0-2/P0-3 |
| overlay P1-2 多屏/DPI位置 | 同意并修复；枚举Windows各显示器工作区，在创建Tk前采用线程per-monitor DPI上下文；原生SetWindowPos支持负绝对坐标；启动、拖动、展开/收回、工作区拓扑变化后约束窗口完整边界，避开任务栏，保存位置与透明度 | `pc/test_hub_overlay_position.py` 10项：左右/上副屏、重启恢复、拔屏、任务栏、展开、缩放后工作区、原生调用签名和DPI上下文恢复；真实混合DPI仍未实机验收 |
| overlay P1-3 profile与文档不一致 | 同意并修复；默认实测布局保持，历史v2_emulation明确标注Space/Q/V为槽位4/5/6、Ctrl+0为interrupt；所有profile禁用Ctrl+C/V，删除旧Ctrl+V猜测绑定，保留其他历史映射 | NI.`test_measured_idle_keys_decode_into_real_hub_effects_in_both_profiles` 从字面USB报文解码到真Hub及替代桌面效果，验证六个新键和留空键；replay历史六槽位布局与旋钮测试 |
| overlay P2-1 字符串/Mock自证 | 同意并补真组件验证，原展示测试不冒充端到端覆盖 | 新增38项测试、replay不再伪造渲染 |

## 文件变更与简化

- 生产代码：`pc/hub.py`、`pc/hub_overlay.py`、`pc/hub_hotkey.py`、`pc/hub_virtual_device.py`、`pc/deck_usb.py`、`pc/agent_lcd.py`。
- 配置/入口/说明：`pc/hub_keys.json`、`pc/hub_keys.md`、`pc/hub_README.md`、`start_agentdeck.bat`、`start_agentdeck_demo.bat`。
- 更新旧测试：`pc/test_hub_nonce.py`、`pc/test_hub_overlay.py`、`pc/test_hub_virtual_device.py`、`pc/test_hub_macos_fix.py`、`research/selftest_hub_replay.py`。
- 新增测试：`pc/test_hub_nonce_integration.py`、`pc/test_hub_input_capture.py`、`pc/test_hub_virtual_nonce_integration.py`、`pc/test_hub_overlay_position.py`。
- 研究/证据：本报告、独立审查、两个修复计划、最终测试TXT/JSON；`pc/sim.py`重新生成 `lcd1602/preview-sim.png`，未修改固件源码。
- 简化：删除错误的LCD按Hub会话数拼后缀逻辑、重复的随机nonce默认工厂、Ctrl+V猜测映射和replay手填渲染快照；复用现有Hub.action、串口协议、热键适配器与标准库，无新增依赖。

## 最终实跑结果

Python为 `D:/conda/miniconda3/python.exe`。完整命令与原始输出见 [hub-nonce-fix1-tests.txt](hub-nonce-fix1-tests.txt)，机器可读结果及受保护文件hash见 [hub-nonce-fix1-test-summary.json](hub-nonce-fix1-test-summary.json)。

```text
python -m unittest discover -s pc -p 'test_hub*.py'
Ran 451 tests in 14.884s
OK

python research/selftest_hub_replay.py
12 PASS / 0 FAIL

python pc/test_ui.py       -> UI: 7 groups passed
python pc/test_daemon.py   -> daemon offline tests: 10 groups passed
python pc/test_pc.py       -> PC and firmware loop: 4 groups passed
python pc/test_deck_usb.py -> 24 groups passed
python pc/sim.py           -> Rendered 42 scenarios -> D:\desk\hardware\h1\lcd1602\preview-sim.png

AST/compile/tabnanny: 15 changed Python files passed
```

项目没有Python lint/typecheck配置，当前环境没有ruff/mypy/pyflakes，未新增依赖；完成标准库AST、编译、缩进静态检查。回归中的 `simulated busy serial`、`stale_nonce`、`switch_guard`、USB不可用日志来自故障注入和预期拒收，所有命令退出码为0。修复前新增NI首8项全部失败；输入IC首5项全部失败；位置首6项全部失败；虚拟设备复现过2 FAIL+1 ERROR，之后均转绿。只读二次复核发现的“LCD滞后时浮窗迟到渲染仍需自己的guard”也已修复并加入回归。

两个禁止修改文件在开始与结束时SHA-256相同：

```text
pc/verify_real_session.py
83448a4ceb82c90fe3754417a15664a72a0c4dc932f0079d89dfaef69faceb61
pc/test_verify_real_session.py
204ae2f37107859bcf308f10a0cc62999e7c8c3e6e5edc85c06ad6bba20c1f4b
```

## 交付边界与对投资人的表述

真实USB硬件、1602像素、系统热键和混合DPI浮窗仍需用户实机验收。串口回显不是渲染回执，物理键盘没有原生nonce回传；无屏模式是终端逻辑绑定降级。多活跃屏不一致时选择拒收，可能暂时降低可用性；已发nonce集合增长是保留的P2风险。此次没有重启当前运行的Hub，也没有改动PRD/BP原文；PRD第337/338行的“nonce未做”应替换为下句，并保持硬件阶段边界。

**对投资人的严谨一句话：已在 Hub 与桌面前端实现并通过离线集成测试验证请求 nonce 绑定、过期拒收和切换防误触，现有物理键盘由 PC 代填绑定、尚未实现设备原生 nonce 回传，硬件闭环仍待固件落地与实机验证。**
