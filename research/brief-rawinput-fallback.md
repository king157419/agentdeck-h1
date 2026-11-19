# 简报：不用 Zadig 也能读 CXT 键盘

## 背景
为了抓灯光包，用户已把 4132:2107 接口 0 恢复成系统 HID 键盘驱动（不再是 WinUSB）。现在 `pc/deck_usb.py` 的 `USBInput` 打不开，hub 读不到按键。
给真实用户用时也不能要求装 Zadig。项目里已有 `pc/deck_input.py` 的 `RawInput`（按设备过滤，v0 的 deck.py 用它做后备）。这把键盘的键发的是 F13–F24 等（见 `pc/hub_keys.json`），漏到窗口里基本无害。

## 要做
1. `pc/hub.py` 第 1175 行附近建 reader 的地方：先试 `USBInput`；接口 0 不是 WinUSB 或打开失败，就改用 `RawInput`，只收 VID 4132 / PID 2107 设备的键，交给同一个 `USBKeys` 回调。日志写清当前用的是哪种方式。设备拔插、驱动变化后能自己重连或切换。
2. 确认 Raw Input 路径下 `USBKeys` 拿到的按键名和 USB 路径一致（F13…F24、组合键、旋钮），不一致就在适配层转换，不改 `hub_keys.json` 的含义。
3. `pc/hub_doctor.py`：不再把"接口 0 是 WinUSB"当成必需项。改成显示"读键方式：USB 直读 / Raw Input"；只有两种都不可用时才报错。删掉面向用户的 Zadig 提示（日志里可以保留）。
4. PyInstaller：确认 `deck_input` 会被打进 exe（必要时改 `agentdeck.spec` 的 hiddenimports）。

## 硬约束
- 不往键盘写任何数据，不碰 0xFF00 接口，不调用 SET_PROTOCOL 之外的新控制传输。
- 不读写真实 `~/.claude`、`~/.codex`。不 git commit。可以打包，但打包前确认 AgentDeck.exe 没在运行，打包后不要启动它（我来启动做验收）。

## 完成标准
- 现有 `pc/test_*.py` 全过，新增"USB 失败 → Raw Input"切换、按键名一致性的测试。
- 结果写 `research/rawinput-results.md`：改动、测试输出摘要、打包是否成功。
