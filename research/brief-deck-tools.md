# 简报：按工具分键 + 自动断言的真机自测

## 问题（用户实测）
E=slot 1、B=slot 2 按"会话加入顺序"选会话。板子上的顺序是 cx-demo1, ds-demo2, cc-…，所以 E/B 只能在 Codex/DeepSeek 间切，Claude 只能靠旋钮到达。用户觉得按键含义不可预测。用户要求：交付前软件自己验证干净，不再让用户反馈。

## 要做的
1. `deck.py` 新增动作 `tool <cc|cx|ds>`：
   - 在 `list` 里找该工具前缀的会话（key 以 `cc-`/`cx-`/`ds-` 开头）。
   - 当前已选中的就是该工具的会话时，再按一次轮到同工具的下一个会话（多个 Claude 会话时可轮换）。否则选该工具里优先级最高的：wait > error > tool > think > done > idle，同级取 list 中靠后的（较新）。
   - 选中后的行为与 slot 相同：发 `focus <key>`、touch `daemon.DECK_HOLD`、更新 `selected`、找窗口并拉到前台。
   - 该工具没有会话时，发 `focus <cc|cx|ds>`（固件支持，会显示该工具 READY），同样 touch hold，返回 "focus cc; no session"。
2. `deck_map.json` 的 bindings 改为：
   - `hid:0x08`(E) = tool cc，`hid:0x05`(B) = tool cx，`ctrl+hid:0x1D`(Ctrl+Z) = tool ds
   - `hid:0x2C`(空格) = next_wait
   - 其余保持不变（approve/deny/cycle/auto/各旋钮）。
   - 说明文字同步更新。
3. 检查 `cycle` 的顺序与 `tool` 的交互：从 tool 选中的会话出发，cycle ±1 应从该会话前后移动。
4. 离线测试：更新现有测试中的默认映射期望，新增 tool 动作的测试，覆盖以下情况：
   - 该工具有 0 / 1 / 多个会话
   - 重复按键时轮换
   - 优先级选择
   - hold 文件被 touch
   - 选中后 cycle 的起点
   
   所有测试都不要写真实 `pc/.deck_hold`：把 hold 路径做成可注入的参数，测试里用临时目录。顺带把已有测试里写真实 hold 文件的地方也改掉。
5. 把 `research/selftest_deck_live.py` 改成**自动断言**的真机自测：
   - 开始时先保存当前 `list`，然后 `clear`，放入固定场景：`cc-test1 tool h1`、`cx-test1 wait demo-cx`、`ds-test1 think demo-ds`、`cc-test2 idle second`。
   - 依次执行 `tool cc`、`tool cc`（应轮到另一个 Claude）、`tool cx`、`tool ds`、`cycle +1`、`cycle -1`、`next_wait`、`auto`。
   - 每步执行后过 0.6 秒和 3 秒，分别读 `dump`，解析第 1 行的工具名（Claude/Codex/DSK）和第 2 行的项目名，断言与预期一致：两次都一致才算通过，3 秒那次用来证明没被 daemon 抢回。`auto` 那步断言屏幕显示 wait 的会话。
   - 结束时 `clear`，再用 `set` 恢复开始时保存的会话，删除 `.deck_hold`。
   - 打印 PASS/FAIL 表，有失败就以非 0 退出。
   - 注意：Controller 用真实 WindowControl 时会把窗口拉到前台。测试场景里的会话都没有匹配窗口，这样没问题；但 `cc-test1 h1` 可能会匹配到真实窗口，所以项目名用不会匹配的值，比如 `zz-selftest`。
6. 改动前把要改的文件备份到 `_rollback/deck-v0-tools/`。

## 做完的标准
全部 9 个测试脚本通过（贴出输出）。自测脚本写好但**不要运行**：沙箱访问不了 COM4，由我来跑。最后列出改动文件清单。
