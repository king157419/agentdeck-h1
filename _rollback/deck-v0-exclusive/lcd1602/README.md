# Agent 状态屏（1602 字符屏版）v0.1

ESP32 + 1602A，通过 USB 显示 Claude Code、Codex、DeepSeek harness 的工具、状态和项目名。优先让需要你处理的会话可见，也能跟随电脑前台窗口。

![v0.1 离线模拟：42 个场景](preview-sim.png)

这张图由实际的 `ui.py` 在电脑上运行生成；字母使用近似的 5×7 字库，精灵和小图标使用固件的真实点阵。实物的对比度、观看距离和动画仍需上板确认。

## 屏幕布局

```text
[精灵上半] Claude THINK[转圈]
[精灵下半] project      12s
```

精灵占左侧 2×2 个字符格，合起来是 10×16 像素。工具名为 `Claude`、`Codex`、`DSK`；其它前缀显示 `Agent`，保留原来的机器人。三个工具分别使用小螃蟹、带 `>_` 提示符的终端、喷水鲸鱼。

第二行右侧：有两个及以上会话时，每个会话一个小图标，按加入顺序排列；只有一个会话时显示当前状态持续时间（`12s`、`5m`、`2h`），空闲不显示时间。项目名最多 24 个可显示字符；空间不足时往返滚动，每 400 毫秒一格，两端各暂停 2 秒。

| 状态 | 第一行 | 左侧精灵和提示 |
|---|---|---|
| `idle` | `READY` | 吉祥物静止，每 5 秒短暂切换一帧 150 毫秒 |
| `think` | `THINK` + 转圈 | 每 600 毫秒上下浮动 1 像素 |
| `tool` | `TOOL` + `>` / 右箭头 | 每 200 毫秒左右晃动 1 像素 |
| `wait` | `WAIT!` / `>YOU<` | 大叹号和吉祥物每 400 毫秒交替，板上 LED 闪烁 |
| `done` | `DONE` | 前 3 秒为大对勾，之后为吉祥物和小对勾 |
| `error` | `ERROR` | 大叉和吉祥物每 500 毫秒交替，LED 闪烁 |

没有会话且没有焦点时，显示闭眼机器人、`Agent Monitor` 和 `ready to work`。

## 会话和焦点

最多保留 8 个会话。没有手动焦点时的优先级为：等你 > 出错 > 刚完成（5 秒内）> 跑工具 > 思考 > 完成 > 空闲；同级会话每 3 秒轮换。容量满时，只淘汰最久没更新的空闲或完成会话；其它会话都忙时返回 `err set: full`。

无新消息的会话自动撤下：空闲或完成 15 分钟、出错 1 小时、思考或跑工具 3 小时、等你 12 小时。重复上报相同状态会续期，但不重置状态持续时间。

```text
focus cc-abcdef    固定显示完整会话 key
focus cc           显示最近更新的 Claude 会话（也支持 cx、ds）
focus -            恢复自动优先级
```

回复为 `ok focus <target>`。焦点自最后一次发送起保留 60 秒，电脑监视程序每 20 秒续期。被聚焦的工具没有会话时显示该工具吉祥物、`<tool> READY` 和 `ready to work`。焦点不会隐藏其它会话的求助：小图标继续闪烁，LED 也会闪。

串口仍为 115200，每行一条命令；兼容 `set <key> <state> [name]`、`end <key>`、`clear`、`list`、`ping`、`dump`。`ping` 报告版本 `0.1`。`clear` 清空会话，焦点用 `focus -` 单独解除。坏命令返回 `err`，过长的整行丢弃后继续处理下一行。屏幕每 5 分钟重新初始化并恢复图案。

## 硬件

经典 ESP32 开发板（CH340，USB 同时供电和传数据）+ 1602A 字符屏，HD44780、A00 字库、4 线模式，MicroPython 1.28：

| 屏 | ESP32 | 屏 | ESP32 |
|---|---|---|---|
| VSS | GND | D4 | GPIO 16 |
| VDD | 5V | D5 | GPIO 17 |
| V0 | 电位器中间脚 | D6 | GPIO 25 |
| RS | GPIO 21 | D7 | GPIO 26 |
| RW | GND | A | 5V（串 220Ω） |
| E | GPIO 22 | K | GND |

板上 LED 使用 GPIO 2。8 个 CGRAM 槽分配：0–3 为大精灵，4 为两帧等待图标，5 为对勾，6 为叉，7 为转圈。仅在点阵字节确实变化时写入。像素源图保存在 `ui.py` 的 `ART` 中，可直接编辑 16 行、每行 10 个 `#` / `.`。

## 文件与电脑端

| 文件 | 作用 |
|---|---|
| `lcd1602/main.py` | 硬件初始化、串口循环和可跨时钟回绕的毫秒累计 |
| `lcd1602/ui.py` | 可在 CPython 测试的会话、命令、布局和动画逻辑 |
| `lcd1602/lcd1602.py` | LCD 驱动 |
| `pc/agent_lcd.py` | 钩子、串口发送、自检、演示；保证统一 daemon 启动 |
| `pc/daemon.py` | 单进程合并 DeepSeek 日志和前台窗口监视，绑定 `127.0.0.1:47613` 保证单实例 |
| `pc/dsh_watch.py` | DeepSeek 压缩日志解析与 `Watcher.tick()`；旧入口仍能运行统一 daemon |
| `pc/preview.py` | 从板子读取画面；`sheet` 和离线模拟共用 42 个场景 |
| `pc/sim.py` | 假 LCD 离线运行 UI，生成 `preview-sim.png` |
| `pc/test_ui.py`、`pc/test_daemon.py`、`pc/test_pc.py` | 纯断言离线测试，外部访问均使用替身 |
| `pc/install.py`、`pc/upload.py` | 安装钩子、上传固件 |

统一监视程序每 300 毫秒查询前台窗口，焦点目标改变时发送命令，每 20 秒发送心跳。按进程名识别 Claude、DeepSeek Harness、ChatGPT/Codex；DeepSeek 可通过日志中的 `session/title` 精确匹配会话。终端或编辑器先匹配板上项目名（每次前台窗口切换最多查询一次 `list`，同一窗口更新标题时复用列表），再匹配标题中的 `claude` / `codex`；其它窗口解除焦点。可编辑的映射表在 `daemon.py` 顶部。

Claude Code 和 Codex 继续使用原有钩子。DeepSeek 没有上报接口，运行时只读其会话日志。即使没有安装 DeepSeek，下一次钩子事件也会拉起统一 daemon，用于跟随前台窗口。原有 `python pc/dsh_watch.py -v` 入口继续可用。

以下命令从工程根目录运行，`python` 指 `D:\conda\miniconda3\python.exe`：

```text
python pc/test_ui.py
python pc/test_daemon.py
python pc/test_pc.py
python pc/sim.py
```

下面这些由使用者连接硬件后运行（本次软件实现未运行）：

```text
python pc/upload.py COM4 lcd1602/lcd1602.py lcd1602/ui.py lcd1602/main.py
python pc/agent_lcd.py doctor
python pc/agent_lcd.py demo
python pc/agent_lcd.py send "focus cx"
python pc/daemon.py -v
python pc/preview.py now lcd1602/preview.png
python pc/preview.py sheet lcd1602/preview-board.png
```

`doctor` 报告板子、钩子和统一 daemon；`demo` 演示三个工具的全部状态和焦点切换。上传前须让电脑端停止占用串口。`preview.py sheet` 和 `demo` 都会清空已有会话。

## 宏键盘（AgentDeck v0）

AgentDeck 在电脑端观察 `VID_4132&PID_2107` 的键盘、鼠标滚轮和多媒体输入，把按键映射成会话操作。使用 Windows Raw Input、ctypes 隐藏窗口和 `RIDEV_INPUTSINK`；按设备句柄核对 VID/PID 后才处理事件，Ace 68（VID_3837）等其它设备的按键不会被打印、执行或拦截。只读探测使用已安装的 `hidapi`，不需要 pynput 或 pywin32。

从工程根目录运行，`python` 仍指 `D:\conda\miniconda3\python.exe`：

```text
python pc/deck.py probe
python pc/deck.py learn
python pc/deck.py run -v
python pc/deck.py run --map pc/deck_map.json -v
python pc/daemon.py --deck -v
python pc/test_deck.py
```

`probe` 列出 VID_4132 的全部 HID 接口，只对 PID_2107、usage page `0xFF60`、usage `0x61`（QMK 标准）或 `0x01` 的接口发送 VIA 读取命令：`0x01` 协议版本、`0x11` 层数、`0x12` keymap。当前设备的厂商接口为 `0xFF00/0x01`，协议未知，程序不会打开该接口或发送任何报文；会说明无法读取的原因并正常退出。程序不自动改键、写配置或切换引导模式。

标准 VIA 的读取命令不提供矩阵行列，尺寸来自[键盘定义文件](https://caniusevia.com/docs/specification/#matrix)。如果以后使用标准 VIA 接口，可以用已知尺寸 `python pc/deck.py probe --rows 2 --cols 3`，或 `python pc/deck.py probe --definition path/to/keyboard.json`（本地 VIA JSON 的 `matrix.rows/cols`）；示例尺寸需要替换成实际定义。提供有效尺寸后会读取所有层，逐项打印 layer、row、col 和十六进制键码；无尺寸时只读协议版本、层数并解释原因，不猜测行列。

宏键盘需要的键应配置为 **F13–F24**，再用 `learn` 逐个确认。Raw Input 不能吞键，原按键仍会传给前台应用；F13–F24 不会输入普通文字，但应用仍可能将它们绑定为快捷键。音量加减会同时改变系统音量，也建议在确认支持该设备的厂商软件中改成 F 键。`deck.py` 的 probe/learn/run 不修改键盘配置。

### 改键工具与当前阻断

`pc/deck_keymap.py` 的命令入口如下（从工程根目录运行）：

```text
python pc/deck_keymap.py backup
python pc/deck_keymap.py show
python pc/deck_keymap.py apply
python pc/deck_keymap.py show
python pc/deck_keymap.py restore research/keymap-backup-<时间>.json
python pc/test_deck_keymap.py
```

**当前设备不能通过这个工具备份或改写。** 只读解包 `D:\VIA-C\resources\app.asar` 后确认，安装的 VIA-C 0.3.5 只筛选 `0xFF60/0x61`，当前 `4132:2107` 是 `0xFF00/0x01`；随附定义中没有该 VID/PID，本机也没有补充定义的缓存。源码中的旋钮表是三种 custom mode，没有证据对应本机四个物理旋钮和各层映射。命令编号也与标准 VIA 不同，不能尝试套用。详情及源码行号见 [`research/via-c-protocol.md`](../research/via-c-protocol.md)。

因此上述四个硬件命令目前都会枚举目标 HID 后以 `BLOCKED`、退出码 `2` 结束，**不打开接口、不发送报文、不创建键位备份、不修改键盘**；没有 `--force` 选项。`restore` 先检查 JSON 文件，随后也受同一限制。2026-11-17 实际已改矩阵位置：**无**。没有真实备份文件，也不需要恢复；上面的恢复命令只是未来有有效备份时的用法模板。

工具中已实现并离线验证的部分包括：源码确认的报文编码/解码、完整各层矩阵及旋钮快照的校验和保存、按普通按键矩阵位置排序生成改键计划、写前自动备份、全量回读校验、不一致或写入中断时恢复并再次校验。完整备份保存为 `research/keymap-backup-<UTC时间>.json`，首次另存 `_rollback/deck-v0/keymap-original.json`，已存在则不覆盖。**这些逻辑目前仅由测试替身验证；真实设备的完整读取和旋钮写入 backend 尚未实现。** 测试中的 4×6 矩阵为合成数据，不能当作本机布局。

待目标设备协议及位置得到确认后，要求的改键计划为：第 0 层按行优先的前八个普通按键（排除旋钮按下和空位）依次设为 F13、F14、F15、F16、F17、F18、F21、F22，存储键码为 `0x0068–0x006D`、`0x0070`、`0x0071`；第一个物理旋钮顺时针为 F19（`0x006E`）、逆时针为 F20（`0x006F`）。其它键位、旋钮按下和其余层保持原值。当前无法确认这些按键的 row/col、旋钮地址和原键码，故没有实际“原码 → 新码”清单。后续必须先补齐目标 backend 和完整备份，再开放硬件写入。

`learn` 在按下时打印 `vk:0x7C`、`scan:0x0064:0` 等可直接用于映射的标识，以及 VKey、扫描码、flags；滚轮打印 `wheel:+1/-1`，多媒体键打印 `consumer:0x00E9/0x00EA` 等 HID usage。按住键不会重复触发；按 Ctrl+C 退出。

映射文件为 `pc/deck_map.json`，编辑 `bindings` 中的键和值即可，文件里的 `_instructions` 也提供了说明。键名复制 `learn` 输出；同一键同时有 VKey 和扫描码映射时，优先 VKey，每次按下只执行一个动作。扫描码末尾是 E0/E1 flags（0、2、4、6）。动作只接受下表中的格式，映射错误会在启动时报出。

| 默认输入 | 动作 | 行为 |
|---|---|---|
| F13–F16（`vk:0x7C`–`vk:0x7F`） | `slot 1`–`slot 4` | 按板子 `list` 顺序聚焦第 N 个会话，并尝试把对应窗口拉到前台 |
| F17（`vk:0x80`） | `approve` | 安全检查通过后发送 Enter |
| F18（`vk:0x81`） | `deny` | 安全检查通过后发送 Esc |
| F19 / F20（`vk:0x82` / `vk:0x83`） | `cycle +1` / `cycle -1` | 在会话之间循环，首尾相接 |
| F21（`vk:0x84`） | `next_wait` | 跳到下一个 wait 会话，首尾相接 |
| F22（`vk:0x85`） | `auto` | 发送 `focus -`，恢复板子的自动优先级 |
| 滚轮正/负；音量加/减（consumer usage 或音量 VKey） | `cycle +1` / `cycle -1` | 供可能存在的旋钮使用 |

前八个普通键的目标动作依次为 slot 1–4、approve、deny、next_wait、auto，旋钮目标为 cycle +1/-1；当前仅更新了说明，实际键位尚未改写。可自行为 F23/F24 添加绑定，`slot` 支持 1–8。滚轮方向可以通过交换两个映射反转。槽位、轮换和等待选择都在动作触发时查询板子的完整 `list`，会话增减后按最新顺序处理。窗口匹配先按项目名，再按 Claude/Codex 标题；会先尝试 `SetForegroundWindow`，失败后用 `AttachThreadInput` 重试。

`approve`/`deny` 只对前台终端/编辑器中**唯一匹配到、且最新 list 状态为 wait** 的会话发键。浏览器、普通文本编辑器、原生 agent 应用窗口、非 wait、歧义或不完整的列表都不发送。查询后以及 `SendInput` 前再次核对前台窗口；Ctrl/Alt/Shift/Win 按住时也不发送。它只发送 Enter/Esc，不能判断 agent 当前提示的选项含义。

`run` 用 `127.0.0.1:47614` 独占绑定保证单实例（daemon 自己继续使用 47613）。`daemon.py --deck` 可启动后台 AgentDeck；已运行的 daemon 需要由使用者以该参数重新启动，普通钩子启动保持现有行为。`-v` 将每次动作和结果输出到控制台；直接 `run` 不加 `-v` 或由 daemon 启动时，写入轮转日志 `pc/deck.log`。单独运行时按 Ctrl+C 退出；后台进程可由任务管理器结束。

限制：窗口标题只是启发式匹配，同项目多会话或多个终端标签可能无法定位具体会话，审批匹配有歧义时拒绝发键。Windows 的前台切换和完整性级别限制可能使拉前台或 `SendInput` 失败，结果会记入日志。状态来自最近一次串口查询，查询之后 agent 状态和窗口仍可能变化；程序不是对提示内容的确认。板子离线、串口被占或列表不完整时，本次动作跳过并记录原因；不会启动固件上传或占用未知 HID 接口。

## 已知限制

- 单色屏不能由软件改变颜色或亮度，A00 字库不支持中文项目名；电脑端过滤不可显示字符。
- 项目名最多传输 24 个字符，实际同时可见长度取决于小图标或计时所占空间。
- 板子重启会清空会话；进行中的 DeepSeek 会话定期重报，钩子会话在下一次事件恢复。
- 串口被其它程序占用时，上报可能丢失，钩子安静退出，daemon 后续继续尝试。
- Codex 拒绝批准后，可能停在 `WAIT!` 直到本轮结束；超长时间无上报的任务会按 TTL 撤下。
