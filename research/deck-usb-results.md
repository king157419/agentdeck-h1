# deck USB 任务验收 — 2026-11-17

已完成 `research/brief-deck-usb.md` 的软件实现及当前未更换驱动环境的验收。所有命令从 `D:\desk\hardware\h1` 运行，Python 使用 `D:\conda\miniconda3\python.exe`。

## 做完的标准：全部测试输出

完整逐项输出、预期警告和每个进程退出码见 [deck-usb-tests.log](deck-usb-tests.log)。9 个脚本全部通过，退出码均为 0：

| 命令 | 真实输出末行 |
|---|---|
| `python pc/test_ui.py` | `UI: 7 groups passed` |
| `python pc/test_daemon.py` | `daemon offline tests: 6 groups passed` |
| `python pc/test_pc.py` | `PC and firmware loop: 4 groups passed` |
| `python pc/test_deck.py` | `AgentDeck offline tests: 31 groups passed` |
| `python pc/test_deck_input.py` | `deck Raw Input offline tests: 4 groups passed` |
| `python pc/test_deck_probe.py` | `deck probe offline tests: 7 groups passed` |
| `python pc/test_deck_exclusive.py` | `deck exclusive offline tests: 9 groups passed` |
| `python pc/test_deck_keymap.py` | `Keymap offline tests: 13 groups passed` |
| `python pc/test_deck_usb.py` | `deck USB offline tests: 19 groups passed` |

`test_deck.py` 自身包含 Raw Input、probe、exclusive 测试，因此不把各脚本组数相加当作独立用例总数。现有测试只更新了预期的默认后端、默认独占选项及旧 vk 映射所在位置，原动作和安全检查继续执行。

新增测试覆盖：多键差分、设备自身修饰位及左右合并、重复报文、抬起和单独修饰键不派发动作、非法长度与 rollover、接口 0/interrupt IN 选择、SET_PROTOCOL 失败、100 ms 超时、2 秒重连、失败清理、Zadig 提示、auto/显式后端、11 条 HID 绑定、旧映射保留、learn 和 run 生命周期。补充回归验证“claim 成功但第一次读失败”时也会提示并回退，探测超时可用且探测取得的首报文不丢失。

语法与 AST 检查、旧映射逐项相等检查及当前真实 USB 驱动的 auto 回退检查见 [deck-usb-checks.log](deck-usb-checks.log)。5 个新增/修改的 Python 文件均通过 `py_compile` 与 `ast.parse`。仓库没有配置 lint/typecheck 工具，本机未找到 ruff、mypy、pyright、pylint，未安装额外依赖。显示输出与固件未修改，因此未运行会重生成屏幕图片的 `pc/sim.py`。

## 做完的标准：当前环境运行 3 秒并正常退出

执行 `python research/smoke_deck_usb.py`，其子进程运行的命令为：

```text
D:\conda\miniconda3\python.exe D:\desk\hardware\h1\pc\deck.py run --backend usb -v
```

3.006 秒后通过 Windows CTRL_BREAK 请求正常退出。子进程退出码 **0**，没有强制终止，动作线程已 join，退出后能再次获取单实例锁。结果为 **SMOKE PASS**。完整输出见 [deck-usb-smoke.log](deck-usb-smoke.log)，机器可读结果见 [deck-usb-smoke.json](deck-usb-smoke.json)。关键真实输出：

```text
agent_deck AgentDeck started; backend=usb; exclusive=False
agent_deck.usb SET_PROTOCOL boot failed ([Errno 22] Invalid parameter); checking actual report lengths; only 8-byte boot reports are supported
agent_deck.usb 请先用 Zadig 把 4132:2107 接口0 换成 WinUSB ([Errno 5] Input/Output Error)
agent_deck AgentDeck stopped; action thread joined
```

当前驱动允许枚举和 claim，却在第一次 interrupt read 返回 I/O Error。因此 `open()` 包含一次 100 ms 读探测：超时代表健康的空闲接口，收到报文则缓存到 `run()`，其它错误释放资源并给出 Zadig 提示。此修正也已用当前真实 USB 驱动验证 auto 会选择 `rawinput`、`exclusive=False` 并输出“宏键盘按键会漏到窗口”；该附加检查的 Raw Input 构造使用替身，不创建输入窗口、不分发动作。

## 做完的标准：改动文件清单

修改现有文件：

- `pc/deck.py`：HID 键名规范化，按后端选择映射；run/learn 的 auto/usb/rawinput 选择；默认关闭钩子；过滤释放及 USB 修饰键事件；支持 CTRL_BREAK 正常清理。
- `pc/deck_map.json`：11 个实测 HID 绑定，旧 10 个 vk 绑定完整保留于 `_rawinput_bindings`，原 `_f13_f22_bindings` 完整保留；记录全部 4 个旋钮出厂键。
- `pc/test_deck.py`：适配有意改变的默认值和映射位置，保留 Raw Input、动作线程及异常清理测试。
- `lcd1602/README.md`：Zadig 接口 0 步骤、恢复原驱动、run/learn 用法、映射及旋钮表、钩子已知无效原因和 USB 报文限制。

新增实现及验收脚本：

- `pc/deck_usb.py`：仅接口 0 的 USB 打开/探测、8 字节 boot 报文差分、100 ms 读取、2 秒重连及资源释放。
- `pc/test_deck_usb.py`：19 组离线测试。
- `research/smoke_deck_usb.py`：可重跑的 3 秒 USB CLI 启动/正常退出检查。

新增验收证据：本文件、`research/deck-usb-tests.log`、`research/deck-usb-checks.log`、`research/deck-usb-smoke.log`、`research/deck-usb-smoke.json`。

改动前已备份 4 个待修改文件至 `_rollback/deck-v0-usb/`，沿用 `pc/` 和 `lcd1602/` 相对路径；不覆盖已存在备份。没有修改固件、驱动、键盘配置或其它 USB 接口，没有打开 COM4，没有上传固件。

## 复用与剩余限制

采用 COMPOSE：复用已安装 PyUSB/libusb-package 和现有 Controller、ActionQueue、Raw Input 与动作安全门；仅补充设备报文解析和后端选择。未引入依赖或重复实现窗口/串口控制。仅核查与任务相关的本地实现和官方库文档，没有开展产品或其它包的广泛调研。

- 只支持确认的 8 字节 boot 报文，不猜 NKRO 或 Report ID；未知长度日志提示并忽略。
- 更换 WinUSB 后的实际按键、旋钮、热拔插及前台隔离效果仍由用户验证；当前缺驱动检查不声称完成这些硬件验证。
- 只接管接口 0，其它接口的滚轮或多媒体输入仍可能被 Windows 处理。
- Raw Input 回退不能隔离前台按键，实验钩子保留但默认关闭。

核查的官方资料：[PyUSB tutorial](https://github.com/pyusb/pyusb/blob/master/docs/tutorial.rst)、[libusb-package README](https://github.com/pyocd/libusb-package/blob/main/README.md)、[Zadig](https://zadig.akeo.ie/)。实现同时核对了本机安装的 PyUSB 及 libusb_package 源码。
