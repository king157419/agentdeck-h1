# AgentDeck.exe 交付结果

已按 `research/briefs/brief-app-exe.md` 完成，最终构建与离线验证均通过。未启动主程序常驻进程；真机启动、托盘交互、USB 真实按键及 1602 实物效果由主会话验证。

## 改动文件

| 文件 | 改动与用途 |
| --- | --- |
| `pc/agentdeck_app.py` | 新增托盘入口；同进程运行 hub、USB、热键及浮窗；总状态图标、会话菜单、键位窗口、诊断、项目安装卸载、HKCU 自启、日志、退出、单实例唤醒、首次引导和用户配置。 |
| `pc/hub.py` | 仅增加可选 `ui_factory`，复用现有 hub 生命周期和动作路径。 |
| `pc/hub_overlay.py` | 仅增加 `run(on_ready=...)` 回调，Tk 初始化后接入托盘。 |
| `pc/hub_install.py` | frozen 环境使用同目录 relay exe 绝对路径；识别移动后的 relay；明确确认后先备份再移除旧 LCD 钩子，支持原安装器的 `command + args` 格式。 |
| `pc/hub_doctor.py` | 中文诊断：USB/接口 0 驱动、token、登记项目钩子、失效路径、全局旧钩子数、串口日志线索和 Codex `/hooks` 提醒。 |
| `pc/agentdeck_icon.py`、`pc/agentdeck.ico` | 使用已有 Pillow 生成原创图标，托盘复用同一绘图函数。 |
| `pc/test_agentdeck_app.py` | 51 项新增离线测试。 |
| `pc/test_hub_app_support.py` | 15 项新增离线测试。 |
| `agentdeck.spec`、`build_exe.bat` | 两个 exe 共用 onedir 和 `_internal/`；收集 libusb DLL、JSON、图标和 Tk 等资源。 |
| `pc/hub_README.md` | 开头新增中文“用 exe”，说明项目钩子、信任、配置、自启、日志和移动目录后的修复。 |
| `research/check_app_exe.py` | 可重复执行的包检查，仅运行短时 relay 和临时本机 HTTP 替身。 |
| `research/app-exe-tests.json`、`research/app-exe-package-check.json` | 最终测试与产物检查记录。 |
| `research/app-exe-results.md` | 本报告。 |

原 `pc/hub_relay.py` 直接作为控制台 exe 入口，保留其行为。没有新增依赖；使用本机已有 PyInstaller 6.11.1、pystray 0.19.5、Pillow、pyusb 和 libusb_package。

复用与简化：保留会话状态机、选择/聚焦、权限处理、串口容错、安装器和浮窗，通过两个小型扩展点接入，没有另写 hub 或启动 Python 子进程。托盘操作经队列交给 Tk；菜单仅在托盘线程打开时刷新，避免销毁正在显示的菜单。切换会话时在 hub 锁内核对完整身份，避免槽位复用切错窗口。

## 测试结果

从项目根目录使用 `D:/conda/miniconda3/python.exe` 执行。最终共 **30 个脚本、517 项 unittest + 137 个断言测试组，全部通过，失败 0**。这是实际执行次数；`test_hub.py` 会聚合部分其他文件的测试，统计包含这些重复执行，不表示 517 个互不重复的测试。

新增测试合计 **66 项**，覆盖状态优先级/提示、菜单队列和菜单线程、4×5 键位及 profile、注册表读写、单实例、frozen 路径、配置不覆盖、项目钩子、引导、旧钩子确认/备份/精确删除、失效路径、串口日志诊断、GUI 回调和异常清理。新增逻辑的外部访问均使用临时 home 和替身，无真实注册表、串口、USB 或 agent 窗口操作。

| 脚本 | 实际数量 | 结果 |
| --- | --- | --- |
| `pc/test_agentdeck_app.py` | 51 项 unittest | 通过，退出码 0 |
| `pc/test_daemon.py` | 10 个断言测试组 | 通过，退出码 0 |
| `pc/test_deck.py` | 55 个断言测试组 | 通过，退出码 0 |
| `pc/test_deck_exclusive.py` | 9 个断言测试组 | 通过，退出码 0 |
| `pc/test_deck_input.py` | 4 个断言测试组 | 通过，退出码 0 |
| `pc/test_deck_keymap.py` | 13 个断言测试组 | 通过，退出码 0 |
| `pc/test_deck_probe.py` | 7 个断言测试组 | 通过，退出码 0 |
| `pc/test_deck_usb.py` | 24 个断言测试组 | 通过，退出码 0 |
| `pc/test_focus_lock.py` | 4 个断言测试组 | 通过，退出码 0 |
| `pc/test_hub.py` | 133 项 unittest | 通过，退出码 0 |
| `pc/test_hub_app_support.py` | 15 项 unittest | 通过，退出码 0 |
| `pc/test_hub_demo.py` | 10 项 unittest | 通过，退出码 0 |
| `pc/test_hub_desktop.py` | 30 项 unittest | 通过，退出码 0 |
| `pc/test_hub_desktop_mac.py` | 35 项 unittest | 通过，退出码 0 |
| `pc/test_hub_doctor.py` | 13 项 unittest | 通过，退出码 0 |
| `pc/test_hub_gate.py` | 20 项 unittest | 通过，退出码 0 |
| `pc/test_hub_hotkey.py` | 36 项 unittest | 通过，退出码 0 |
| `pc/test_hub_input_capture.py` | 5 项 unittest | 通过，退出码 0 |
| `pc/test_hub_install.py` | 35 项 unittest | 通过，退出码 0 |
| `pc/test_hub_macos_fix.py` | 3 项 unittest | 通过，退出码 0 |
| `pc/test_hub_nonce.py` | 33 项 unittest | 通过，退出码 0 |
| `pc/test_hub_nonce_integration.py` | 16 项 unittest | 通过，退出码 0 |
| `pc/test_hub_overlay.py` | 32 项 unittest | 通过，退出码 0 |
| `pc/test_hub_overlay_position.py` | 10 项 unittest | 通过，退出码 0 |
| `pc/test_hub_relay.py` | 12 项 unittest | 通过，退出码 0 |
| `pc/test_hub_runtime.py` | 6 项 unittest | 通过，退出码 0 |
| `pc/test_hub_virtual_device.py` | 15 项 unittest | 通过，退出码 0 |
| `pc/test_hub_virtual_nonce_integration.py` | 7 项 unittest | 通过，退出码 0 |
| `pc/test_pc.py` | 4 个断言测试组 | 通过，退出码 0 |
| `pc/test_ui.py` | 7 个断言测试组 | 通过，退出码 0 |

逐脚本原始 stdout/stderr 和退出码见 [app-exe-tests.json](app-exe-tests.json)，完整执行日志见 `research/app-exe-tests.log`；日志尾部的 final integration reruns 是修正复查问题后的结果。

静态检查实际执行并通过：

```text
D:/conda/miniconda3/python.exe -m compileall -q pc
D:/conda/miniconda3/python.exe -m py_compile agentdeck.spec research/check_app_exe.py
git diff --check
```

三项退出码均为 0。仓库未配置独立 lint/typecheck 命令，本机未装 ruff、flake8、pyflakes 或 mypy；未额外安装工具。Git 仅提示既有 CRLF 转换策略，无空白错误。没有改变 LCD 输出，因此未运行会重新生成 `lcd1602/` 图片的 `pc/sim.py`。

## 打包与产物

最终实际执行 `build_exe.bat`，退出码 **0**。从 `research/` 工作目录通过绝对路径调用也成功。产物共用同一个目录：

```text
D:\desk\hardware\h1\dist\AgentDeck\AgentDeck.exe
D:\desk\hardware\h1\dist\AgentDeck\AgentDeck-relay.exe
D:\desk\hardware\h1\dist\AgentDeck\_internal\
```

请保留整个 `dist/AgentDeck/` 文件夹。整个包共 **52,844,542 字节**。

| 文件 | 大小 | Windows PE 子系统 | SHA-256 |
| --- | --- | --- | --- |
| `AgentDeck.exe` | 5,709,739 字节 | 2，主程序无控制台 | `6b04a339d3da4cbb249e31b7cefc875c864c8e833e4577a3ddc1b2cda30ea1c2` |
| `AgentDeck-relay.exe` | 1,754,575 字节 | 3，控制台 relay | `6a179b2575aef083d69785363b86ed3992ea9802a891f4a34e27db3e842771b7` |

最终运行 `D:/conda/miniconda3/python.exe research/check_app_exe.py`，退出码 **0**，验证：

- 2 个 PE 子系统；8 项必需资源，包括 Python DLL、Tk/Tcl、JSON、图标和 `libusb_package/libusb-1.0.dll`。
- 主程序归档的 14 个必需模块，包括 hub、浮窗、安装器、诊断、pystray Win32 后端和图标模块。
- 编译 relay 使用临时 home 且缺少 token 时：退出码 0、stdout 0 字节、stderr 0 字节。
- 编译 relay 对临时本机 HTTP 替身转发 PermissionRequest：路径、token 头和事件正确；原样输出 102 字节决策响应，退出码 0、stderr 0 字节。替身线程已退出。

详情：[app-exe-package-check.json](app-exe-package-check.json)。最终构建日志：`research/app-exe-build.log`。PyInstaller 有可选模块、非 Windows 框架和通用 USB 后端探测警告；构建成功，显式收集的 libusb DLL 已在产物中检查通过。

## 使用与验证边界

首次双击 exe 后，仅在目标文件不存在时复制默认键位和模板到 `~/.agentdeck/`；以后以该目录为准，修改后重启。`app.json` 保存登记项目、profile 和“不再提示”；`logs/app.log` 保存轮转日志。项目诊断仅检查登记项目，不递归扫描磁盘。

COM4 占用检查遵守“不打开串口”：有日志证据时显示“最近被占用或权限不足”，无证据则显示“未确认”，不将设备存在误报为空闲。此项不保证知道此刻的端口占用状态。

本次未启动主程序做真机验收，未修改真实 `~/.claude` 或 `~/.codex` 配置、未打开 COM4、未上传固件、未访问键盘厂商接口 `0xFF00`、未修改驱动、未改动 `lcd1602/`、`wokwi/`、`backup/` 或 `_rollback/`。真实 USB/热键、窗口聚焦、托盘和自启行为仍需主会话在真机确认，符合简报的交付边界。

实现时核对的官方说明：[pystray 0.19.5 用法](https://pystray.readthedocs.io/en/latest/usage.html)、[PyInstaller 6.11.1 frozen 资源路径](https://pyinstaller.org/en/v6.11.1/runtime-information.html)。
