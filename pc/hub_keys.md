# 用 CXT 宏键盘模拟 v2

`hub_keys.json` 的顶层 `bindings`（第 6 版）对应下面的 4×5 实测布局。`v2_emulation` 是保留的历史六槽位布局，有以下差异：Space→slot 4、Q→slot 5、V→slot 6、Ctrl+0→interrupt；两种布局均禁用 Ctrl+C/V，均含 M、Ctrl+T/D、U、X、Tab 新绑定。

```text
D:/conda/miniconda3/python.exe pc/hub.py --backend usb
# 历史六槽位布局，与下面的默认实测动作不同
D:/conda/miniconda3/python.exe pc/hub.py --backend usb --profile v2_emulation
```

这些绑定只解释现有 USB 报文，不改键、不安装钩子。

## 实测 4 列 × 5 排 宏键盘出厂键位表

2026-11-20 用只读 Raw Input 探针实测：用户按位置从上到下、从左到右逐颗按，再从左到右逐个旋钮转和按。
**键帽上印的字不可靠**，找键一律按位置。旧表把 U、X 放在第 4 排第 1、2 颗，还漏了第 2 排第 4 颗；实测 U、X 在第 4 排第 3、4 颗。
这把键盘有 3 颗键只发修饰键（Alt、Ctrl、Shift），不带字母，默认都不绑定。

| 排 \ 列 | 第 1 列 | 第 2 列 | 第 3 列 | 第 4 列 |
| --- | --- | --- | --- | --- |
| **第 1 排** | E (`hid:0x08`)<br>`slot 1`（会话 1） | B (`hid:0x05`)<br>`slot 2`（会话 2） | Ctrl+Z (`ctrl+hid:0x1D`)<br>`slot 3`（会话 3） | Space (`hid:0x2C`)<br>`interrupt`（打断） |
| **第 2 排** | G (`hid:0x0A`)<br>`approve`（✓ 批准） | Ctrl+F (`ctrl+hid:0x09`)<br>`deny`（✗ 拒绝） | H (`hid:0x0B`)<br>`voice_down`/`up`（按住说话） | Alt（只发修饰键）<br>未绑定 |
| **第 3 排** | L (`hid:0x0F`)<br>`screenshot`（截图） | M (`hid:0x10`)<br>`prompt continue`（继续） | Ctrl+T (`ctrl+hid:0x17`)<br>`prompt tests`（跑测试） | Ctrl+D (`ctrl+hid:0x07`)<br>`prompt summary`（总结进度）<br>⚠ 危险键：漏进窗口时连按两次会退出 Claude Code |
| **第 4 排** | Ctrl（只发修饰键）<br>未绑定 | Shift（只发修饰键）<br>未绑定 | U (`hid:0x18`)<br>`prompt commit`（提交） | X (`hid:0x1B`)<br>`cycle +1`（下个会话） |
| **第 5 排** | Tab (`hid:0x2B`)<br>`next_wait`（跳到等我的会话） | Ctrl+C (`ctrl+hid:0x06`)<br>（留空）⚠ 危险键：漏进窗口会打断 agent，连按会退出 | Ctrl+V (`ctrl+hid:0x19`)<br>（留空）⚠ 危险键：漏进窗口会粘贴剪贴板 | P (`hid:0x13`)<br>`cycle -1`（上个会话） |

### 旋钮绑定（从左到右编号 1–4）

| 旋钮 | 旋转 / 按下 | 出厂码 | 动作 | 功能说明 |
| --- | --- | --- | --- | --- |
| 旋钮 1（最左） | 顺时针 F / 逆时针 S | `hid:0x09` / `hid:0x16` | `cycle +1` / `cycle -1` | 下一个 / 上一个会话 |
| 旋钮 1 按下 | L 键 | `hid:0x0F` | `screenshot` | 截图并粘贴路径 |
| 旋钮 2 | 顺时针 R / 逆时针 P | `hid:0x15` / `hid:0x13` | `cycle +1` / `cycle -1` | 下一个 / 上一个会话 |
| 旋钮 2 按下 | Q 键 | `hid:0x14` | `show` | 显示浮窗（隐藏后不用鼠标也能叫回来） |
| 旋钮 3 | - / = | `hid:0x2D` / `hid:0x2E` | `scroll 1` / `scroll -1` | 在所选 agent 窗口上滚轮：往下看新内容 / 往上翻。实测只录到一格 -，哪个方向发 - 还没测准 |
| 旋钮 3 按下 | V 键 | `hid:0x19` | `scroll end` | 直接滚到底 |
| 旋钮 4（最右） | ] / [ | `hid:0x30` / `hid:0x2F` | `nav down` / `nav up` | 下 / 上方向键：agent 提问时换选项（只在“等你”时可用）。实测只录到一次 [，转向还没测准 |
| 旋钮 4 按下 | C 键 | `hid:0x06` | `nav enter` | 回车：提交选项，或把语音说完的话发出去 |

旋钮 4 按下实测发 C（旧表写的 Ctrl+0 不对，所以第 5 版里 `nav enter` 在这把键盘上从来没触发过）。
`ctrl+hid:0x27`（Ctrl+0）仍绑定 `nav enter`，留给别的键盘。
旋钮 1 实测逆时针发 S、顺时针发 F；第 6 版按“顺时针 = 下一个”把 F 绑成 `cycle +1`、S 绑成 `cycle -1`，和旋钮 2 一致。

旋钮 4 的方向键和回车有两条保护：所选会话有待批请求（或 agent 自己的权限对话框）时一律拒绝，提示用 ✓/✗；
上下键只在会话“等你”（AskUserQuestion、MCP 表单）时可用，免得空闲时翻出旧提问再被回车重发。

只要读键方式不是 USB 直读（接口 0 还是系统 HID 驱动，走 Raw Input），每颗键都会同时打进前台窗口。
这时 `prompt`、`nav`、语音和截图会被拒绝，浮窗顶部常驻红字提示先用 Zadig 换 WinUSB。
Ctrl+C、Ctrl+D、Ctrl+V 三颗是危险键：漏进 agent 窗口分别会打断、退出、粘贴。
3 颗修饰键在 Raw Input 下也会漏进窗口，单按 Alt 可能让当前窗口的菜单栏获得焦点。

低风险请求按一次 ✓；高风险请求需在 1.5 秒内松开并再按一次 ✓。
极危请求转回 agent 原生确认，✓ 返回 `locked`。持续按住产生的重复报文
不会代替第二次确认。会话键选择固定槽位 1–6，旋钮首尾循环。

未改动过的 v3、v4、v5 键位文件（`%USERPROFILE%\.agentdeck\hub_keys.json`）启动时自动升级到 v6，
旧文件存为 `hub_keys.json.bak-v3` / `.bak-v4` / `.bak-v5`；改过绑定的文件不动。

## Ctrl 模板与待确认的物理输出

下面四个逻辑组合已写入历史 profile，使用的主键 HID usage 已确认，
**对应物理组合输出仍是“待用户按一遍确认”**。这不是已测得的出厂宏清单。
只有宏键盘自身报文里的 Ctrl 有效；主键盘按住 Ctrl 不会给该 USB 设备加修饰键。
宏键盘是否有独立 Ctrl、如何从现有键生成这些组合，仓库没有足够证据。

| 待确认的组合 / 位置 | 逻辑绑定 | 模板动作 | 确认状态 |
| --- | --- | --- | --- |
| Ctrl + 会话 1，E 键 | `ctrl+hid:0x08` | `prompt continue` | 待用户按一遍确认 |
| Ctrl + 会话 2，B 键 | `ctrl+hid:0x05` | `prompt tests` | 待用户按一遍确认 |
| Ctrl + 会话 4，Space 键 | `ctrl+hid:0x2C` | `prompt commit` | 待用户按一遍确认 |
| Ctrl + 会话 5，旋钮 2 按下 Q | `ctrl+hid:0x14` | `prompt tests` | 待用户按一遍确认 |
| Ctrl + V | 无绑定 | 留空 | 按用户要求禁用 |
| Ctrl + 会话 3，原 Ctrl+Z 键 | 无独立绑定 | 计划为 `prompt summary` | 已含 Ctrl；与 `slot 3` 无法区分，待用户按一遍确认另一个键 |
| Ctrl + ✗，原 Ctrl+F 键 | 无独立绑定 | `interrupt` 使用历史 profile 的 Ctrl+0 替代 | 已含 Ctrl；与 `deny` 无法区分，待用户按一遍确认另一个键 |

后两项不会添加猜测键码，也不会覆盖 `slot 3` / `deny`。历史 profile 用
Ctrl+0 中断；注意 2026-11-20 实测这把键盘的旋钮 4 按下发的是 C，不是 Ctrl+0，
所以这把键盘上 `v2_emulation` 的 Ctrl+0 中断不会触发。确认更多普通键后，可把会话 3、✗ 分配到独立裸键，再设置
其 Ctrl 组合；配置中的 `pending_confirmation` 记录这些缺口。
`prompt` 会粘贴模板并发送 Enter，确认物理输出时应使用只打印报文的
`pc/deck.py learn --backend usb`，由用户运行。

出厂 Ctrl 宏通常先发一帧 Ctrl，再发主键；`deck_usb.ReportState` 会把
未被主键消费的 Ctrl 保持为 fresh，因此 Ctrl+Z、Ctrl+F 和 Ctrl+0 的
两帧序列都能命中（Ctrl+0 是别的键盘的写法，这把键盘没有这颗）。修饰键已被前一个主键消费后，持续按住的 Ctrl 不会
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
