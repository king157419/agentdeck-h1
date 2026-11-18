# 简报：用代码给宏键盘改键（用户已授权，用户已睡，无人值守）

## 背景
- 宏键盘 USB `VID_4132&PID_2107`，hidapi 已装。接口3 是厂商 HID，usage_page 0xFF00 / usage 0x1，协议未知。
- 厂商改键软件 VIA-C（Electron）已装在 `D:\VIA-C\`（`via-c.exe`），它就是通过这个接口读写键位的。
- 当前出厂键位是 Photoshop 快捷键（字母、Ctrl+Z 等），20 个键 + 4 个旋钮。
- `pc/deck_map.json` 默认按 F13–F22 写好了动作（VK 0x7C–0x85）。

## 要做的
1. **找协议**：解包 `D:\VIA-C\resources\app.asar`（用 `npx asar extract` 或自己写 Python 解析 asar 头，解到 `research/via-c-src/`，不要改 D:\VIA-C 本身）。在 JS 里找：HID 打开方式（usage page 0xFF00）、报文长度、命令字节——获取协议版本、层数、读键位(get keycode / keymap buffer)、写键位(set keycode)、旋钮读写(encoder get/set)、是否需要"保存"命令。确认 F13–F24 的键码值（QMK 里 KC_F13=0x68 … KC_F24=0x73，以 VIA-C 源码为准）。把发现写进 `research/via-c-protocol.md`，附源码出处行。
2. **写工具 `pc/deck_keymap.py`**：
   - `backup`：读出全部层的完整键位 + 旋钮映射，存 `research/keymap-backup-<时间>.json`（同时复制一份到 `_rollback/deck-v0/keymap-original.json`，已存在则不覆盖）。
   - `show`：打印第 0 层矩阵（行列 + 键码名）。
   - `apply`：只改第 0 层：按矩阵顺序（行优先）的前 8 个**普通按键**改成 F13–F18、F21、F22；第一个旋钮顺时针=F19、逆时针=F20。其余键位不动。写之前必须先自动 backup。写完立即回读核对，不一致就自动用备份恢复并报错。
   - `restore <json>`：按备份恢复。
   - 任何协议不确定（找不到命令、回读格式不明）就**不要写**，停在 backup/show，报告原因。
3. **执行**：真实运行 `backup` → `show` → `apply` → `show`，贴出完整输出。
4. 更新 `pc/deck_map.json` 的说明文字（如需要）和 `lcd1602/README.md` 宏键盘一节：写清楚 deck_keymap 的用法和恢复命令，以及哪 8 个键 + 哪个旋钮被改了（按矩阵位置描述）。
5. 加离线测试 `pc/test_deck_keymap.py`（报文编码/解码、apply 只改目标位置、回读不一致时恢复），全部现有测试继续通过。

## 做完的标准
- 贴出 backup/show/apply/show 的真实输出和全部测试输出。
- 列出被改的矩阵位置：原键码 → 新键码。
- 给出一行恢复命令。
