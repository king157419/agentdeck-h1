# 简报：AgentDeck.exe（像键盘驱动一样的托盘程序）

## 目标

用户要能**双击一个 exe** 就用 CXT 宏键盘管理 agent：常驻系统托盘，启动后 hub、USB 键盘、浮窗全部就绪；
托盘能看状态、装钩子、开机自启。不需要打开终端、不需要记命令行。

## 现状（先读，不要重写）

- `pc/hub.py`：中枢，`--backend usb,hotkey --overlay --require-nonce` 是日常组合（见 `start_agentdeck.bat`），HTTP 127.0.0.1:47800，`/health` 不要 token。
- `pc/hub_overlay.py` 浮窗（tkinter）、`pc/hub_relay.py` 钩子转发、`pc/hub_install.py`（支持 `--project DIR`）、`pc/hub_doctor.py`、`pc/hub_keys.json` 键位、`pc/hub_prompts.json` 模板。
- 文档：`pc/hub_README.md`。

## 要做

### A. 托盘程序 `pc/agentdeck_app.py`

一个进程里跑 hub（直接调用 hub 的入口或内部 API，不要再起 python 子进程——打包后没有 python）。用 `pystray`（已装 0.19.5）+ PIL 画托盘图标。

1. **托盘图标颜色 = 总状态**：无会话灰、有运行绿、有待批琥珀（闪烁可选）、有出错红。悬停提示：`AgentDeck · N 个会话 · M 个待批`。
2. **菜单**：
   - 显示 / 隐藏浮窗
   - 会话（子菜单）：每个会话一行 `状态 工具 项目名`，点击 = 切到该会话窗口（复用 hub 已有的选择/聚焦逻辑）；外加"跳到等我的会话"
   - 键位：打开一个只读小窗口，按 4 列 × 5 排画出 CXT 键盘每颗键当前的动作（读 `hub_keys.json` 的当前 profile），旋钮单独列出
   - 诊断：弹窗显示 `hub_doctor` 的结果，用中文说人话：键盘 USB 是否已连接、接口 0 驱动是否为 WinUSB、token、哪些项目装了钩子、全局里还有几个旧版 `agent_lcd.py` 钩子、COM4 是否被占用，以及"Codex 需要在项目里输入 /hooks 信任"的提醒
   - 安装到项目…：选文件夹 → 等价于 `hub_install.py install --project <DIR>`；完成后弹窗提示 Codex 的 `/hooks` 信任步骤
   - 从项目卸载…：同上，`uninstall --project`
   - 开机自启（勾选项）：写/删 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\AgentDeck`
   - 打开日志文件夹、退出
3. **单实例**：已在运行时第二次双击只把浮窗显示出来，不起第二个 hub。
4. **首次运行**：没有任何项目装过钩子时，弹一个三步引导（装到项目 → Codex 里 /hooks 信任 → 开始干活），可勾选"不再提示"，状态存 `~/.agentdeck/`。
5. **不自动改全局配置**：不碰 `~/.claude/settings.json`、`~/.codex/hooks.json`。诊断里如果发现旧版 `agent_lcd.py` 钩子，只提供一个按钮"移除旧版钩子"，点了先确认、先备份（`*.bak-agentdeck-<时间>`）再删，只删 `agent_lcd.py` 那几条。
6. 1602 屏：串口被占时只记日志并继续，不能让程序退出。

### B. 钩子转发要能脱离 python

打包后 `hub_install` 写进钩子的命令不能再是 `python hub_relay.py`。做一个控制台程序 `AgentDeck-relay.exe`（和主程序同一个 onedir 文件夹），行为与 `hub_relay.py` 完全一致（hub 不在线时不输出、退出码 0）。
`hub_install` 在打包环境里（`sys.frozen`）写 relay exe 的绝对路径；源码运行时保持原行为。诊断检查钩子里的路径是否还存在（用户挪了文件夹要提示重装）。

### C. 打包

- `build_exe.bat` + `agentdeck.spec`：PyInstaller 6.11.1（已装），**onedir**，主程序无控制台，relay 有控制台，两者共用一个 `dist/AgentDeck/`。
- 带上 libusb 的 dll（`libusb_package`）、`hub_keys.json`、`hub_prompts.json`、图标（用 PIL 生成 `.ico`，原创简单图形即可）。
- 用户可编辑的配置：首次运行时把默认 `hub_keys.json` / `hub_prompts.json` 复制到 `~/.agentdeck/`，之后以那里为准。

## 做完的标准

1. 新逻辑有离线测试（状态聚合、菜单动作、自启注册表读写、单实例、frozen 路径分支），外部访问全部替身。
2. 原有测试全部仍通过：`pc/test_hub*.py`、`pc/test_ui.py`、`pc/test_daemon.py`、`pc/test_pc.py`、`pc/test_deck*.py`。
3. `build_exe.bat` 能在本机成功产出 `dist/AgentDeck/AgentDeck.exe` 和 `AgentDeck-relay.exe`。
4. `pc/hub_README.md` 开头加一节"用 exe"，中文，写用户要做的步骤。
5. 汇报：改了哪些文件、测试数量和结果、打包输出路径。真机启动、真按键由主会话验证，你不用起常驻进程。

## 禁止

- 不修改真实的 `~/.claude`、`~/.codex` 配置；测试用临时 home。
- 不向键盘厂商接口 `0xFF00` 发报文，不改驱动。
- 不动 `lcd1602/` 固件。
