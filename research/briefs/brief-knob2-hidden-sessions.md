# 简报：旋钮 2 不列、不跳到侧栏里没有的会话（定时任务、已归档）

## 现象
hub 记着一个定时任务跑出来的 Claude 会话"处理平板手写批注"（状态 wait）。它在 Claude 本地清单里带 `scheduledTaskId`，
不在侧栏里，但仍出现在旋钮 2 卡片里；卡片没打开时按下旋钮 2（跳到下一个等你的会话）也会先跳到它。两种情况都必然"打开会话失败"。

## 要做的
1. `pc/claude_sessions.py`：在同一次读目录时，另外给出"隐藏的 cliSessionId 集合"（`isArchived` 为真或带 `scheduledTaskId` 的记录的 `cliSessionId`），
   例如 `hidden_cli_session_ids()` 或让现有读取返回两样东西；复用同一份缓存，不要多读一遍目录。
2. `pc/hub_controls.py`：
   - 卡片合并时，hub 里 agent 为 cc、`session_id` 在隐藏集合里的会话不列入卡片。
   - 卡片没打开时按下的"下一个等你的会话"也跳过这些会话。
   - 隐藏集合读不到（清单读失败、为空）时，行为和现在一样，不要把 hub 会话全滤掉。
   - 不影响批准/拒绝：这些会话的批准请求照常能用批准键处理。
3. 测试：隐藏会话不进卡片、不被"下一个等你的"选中；清单读失败时 hub 会话照常列出。

## 不要做
- 不写 `%APPDATA%\Claude` 下任何文件；不动键位、动画、读键逻辑。

## 做完的标准
`pc/test_*.py` 全过（逐个用 `D:\conda\miniconda3\python.exe -X utf8` 跑），列出改动文件，不提交 git。
