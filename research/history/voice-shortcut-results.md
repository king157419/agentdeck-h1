# 语音快捷键实现结果

2026-11-18，按 `research/briefs/brief-voice-shortcut.md` 完成。全部 33 个 `pc/test_*.py` 脚本退出码为 0。

## 使用

托盘菜单 → **键位** → **语音快捷键**：按一次 Typeless 中设置的快捷键并松开，选择“按住说话”或“按一下开始、再按结束”，点击保存。保存后立即生效，重启时从同一配置加载。取消、失焦或重录不会改配置；正在语音输入时不能更换快捷键。

录制期间临时使用 Windows 键盘钩子，避免 Typeless 或系统热键抢走输入；仅录制窗口处于前台时拦截。录完、失焦、取消、关闭或异常都会停止拦截并尝试卸载。支持单独 Right Alt，也保留 Right Alt + K 等组合的右侧修饰键。

配置位置为运行时 home 下的 `.agentdeck/config.json`。Windows 的 `key_codes` 使用虚拟键码，字段名称沿用 macOS；两个系统的键码数值不能直接互换。例如以 Right Alt 作为按住说话快捷键：

```json
{
  "dictation_shortcut": {
    "key_codes": [165],
    "modifiers": [],
    "mode": "hold"
  }
}
```

| 字段 | Windows 行为 |
| --- | --- |
| `key_codes` | 1–4 个不同的虚拟键码，范围 1–254；可包含指定侧别的修饰键 |
| `modifiers` | 可选，`control` → Ctrl、`option` → Alt、`shift` → Shift、`command` → Win |
| `mode: "toggle"` | 宏键盘语音键按下时发送一次完整组合键，松开时再发送一次 |
| `mode: "hold"` | 宏键盘语音键按下时按住组合键，松开时按相反顺序释放 |

省略整个配置时仍为 **Win+H / toggle**；配置中省略 `mode` 也采用 toggle。配置保存保留其他字段，使用临时文件和原子替换；写入失败恢复原内存配置。Hub CLI 的默认配置路径和 `--config` 路径都支持 Windows 快捷键。

## 安全与实现

- 语音期间沿用 Hub 的审批拦截；不注入文字、Enter 或审批操作。
- 复用原来的 100 ms 前台守护、60 秒上限、原窗口恢复和 USB/Raw Input 设备移除释放事件。
- 新的按下/触发操作仍使用原目标的 `expected` 前台检查。目标丢失或无法恢复时，不向其他窗口触发停止快捷键。
- hold 的异常清理只发送本程序已持有按键的 key-up。清理不依赖原窗口仍存在，否则窗口消失后会无法松开修饰键；不会向其他窗口新增 key-down。
- 原生输入记录按键所有权，处理部分发送和释放失败，并重试释放。释放尚未确认成功时保留语音占用和审批拦截。
- toggle 分别记录“全部 key-down 已发送”和“停止已经触发”。启动部分成功时仍会收尾；停止已经触发但 key-up 失败时，重试只松键，避免再次切换而重开听写。
- 原生调用中断、无法确定快捷键是否触发时，先尝试松键，继续保留审批拦截。

复用决定为 ADAPT：扩展已有 `DesktopEffects` 生命周期、`HubWindowControl` 和托盘主题；共享组合键发送/所有权处理，避免另起语音状态机。录制适配器复用 `deck_input` 的钩子类型与结构体，无新增依赖。macOS 的现有实现没有修改，其 35 项测试通过。

## 修改文件

| 文件 | 改动 |
| --- | --- |
| `pc/hub_desktop.py` | 配置校验与即时更新、toggle/hold、按键所有权与异常清理 |
| `pc/hub.py` | Windows 启动时同样传入 `dictation_shortcut` |
| `pc/agentdeck_app.py` | 录制入口、模式选择、原子配置保存和失败回滚 |
| `pc/voice_shortcut_capture.py` | 新增临时前台键盘录制适配器，导入时无原生副作用 |
| `pc/test_hub_desktop.py` | 默认行为、配置、hold 生命周期、部分发送与重试回归 |
| `pc/test_hub.py` | hold 期间禁止批准、设备移除释放、丢窗后继续拦截批准 |
| `pc/test_hub_runtime.py` | Windows 默认/自定义配置路径加载 |
| `pc/test_agentdeck_app.py` | 录制、侧别、钩子清理、UI 事件、配置保存与回滚 |
| `research/voice-shortcut-results.md` | 本报告 |

## 实际验证

从项目根目录使用 `D:\conda\miniconda3\python.exe`，逐个运行全部 `pc/test_*.py`。每个子进程都把 `HOME` 和 `USERPROFILE` 指向临时目录；原生键盘、桌面和硬件操作使用测试替身。总结果：

```text
SCRIPTS 33; PASS 33; FAIL 0
```

| 测试脚本 | 结果 |
| --- | --- |
| `test_agentdeck_app.py` | 96 tests，OK |
| `test_capture_etl.py` | 18 tests，OK |
| `test_daemon.py` | 10 groups passed |
| `test_deck.py` | 56 groups passed |
| `test_deck_exclusive.py` | 9 groups passed |
| `test_deck_input.py` | 5 groups passed |
| `test_deck_keymap.py` | 13 groups passed |
| `test_deck_probe.py` | 7 groups passed |
| `test_deck_usb.py` | 所有断言通过，退出码 0 |
| `test_focus_lock.py` | 4 groups passed |
| `test_hub.py` | 156 tests，OK |
| `test_hub_app_support.py` | 24 tests，OK |
| `test_hub_demo.py` | 10 tests，OK |
| `test_hub_desktop.py` | 58 tests，OK |
| `test_hub_desktop_mac.py` | 35 tests，OK |
| `test_hub_doctor.py` | 17 tests，OK |
| `test_hub_gate.py` | 20 tests，OK |
| `test_hub_hotkey.py` | 36 tests，OK |
| `test_hub_input_capture.py` | 7 tests，OK |
| `test_hub_install.py` | 35 tests，OK |
| `test_hub_keyboard.py` | 18 tests，OK |
| `test_hub_macos_fix.py` | 3 tests，OK |
| `test_hub_nonce.py` | 33 tests，OK |
| `test_hub_nonce_integration.py` | 16 tests，OK |
| `test_hub_overlay.py` | 32 tests，OK |
| `test_hub_overlay_position.py` | 10 tests，OK |
| `test_hub_relay.py` | 12 tests，OK |
| `test_hub_runtime.py` | 7 tests，OK |
| `test_hub_virtual_device.py` | 15 tests，OK |
| `test_hub_virtual_nonce_integration.py` | 7 tests，OK |
| `test_pc.py` | 4 groups passed |
| `test_ui.py` | 7 groups passed |
| `test_verify_real_session.py` | 20 tests，OK |

项目指定的三个检查实际输出为：

```text
UI: 7 groups passed
daemon offline tests: 10 groups passed
PC and firmware loop: 4 groups passed
```

新增回归覆盖 toggle/hold、自定义修饰键、默认 Win+H、参数拒绝、即时更新、重复按下/释放、超时、丢窗、恢复失败、窗口查询/等待/线程启动异常、部分输入、释放异常与重试、无法确定输入结果、设备拔出、配置读写/失败回滚、录制键拦截及卸载。

独立复核还用 key-down 驱动的热键监听替身验证了部分启动、部分停止及异常不确定场景，确认不会因松键重试而重开听写，或提前解除审批拦截。

八个变更的 Python 文件通过 `py_compile` 和 `tabnanny`；`git -c core.whitespace=cr-at-eol diff --check` 无输出、退出码 0。该参数只让检查认可现有 CRLF 文件，没有修改 Git 配置。仓库未配置独立类型检查器，当前 Python 环境也未安装 Ruff/Pyflakes/Mypy/Pyright，未新增依赖。

独立 Tk 窗口使用临时 home 和原生录制替身完成实际渲染，截图复查通过，visual-verdict 为 96/100。完整日志/汇总位于 `.omx/state/voice-shortcut-checks/`，截图和判定 JSON 位于 `.omx/state/voice-shortcut-ui/`。

## 验证边界

- 未读写真实 Claude/Codex 配置，未安装真实录制钩子、未发送系统按键、未打开串口或上传固件。没有改固件/LCD 输出，因此未运行 `pc/sim.py`；没有打包、启动 AgentDeck 或执行 Git 提交。
- Typeless 的真实热键响应及实际 Windows 钩子仍需设备端使用验证；本次原生边界均以替身验证。
- toggle 目标永久消失或发送结果不确定时，无法同时证明听写已停止并遵守不向其他窗口触发热键，因此保持输入/审批拦截。目标恢复后可再次按下并松开语音键重试；若目标无法恢复或输入结果始终不确定，应先在语音软件结束听写，再重启 AgentDeck。
- 如果 Windows 持续拒绝 key-up，程序会保留所有权并重试、继续拦截审批；无法声称操作系统已接受它拒绝的释放请求。

实现核对依据：[Microsoft SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)、[KEYBDINPUT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-keybdinput)、[LowLevelKeyboardProc](https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelkeyboardproc)、[KBDLLHOOKSTRUCT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-kbdllhookstruct)。
