# 简报：审批 nonce 校验（任务 B：Codex 做，Carbon 审）

## 为什么
BP、PRD（`agentdeck/06-PRD-详细版.md` 第 306–307、337 行）和 Demo 口播都说"每条请求带 nonce，设备回报按键时带上它当时显示的 nonce，中枢核对一致才执行"，但现在没实现。技术方案见 `agentdeck/07-技术方案.md` 第 295–310 行的时序图。

## 要做的（先读 `pc/hub.py`、`pc/hub_README.md`、`pc/hub_overlay.py`、`pc/hub_virtual_device.py`、`pc/agent_lcd.py` 的显示协议部分）
1. 每条待批请求生成 `nonce`（`secrets.randbits(32)`），和 req_id 一起进 `/state`。
2. 审批动作（approve / deny，包括高危第二次确认）可以带 `nonce`：
   - 带了且和**当前显示的那条**请求一致、未过期 → 照常执行；
   - 带了但不一致或已过期 → 拒收，返回 409 和原因 `stale_nonce`，写审计日志，不改变任何请求状态；
   - 显示的请求刚切换后 300 ms 内收到的 approve 一律拒收（`switch_guard`），deny 不受此限。
3. 各输入后端怎么带 nonce：
   - 浮窗、虚拟设备：点击时带上它画面上当时显示的 nonce；
   - 热键、USB 宏键盘：这些硬件本身不知道 nonce，由 hub 在**收到按键的那一刻**取 LCD/浮窗**最后一次实际渲染**的 nonce 附上（不是取当前队首），这样渲染和按键之间换了请求也能拦住；
   - HTTP 直接调用：不带 nonce 时保持旧行为（兼容 demo 和现有测试），但在 `/state` 里标 `nonce_required: false`；加配置项 `require_nonce`（默认 false），打开后不带 nonce 的 approve 一律拒收。
4. LCD 和浮窗上显示 nonce 的后 4 位十六进制（1602 第二行末尾放得下就放，放不下就只在浮窗上显示），方便人眼核对。
5. 过期：hub 的审批超时（110 s）到了以后，该 nonce 永久作废。

## 不要做
不改固件；不改 hook 协议；不改风险分级规则；不启停正在运行的 hub。

## 测试
改前备份到 `_rollback/hub-nonce/`。新增测试覆盖：一致放行、不一致拒收、过期拒收、300 ms 切换保护、高危两次确认时第二次带错 nonce、热键取"最后渲染"的 nonce（模拟渲染后队首变化）、`require_nonce` 开关、审计日志条目。`pc/test_hub*.py` 全部和 `research/selftest_hub_replay.py` 必须通过，Python 用 `D:/conda/miniconda3/python.exe`。

## 汇报
改动文件、每条要求对应的测试名、测试通过数、PRD 第 337 行"nonce 校验尚未实现"这句现在应该怎么改写。
