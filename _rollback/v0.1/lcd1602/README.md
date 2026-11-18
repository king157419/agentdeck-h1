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

## 已知限制

- 单色屏不能由软件改变颜色或亮度，A00 字库不支持中文项目名；电脑端过滤不可显示字符。
- 项目名最多传输 24 个字符，实际同时可见长度取决于小图标或计时所占空间。
- 板子重启会清空会话；进行中的 DeepSeek 会话定期重报，钩子会话在下一次事件恢复。
- 串口被其它程序占用时，上报可能丢失，钩子安静退出，daemon 后续继续尝试。
- Codex 拒绝批准后，可能停在 `WAIT!` 直到本轮结束；超长时间无上报的任务会按 TTL 撤下。
- DeepSeek 日志格式改变、真实 Windows 前台识别、LED 电平、动画观感仍需在使用环境确认。
