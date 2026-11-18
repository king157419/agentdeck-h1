# 简报：修掉审查发现的 9 个问题

审查原文见 `research/codex-review.log` 末尾（共 9 条）。全部修掉，按下面定的方案做，不要另起炉灶：

1+2. **批准/拒绝要绑定按下那一刻的目标，并且严格匹配。**
   - USB 事件在收到报文时就记录 `hwnd=GetForegroundWindow()` 和 `t=monotonic()`，跟着事件一起进队列。
   - approve/deny 执行前依次检查，任何一项不满足就拒绝，并返回 `blocked: <原因>`：
     - 前台 hwnd 仍等于按下时记录的 hwnd；
     - 事件产生后不超过 1.0 秒；
     - 同一报文里没有其它已绑定的主键；
     - 前台窗口能**严格**匹配到唯一一个 wait 会话，即项目名命中，且进程/标题类型与会话前缀一致。仅凭工具关键词回退匹配的情况一律拒绝。
3. **修饰键歧义。** 事件带上完整的“当前按下的主键集合”。
   - approve/deny 只在按下后集合里恰好一个主键、且修饰键集合与绑定完全一致时才执行。
   - 如果修饰键是在更早的报文里就按着的（不是和主键同一报文新按下），带修饰键的绑定一律不匹配，改按裸键查找。例如 Ctrl 先按着、再拧旋钮出 F，应匹配 `F = cycle -1`，不能匹配 `ctrl+F = deny`。
4. **USB 断开时自动恢复。** `--backend auto` 在 USB 打不开时不要永久退回 rawinput：只要设备的接口 0 是 WinUSB 驱动（或者设备不在），就留在 USB 后端，每 2 秒重试。只有能确认接口 0 还是 HidUsb 时才用 rawinput 观察模式，并打印 Zadig 提示。
5. **hold 竞争。**
   - deck 先 touch hold，再发 `focus`；发完 0.4 秒后再补发一次同样的 `focus`，抢回可能被 daemon 旧 tick 覆盖的焦点。
   - daemon 在真正调用 sender 之前，再检查一次 hold。
6+9. **hold 期间由 deck 自己维护焦点。** deck 起一个后台线程，在 hold 有效期内每 2 秒执行一次：
   - 用 `list` 检查 selected 还在不在；不在了就发 `focus -`、删除 hold、清空 selected。
   - 距上次发 focus 满 20 秒就重发一次 `focus <selected>`（心跳），保证固件的 60 秒焦点 TTL 不会早于 hold 先过期。
   - hold 到期后线程停止心跳，交还给 daemon。
   - 线程要能干净退出；串口访问和动作线程不能并发打架：统一走一个加锁的 sender，或者把心跳也放进动作队列执行。
7+8. **窗口匹配必须严格且无歧义。**
   - 切换窗口时，进程或标题对应的工具类型必须和会话前缀一致：ChatGPT/Codex 对应 cx，Claude 对应 cc，DeepSeek 对应 ds。
   - 必须唯一匹配到目标会话的项目名。匹配不唯一或匹配不上，就不切窗口，只切屏幕，返回 `focus X; window ambiguous` 或 `no matching window`。

## 测试与验收
- 为每一条新增离线测试，复现审查里描述的场景并断言已修复。现有 9 个测试脚本继续通过。
- `research/selftest_deck_live.py` 仍然适用；如果接口变了就同步改，但不要运行（COM4 由我来跑）。
- 改动前备份到 `_rollback/deck-v0-fix/`。
- 汇报：逐条说明怎么修的，贴全部测试输出，列出改动文件。
