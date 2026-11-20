# 简报：同窗会话优先用唯一标题匹配切窗

只改 `pc/` 下的文件。不要 git commit，不要碰真实 `~/.claude`、`~/.codex`，不要打开 COM4。

## 现象（已证实，不要再推导）

验收脚本 2026-11-19 04:56 那次（桌面未锁屏）`window-switch` 失败：
两个会话 alpha（cc）、beta（cx）的 relay 都是从 Claude 桌面版里的进程链启动的，
`find_agent_window()` 给两者记下了同一个窗口（claude.exe 的 "Claude" 主窗口，和真实的 h1 会话也是同一个）。
屏幕上另有两个 Windows Terminal 窗口，标题分别是 `accept-alpha-082205 - Claude Code`、`accept-beta-082205 - Codex`。
`POST /action {"action":"slot 2"}` 返回 `window=focused, shared_window=true`，前台仍是 "Claude"，四步全失败。

原因：`pc/hub_desktop.py` 的 `DesktopEffects._focus` 只要 `_bound_window()` 找到 relay 记下的句柄就直接用它；
这个句柄被 2 个以上会话共用时，它只代表“宿主窗口”，而 `deck.window_for_session()` 的严格标题匹配
（终端/编辑器进程 + 标题同时含项目名和唯一的工具词 + 无歧义）能唯一指出这个会话自己的窗口，却没有被尝试。

## 要做

1. `DesktopEffects._focus(session, sessions)`：
   - 记下的窗口存在、且它的 hwnd 在 `sessions` 里被 2 个及以上会话共用（比较各会话的 int `hwnd`）时，
     先用和现在回退路径相同的方式调用 `window_for_session()`；返回了窗口且其 hwnd 与记下的不同，就激活它。
   - 匹配不到、有歧义、或匹配到的就是同一个 hwnd：照旧用记下的窗口。
   - 记下的窗口没被共用：行为完全不变（不做标题匹配）。记下的窗口不存在：回退逻辑不变。
   - 激活与核对仍只比句柄（`activate()` 后 `self.windows()[0] == window[0]`）。
2. `pc/hub.py` 的 `Hub._focus_effect`：`desktop.focus()` 返回 `(hwnd, exe, title)` 这种窗口元组时，
   只有返回的 hwnd 等于这个会话记下的共用 hwnd 才带 `shared_window: True`；
   返回别的类型（测试替身返回 True 等）保持现在的判断。这样按键反馈不会对已经精确切过去的会话说“同窗：只能调到前台”。
3. `pc/hub_README.md` 讲 “Several sessions in one window …” 的那句后补一句：共用窗口时若能按项目名+工具词唯一匹配到别的终端窗口，先切到那个窗口。

## 测试（加到 `pc/test_hub_keypad.py`）

- `DesktopFocusTests`：alpha（key `cc-...`）和 beta（key `cx-...`）都记下同一个 `claude.exe` 窗口；
  窗口列表里另有 `WindowsTerminal.exe` 的 `alpha - Claude Code` 和 `beta - Codex`：
  focus(alpha) 激活 alpha 终端，focus(beta) 激活 beta 终端。
- 共用但没有标题匹配 → 激活记下的窗口；共用但标题有歧义（两个窗口都匹配 alpha）→ 激活记下的窗口。
- 未共用：记下的窗口存在时，即使别处有 `alpha - Claude Code` 也激活记下的窗口。
- Hub 层（`WindowBindingTests`）：把文件顶部的 `Desktop.focus` 替身改成返回 `(session.get("hwnd") or 1, "WindowsTerminal.exe", "x")`，
  让现有 `test_slot_in_a_shared_window_says_it_can_only_bring_it_forward` 仍表达原意并通过；
  再加一例：共用窗口但替身返回另一个 hwnd → 结果里没有 `shared_window`，`describe_input` 是 “已选槽位 N”。

## 做完的标准

从项目根目录依次运行并贴真实输出摘要：
`python pc/test_hub_keypad.py`、`python pc/test_hub_desktop.py`、`python pc/test_hub.py`、`python pc/test_ui.py`、`python pc/test_daemon.py`、`python pc/test_pc.py`。
`python` 用 `D:\conda\miniconda3\python.exe`。回复只写改了哪些文件、每个文件改了什么、测试结果。
