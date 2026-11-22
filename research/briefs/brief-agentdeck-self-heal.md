# 简报：AgentDeck 被 Claude 连带关掉以后要能自己回来

## 已查实的原因（2026-11-22）
- 用户报"键盘连着但没反应"：AgentDeck.exe 根本没在运行。日志最后一行停在 11-21 02:56，没有报错、没有崩溃事件。
- 11-21 02:47 那次重启，是 Claude 会话里用 PowerShell 工具 `Start-Process AgentDeck.exe` 启动的。
- 已用只读探针确认：从 Claude 的 PowerShell 工具启动的进程，会落在 Claude 桌面主进程持有的一个作业对象里。这个作业的 flags=0x3c00，带 KILL_ON_JOB_CLOSE。
  Claude 退出、重启或更新时，作业关闭，里面的进程全部被系统直接杀掉，不会留下日志。
- 11-21 03:11:53 Claude 的应用包关闭过一次（系统日志 Kernel-General 16），hub 最后一次写 `sessions.json` 是 03:11:51。
- 开机时由计划任务 `AgentDeck`（登录触发，`dist\AgentDeck\AgentDeck.exe --background`，IgnoreNew，不限时）启动的那份，早被重新打包时的 `taskkill` 关掉了，之后再没有东西把它拉起来。
- 刚才改用 `schtasks /Run /TN AgentDeck` 启动，新进程的父进程是 svchost，不在 Claude 的任何作业里。

## 要改
1. **relay 自愈**（`pc/hub_relay.py`）：每次钩子事件发现 hub 不在时，请计划任务把 AgentDeck 拉起来。
   - 触发条件：`hub_status` 判定为 down；或者连接失败（拒绝或超时），而且 hub.json 里的进程已经不是 hub 本身。
   - 防 PID 被复用：hub 写 `hub.json` 时加上 `"created"`（hub 进程的创建时间，用 GetProcessTimes 取）。
     `hub_status` 发现同 PID 的创建时间对不上，就当作 down；没有这个字段时沿用旧逻辑。
   - 拉起方式：`schtasks /Run /TN AgentDeck`，用 subprocess.run，CREATE_NO_WINDOW，超时 3 秒。
     只走计划任务，不要直接启动 exe（直接启动会再次落进 Claude 的作业）。
   - 不拉起的情况：
     - `~/.agentdeck/app.json` 里 `"quit_by_user": true`（用户自己点了退出）；
     - `~/.agentdeck/maintenance` 存在且修改时间在 15 分钟以内（正在重新打包）；
     - 距上次尝试不到 60 秒，时间戳记在 `~/.agentdeck/relay_restart.json`，尝试前先写；
     - 不是 Windows。
   - 每次尝试往 relay.log 记一行（成功：已请计划任务启动 AgentDeck；失败：错误原文，例如任务不存在）。
   - 钩子原有语义完全不变：gate 事件照旧返回 `gate_failure`，普通事件照旧返回 None；自愈出错也不能影响钩子返回。
2. **退出原因看得见**（`pc/agentdeck_app.py`，必要时 `pc/hub.py`）：
   - 启动时记一行：pid、父进程名、是否在作业里（IsProcessInJob）。
     在作业里就记 WARNING："AgentDeck 在别的程序的进程组里启动，那个程序退出时会把它一起关掉，请用计划任务或 restart_agentdeck.bat 启动"。
     只记日志，不要自己重启自己（避免循环）。
   - 退出时记一行原因：菜单退出、启动失败（附错误）、主循环结束、未捕获异常。
   - `sys.excepthook` 和 `threading.excepthook` 把未捕获异常写进 app.log。
   - `faulthandler.enable` 写到 `~/.agentdeck/logs/crash.log`（文件对象要一直持有）。
   - 每 30 分钟记一行心跳："运行中：读键方式=…，会话=…"。用已有的状态快照，不要额外拿 hub 锁。
   - 菜单"退出"：先把 `quit_by_user=true` 存进 app.json 再退出；每次启动时清成 false。
3. **重启脚本** `restart_agentdeck.bat`（仓库根目录）：
   1. 建 `%USERPROFILE%\.agentdeck\maintenance`；
   2. `taskkill /IM AgentDeck.exe /F`；
   3. 参数是 `build` 时调用 `build_exe.bat`，失败则删标记、退出码 1；
   4. 删标记，`schtasks /Run /TN AgentDeck`；
   5. 最多等 15 秒，确认 AgentDeck.exe 在运行，打印 PID；没起来就退出码 1。
4. **文档**：
   - `AGENTS.md` 加一句：重启 AgentDeck 只用 `restart_agentdeck.bat`（走计划任务），不要用 Start-Process 或直接运行 exe，否则 Claude 退出时会被一起关掉。
   - `agentdeck/使用说明书.md` 的排障部分加一句：键全部失灵时先看托盘有没有 AgentDeck 图标；新版会在下一次 Claude/Codex 有动作时自己拉起来。
5. **测试**（新建 `pc/test_self_heal.py`，或并进已有测试）：
   - relay：
     - hub down 且无标记 → 调一次 schtasks，参数正确；
     - 60 秒内第二次 → 不调；
     - quit_by_user → 不调；
     - 新的维护标记 → 不调，超过 15 分钟的旧标记 → 调；
     - schtasks 失败 → 记日志，钩子照常返回；
     - hub up → 不调；
     - PID 活着但创建时间对不上 → 当 down；
     - gate 事件返回值不变。
   - app：
     - 退出菜单写 quit_by_user，启动清掉；
     - 退出原因有日志；
     - 两个 excepthook 已装；
     - 心跳按 30 分钟记（假时钟）。
   - hub.json 带 created。

## 不要做
- 测试里不要真的运行 schtasks、taskkill，也不要动正在运行的 AgentDeck；不要重新打包（我来做）。
- 不新建、不修改计划任务和注册表 Run 值（只允许运行已有的任务）。
- 不写 `~/.claude`、`~/.codex`、`%APPDATA%\Claude`。不往 0xFF00 接口或 COM4 发东西。不动动画。

## 做完的标准
- `pc/test_*.py` 全部通过（逐个用 `D:\conda\miniconda3\python.exe -X utf8` 跑；`test_verify_real_session.py` 偶发失败时单独重跑确认）。
- 列出改动文件；不要提交 git。
