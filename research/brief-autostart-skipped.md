# 简报：开机自启被 Windows 跳过（只调研，不改代码）

## 现象（已查实）
- 本机 Windows 11 Pro 10.0.26300（Insider/Canary 级别的版本号），普通用户，未提权。
- `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 里有值 `AgentDeck` = `D:\desk\hardware\h1\dist\AgentDeck\AgentDeck.exe --background`（REG_SZ，路径无空格、无引号）。键最后写入时间 2026-11-19 03:06 本地时间。
- `HKCU\...\Explorer\StartupApproved\Run` 里**没有** AgentDeck 这一项（也就是没有被用户在任务管理器里禁用）。
- 2026-11-19 07:07 重启。`Microsoft-Windows-Shell-Core/Operational` 日志显示 07:08:25–07:09:02 枚举 HKCU Run 时依次启动了 OneDrive、Steam、WallpaperEngine、Typeless、EDeviceMonitor、LGHUB、RazerAppEngine（事件 9707/9708），**AgentDeck 没有 9707 事件**，就是根本没尝试启动。同表里 Typeless、LGHUB、Razer 也不在 StartupApproved 里，却被启动了。WorkBuddy 两项也没启动，但它们的 exe 已不存在，可以解释。
- AgentDeck.exe 在 05:58 就已存在；手动用同一条命令启动正常（1 秒内 /health 正常）。CodeIntegrity / Defender / AppLocker / SmartScreen 日志里没有 AgentDeck 相关事件，Smart App Control 关闭（VerifiedAndReputablePolicyState=0）。
- AgentDeck.exe 是 PyInstaller onedir 打包的、未签名的 exe。

## 要你做的
1. 查官方文档和可靠资料：Explorer 处理 HKCU Run 时，什么情况下会**不记 9707、直接跳过**某一项？重点看 Windows 11 24H2 及以后 / Insider 26xxx 有没有新规则（例如新加入的启动项要先在“设置 > 应用 > 启动”里确认、未签名程序、新加入后首次登录不执行、StartupApproved 缺项的处理、路径不加引号等）。
2. 只读地检查本机，找出能解释"AgentDeck 被跳过而 Typeless 没被跳过"的差异（可以看 `HKCU\...\Explorer\StartupApproved\*`、`HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\` 下与启动相关的键、Typeless 的注册方式、文件属性/区域标识 Zone.Identifier 等）。**不要改注册表、不要建计划任务、不要动 Run 键**。
3. 给出最可靠的普通用户（非管理员）开机自启方案，按可靠性排序，并说明每种方案在本机是否需要管理员、会不会被同样的规则拦：Run 键加引号、启动文件夹快捷方式（shell:startup）、任务计划程序登录触发器（当前用户、无需提权能否创建）、其他。

## 做完的标准
写到 `research/autostart-skipped-results.md`：结论（最可能的原因 + 证据链接/本机证据）、推荐方案和理由、需要改的代码位置（`pc/agentdeck_app.py` 的 `AutoStart` 类）建议。不改任何代码和系统设置。
