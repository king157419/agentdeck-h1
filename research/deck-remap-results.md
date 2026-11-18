# 宏键盘改键执行记录

日期：2026-11-17。结论：按简报“任何协议不确定就不要写”条款安全停止，**真实备份、矩阵读取和改键未完成**。协议调查、拒绝路径、离线事务逻辑、测试和文档已交付。

## 阻断证据

安装的 VIA-C 0.3.5 仅筛选 FF60/0061；当前目标设备为 FF00/0001。软件默认定义没有 4132:2107，本机没有补充定义缓存。旋钮源码是三种 custom mode，无法对应四个物理旋钮及其每层地址。不能套用它的读写命令，更不能猜测原键码或矩阵。详见 [via-c-protocol.md](via-c-protocol.md)。

## 做完的标准逐项核对

| 标准 | 实际结果 |
|---|---|
| backup → show → apply → show 真实输出 | 已按顺序执行，四次均退出 2，完整输出如下；拒绝发生在 HID open/write 之前 |
| 全部测试输出 | 既有 37 组 + 新增 13 组，共 50 组通过，完整输出如下 |
| 被改矩阵位置：原码 → 新码 | 无；未改写任何位置，原码及 row/col 未读出，不能伪造清单 |
| 一行恢复命令 | 本次不适用：未改键，也未生成真实完整备份，没有可执行的恢复命令 |

未来在目标协议及 backend 完整确认、真实 backup 成功后，恢复命令的**用法模板**（当前没有该文件，且仍会被协议门禁阻止）是：

```powershell
& 'D:\conda\miniconda3\python.exe' pc/deck_keymap.py restore 'research/keymap-backup-<时间>.json'
```

测试仅使用合成 4×6 矩阵和假 HID/backend；它们不是当前硬件的矩阵定义或键位备份。`pc/deck_keymap.py` 仍缺少真实设备的完整读取和旋钮读写 backend；没有绕过门禁的选项。没有写入 `_rollback/deck-v0/keymap-original.json`。

## 四条硬件命令的完整输出

```text
> D:\conda\miniconda3\python.exe pc/deck_keymap.py backup
AgentDeck keymap: backup
Target: VID_4132&PID_2107; matching HID interfaces=4
interface=0 usage_page=0x0001 usage=0x0006
interface=1 usage_page=0x0001 usage=0x0002
interface=2 usage_page=0x000C usage=0x0001
interface=3 usage_page=0xFF00 usage=0x0001
Installed VIA-C 0.3.5 only selects usage_page=0xFF60 usage=0x0061.
No 4132:2107 matrix definition or confirmed four-encoder mapping was found.
BLOCKED: FF00/0001 protocol is unconfirmed. No HID interface opened; no reports sent; no keymap backup created; no configuration changed.
exit_code=2
```

```text
> D:\conda\miniconda3\python.exe pc/deck_keymap.py show
AgentDeck keymap: show
Target: VID_4132&PID_2107; matching HID interfaces=4
interface=0 usage_page=0x0001 usage=0x0006
interface=1 usage_page=0x0001 usage=0x0002
interface=2 usage_page=0x000C usage=0x0001
interface=3 usage_page=0xFF00 usage=0x0001
Installed VIA-C 0.3.5 only selects usage_page=0xFF60 usage=0x0061.
No 4132:2107 matrix definition or confirmed four-encoder mapping was found.
BLOCKED: FF00/0001 protocol is unconfirmed. No HID interface opened; no reports sent; no keymap backup created; no configuration changed.
exit_code=2
```

```text
> D:\conda\miniconda3\python.exe pc/deck_keymap.py apply
AgentDeck keymap: apply
Target: VID_4132&PID_2107; matching HID interfaces=4
interface=0 usage_page=0x0001 usage=0x0006
interface=1 usage_page=0x0001 usage=0x0002
interface=2 usage_page=0x000C usage=0x0001
interface=3 usage_page=0xFF00 usage=0x0001
Installed VIA-C 0.3.5 only selects usage_page=0xFF60 usage=0x0061.
No 4132:2107 matrix definition or confirmed four-encoder mapping was found.
BLOCKED: FF00/0001 protocol is unconfirmed. No HID interface opened; no reports sent; no keymap backup created; no configuration changed.
exit_code=2
```

```text
> D:\conda\miniconda3\python.exe pc/deck_keymap.py show
AgentDeck keymap: show
Target: VID_4132&PID_2107; matching HID interfaces=4
interface=0 usage_page=0x0001 usage=0x0006
interface=1 usage_page=0x0001 usage=0x0002
interface=2 usage_page=0x000C usage=0x0001
interface=3 usage_page=0xFF00 usage=0x0001
Installed VIA-C 0.3.5 only selects usage_page=0xFF60 usage=0x0061.
No 4132:2107 matrix definition or confirmed four-encoder mapping was found.
BLOCKED: FF00/0001 protocol is unconfirmed. No HID interface opened; no reports sent; no keymap backup created; no configuration changed.
exit_code=2
```

## 全部测试的完整输出

```text
> D:\conda\miniconda3\python.exe pc/test_ui.py
test_layout_states: PASS
test_marquee: PASS
test_focus: PASS
test_compatibility: PASS
test_priority_rotation: PASS
test_bad_commands_glyphs: PASS
test_dance: PASS
UI: 7 groups passed
exit_code=0
```

```text
> D:\conda\miniconda3\python.exe pc/test_daemon.py
test_mapping: PASS
test_focus: PASS
test_state_machine: PASS
test_log_tick: PASS
test_main_schedule_and_lock: PASS
test_process_snapshot: PASS
daemon offline tests: 6 groups passed
exit_code=0
```

```text
> D:\conda\miniconda3\python.exe pc/test_pc.py
test_names_hooks: PASS
test_ensure_daemon: PASS
test_demo: PASS
test_firmware_loop: PASS
PC and firmware loop: 4 groups passed
exit_code=0
```

```text
> D:\conda\miniconda3\python.exe pc/test_deck.py
test_mapping: PASS
test_list_and_selection: PASS
test_actions_and_logging: PASS
test_approval_guards: PASS
test_window_matching_and_input: PASS
test_foreground_fallback_cleanup: PASS
test_single_instance_and_daemon_launch: PASS
test_cli_and_learn: PASS
test_run_event_dispatch_and_cleanup: PASS
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
AgentDeck offline tests: 20 groups passed
exit_code=0
```

```text
> D:\conda\miniconda3\python.exe pc/test_deck_keymap.py
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
exit_code=0
```

## 其它验证

```text
Python AST / compile / whitespace: 3 files PASS
deck_map.json syntax: PASS
Real keymap backup files: 0
Display firmware unchanged; pc/sim.py not required.
No configured lint/typecheck tools; ruff/mypy/pyflakes unavailable.
```

`D:\VIA-C\resources\app.asar` 前后 SHA-256 相同：

```text
088BF462E870650FEBBE3C22157168BD9A0957BCF70746567945122901D3EAE0
```

未修改 `D:\VIA-C`，未打开 COM4，未上传或编辑固件；显示逻辑未变，因此未运行 `pc/sim.py`。未新增依赖。未配置独立 lint/typecheck，且 ruff/mypy/pyflakes 未安装；本次执行 AST、编译和空白检查，不将它们冒称为类型检查。

## 文件与实现范围

- `pc/deck_keymap.py`：命令入口、协议门禁、源码协议报文编解码、快照校验/备份、纯改键计划及可回滚事务逻辑；真实 backend 尚未实现。
- `pc/test_deck_keymap.py`：13 组离线测试，含部分写入、错误回读、非目标位置变化和回滚准备阶段再次中断的恢复测试。
- `pc/deck_map.json`：仅更新说明，动作绑定不变。
- `lcd1602/README.md`：工具用法、恢复模板、当前阻断与尚不能给出真实矩阵位置的原因。
- `research/via-c-protocol.md`：源码路径/行号、命令、键码、旋钮与持久化的已知和未知项。
- `research/extract_via_asar.py`、`research/via-c-src/`：只读提取器及 8215 个有效提取文件；18 个越界条目被跳过。
- `research/deck-remap-results.md`：本记录。

复用选择：使用既有 hidapi 和 deck_probe 的 VID/PID 常量，以本机厂商源码为参考，不增加第三方库或改动既有监听/动作实现。独立审查发现的回滚准备阶段中断问题已用回归测试复现并修复；复核通过。剩余阻断是当前设备的真实协议、矩阵与旋钮地址缺失，离线通过不等于硬件改键成功。

