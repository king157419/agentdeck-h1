# 简报：钩子改成"一次启用，所有项目生效"

## 背景
用户反馈：每开一个新项目都要"安装到项目…"太麻烦。`hub_install.apply(action, home=...)`（project=None）已经能装到全局
`~/.claude/settings.json` 和 `~/.codex/hooks.json`，托盘只是没暴露。全局里现在还各有 8 个 v0 `agent_lcd.py` 钩子。

## 要做
1. `pc/agentdeck_app.py` 托盘菜单：
   - 新增可勾选项 **"所有项目启用"**，放在原"安装到项目…"的位置。勾选状态从真实配置读（两个文件里都有我们的钩子才算勾上），不从 prefs 读。
   - 勾上：弹一次确认（文案一句话：会先备份两份全局配置、换掉旧版 1602 钩子；AgentDeck 没开时 agent 照常在终端确认）。
     确认后依次 `remove_legacy_hooks(home=..., confirmed=True)`、`apply("install", home=...)`。
   - 取消勾：`apply("uninstall", home=...)`，不恢复旧版钩子。
   - 原"安装到项目… / 从项目卸载…"挪进子菜单 **"单个项目"**。
2. 首次运行引导：主按钮改成"所有项目启用"；全局已启用或已有项目安装时不再弹引导。
3. 自修复：exe 启动时若全局已启用、但配置里的 relay 路径不是当前 `AgentDeck-relay.exe` 的路径（文件夹被挪过），静默重装一次并写日志。
4. `pc/hub_doctor.py` 诊断里加一行全局状态（已启用 / 未启用 / 路径失效）。
5. 确认 relay 在 hub 没运行时快速退出、不输出，agent 退回普通终端确认；没有测试就补一个。

## 硬约束
- 测试一律用临时 home，**绝不读写真实的 `~/.claude`、`~/.codex`**。
- 不打包 exe（之后统一打）。不动 `hub_overlay.py` 的样式（另有美化任务）。
- 文案中文、短，不写提示性废话。

## 完成标准
- `D:\conda\miniconda3\python.exe` 跑 `pc/test_agentdeck_app.py`、`pc/test_hub_app_support.py`、`pc/test_hub.py` 及 hub_install 相关测试全过，新增功能有测试。
- 结果写进 `research/global-install-results.md`：改了哪些文件、测试命令和输出摘要。
