# 简报：第二轮复审的 5 个问题（见 research/codex-review2.log 末尾）

按下面的方案修，不要另起炉灶：

① **审批绑定完整窗口上下文。** 按下时记录 `(hwnd, 进程名, 窗口标题)`；执行时三者必须和当时完全一致，否则返回 `blocked: window context changed`。标题变化就说明终端切了标签。

② + ④ **用跨进程互斥代替 0.4 秒补发。**
- 新建一个小模块 `pc/focus_lock.py`，基于 Windows 命名互斥量（ctypes 调 CreateMutexW / WaitForSingleObject，名字用 `Local\AgentDeckFocus`），提供 `with focus_lock(timeout=1.0):`。拿不到锁就跳过这一次，不要阻塞太久。
- deck：在锁内依次完成 touch hold → 发 focus。
- daemon：在锁内依次完成检查 hold → 发 focus。
- 删掉 0.4 秒同步补发。
- 非 Windows 平台或测试时可以注入替身。

④ **积压合并 + 退出取消。**
- 动作线程取事件时，把队列里已排着的导航事件合并：连续的 `cycle ±1` 累加成一次 `cycle ±N`（Controller 要支持 N 步）；连续的 `tool`/`next_wait`/`slot` 只执行最后一个。
- approve/deny 不参与合并，也不能被跳过。
- 退出时丢弃所有未执行的事件，不再排空执行。
- 另外，`list` 查询的 `wait_reply` 降到能可靠拿到回复的最小值（看 agent_lcd 的实现决定）。用离线测试证明单次导航动作的耗时明显下降。

③ **工具身份不能被项目名干扰。**
- 进程名能确定工具时（ChatGPT/Codex 原生进程 → cx，Claude 原生进程 → cc，DeepSeek → ds），直接以进程为准。
- 终端或编辑器窗口：先在标题里找到项目名的位置，只在项目名以外的部分识别工具关键词。
- 回归用例：`deepseek-project - Codex` 匹配 `cx-a`；`chatgpt-demo - Claude` 匹配 cc 会话。

⑤ **focus 发送失败时回滚。** 恢复到发送前的 hold、selected、focus_target 状态。如果 hold 是这次新建的，就删掉，让 daemon 接管。

## 测试与验收
- 每一条都加离线回归测试，复现复审里描述的场景。现有测试全部通过。
- `research/selftest_deck_live.py` 只做接口适配，不要运行。
- 改动前备份到 `_rollback/deck-v0-fix2/`。
- 汇报：逐条怎么修的、全部测试输出、改动文件清单。
