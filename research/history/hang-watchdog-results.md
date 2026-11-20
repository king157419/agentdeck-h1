# 未响应排查与看门狗：结果

## 改了什么
- `pc/hub_watchdog.py`（新）：心跳看门狗。监视项超过 3 秒没 beat，把所有线程调用栈写进日志并标"UI 卡顿 N 秒"；同一次卡顿只记一次，恢复时再记一行。
- `pc/hub.py`：`main()` 里创建 Watchdog，读键线程（`keyboard`）和 Tk 主线程（`UI`）各自 beat；退出时 unwatch/stop。AgentDeck.exe 经 `agentdeck_app.main -> hub.main` 走这条路径，所以已接入 exe 入口。
- `pc/deck_usb.py` / `pc/hub_keyboard.py`：USB 探测只在接口 0 驱动为 WinUSB 时才 `open()`，状态变化才记日志；读键循环带心跳；按键进入 hub 记 debug 日志（Codex 完成）。
- `pc/hub_overlay.py`：Overlay 在 live 模式下有后台工作线程（`defer`），状态快照在后台取，Tk 的 `_poll` 只读最新快照（Codex 完成）。
- `pc/agentdeck_app.py`（本次补齐）：
  - 新增 `_background_enabled`，`ready()` 里按 overlay 是否已启动后台线程设置。
  - `pump()` live 模式读 `overlay.state`，不再同步调 `engine.state()`。
  - `select` / `next_wait` 菜单动作经 `_run_slow` 交给 `overlay.defer` 的工作线程，hub 锁和窗口聚焦都在工作线程；失败回 Tk 线程弹提示并记日志。非 live（无后台线程）时保持同步，旧测试行为不变。

## 查到的 Tk 主线程阻塞点
1. `pump()` 每 300ms 同步 `hub.state()`（要拿 hub 锁）：已改读后台快照。
2. 托盘菜单 `select`：在 Tk 线程持 `hub.lock` 并调 `hub.action`（会聚焦原生窗口）：已移到工作线程。
3. `next_wait`：同样调 `hub.action` 聚焦窗口：已移到工作线程。
4. Raw Input 消息循环线程里每 2 秒 `USBInput.open()` 探测：已改为仅 WinUSB 才探测。
5. 未处理（本质是用户交互的模态）：`global_action` 的确认框、`project_action` 的文件夹选择框、`hub_install.apply` 的文件读写。确认框/选择框属于用户等待，不算卡死；文件读写通常很快，但未挪线程。

## 测试结果
全部 34 个 `pc/test_*.py` 逐个运行，全部通过（无失败）：
test_agentdeck_app 98 OK；test_capture_etl 18 OK；test_daemon 10 组；test_deck 56 组；test_deck_exclusive 9 组；test_deck_input 5 组；test_deck_keymap 13 组；test_deck_probe 7 组；test_deck_usb 25 组；test_focus_lock 4 组；test_hub 156 OK；test_hub_app_support 24；test_hub_demo 10；test_hub_desktop 58；test_hub_desktop_mac 35；test_hub_doctor 17；test_hub_gate 20；test_hub_hotkey 36；test_hub_input_capture 7；test_hub_install 35；test_hub_keyboard 25；test_hub_macos_fix 3；test_hub_nonce 33；test_hub_nonce_integration 16；test_hub_overlay 34；test_hub_overlay_position 10；test_hub_relay 12；test_hub_runtime 7；test_hub_virtual_device 15；test_hub_virtual_nonce_integration 7；test_hub_watchdog 6；test_pc 4 组；test_ui 7 组；test_verify_real_session 20 OK（86 秒）。

## 不确定 / 需用户确认
- 未打包、未启动 AgentDeck.exe，真机是否还卡死只能由用户长时间运行后确认；卡顿时看 `~/.agentdeck/logs/app.log` 里的调用栈。
- 看门狗误报阈值 3 秒是否合适，未在真机验证。
- 其它菜单动作（global/install）仍在 Tk 线程，若再卡看调用栈。
