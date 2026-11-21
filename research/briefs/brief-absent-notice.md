# 简报：宏键盘没被电脑认出时，弹一条托盘通知

## 背景（一句话）
2026-11-20 开机时 USB 握手失败（设备管理器显示"未知 USB 设备（设备描述符请求失败）"），键盘不在系统里，
AgentDeck 进入 `input_reader == "absent"`，但 v9 浮窗平时隐藏，用户按了半天才发现没反应。

## 要做的
在 `pc/agentdeck_app.py` 的 `pump()`（每 300 ms 在 Tk 线程跑，已拿到 `self.state`）里加"键盘在不在"的提醒：

1. 写一个小的、可单测的类（比如 `KeyboardPresenceNotice`，放在 agentdeck_app.py 或新模块都行），
   输入 `reader`（`self.state.get("input_reader")`）和单调时钟时间，输出 `"lost"`、`"back"` 或 `None`：
   - `reader == "absent"` 连续满 **10 秒** → 返回一次 `"lost"`；同一次断开期间不再重复。
   - 发过 `"lost"` 之后，`reader` 变成 `"usb"` 或 `"raw"` → 返回一次 `"back"`，然后复位，下一次断开还能再提醒。
   - 没发过 `"lost"` 就恢复（比如 3 秒内拔插）→ 什么都不返回，计时清零。
   - `reader is None`（启动中）不算断开也不算连上：不清计时、不触发。
2. `pump()` 里：
   - `"lost"` → `self.icon.notify("电脑没认出宏键盘，按键不会有反应。插着的话，拔下来再插回去（最好直插电脑，不经过集线器）。", "宏键盘没连上")`，并 `log.warning` 一行。
   - `"back"` → `self.icon.notify("按键恢复正常。", "宏键盘已连上")`，并 `log.info` 一行。
   - `notify` 抛异常就 `log.info` 吞掉（照 `tray_hint()` 的写法），不能影响 `pump()` 其余部分。
3. 测试：在 `pc/test_agentdeck_app.py`（或新测试文件）里覆盖上面 4 条规则，用假时钟，不起真托盘。

## 不要做
- 不改读键逻辑（`hub_keyboard.py`、`deck_usb.py`），不重置 USB 口，不要管理员权限。
- 不动浮窗、动画、键位文件。
- 不往 0xFF00 接口或 COM4 发任何东西。

## 做完的标准
- `D:\conda\miniconda3\python.exe pc/test_agentdeck_app.py` 通过，新测试覆盖 4 条规则。
- 其余 `pc/test_*.py` 不因此失败。
- diff 只涉及 agentdeck_app.py、测试文件（以及新模块，如果拆了的话；拆了就把模块名加进 `agentdeck.spec` 的 hiddenimports）。
