# Codex 对 Carbon 浮窗与键位改动的独立审查

评审基线：`research/review-input-overlay.diff`、`_rollback/overlay-keys/` 和修复前当前文件；以下行号固定指向这个基线，后续 nonce 修复会改变行号。本审查未读取 Carbon 对 nonce 的审查，也未修改实现或测试。优先级：P0 为可能错误执行审批，P1 为主要功能失效或违背使用约定，P2 为验证和边界问题。

## P0

本次浮窗/键位 diff 未发现可独立归因于新增改动的 P0。已有 nonce 设计的全部正确性不在这个结论的覆盖范围内。

## P1

### P1-1：隐藏清空唯一显示快照，无 LCD 时当前待批请求不能继续用 USB/热键批准或拒绝

- 文件与行号：`pc/hub_overlay.py:222`、`:229`、`:535`；交互位置 `pc/hub.py:210`、`:868`、`:909` 和 `pc/hub_hotkey.py:61`。
- 复现：创建真实 `Hub(lcd_enabled=False, desktop_enabled=False)`；通过真实 `Hub.event()` 线程提交普通 `PermissionRequest`；让真实 `Overlay._poll()` 确认已显示，等待超过 300ms，然后调用 `hide()`，再通过真实 `HotkeyKeys.dispatch()` 按 F19。实测输出为 `BEFORE_HIDE {request_id: <当前请求>, nonce: <整数>}`、`AFTER_HIDE {request_id: None, nonce: None} hub_closed=False overlay_stopped=False`、`HIDDEN_HOTKEY_APPROVE False pending=1`，日志为 `stale_nonce`。USB 同样把该空快照传给 `Hub.action()`。隐藏窗口不退出 Hub 的目标达到了，但已有待批操作失效；被隐藏的旧请求也不会自行触发重新出现。
- 改法：分别维护各显示面的可见快照，隐藏只撤销 overlay 的快照。物理按键必须有明确来源和目标策略：优先可靠可见显示，或保留用户已经见过的同一请求的输入绑定；不得借此盲批从未显示的新请求。补真 Hub + Overlay.hide + USBKeys/HotkeyKeys 测试，覆盖同一请求、换队首、LCD 同时存在三种情况。

### P1-2：坐标处理仅覆盖主屏，左/上副屏不可拖入，右/下副屏位置不能重启恢复

- 文件与行号：`pc/hub_overlay.py:345`、`:356`、`:528`、`:569`。
- 复现：副屏位于主屏左侧（桌面 x 为负）时拖向副屏，`_move()` 的 `max(0, ...)` 把位置硬截到主屏边缘；离线实测对 `x_root=-500, y_root=-100` 得到 `geometry('+0+0')`。把窗口放在右副屏并保存（例如 x=2200，主屏宽1920），重启时 `winfo_screenwidth()` 的主屏宽把 x 改为1560。拖动后也未限制右/下边界，关闭按钮可落在屏幕外；运行中拔掉副屏且窗口高度不变时没有重新约束坐标，窗口可能完全不可见。屏幕尺寸/鼠标坐标没有共同的 Windows DPI 坐标契约，高缩放和不同 DPI 副屏未验证。
- 改法：使用 Windows 各显示器工作区与统一 DPI 坐标；按窗口实际宽高选择/夹入一个可用工作区，支持负桌面坐标。Tk 的负 geometry 偏移表示从右/下边缘计数，不应直接当成负绝对坐标；Windows 可通过原生定位处理。启动、展开收回、拖动结束、显示拓扑变化后均重新约束，覆盖任务栏和副屏移除。补负坐标、右副屏恢复、显示器断开、混合 DPI 的定位测试；真实混合 DPI 仍需设备环境验证。

### P1-3：文档把 v2_emulation 当成同一实测键位，实际空格不会打断，Ctrl+V 也没有留空

- 文件与行号：`pc/hub_keys.md:3`、`:19`、`:23`；实际配置 `pc/hub_keys.json:76`、`:77`、`:92`、`:105`，profile 选择在 `pc/hub.py:851`。
- 复现：按文档运行 `--backend usb --profile v2_emulation`；其 `hid:0x2C` 仍为 `slot 4`，而文档承诺 Space=`interrupt`。`ctrl+hid:0x19` 仍为 `prompt summary`，而表中写 Ctrl+V 留空。离线读取真实配置得到 `default: space=interrupt, Ctrl+V=None`，`v2_emulation: space=slot 4, Ctrl+V=prompt summary`。该 profile 另有 Q/V/Ctrl+0 等有意保留的历史布局差别。新增六个闲键在默认布局中与简报相符，不能因此推论两个 profile 全部一致。
- 改法：要么让此实测 profile 与用户约定一致并明确保留历史映射的位置，要么保持历史 profile 并在文档/命令示例中明确其不同，尤其禁用用户要求留空的 Ctrl+C/Ctrl+V。用真实 USB 报文解码到 USBKeys 的动作效果验证各可选 profile，而非只检查默认 JSON 字符串。

## P2

### P2-1：新增测试对关键端到端行为提供了错误的确定感

- 文件与行号：`pc/test_hub_overlay.py:337`、`:345`、`:351`、`:453`、`:475`；已有相关假 Hub 断言位于 `:96`。
- 复现：`test_hide_withdraws_root_without_stopping_hub` 仅检查 Mock root.withdraw 和 overlay.stopped，未跑真实 Hub/mainloop/HTTP 存活；`test_hide_clears_rendered_request_if_overlay_was_source` 反而把 P1-1 的错误状态当成成功；拖动只验证正坐标产生自己预期的 geometry 字符串；键位只断言默认 JSON，没有经过 USB 解码，也不检查文档推荐的 profile。真实 Hub 复现已经表明这些测试全绿时隐藏审批仍失败。
- 改法：保留纯展示模型单测，补真 Hub + Overlay 的隐藏/重新显示/审批测试、真实输入事件集成测试，以及基于工作区几何约束的定位测试。审批测试必须验证请求响应和剩余队列，而不是 Mock.action 返回的 `allowed`；生命周期测试应确认隐藏后后台 HTTP 仍响应。

## 已核实的正确部分及验证边界

- × 和 WM_DELETE_WINDOW 均绑定 `hide()`，它不调用 quit/destroy/stop；`_poll()` 继续调度，新的未忽略 request ID 会重新显示。未发现关闭按钮仍直接退出 Hub 的问题。
- 透明度默认0.85，开关和 JSON 布尔偏好逻辑一致；未发现透明度数值本身导致越界的缺陷。透明度、窗口重显、Windows noactivate 与实际混合 DPI 的组合尚没有真实窗口验证。
- 默认键表中 M、Ctrl+T、Ctrl+D、U、X、Tab 与实测简报一致，Ctrl+C/Ctrl+V 留空；历史 Q/V/Ctrl+0 映射保留。未接触 USB 设备、COM4、固件或受保护脚本。
- 主代理报告本基线 `pc/test_hub*.py` 共413项、replay共12项通过；本审查独立复现了上述隐藏快照和负坐标问题，测试通过不构成这些场景正确的证据。

结论：本基线关闭浮窗后 Hub 确实继续运行，但隐藏后的审批可用性、多显示器定位与 profile 键位说明仍有 P1 缺陷，建议修复并补真实组件集成验证后再验收。
