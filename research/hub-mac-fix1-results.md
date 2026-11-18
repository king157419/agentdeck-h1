# macOS 审查修复结果

必修 P0-1～P0-5、P1-1～P1-5 全部修复。改前快照位于 `_rollback/hub-mac-fix1/pc/`；审查与简报也已随快照保存。没有修改固件、精灵或动画，没有启停现有 Hub、打开 COM4、上传固件或修改真实 `~/.codex`、`~/.claude`。

## 按审查编号汇报

| 编号 | 状态与修复方式 | 对应回归测试 |
|---|---|---|
| P0-1 | 已修。`hub_desktop.py` 的 Win32 导入及依赖类仅在 Windows 定义；同步隔离间接导入链 `daemon.py`、`dsh_watch.py` 的结构体、`focus_lock.py`、`hub_overlay.py`。检查过 `hub.py`、`hub_hotkey.py`；后者的 WinDLL 调用原已在实例化路径内。 | `test_hub_runtime.py::RuntimeTests.test_macos_imports_when_wintypes_is_unavailable`：独立子进程强制所有 wintypes 导入抛 ValueError，同时导入 hub、hub_desktop_mac、hub_hotkey、hub_overlay。 |
| P0-2 | 已修。删除启动前类属性信任检查；创建 Listener，start、wait 后验证实例 running/is_alive。仅有输入监控、实例 IS_TRUSTED=False 但监听器存活时允许工作。fake 类属性固定 False。 | `test_hub_hotkey.py`：`test_false_class_trust_does_not_prevent_listener_start`、`test_input_monitoring_listener_runs_without_accessibility_trust`、`test_dead_listener_is_rejected_even_when_accessibility_is_trusted`。 |
| P0-3 | 已修。按全部九个 bundle ID 白名单过滤；只有 missing value 才按安全进程名回退，空 ID 或其他 ID 不回退。删除 Python 二次名称过滤。 | `test_hub_desktop_mac.py::test_bundle_ids_select_real_warp_and_electron_processes`：覆盖 stable、preview、Electron 及九个 ID，并拒绝 Slack/未知 ID。 |
| P0-4 | 已修。不提供合成 Fn 默认值；必须显式配置 dictation_shortcut，未配置返回不可用并记录设置示例，doctor 同样提供说明。停止时只有原句柄在前台才发快捷键，丢失窗口/恢复失败时直接结束占用，不对新窗口补发。 | `test_voice_without_config_is_unavailable_without_sending_shortcut`、`test_window_lost_or_failed_refocus_never_toggles_new_foreground`（mac 桌面套件）；`test_macos_doctor_explains_required_dictation_shortcut`（doctor 套件）。 |
| P0-5 | 已修。Windows 全局默认解释器恢复旧固定值 D:/conda/miniconda3/python.exe，路径用 as_posix；macOS 和 --project 保留当前解释器行为。voice_up False 的不可用分支仅作用于 macOS；Windows 一次性 voice 的 down/up 流程也保持旧行为。 | 安装器：`test_windows_global_hook_commands_match_pre_mac_bytes`（16 组合）、`test_windows_global_reinstall_of_pre_mac_config_never_writes`（换启动解释器仍不写入、不备份，保留 BOM/CRLF）、`test_windows_explicit_python_override_uses_forward_slashes`、`test_project_default_uses_current_interpreter_on_windows`。语音：`test_hub_macos_fix.py::test_windows_voice_flow_matches_pre_mac_bytes`（直接加载 hub-pre-mac 旧实现，对返回值、动作顺序、LCD 命令和目标序列化逐字节比较，含 down/up False），及 `test_false_voice_up_is_unavailable_only_on_macos`。 |
| P1-1 | 已修。当前代码从 desktop.voice_active 派生活动状态，没有独立 Hub.voice_active 字段。macOS voice_down False 时立即清空 voice_target 并重绘；只有成功启动才清除 pending.armed_at。 | `test_hub_macos_fix.py::test_failed_macos_voice_down_preserves_confirmation_and_redraws_cleared_target`：同时覆盖 voice、voice_down，验证状态、最终重绘、确认状态保留及没有补调 voice_up。 |
| P1-2 | 已修。只比较句柄，忽略动态标题；activate 后轮询总预算 300 ms，每个前台查询 subprocess timeout 也限制为剩余预算。粘贴移除冗余查询，由 guarded 脚本核对。 | `test_focus_waits_for_activation_and_ignores_spinner_title`、`test_focus_activation_polling_stops_within_300ms`、`test_prompt_does_not_requery_foreground_before_guarded_paste`。 |
| P1-3 | 已修。先去掉 osascript 输出的一个尾随换行，再判断是否存在窗口记录；保留标题自身的换行。 | `test_empty_osascript_result_with_newline_does_not_log`、`test_trailing_newlines_in_window_titles_are_preserved`。 |
| P1-4 | 已修。missing value 标题转为空串，枚举循环对每个窗口单独 try；Python 解析一条坏行也不会清空正常结果。 | `test_titleless_windows_and_disappearing_windows_are_isolated_in_script`、`test_enumeration_keeps_good_rows_when_one_row_is_invalid`。 |
| P1-5 | 已修。pbcopy 传 LC_CTYPE=UTF-8；物理 key code 9 的 Command+V、delay 0.08、Return 合并为一个 guarded 脚本；延迟后再次核对进程和窗口，阻止向另一窗口发回车。 | `test_prompt_uses_utf8_locale_and_single_guarded_paste_submit`、`test_focus_change_after_copy_or_paste_blocks_following_input`、`test_another_window_of_same_app_during_paste_blocks_return`。 |
| P1-6（选修） | 已修。父类公共 focus 委托 _focus，内部模板方法直接调用抛异常的 _focus；macOS 仅公共入口捕获异常。Mac _key 检查 send_key False，并由脚本原子核对句柄。 | `test_missing_window_action_reports_focus_failure_once`、`test_copy_capture_and_return_failures_do_not_continue`；Windows 桌面原 30 项也全部通过。 |
| P1-7（选修） | 按简报允许的提示方案完成。doctor 与桌面权限提示补全屏幕录制、输入监控；没有新增 C API 探测。 | `test_hub_doctor.py::test_macos_doctor_lists_screen_recording_and_input_monitoring`、现有 macOS 权限失败/超时诊断测试。 |
| P1-8（选修） | 部分修复。register 限定 VK_F1～VK_F20，超范围返回 False。丢失 key-up 后的 held 恢复未改：仅用超时清理可能把长按重复事件误当新按键，重复触发审批；可靠处理需配合系统物理状态及重复事件信息，留待后续独立实现。 | `test_hub_hotkey.py::test_register_rejects_virtual_key_outside_f1_to_f20`；现有重复按键和左右修饰键测试保留通过。 |
| P2-1、P2-2 | 按简报不做。 | 无新增测试。 |

除特别注明外，上表 macOS 桌面测试均位于 `pc/test_hub_desktop_mac.py`。旧实现比较只读 `_rollback/hub-pre-mac/`。

## 实际验证结果

全部命令均从项目根目录运行，解释器为 `D:/conda/miniconda3/python.exe`。完整 stdout/stderr 在 [hub-mac-fix1-tests.txt](hub-mac-fix1-tests.txt)，结构化结果在 [hub-mac-fix1-test-summary.json](hub-mac-fix1-test-summary.json)。

| 命令参数 | 实际输出摘要 |
|---|---|
| pc/test_hub.py | Ran 133 tests in 2.993s / OK |
| pc/test_hub_demo.py | Ran 10 tests in 0.669s / OK |
| pc/test_hub_desktop.py | Ran 30 tests in 0.163s / OK |
| pc/test_hub_desktop_mac.py | Ran 35 tests in 0.160s / OK |
| pc/test_hub_doctor.py | Ran 13 tests in 0.345s / OK |
| pc/test_hub_gate.py | Ran 20 tests in 2.686s / OK |
| pc/test_hub_hotkey.py | Ran 34 tests in 0.041s / OK |
| pc/test_hub_install.py | Ran 35 tests in 2.226s / OK（保留原 31 项，新增 4 项） |
| pc/test_hub_macos_fix.py | Ran 3 tests in 0.033s / OK |
| pc/test_hub_overlay.py | Ran 19 tests in 0.016s / OK |
| pc/test_hub_relay.py | Ran 12 tests in 1.514s / OK |
| pc/test_hub_runtime.py | Ran 6 tests in 1.012s / OK |
| pc/test_hub_virtual_device.py | Ran 12 tests in 0.001s / OK |
| pc/test_ui.py | UI: 7 groups passed |
| pc/test_daemon.py | daemon offline tests: 10 groups passed |
| pc/test_pc.py | PC and firmware loop: 4 groups passed |
| research/selftest_hub_replay.py | 12 条 PASS，包括 Temporary Hub startup and cleanup；仅隔离临时进程、随机端口 |
| pc/sim.py | Rendered 42 scenarios -> D:\desk\hardware\h1\lcd1602\preview-sim.png |

首轮 `pc/test_hub.py` 的 loopback 鉴权测试曾出现一次 `ConnectionAbortedError: [WinError 10053]`，输出保留在同一日志。该用例单独重跑为 `Ran 1 test in 0.083s / OK`，随后完整 133 项重跑通过；没有为此改代码或加测试重试。

新增回归均先跑红再修：导入隔离失败 1 项；语音首次 6 个子场景失败；doctor 提示失败 2 项；安装器差分 18 个子场景失败；热键真实类属性替身出现 5 failures/5 errors；macOS 窗口第一轮出现 12 failures/1 error。最终均通过。

对 16 个新增/修改 Python 文件完成 AST 解析、py_compile 和 tabnanny 检查。环境没有 ruff/mypy/pyright，项目也没有相应配置，因此没有声称执行独立类型检查器，未安装新依赖。独立只读复核未发现必修项残留。

## 改动文件与简化

实现：`pc/daemon.py`、`pc/dsh_watch.py`、`pc/focus_lock.py`、`pc/hub.py`、`pc/hub_desktop.py`、`pc/hub_desktop_mac.py`、`pc/hub_doctor.py`、`pc/hub_hotkey_mac.py`、`pc/hub_install.py`、`pc/hub_overlay.py`。

文档：`pc/hub_README.md`；本报告和两份测试输出文件。

测试：`pc/test_hub_desktop_mac.py`、`pc/test_hub_doctor.py`、`pc/test_hub_hotkey.py`、`pc/test_hub_install.py`、`pc/test_hub_macos_fix.py`（新增）、`pc/test_hub_runtime.py`。

简化：删除类属性预检、默认合成双 Fn 和窗口名称二次过滤；复用原窗口匹配与语音生命周期，只增加供平台覆盖的 _focus/_close_voice 方法；粘贴及提交合并为单次脚本，移除重复前台查询。没有新增依赖。

## 剩余风险

本轮在 Windows 上用离线替身与子进程导入故障注入验证，未运行真实 macOS。实际 AppleScript 执行、应用激活、听写快捷键和系统授权仍需真机验证。P1-7 仅补权限说明，不能识别系统返回成功但截图缺少窗口内容的情况。P1-8 丢失 key-up 恢复仍未完成。P2 两项按简报保留。
