# 简报：会话显示标题、按最近活动排序、直接点 Claude 侧栏切会话、旋钮 1 改成 Alt+Tab

用户实际用下来的问题：
- 浮窗上 5 个会话都显示"h1"（文件夹名），分不清；
- 顺序按"先报到先占位"（slot），不是最近使用；
- 旋钮 1 切会话（激活 Claude 窗口后发 Ctrl+Shift+]）必须先用鼠标点一下 Claude 才生效；
- 没有切窗口的办法。

## 已验证的事实（2026-11-20 在用户机器上实测）
1. Claude 对话记录（钩子数据里的 `transcript_path`，jsonl）里有 `{"type":"custom-title","customTitle":"现状与前景讨论",...}` 记录，取**最后一条**就是 Claude 侧栏显示的会话标题。
2. Claude 桌面版窗口（claude.exe，标题 "Claude"，类名 Chrome_WidgetWin_1）通过 UI Automation 暴露侧栏：
   - 每个会话是一个 Button，Name = `标题` 或 `标题 状态`（如 `现状与前景讨论 Running`、`授权 BibiGPT MCP Started by Claude from …`），**紧跟着**的下一个 Button 的 Name 是 `More options for 标题`，用它切出标题和状态；
   - 当前打开的会话：有一个 Button 的 Name 是 `标题, rename session`；
   - 会话 Button 支持 InvokePattern。实测：Invoke 后约 1.5 秒内当前会话变成目标会话，再 Invoke 原会话能切回；不需要鼠标、键盘焦点或快捷键；
   - 只取 Button（ControlType=Button 条件 + Descendants）读一遍约 0.4 秒（43 个会话）。
   - 实测脚本可参考（PowerShell 5.1 + System.Windows.Automation）：`C:\Users\king\AppData\Local\Temp\claude\2eaaed337eda2448\5ac40f04-0220-4bd3-8b9e-3d2718140ee8\scratchpad\uia_invoke_test.ps1`

## 要做的
1. **会话标题**：hub 收到 Claude 钩子事件时，若有 `transcript_path`，从文件尾部（读最后约 256 KB，必要时再往前）找最后一条 `custom-title` 取 `customTitle`；payload 里有 `session_title` 时优先用它。存进 session 的 `title` 并持久化到 sessions.json。浮窗、日志、反馈文字里会话名一律用标题（截断到合适长度），没有标题时退回文件夹名。读文件失败不能影响事件处理。
2. **候选顺序**：旋钮 2（`cycle ±1`）在会话间选择时，按最近活动时间（`last_updated`）从新到旧排；等批准的会话在浮窗上标出来，但不插队。浮窗列表也按这个顺序显示。slot 仍用于 LCD/硬件槽位，不要破坏现有 slot 相关测试；如果 slot 和显示顺序必须解耦，就解耦。超过 24 小时没有任何事件的会话不进候选、从 sessions.json 清掉。
3. **直接切 Claude 会话**（新模块，例如 `pc/claude_uia.py`）：
   - 不新增需要下载的依赖：用一个常驻的 PowerShell 子进程（`powershell.exe -NoProfile`，隐藏窗口）跑 UI Automation，stdin/stdout 一行一个 JSON；命令至少有 `list`（返回当前会话标题 + 会话列表 [标题, 状态]）和 `invoke`（按标题、同名时按第几个）。懒启动，子进程挂了自动重启，每条命令有超时（约 3 秒），超时就当失败。PowerShell 5.1 读无 BOM 的脚本会按 ANSI 解析，脚本里不要写中文字面量，或者写入时带 BOM；输出用 UTF-8。
   - 旋钮 2 按下（`show`）：所选会话是 claude.exe 里的会话时 → 激活 Claude 窗口（用现有 deck_windows.activate）→ invoke 侧栏里同标题的按钮 → 再 `list` 一次确认当前会话已变 → 反馈 `已切到：标题`。找不到按钮或确认失败 → 退回原来的行为（只激活窗口）并反馈 `Claude 侧栏里没找到：标题`。同名多个时取第一个并在日志里记一笔。
   - 开始转旋钮 2 时，先读一次 Claude 当前打开的会话，让选择从它开始（若它在候选里）。不做后台轮询。
   - 非 Claude 的会话（Codex、终端等）保持原来的激活窗口行为。
4. **旋钮 1 改成 Alt+Tab**：`hid:0x09`（顺时针）→ `window next`，`hid:0x16`（逆时针）→ `window prev`。第一格：按下 Alt（扫描码 0x38）再点一下 Tab（prev 用 Shift+Tab）；之后每格再点一下 Tab/Shift+Tab；停转 900 毫秒自动松开 Alt。任何其他动作开始前、hub 退出时都必须先松开 Alt（不能留下卡住的 Alt）。Raw Input 读键模式下拒绝（和 `app` 一样加进 RAW_INPUT_BLOCKED）。删掉 `app next/prev` 的绑定（代码可保留）。
5. `pc/hub_keys.json` 升到 version 8（沿用"用户没改过的文件自动升级并备份 .bak-v7"的机制）。状态窗口/键位窗口（agentdeck_app.py 的 KEY_ROWS 等）里旋钮 1 写"切窗口"，旋钮 2 写"选会话 / 按下切过去"。
6. 更新 `agentdeck/使用说明书.md` 对应小节（旋钮 1 切窗口、旋钮 2 选会话并直接跳过去、会话显示 Claude 里的标题），PDF 按老命令重新生成：复制 md 到临时目录，`D:/conda/miniconda3/python.exe -X utf8 D:/desk/claudex/_reports/tools/report.py <copy>.md --css agentdeck/使用说明书.css --out agentdeck/使用说明书.pdf`。
7. 测试：标题解析（有/无 custom-title、多条取最后、文件不存在、payload session_title 优先）；候选按 last_updated 排序和 24 小时清理；UIA 模块用假的子进程覆盖 list/invoke/超时/重启/找不到时退回；Alt+Tab 的按键序列、900 毫秒后松开、其他动作前强制松开、退出时松开。

## 做完的标准
每个 `pc/test_*.py` 单独跑都退出 0。不打包 exe，不 git commit。不碰真实的 ~/.claude、~/.codex、~/.agentdeck、计划任务、注册表、键盘 0xFF00 接口。不要在测试里真的去 Invoke 用户的 Claude 窗口。
