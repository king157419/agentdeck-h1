# 用 CXT 宏键盘模拟 v2

`hub_keys.json` 的顶层 `bindings` 保留现有默认布局；新增的
`v2_emulation` 需要显式选择：

```text
D:/conda/miniconda3/python.exe pc/hub.py --backend usb --profile v2_emulation
```

这些绑定只解释现有 USB 报文，不改键、不安装钩子。以下出厂码来自
`deck_map.json`；旋钮从左到右编号 1–4。普通键按现有功能标记定位，
仓库没有确认它们的行列位置，因此不编造第几行第几列。可以按“建议标签”贴纸。

| 物理键 / 位置描述 | 已确认的出厂码 | v2 动作 | 建议标签 |
| --- | --- | --- | --- |
| E，原橡皮擦键 | `hid:0x08` | `slot 1` | 会话 1 |
| B，原画笔键 | `hid:0x05` | `slot 2` | 会话 2 |
| Ctrl+Z，原撤销键 | `ctrl+hid:0x1D` | `slot 3` | 会话 3 |
| Space，原平移键 | `hid:0x2C` | `slot 4` | 会话 4 |
| 旋钮 2 按下，Q | `hid:0x14` | `slot 5` | 会话 5 |
| 旋钮 3 按下，V | `hid:0x19` | `slot 6` | 会话 6 |
| G，原渐变 / 油漆桶键 | `hid:0x0A` | `approve` | ✓ |
| Ctrl+F，原滤镜快捷键 | `ctrl+hid:0x09` | `deny` | ✗ |
| H，原抓手键，按住 / 松开 | `hid:0x0B` | `voice_down` / `voice_up` | 按住说话 |
| 旋钮 1（最左）按下，L | `hid:0x0F` | `screenshot` | 截图 |
| 旋钮 4（最右）按下，Ctrl+0 | `ctrl+hid:0x27` | `interrupt` | 中断（替代键） |
| 旋钮 1 顺时针 / 逆时针，S / F | `hid:0x16` / `hid:0x09` | `cycle +1` / `cycle -1` | 下个 / 上个会话 |
| 旋钮 2 顺时针 / 逆时针，R / P | `hid:0x15` / `hid:0x13` | `cycle +1` / `cycle -1` | 下个 / 上个会话 |
| 旋钮 3 顺时针 / 逆时针，- / = | `hid:0x2D` / `hid:0x2E` | `cycle +1` / `cycle -1` | 下个 / 上个会话 |
| 旋钮 4 顺时针 / 逆时针，] / [ | `hid:0x30` / `hid:0x2F` | `cycle +1` / `cycle -1` | 下个 / 上个会话 |

低风险请求按一次 ✓；高风险请求需在 1.5 秒内松开并再按一次 ✓。
极危请求转回 agent 原生确认，✓ 返回 `locked`。持续按住产生的重复报文
不会代替第二次确认。会话键选择固定槽位 1–6，旋钮首尾循环。

## Ctrl 模板与待确认的物理输出

下面五个逻辑组合已写入 profile，使用的主键 HID usage 已确认，
**对应物理组合输出仍是“待用户按一遍确认”**。这不是已测得的出厂宏清单。
只有宏键盘自身报文里的 Ctrl 有效；主键盘按住 Ctrl 不会给该 USB 设备加修饰键。
宏键盘是否有独立 Ctrl、如何从现有键生成这些组合，仓库没有足够证据。

| 待确认的组合 / 位置 | 逻辑绑定 | 模板动作 | 确认状态 |
| --- | --- | --- | --- |
| Ctrl + 会话 1，E 键 | `ctrl+hid:0x08` | `prompt continue` | 待用户按一遍确认 |
| Ctrl + 会话 2，B 键 | `ctrl+hid:0x05` | `prompt tests` | 待用户按一遍确认 |
| Ctrl + 会话 4，Space 键 | `ctrl+hid:0x2C` | `prompt commit` | 待用户按一遍确认 |
| Ctrl + 会话 5，旋钮 2 按下 Q | `ctrl+hid:0x14` | `prompt tests` | 待用户按一遍确认 |
| Ctrl + 会话 6，旋钮 3 按下 V | `ctrl+hid:0x19` | `prompt summary` | 待用户按一遍确认 |
| Ctrl + 会话 3，原 Ctrl+Z 键 | 无独立绑定 | 计划为 `prompt summary` | 已含 Ctrl；与 `slot 3` 无法区分，待用户按一遍确认另一个键 |
| Ctrl + ✗，原 Ctrl+F 键 | 无独立绑定 | `interrupt` 使用上表 Ctrl+0 替代 | 已含 Ctrl；与 `deny` 无法区分，待用户按一遍确认另一个键 |

后两项不会添加猜测键码，也不会覆盖 `slot 3` / `deny`。先用已确认的
Ctrl+0 中断。确认更多普通键后，可把会话 3、✗ 分配到独立裸键，再设置
其 Ctrl 组合；配置中的 `pending_confirmation` 记录这些缺口。
`prompt` 会粘贴模板并发送 Enter，确认物理输出时应使用只打印报文的
`pc/deck.py learn --backend usb`，由用户运行。

出厂 Ctrl 宏通常先发一帧 Ctrl，再发主键；`deck_usb.ReportState` 会把
未被主键消费的 Ctrl 保持为 fresh，因此 Ctrl+Z、Ctrl+F 和 Ctrl+0 的
两帧序列都能命中。修饰键已被前一个主键消费后，持续按住的 Ctrl 不会
自动变成新的组合。Hub 还会核对完整修饰键，避免把不精确的组合当作裸键动作。

## 离线回放

```text
D:/conda/miniconda3/python.exe research/selftest_hub_replay.py
```

脚本用临时 home、临时 token 和随机本机 HTTP 端口启动独立 Hub，
使用 `--backend none --no-lcd --profile v2_emulation`。它将手写的
8 字节 boot report 经真实解码与绑定分发逻辑送入 `/action`，并发调用
`hub_relay.relay()` 提交 Codex PermissionRequest，再核对批准、拒绝、
极危锁定、槽位和旋钮结果。它不打开 COM4、不读真实 USB、不安装钩子、
不注入真实按键；合成报文通过只证明解码和分发，不代表待确认组合已在硬件上测得。
