# 简报：Hub v1.3 —— 让没有我们硬件的用户也能用（试用招募要用）

背景：路演前要招 30–50 个重度用户来试用，他们手上只有普通宏键盘、VIA/QMK 键盘、Stream Deck 或者什么都没有。免费软件必须让他们**不装驱动、不换 WinUSB** 就能用。

## 1. `--backend hotkey`：全局热键输入（Windows）
- 用 `RegisterHotKey` 注册 F13–F24，以及 Ctrl / Shift / Alt + F13–F24。大多数宏键盘和 VIA 键盘都能把键改成 F13–F24，而这些键在普通软件里基本没人用，不会冲突。
- 映射写在 `pc/hub_keys.json` 新加的 `hotkey` 段里。默认映射：
  - F13–F18 → `slot 1..6`；
  - F19 → `approve`，F20 → `deny`；
  - F21 → 按住说话：注册热键只能拿到按下，所以改成"按一下开始、再按一下结束"，对应 `voice_down` / `voice_up` 交替；
  - F22 → `screenshot`，F23 → `cycle +1`，F24 → `cycle -1`；
  - Ctrl+F20 → `interrupt`；Ctrl+F13..F16 → `prompt` 的 4 个模板。
- 消息循环跑在独立线程里；退出时注销全部热键。注册失败（被别的程序占用）只记一条警告，其余热键照常工作。
- `--backend` 支持组合写法，比如 `usb,hotkey`，可以同时开。

## 2. `--overlay`：屏幕角落的小浮窗（tkinter，标准库）
- 始终置顶、无边框、可以拖动，默认放在屏幕右下角，宽约 360 px。
- 显示 6 个槽位：编号、项目名、状态色块（RUN 绿 / ASK 琥珀 / DONE 蓝 / ERR 红 / IDLE 灰）。有正在显示的待批请求时，再显示：
  - 命令摘要（截断到 80 字）和风险档，high 显示为红色，critical 显示 `LOCKED: use terminal`；
  - ✓ 和 ✗ 两个按钮，点击和按键走同一条 `/action` 路径。
- 通过 `GET /state` 每 300 ms 刷新一次（同一进程内可以直接读状态，但要线程安全）。
- 浮窗**不能抢焦点**：点按钮之后焦点要回到原来的窗口，Windows 上给窗口加 `WS_EX_NOACTIVATE`。
- `--overlay` 可以和任何 backend 一起用，也可以单独用。

## 3. 测试
- 离线：热键映射解析；热键事件 → 动作，注入替身；注册失败时降级；浮窗的状态 → 显示模型。显示模型做成纯函数测试，不实际弹窗。
- 现有测试全部通过。不碰 COM4，不装钩子。
- 在 `pc/hub_README.md` 补"没有 AgentDeck 硬件怎么用"一节：用 VIA/QMK 把键改成 F13–F24；Stream Deck 用"系统 → 热键"发 F13–F24；也可以只开浮窗用鼠标点。

改动前备份到 `_rollback/hub-v1_2b/`。汇报：改动文件和测试输出。真机上的热键和浮窗由 Claude 主会话验证。
