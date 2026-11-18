# 简报：用宏键盘模拟 v2 布局 + Hub 按键回放自测

目标：在没有 v2 硬件的情况下，用现有的 CXT 宏键盘（20 键 + 4 旋钮，已经通过 WinUSB 直读）模拟 v2 的按键布局，并且能离线回放真实的按键报文，验证"按键 → 动作"这条链路。

## 1. `pc/hub_keys.json` 加一套 `v2_emulation` 映射
- 宏键盘的物理键码：读 `pc/deck_map.json`，里面有已知的出厂键码和注释。另外，出厂宏是先单独发一帧 Ctrl，再发主键（见 `deck_usb.ReportState` 的 fresh modifier 逻辑）。
- 映射要求：
  - 6 个会话键 → `slot 1..6`；
  - ✓ → `approve`，✗ → `deny`；
  - 按住说话 → 按下 `voice_down`，松开 `voice_up`；
  - Ctrl+✗ → `interrupt`；截图键 → `screenshot`；
  - 旋钮转动 → `cycle ±1`；
  - Ctrl + 会话键 → `prompt` 模板。
- 尽量只用 `deck_map.json` 里已经确认过的键码。键码不够分配时，写清楚"待用户按一遍确认"，不要猜。
- 在 `pc/hub_keys.md` 里画一张表：物理键（位置描述 + 键码）→ 动作。用户以后照着表贴标签。

## 2. `research/selftest_hub_replay.py`（离线 + 本机 HTTP）
- 启动一个**临时 hub 进程**：用随机端口和临时 token 目录（`--home` 或环境变量；hub 不支持的话，加一个只用于测试的参数），`--backend none`，并且用参数关掉 LCD 输出，避免碰 COM4。
- 用 `deck_usb.ReportState` 把手写的 8 字节 boot report 序列解码成事件，再按 `v2_emulation` 映射成动作，通过 `POST /action` 发给临时 hub。
- 同时用 `hub_relay.py` 的 `relay()` 往临时 hub 发 Codex 格式的 PermissionRequest（低风险、高风险、极危各一条）。
- 断言以下结果：
  - ✓ 键批准低风险请求；
  - 高风险要 ✓ 两次；
  - 极危请求立即返回 `{}`，按 ✓ 得到 `locked`；
  - ✗ 键拒绝；
  - 旋钮循环会话；
  - 会话键选中对应槽位；
  - 带 Ctrl 的组合按出厂宏的两帧顺序输入，也能识别。
- 最后打印 PASS/FAIL 表，并关掉临时 hub。不碰 COM4，不装钩子，不发真实按键。

## 3. 验收
- `D:/conda/miniconda3/python.exe research/selftest_hub_replay.py` 全部 PASS。
- 现有测试全部通过。
- 改动前备份到 `_rollback/hub-v1_2/`。汇报：映射表、自测输出。
