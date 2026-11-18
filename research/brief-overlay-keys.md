# 简报：浮窗不挡视野 + 空闲键配上指令（Carbon 做，Codex 审）

## 背景（用户实测反馈，2026-11-18）
- 浮窗固定在右下角，挡视野，用户点了关闭，结果整个 hub 跟着退出（`pc/hub_overlay.py` 第 361–373 行：mainloop 结束就调 `on_close` → hub 停机）。
- 宏键盘实测键位（4 列 × 5 排，出厂键码，hub 通过 USB 独占读取，映射在 `pc/hub_keys.json`）：
  - 第 1 排：E 会话1、B 会话2、Ctrl+Z 会话3、空格 打断
  - 第 2 排：G 批准、Ctrl+F 拒绝、H 按住说话、（第 4 颗无信号）
  - 第 3 排：L 截图、M、Ctrl+T、Ctrl+D
  - 第 4 排：U、X、（第 3、4 颗无信号）
  - 第 5 排：Tab、Ctrl+C、Ctrl+V、P 上一个会话
  - 未绑定的有：M(hid:0x10)、Ctrl+T(ctrl+hid:0x17)、Ctrl+D(ctrl+hid:0x07)、U(hid:0x18)、X(hid:0x1B)、Tab(hid:0x2B)、Ctrl+C(ctrl+hid:0x06)、Ctrl+V(ctrl+hid:0x19)

## 要做的
1. **关浮窗不再关 hub**：点关闭只隐藏浮窗，hub 继续运行；有新的待批请求时浮窗自动重新出现；hub 真正退出只走原来的停止脚本（`stop_agentdeck.bat`）或 Ctrl+C。
2. **浮窗不挡视野**：
   - 默认缩成一条细条（只显示"N 个会话 / M 个待批"），有待批请求时才展开显示详情，批完自动收回；
   - 可以用鼠标拖到任意位置，位置记到 `~/.agentdeck/overlay.json`，下次启动沿用；
   - 加一个"半透明"开关（窗口透明度 0.85），默认开。
3. **空闲键配指令**（只改 `pc/hub_keys.json` 的映射，不改键盘本身）：
   - M → `prompt continue`（继续）
   - Ctrl+T → `prompt tests`（跑测试）
   - Ctrl+D → `prompt summary`（总结进度）
   - U → `prompt commit`（提交）
   - X → `cycle +1`（下一个会话）
   - Tab → `next_wait`（跳到下一个在等我的会话）
   - Ctrl+C、Ctrl+V 先留空（容易和系统快捷键混淆）
   - 同时更新 `pc/hub_keys.md` / README 里的键位说明，写成上面那张 4×5 的表。
   - 如果 `hub_keys.json` 里原有的 `hid:0x14`、`hid:0x19`、`ctrl+hid:0x27` 这些在实测里不存在的键码映射和新映射冲突，以新映射为准，旧的保留不删。

## 约束
- 改前把要改的文件复制到 `_rollback/overlay-keys/`。
- 只用标准库（tkinter 已在用）。
- 不改 nonce、闸门、风险规则、hook 协议。
- 现有测试必须继续通过；为 1、2、3 各加测试（tkinter 部分用现有测试里的假窗口写法，参考 `pc/test_hub_overlay.py`）。

## 汇报
改动文件、每条要求怎么实现、对应测试名。
