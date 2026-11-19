# Raw Input 后备读键结果

2026-11-18：任务已完成。最终全量验证 **33/33 个 `pc/test_*.py` 脚本通过**，PyInstaller 打包成功，未启动生成的程序。

`--backend usb` 先验证 USB 接口 0 能否打开并实际读取；失败或断开后，自动使用按 VID `4132` / PID `2107` 过滤的 Raw Input。Raw Input 工作期间每 2 秒探测 USB，恢复后先关闭 Raw Input，再交给 USB 读键。两种方式都不可用时定时重试，退出请求可打断等待。日志标明 `读键方式：USB 直读` 或 `读键方式：Raw Input`。

复用已有 `RawInput`、`ReportState` 和 `USBKeys`，没有新增依赖。Raw Input 的 VK/修饰键转换为现有 HID usage，现有默认 profile、`v2_emulation`、F13–F24 及旋钮键使用同一事件规则。`hub_keys.json` 未修改；其中独立的 `hotkey` 配置也没有并入 HID 绑定。

补齐了抬键、设备移除、自动重复过滤、每设备修饰键隔离、组合键 freshness、多键保护及切换时的合成释放。按住语音时拔出设备或切换后端会释放对应动作。超过 boot 6KRO 的输入等待全部松开后重新接收，避免把仍按住的键重放为新按键。

Raw Input 在原生读取前记录绝对时间，并根据 Windows 消息时间查询 Hub 的历史请求快照。回归测试验证：消息排队或读取设备信息发生延迟时，旧按键不会批准/拒绝后来显示的请求。

**改动文件**

| 文件 | 改动 |
| --- | --- |
| `pc/hub_keyboard.py`（新增） | USB/Raw Input 适配、切换、重试和释放 |
| `pc/hub.py` | 接入自动读键器；提供历史输入快照入口 |
| `pc/deck_input.py` | 可选双边沿事件、原始时间、设备移除、轮询和可中断停止；旧 deck 默认行为保留 |
| `pc/deck_usb.py` | 可选 `reconnect=False`，让 Hub 接管打开/读取失败；原默认重连行为保留 |
| `pc/hub_doctor.py` | 显示可用读键方式，两种都不可用才记键盘检查失败；移除用户侧 Zadig 指引；只读枚举目标键盘 |
| `agentdeck.spec` | 显式打包 `deck_input`、`hub_keyboard` |
| `pc/hub_README.md` | 更新读键方式、连接恢复和释放说明 |
| `pc/test_hub_keyboard.py`（新增） | 18 项适配/切换/过滤/生命周期测试，含各绑定和 F13–F24 的一致性子测试 |
| `pc/test_deck_input.py`、`pc/test_deck_usb.py` | 双边沿、消息时间回绕、停止及 USB 失败传播测试 |
| `pc/test_hub_input_capture.py` | 排队旧按键、原生读取延迟与真实 Hub 请求绑定回归测试 |
| `pc/test_hub_doctor.py`、`pc/test_hub_app_support.py` | 两后端可用性、只读精确设备过滤、自检文案 |
| `pc/test_hub_runtime.py` | CLI 生命周期测试替身改为自动读键器 |
| `research/rawinput-results.md` | 本结果记录 |

**测试实际输出摘要**

使用 `D:\conda\miniconda3\python.exe` 从项目根目录逐个执行全部测试脚本。每个脚本在独立进程内运行；测试使用替身和临时 home，并对测试主进程增加审计钩子，拒绝访问真实用户的 `.claude` / `.codex`。完整 stdout/stderr 保存于 `research/rawinput-tests.log`。

```text
UI: 7 groups passed
daemon offline tests: 10 groups passed
PC and firmware loop: 4 groups passed
deck Raw Input offline tests: 5 groups passed
deck USB offline tests: 25 groups passed
test_hub_keyboard.py: Ran 18 tests ... OK
test_hub_input_capture.py: Ran 7 tests ... OK
test_hub_doctor.py: Ran 17 tests ... OK
test_hub_app_support.py: Ran 24 tests ... OK
test_hub_runtime.py: Ran 6 tests ... OK
test_verify_real_session.py: Ran 20 tests ... OK
All pc/test_*.py: 33/33 passed; failures=[]
```

脚本输出合计 624 个 unittest 测试、140 个旧式断言组；子测试另计。新增模块/改动的 Python 与 spec 共 13 个文件通过静态语法检查，`git diff --check` 通过。仓库没有独立的 lint/typecheck 配置，环境未安装 Ruff/mypy，未新增这些依赖或宣称运行过它们。显示输出未变，因此未重新生成模拟图。

只运行键盘可用性的只读探测（未运行会检查用户配置的完整 doctor），实际结果为：

```json
{"connected": true, "driver": null, "usb_available": false, "rawinput_available": true, "errors": []}
```

这确认当前系统能枚举到目标 Raw Input 键盘；PnP 驱动元数据未确认，不影响 Raw Input 可用性判断。探测不注册监听器、不打开 USB 端点、不访问厂商 HID collection。

**打包结果**

打包前检查 `AgentDeck.exe` 无运行进程，并确认输出目录位于本工程 `dist\AgentDeck`。运行现有 `build_exe.bat`，退出码 0，构建日志保存于 `research/rawinput-build.log`：

```text
Building COLLECT COLLECT-00.toc completed successfully.
Built: D:\desk\hardware\h1\dist\AgentDeck\AgentDeck.exe
Relay: D:\desk\hardware\h1\dist\AgentDeck\AgentDeck-relay.exe
```

通过 PyInstaller 归档读取器静态检查成品，确认 `hub_keyboard`、`deck_input`、`deck_usb` 均包含在 exe 的 PYZ 中。主程序 5,740,259 字节，relay 1,762,255 字节。没有启动任何生成的 exe。

**待用户验收**

实际按键、组合键、旋钮、按住语音后拔插，以及 HID/WinUSB 驱动变化后的恢复，仍需用户启动成品验证；离线替身与只读枚举不等同于这些实机操作。Raw Input 不拦截系统键盘事件，按键也可能到达前台窗口。

本次没有连接 COM4、上传固件、写键盘配置、访问 `0xFF00` 接口、增加控制传输、访问真实 Claude/Codex 配置或创建 git commit。未修改固件和受保护目录。
