# 简报：AgentDeck v0 —— 宏键盘 + 状态屏联动

## 现状（已确认）
- ESP32+1602 在 COM4，固件 0.2 已在跑，Claude/Codex 钩子和 `pc/daemon.py` 正常（`agent_lcd.py doctor` 全绿）。
- 新接的宏键盘：USB `VID_4132&PID_2107`，4 个接口 MI_00..MI_03（MI_00 是键盘，MI_03 是厂商自定义 HID，很可能是 VIA 的 raw HID，usage page 0xFF60）。厂商软件是 VIA-C（VIA 分支，QMK 系固件）。按键数量、有无旋钮未知。
- 用户主键盘是另一把（Ace 68，VID_3837），绝不能拦截它的按键。
- Python：`D:\conda\miniconda3\python.exe`，已有 pyserial；没有 hidapi/pynput/pywin32。可以 `pip install hidapi`；Windows API 优先用 ctypes，不加别的依赖。

## 实测补充（hidapi 已装好）
`hid.enumerate(0x4132,0x2107)` 结果：接口0 = 键盘(0x1/0x6)，接口1 = 鼠标(0x1/0x2)，接口2 = 多媒体(0xC/0x1)，接口3 = 厂商自定义 **0xFF00**/0x1（不是标准 VIA 的 0xFF60，协议未知）。
因此：probe 只列接口，**不向 0xFF00 发任何报文**（协议未知，可能被当成写命令）；只有遇到 0xFF60 才发 VIA 只读命令。learn 和 run 要同时收这个设备的键盘、鼠标（旋钮可能发滚轮）、多媒体键（旋钮可能发音量，用 Raw Input 注册 usage page 0xC）三类事件。默认映射里给滚轮和音量加/减各配 `cycle`。注意：音量键会同时改系统音量，README 里同样建议在 VIA-C 改成 F 键。

## 要做的（不改固件，只改/加 pc/ 下文件）
1. **`pc/deck.py probe`**：只读探测宏键盘。
   - 用 hidapi 列出 VID_4132 的所有接口（usage_page/usage）。
   - 若有 0xFF60 接口，按 VIA 协议**只读**：协议版本(0x01)、层数(0x11)、读整张 keymap(0x12)，打印矩阵行列和每个键当前键码。**禁止任何写命令**（0x05/0x13 等）。
   - 读不到就说明原因，不报错退出。
2. **`pc/deck.py learn`**：用 Windows Raw Input（ctypes，RIDEV_INPUTSINK，隐藏窗口）只接收 VID_4132&PID_2107 的键盘事件，打印每次按下的 VKey/扫描码，让用户逐个按键确认。按设备句柄过滤，主键盘的按键不打印。
3. **`pc/deck.py run`**（主功能，也可由 daemon 拉起，单实例）：
   - 用 Raw Input 收宏键盘按键 → 查 `pc/deck_map.json` 动作表 → 执行动作。
   - 动作：
     - `slot N`：聚焦板上第 N 个会话（顺序同 `list`）。给板子发 `focus <key>`，并把该会话所在窗口拉到前台：EnumWindows 按标题匹配项目名，再匹配 `claude`/`codex`；SetForegroundWindow 失败时用 Alt 键或 AttachThreadInput 技巧。
     - `next_wait`：跳到下一个状态为 wait 的会话（同上：聚焦 + 拉前台）。
     - `approve` / `deny`：先确认前台窗口属于某个 agent 会话（终端/编辑器且能匹配到会话），否则什么都不发。approve 发 Enter，deny 发 Esc（SendInput）。只在该会话当前状态是 wait 时才发，防止误按。
     - `cycle +1/-1`：在会话之间轮换（给旋钮或两个键用）。
     - `auto`：发 `focus -` 恢复自动优先级。
   - 默认 `deck_map.json` 用 learn 模式能拿到的键码做键，按键数量未知时先给 6 个键的示例映射：键1-4=slot 1-4，键5=approve，键6=deny；旋钮（若有）=cycle。文件里写清楚怎么改。
   - **宏键盘原本的按键仍会传到前台应用**（Raw Input 不能吞键）。处理：在 README 写明推荐用户在 VIA-C 里把这些键改成 F13–F24（不会在任何应用里打字）；默认映射也按 F13–F24 写。不要自动改键盘配置。
   - 每次动作把结果打印到 `-v` 日志。
4. **测试**：新建 `pc/test_deck.py`，纯断言离线测试，外部全部替身：动作表解析、slot/next_wait/cycle 选会话逻辑（基于 `list` 输出解析）、approve/deny 的安全门（非 wait 或非 agent 窗口时不发键）、单实例。现有三个测试必须继续通过。
5. **文档**：在 `lcd1602/README.md` 加一节"宏键盘（AgentDeck v0）"：命令、映射文件、F13–F24 建议、已知限制。上板和实际手感不写进 README。

## 做完的标准
- `python pc/test_ui.py`、`pc/test_daemon.py`、`pc/test_pc.py`、`pc/test_deck.py` 全过，贴出输出。
- 真实跑一次 `python pc/deck.py probe`（键盘已插着），贴出输出。不要运行会写键盘的任何东西。
- 改动前把要改的现有文件复制到 `_rollback/deck-v0/`。
- 最后列出改动的文件清单。
