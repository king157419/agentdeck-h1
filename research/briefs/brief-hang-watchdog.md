# 简报：查"程序未响应"+ 停掉每 2 秒戳一次系统键盘

## 现象
用户报 AgentDeck.exe "未响应"，按键和旋钮都没反应。`~/.agentdeck/logs/app.log` 没有 ERROR / Traceback。
我在本机空跑 60 秒复现不了（窗口 IsHungAppWindow 一直 False），`init_all` 本身 0.01 秒。
日志里 22:11–22:24 之间除 USB 探测外没有任何按键事件，22:24:14 突然连着处理了几次旋钮——像是某个线程堵了十几分钟后才放开。

## 已知可疑点
1. Raw Input 模式下，`hub_keyboard.py` 的 `_probe_usb` 每 2 秒调一次 `USBInput.open()`。这个调用会用 libusb 的 HID 后端去 claim 系统键盘接口、发 SET_PROTOCOL、读一次中断端点，日志里已经刷了 1300 多行。它跑在 Raw Input 的消息循环线程里，阻塞时 WM_INPUT 就没人处理。HID 后端的读调用可能会抢走按键报告（日志里"USB keyboard report length=8"就是探测时读到的），也可能卡住。
2. Tk 主线程上可能有阻塞调用（窗口聚焦、语音快捷键录制、托盘回调、确认对话框等）。

## 要做
1. **只在真有 WinUSB 时才探测 USB**：先用 `deck_usb.interface0_driver()`（或同等的只读查询，不打开设备）确认接口 0 的驱动是 WinUSB，是才 `open()`。不是就不碰设备，日志里只在状态变化时记一行。
2. **看门狗**：加一个后台线程，监视 Tk 主线程和键盘读取线程的心跳。任何一个超过 3 秒没动静，就把所有线程的调用栈（`faulthandler.dump_traceback` 或 `sys._current_frames`）写进日志，并标记"UI 卡顿 N 秒"。同一次卡顿只记一次，恢复时再记一行。
3. 读代码排查 Tk 主线程上的同步阻塞调用，有就挪到工作线程或加超时；结果里列出查到的点。
4. 加日志：按键事件进入 hub 时记一行 debug，带读键方式和动作结果。

## 硬约束
- 不往键盘写数据，不碰 0xFF00 接口。不读写真实 `~/.claude`、`~/.codex`。不 git commit。
- 可以打包，但打包前确认 AgentDeck.exe 没在运行，打包后不要启动它。

## 完成标准
- 现有 `pc/test_*.py` 全过 + 新测试（非 WinUSB 时不调用 open；看门狗能检测到人为制造的 4 秒阻塞并写出调用栈；恢复后记一行）。
- 结果写 `research/hang-watchdog-results.md`，列出排查到的阻塞点。
