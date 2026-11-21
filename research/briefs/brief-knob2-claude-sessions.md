# 简报：旋钮 2 列出 Claude 窗口里的全部会话；侧栏收起时也能跳过去

## 现象（2026-11-20 实测）
1. 旋钮 2 的会话卡片只列 AgentDeck 收到过钩子的会话（现在只有 4 个），用户在 Claude 窗口里有 40 多个会话，转不到。
2. 用户把 Claude 侧栏收起来了。收起时窗口里没有任何会话按钮，`claude_uia.ps1` 的 `invoke` 找不到标题，
   日志：`Claude 侧栏里没找到：全书审校与排版`、`打开会话失败`。

## 已查明的事实（不用再查）
- Claude 桌面版把每个会话存成只读可读的 JSON：
  `%APPDATA%\Claude\claude-code-sessions\<账号>\<组织>\local_*.json`。
  - 有 6 个 `<账号>\<组织>` 目录，内容大多是旧副本；**当前账号 = 里面文件 mtime 最新的那个目录**。
  - 字段：`sessionId`（local_…）、`cliSessionId`（= 钩子里的 session_id / 转录文件名）、`title`、`cwd`、
    `lastActivityAt`（毫秒）、`isArchived`、`scheduledTaskId`、`spawnedFrom`。
  - **过滤规则**：去掉 `isArchived` 为真、带 `scheduledTaskId`、没有 `title` 的；剩下的按 `lastActivityAt` 倒序，和侧栏完全对得上（实测 48/48）。
  - 当前目录 252 个文件，冷读 0.25 秒；个别文件 300 KB。按 (mtime, size) 缓存，只重读变了的。
- 侧栏开关（UIA，Button，AutomationId 不稳定，按名字找）：
  - 收起时名字是 `Show sidebar`，**只支持 ExpandCollapsePattern**，用 `.Expand()` 展开；约 1.2 秒后会话按钮出现在树里。
  - 展开时名字是 `Hide sidebar`，**只支持 InvokePattern**，`.Invoke()` 收起。
  - 侧栏里每组前有 `New session in <组名>` 按钮，组名 = 会话 cwd 的最后一级文件夹名（xmomo、h1、llm、12…）。
  - 重名标题存在（如"项目整合评估与优化"×3、"文档编译与交互版本"在 CN 和 llm 各一个）。

## 要做的
1. **新模块 `pc/claude_sessions.py`**：`recent_sessions(limit=12)` 按上面规则读当前账号目录，返回
   `[{"session_id", "cli_session_id", "title", "cwd", "last_activity"}]`（倒序）。只读、不写那个目录、任何异常返回 `[]`；
   带 (mtime,size) 缓存；路径可注入以便测试。加进 `agentdeck.spec` 的 hiddenimports。
2. **旋钮 2 卡片（`pc/hub_controls.py` 的 `session next/prev/select`）改为列 Claude 窗口里的会话**：
   - 列表 = `recent_sessions()` 的结果，和 hub 已知会话合并：hub 里 agent 为 cc 且 `session_id == cli_session_id` 的，
     用 hub 的状态（批/问/跑/完/错），否则显示"闲"。hub 里的 Codex 会话也并进来，按最近活动混排。总数封顶 12。
   - 读 `recent_sessions()` 不能拿着 hub 锁做文件 IO：后台线程预取（hub 启动时一次、之后每 10 秒或每次卡片打开时异步刷新），卡片打开时用缓存。
   - 卡片一次显示 7 行（`hub_overlay._v9_display` 的 `card_entries[:7]`）；选中项超出 7 行时让可见窗口跟着滚，不要选中项消失。
   - 卡片打开时仍按现有 `_origin` 逻辑把当前打开的会话设为初始选中项。
   - 按下：hub 已知的会话走现有 `_show_session`；只在 Claude 清单里的会话，先把 Claude 窗口拉到前台（复用 app claude 的找窗逻辑），
     再按标题 + 组名在侧栏里点开，成功/失败照现有提示（"已打开：…" / "打开会话失败：…"）。
   - 卡片没打开时按下 = 跳到下一个等你的会话，保持不变。
3. **`pc/claude_uia.ps1` 的 `invoke`**：
   - 标题找不到、且存在 `Show sidebar` 按钮时：`.Expand()`，每 100 ms 重新取快照，最多等 2.5 秒；点开会话后，
     **只有是自己展开的**才用 `Hide sidebar` 的 `.Invoke()` 收回去。响应里加 `expanded: true/false`。
   - 请求可带可选 `group`（组名）：有重名时，优先选 `New session in <group>` 之后、下一个组头之前的那一个；没有 `group` 时行为不变。
   - `list` 不做展开（它只用来读当前标题）。
   - 脚本保持纯 ASCII（PowerShell 5.1 会把无 BOM 的 .ps1 当 ANSI 读）。
   - `claude_uia.py` 的 `invoke()` 增加可选 `group` 参数并透传；`hub_desktop.show_session` 传入 cwd 的最后一级目录名。

## 不要做
- 不写、不改、不删 `%APPDATA%\Claude` 下任何文件；不改 Claude 设置。
- 不动键位文件、动画、读键逻辑；不往 0xFF00 接口或 COM4 发东西。

## 做完的标准
- 新测试覆盖：`claude_sessions` 的过滤、最新目录选择、倒序、封顶、缓存（用临时目录造 JSON）；卡片合并与去重、状态字、
  Codex 会话混排、超过 7 行时的可见窗口、按下 hub 会话 / 只在清单里的会话分别走哪条路；`claude_uia.py` 透传 `group`。
- `pc/test_*.py` 全部通过（`D:\conda\miniconda3\python.exe -X utf8 <文件>` 逐个跑）。
- 列出改了哪些文件；不要提交 git。

## 第二轮修正（审查确认的 3 处，2026-11-20）
1. **按下用了 hub 的旧标题**（`hub_controls.py` select → `_show_session` → `hub._focus_effect` 用 `dict(hub.sessions[identity])`）：
   卡片行里如果合并了 Claude 清单（有 claude_session_id），按下时要把**卡片行的 title 和 cwd**（清单里的值）带给 show 路径，
   覆盖 hub 记录里的旧标题/空标题。给 `_show_session` / `_focus_effect` 加一个可选覆盖参数即可，不要改 hub.sessions 里存的值。
   测试：hub 里 ('cc','X') 标题 'Old'，清单 cli='X' 标题 'New' → 按下时 show_session 收到 'New' 和清单的 cwd。
2. **invoke 超时余量**（`claude_uia.py` COMMAND_TIMEOUT=5.0）：invoke 冷启动 + 展开轮询 2.5 s + 收回快照可能超过 5 s，
   Python 杀掉 PowerShell 时侧栏还没收回。改法：`_command` 支持按命令传超时，**invoke 用 10 秒**，其余命令保持原值；
   PowerShell 侧给 invoke 加总截止时间（从收到请求起 7 秒），轮询循环在截止前 2 秒停，保证 finally 里的收回一定有时间跑。
   测试：invoke 用到更长超时、list 仍用默认超时。
3. **卡片初始选中的重名**（`hub_controls.py` `_origin`）：当前标题在合并列表里有多个同名项时，优先 hub.selected 对应的那一项，
   其次最近活动的那一项（现在的行为）。测试覆盖两种情况。

做完标准同上：`pc/test_*.py` 全过，列出改动文件，不提交 git。
