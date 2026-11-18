# AgentDeck 独占模式交付记录

实现、文档与全部离线测试已完成；真机“SendInput 注入事件放行”尚未完成验收，原因是当前沙箱桌面拒绝注入。不能将本次结果标为全部验收通过。

## 按“做完的标准”核对

| 项目 | 结果与证据 |
|---|---|
| 改动前备份 | 5 个既有文件先复制到 `_rollback/deck-v0-exclusive/`，保留相对路径；`manifest.json` 保存 SHA-256，最终校验全部未变 |
| 独占与异步动作 | `run` 默认独占；Raw Input 与 WH_KEYBOARD_LL 同线程，最多等待 50 ms，最近事件有效期 100 ms；动作和日志由队列线程执行 |
| 安全放行 | 非目标、未知设备、注入、超时、歧义均放行；按设备变更通知清理缓存，覆盖拔插后句柄复用 |
| 组合键 | 按设备维护 Ctrl/Shift/Alt/Win；组合优先、裸键回退；修饰键只响应显式绑定；仅首次按下执行动作 |
| 默认映射 | 启用任务书指定的 10 个出厂快捷键；其它键 `unbound`，确认来源后吞掉；旧映射保留在 `_f13_f22_bindings` |
| 关闭独占 | `deck run --no-exclusive` 不安装键盘钩子，保留动作映射；`learn` 保持观察模式 |
| 离线测试 | 8 个测试脚本全部退出码 0，完整输出见下文及 `deck-exclusive-tests.log` |
| 真机 10 秒生命周期 | 运行 10.003 秒，钩子正常安装/卸载，动作线程结束，deck 子进程退出码 0；随后确认 47614 端口空闲，无常驻 deck |
| 真机注入放行 | **未验证通过**：Q/W/R 三次 SendInput 各请求 2 个事件，全部插入 0 个，错误码 5；下游观察数为 0，deck 注入日志也为 0 |
| README | 已更新独占说明、出厂功能映射、关闭方式、备选配置、冒烟命令与限制 |

未打开 COM4、未上传或修改固件、未打开未知 FF00 厂商接口、未写键盘。没有新增依赖。显示输出未变，因此未运行会生成预览图的 `pc/sim.py`。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| [pc/deck.py](../pc/deck.py) | 组合键解析、动作与日志队列、默认独占、--no-exclusive、退出等待线程 |
| [pc/deck_input.py](../pc/deck_input.py) | 低级钩子、两种事件顺序匹配、逐设备修饰键、重复过滤、设备变更与安装/卸载清理 |
| [pc/deck_map.json](../pc/deck_map.json) | 10 个出厂默认绑定、说明、F13–F22 及旧滚轮/音量备选 |
| [pc/test_deck.py](../pc/test_deck.py) | 新默认表与组合规范化验证、异步执行/失败清理、CLI 开关、纳入独占测试 |
| [pc/test_deck_exclusive.py](../pc/test_deck_exclusive.py)（新增） | 9 组离线钩子、设备变更、组合、重复、生命周期测试 |
| [lcd1602/README.md](../lcd1602/README.md) | 宏键盘章节说明与限制 |
| [research/smoke_deck_exclusive.py](smoke_deck_exclusive.py)（新增） | 可复现 10 秒冒烟、带标记的 SendInput、下游观察、正常关闭及结构化结果 |

交付证据新增文件：本报告、[完整测试输出](deck-exclusive-tests.log)、[最终冒烟日志](deck-exclusive-smoke.log)、[冒烟 JSON](deck-exclusive-smoke.json)、[首次失败尝试日志](deck-exclusive-smoke-attempt1.log)。备份目录另有上述 5 份原文件及 [SHA-256 清单](../_rollback/deck-v0-exclusive/manifest.json)。Python 验证产生的 `__pycache__` 为运行缓存。

沿用现有 Raw Input、EventState 和 Controller，在输入边界补上关联逻辑；既有窗口与审批安全门继续复用。F 键方案降为备选，当前默认配置仅保留要求的 10 个绑定。

## 全部测试原始输出

```text
$ D:\conda\miniconda3\python.exe pc/test_ui.py
test_layout_states: PASS
test_marquee: PASS
test_focus: PASS
test_compatibility: PASS
test_priority_rotation: PASS
test_bad_commands_glyphs: PASS
test_dance: PASS
UI: 7 groups passed
Exit code: 0

$ D:\conda\miniconda3\python.exe pc/test_daemon.py
test_mapping: PASS
test_focus: PASS
test_state_machine: PASS
test_log_tick: PASS
test_main_schedule_and_lock: PASS
test_process_snapshot: PASS
daemon offline tests: 6 groups passed
Exit code: 0

$ D:\conda\miniconda3\python.exe pc/test_pc.py
test_names_hooks: PASS
test_ensure_daemon: PASS
test_demo: PASS
test_firmware_loop: PASS
PC and firmware loop: 4 groups passed
Exit code: 0

$ D:\conda\miniconda3\python.exe pc/test_deck.py
test_mapping: PASS
test_list_and_selection: PASS
test_actions_and_logging: PASS
test_approval_guards: PASS
test_window_matching_and_input: PASS
test_foreground_fallback_cleanup: PASS
test_single_instance_and_daemon_launch: PASS
test_cli_and_learn: PASS
test_run_event_dispatch_and_cleanup: PASS
test_action_queue_combo_priority_and_isolation: PASS
test_run_action_thread_and_error_cleanup: PASS
test_deck_input_transitions: PASS
test_deck_input_device_filter: PASS
test_deck_input_packets: PASS
test_deck_input_lifecycle: PASS
test_probe_unknown_interfaces_never_open: PASS
test_probe_readonly_keymap: PASS
test_probe_standard_qmk_usage: PASS
test_probe_transport_rejects_writes_and_bad_responses: PASS
test_probe_failures_close_and_exit_cleanly: PASS
test_probe_matrix_definition_and_missing_dimensions: PASS
test_probe_old_protocol_and_invalid_definition: PASS
test_hook_raw_before_and_after_both_directions: PASS
test_hook_other_unknown_injected_and_timeout_pass: PASS
test_hook_matches_direction_scan_timestamp_and_exact_device: PASS
test_hook_recent_expiry_one_use_ambiguity_and_late_raw: PASS
test_hook_device_change_invalidates_cached_handle_and_recent_evidence: PASS
test_hook_sided_modifiers_and_repeat_suppression: PASS
test_modifiers_per_device_sides_release_and_explicit_binding: PASS
test_hook_fail_open_callback_error_and_reentrancy: PASS
test_hook_lifecycle_install_failure_and_observer: PASS
AgentDeck offline tests: 31 groups passed
Exit code: 0

$ D:\conda\miniconda3\python.exe pc/test_deck_input.py
test_deck_input_transitions: PASS
test_deck_input_device_filter: PASS
test_deck_input_packets: PASS
test_deck_input_lifecycle: PASS
deck Raw Input offline tests: 4 groups passed
Exit code: 0

$ D:\conda\miniconda3\python.exe pc/test_deck_probe.py
test_probe_failures_close_and_exit_cleanly: PASS
test_probe_matrix_definition_and_missing_dimensions: PASS
test_probe_old_protocol_and_invalid_definition: PASS
test_probe_readonly_keymap: PASS
test_probe_standard_qmk_usage: PASS
test_probe_transport_rejects_writes_and_bad_responses: PASS
test_probe_unknown_interfaces_never_open: PASS
deck probe offline tests: 7 groups passed
Exit code: 0

$ D:\conda\miniconda3\python.exe pc/test_deck_keymap.py
test_vendor_report_encoding: PASS
test_vendor_response_decoding: PASS
test_vendor_transport_read_only_and_errors: PASS
test_plan_changes_exactly_eight_keys_and_first_encoder: PASS
test_snapshot_validation_rejects_incomplete_or_guessed_geometry: PASS
test_backup_complete_exclusive_original_and_no_overwrite: PASS
test_apply_backs_up_before_any_write_and_verifies_every_layer: PASS
test_apply_readback_mismatch_and_partial_failures_restore_backup: PASS
test_rollback_failure_is_reported_with_backup: PASS
test_second_interrupt_during_rollback_preparation_still_restores: PASS
test_restore_uses_complete_backup_and_rejects_geometry_mismatch: PASS
test_show_layer_zero_names_and_encoder_directions: PASS
test_real_cli_gate_never_opens_or_sends_even_with_fake_supported_usage: PASS
Keymap offline tests: 13 groups passed
Exit code: 0

$ D:\conda\miniconda3\python.exe pc/test_deck_exclusive.py
test_hook_raw_before_and_after_both_directions: PASS
test_hook_other_unknown_injected_and_timeout_pass: PASS
test_hook_matches_direction_scan_timestamp_and_exact_device: PASS
test_hook_recent_expiry_one_use_ambiguity_and_late_raw: PASS
test_hook_device_change_invalidates_cached_handle_and_recent_evidence: PASS
test_hook_sided_modifiers_and_repeat_suppression: PASS
test_modifiers_per_device_sides_release_and_explicit_binding: PASS
test_hook_fail_open_callback_error_and_reentrancy: PASS
test_hook_lifecycle_install_failure_and_observer: PASS
deck exclusive offline tests: 9 groups passed
Exit code: 0
```

## 编译与静态检查原始输出

```text
pc/deck.py: py_compile / AST / tabnanny PASS
pc/deck_input.py: py_compile / AST / tabnanny PASS
pc/test_deck.py: py_compile / AST / tabnanny PASS
pc/test_deck_exclusive.py: py_compile / AST / tabnanny PASS
research/smoke_deck_exclusive.py: py_compile / AST / tabnanny PASS
Pre-edit backup manifest: all 5 hashes unchanged
No project lint/type-check configuration or installed ruff/mypy/pyright found; those checks were not run.
Post-smoke single-instance port 47614: free (no resident deck)
```

仓库没有 lint/type-check 配置，本机未找到 ruff/mypy/pyright；未安装新依赖，因此未声称完成这些工具的检查。已执行编译、AST 解析、tabnanny，以及独立只读代码复核；复核发现的设备句柄复用问题已修复并有回归测试。

## 最终冒烟原始日志

```text
SMOKE: deck run -v; 10 seconds; no serial/HID commands
SMOKE: preinstalled downstream hook captures only tagged test letters
SMOKE: current desktop=CodexSandboxDesktop-521d42a24a6d2036c860dd748b1806e2; input desktop=Default
2026-11-17 06:12:58,225 agent_deck AgentDeck started; exclusive=True; map=D:\desk\hardware\h1\pc\deck_map.json
2026-11-17 06:12:58,228 agent_deck hook installed ()
2026-11-17 06:13:08,104 agent_deck hook uninstalled ()
2026-11-17 06:13:08,104 agent_deck AgentDeck stopped; action thread joined
SMOKE INCOMPLETE: {"duration_seconds": 10.003, "sent_letters": "QWR", "sendinput_attempts": [{"vkey": 81, "requested": 2, "inserted": 0, "error": 5}, {"vkey": 87, "requested": 2, "inserted": 0, "error": 5}, {"vkey": 82, "requested": 2, "inserted": 0, "error": 5}], "downstream_observed": 0, "deck_injected_passes": 0, "suppressed_events": 0, "current_desktop": "CodexSandboxDesktop-521d42a24a6d2036c860dd748b1806e2", "input_desktop": "Default", "normal_exit": true, "exit_code": 0, "injection_verified": false, "limitation": "SendInput pass-through was not verified; the process desktop differs from the input desktop"}
```

冒烟脚本退出码为 1，表示注入验收不完整；其中 deck 子进程通过 WM_CLOSE 正常退出，退出码为 0，两者含义不同。首次尝试因 SendInput 失败提前停止，日志另存；最终运行完成了全部 10 秒及三次注入尝试。

现场只读诊断显示进程线程桌面为 `CodexSandboxDesktop-521d42a24a6d2036c860dd748b1806e2`，系统输入桌面为 `Default`。最终三次 SendInput 都返回 `inserted=0, error=5`，两级钩子均未观察到这些测试事件。该现象与当前桌面隔离一致；不能用“无吞键日志”推断放行成功，也没有尝试切换桌面或绕过沙箱。

在系统交互桌面的 PowerShell 中可以复现验收：

```powershell
& D:\conda\miniconda3\python.exe research/smoke_deck_exclusive.py
```

成功条件是 `injection_verified=true`、6 个注入事件通过 deck 后被下游探针观察到、吞键数为 0、正常退出。探针只截获带本次测试标记的字母，避免写入前台应用；其它输入继续调用下一钩子。

## 剩余限制

- 真机注入放行和人工物理宏键盘/主键盘同时操作尚未验证。离线替身覆盖所要求的判断分支。
- WH_KEYBOARD_LL 本身没有设备 ID。当前实现对已观察到的冲突放行，并严格匹配时间、方向与扫描码；对完全不可区分的多设备同时输入，不能保证绝对无误判。要求“绝不能吞主键盘”在该 API 方案下无法提供无条件保证。
- 严格匹配、50 ms 超时或系统移除钩子可能使原宏键盘快捷键到达前台；直接接收 Raw Input 的应用仍可能看到原始输入；鼠标滚轮和仅走 consumer HID 的报告不由键盘钩子吞掉。

## 复用依据

采用 ADAPT：扩展现有 Raw Input 与动作控制器。LuaMacros 仅作 REFERENCE，借鉴“先查最近 Raw 事件，再处理等待中的 WM_INPUT”的思路，没有引入其 DLL 或复制实现。已查看其 [ProcessWaitingRawMessages](https://raw.githubusercontent.com/me2d13/luamacros/master/src/ukbddeviceservice.pas)、[AssignDevice](https://raw.githubusercontent.com/me2d13/luamacros/master/src/ukeylogservice.pas) 与 [SetHook](https://raw.githubusercontent.com/me2d13/luamacros/master/src/uhookservice.pas)。其实现使用 WH_KEYBOARD，当前实现按任务书要求使用 WH_KEYBOARD_LL。

微软说明低级钩子在安装线程执行，并建议把工作交给其它线程；当前动作队列遵循该约束。见 [LowLevelKeyboardProc](https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelkeyboardproc)。事件时间及注入标记依据 [KBDLLHOOKSTRUCT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-kbdllhookstruct)。SendInput 可能受输入权限限制，返回值表示成功插入的事件数；本次零返回已按失败记录，见 [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)。

