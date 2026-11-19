# 一键初始化与灯光抓包交付结果

已按 `research/brief-init-and-capture.md` 完成实现与离线验证。**未用真实抓包验证**，没有启动真实 ETW 跟踪，也没有生成或冒充真实的 `light.etl`。

## 修改文件与行为

| 文件 | 结果 |
| --- | --- |
| `pc/agentdeck_app.py` | 新增可重复调用的 `init_all(home)`；全局钩子先备份并移除旧版，再安装现有 hub 钩子，启用自启，全部成功后写入 `initialized`。新增静默 `--init` / `--uninstall`，输出 JSON 与退出码；在创建单实例、GUI、hub 或硬件监听前分流。windowed exe 可复用已有控制台或输出管道。 |
| `pc/test_agentdeck_app.py` | 73 项测试覆盖备份、旧钩子替换、保留其他配置、字节级幂等、失败重试、初始化标记、源码/frozen CLI 分流、首次引导及控制台替身。 |
| `research/capture/抓包.bat` | 自提权，按微软参数开启 USB ETW；中文列出六步，每步停 3 秒，回车停止。在脚本目录生成 `light.etl`，旧文件另存 `light-previous-<随机标识>.etl`。使用独立会话名；配置失败清理本次会话，停止失败给出手动清理命令。 |
| `research/capture/parse_etl.py` | 只读解析 `.etl` 或已有 tracerpt `.xml`。过滤 `4132:2107` 的 OUT，识别 HID `SET_REPORT`，输出时间、端点/接口、传输长度、实际捕获长度及十六进制数据，默认按 2 秒空闲间隔分组。 |
| `pc/test_capture_etl.py` | 18 项离线测试覆盖合成 USB rundown、方向、设备过滤、SET_REPORT、六组排序、截断/缺失载荷、未补零字节数组、CLI 和 BAT 成功/失败/提权参数路径。 |
| `research/init-capture-tests.json`、`research/init-capture-tests.log` | 每个测试脚本的真实退出码、计数与完整输出。日志受现有 gitignore 忽略，但已保存在本地。JSON 中抓包专项记录已更新为审查修复后的 18 项。 |
| `research/init-capture-results.md` | 本说明。 |

首次引导已删除旧三步、勾选和额外确认，只保留一行说明和“开始使用”。成功后，安装前已存在 `.codex` 的机器在同一窗口显示“在 Codex 里输入 /hooks，信任一次”，移除按钮；其他机器直接关闭引导。检测发生在安装之前，避免安装器新建 `.codex` 后误判。

简化与复用决策（reuse-first）：组合现有 `hub_install.remove_legacy_hooks`、`hub_install.apply`、`AutoStart` 和 `agentdeck_theme`；`global_action` 与初始化共享一个小 helper。抓包采用系统 `logman`、`tracerpt` 与 Python 标准库，不新增依赖。未引入另一套安装器、USB 通信实现或 UI 框架。

## 验证结果

解释器为 `D:\conda\miniconda3\python.exe`，从项目根目录执行。全部 **32 个 `pc/test_*.py` 脚本退出码为 0**。按各脚本最终通过结果计，包含 **598 次 unittest 执行 + 137 个断言测试组**；`test_hub.py` 聚合了其他部分测试，这些数字包含重复执行，不代表独立测试数量。

全套测试为每个脚本设置独立临时 `HOME` / `USERPROFILE` / `APPDATA` / `LOCALAPPDATA`，并拦截真实注册表与串口访问；相关测试使用自己的替身。没有读取或写入真实用户的 `.claude` / `.codex` 或 Run 键。

关键真实输出摘要：

```text
pc/test_agentdeck_app.py: Ran 73 tests ... OK
pc/test_capture_etl.py: Ran 18 tests ... OK
pc/test_hub_install.py: Ran 35 tests ... OK
pc/test_ui.py: UI: 7 groups passed
pc/test_daemon.py: daemon offline tests: 10 groups passed
pc/test_pc.py: PC and firmware loop: 4 groups passed
pc/test_verify_real_session.py: Ran 20 tests ... OK
Final scripts: 32 failures: 0
AST + py_compile: 4 files passed
```

`parse_etl.py --help` 实际退出码为 0。四个修改/新增 Python 文件通过 AST 与 `py_compile`；`git -c core.whitespace=cr-at-eol diff --check` 通过，保留原测试文件的 CRLF。仓库没有配置 Python lint/typecheck，当前环境未提供 ruff、mypy、pyright 或 pylint，因此没有虚称运行这些检查，也没有安装依赖。固件和 1602 输出未变，未运行 `pc/sim.py`。

BAT 测试在临时目录中执行副本，替换管理员检查和 logman；提权分支替换 `Start-Process`，验证最终 cmd 参数的引号，不启动提权进程。路径包含中文、空格和 `&`；成功路径实际验证旧 ETL 保留和新文件整理。另验证配置失败清理、停止失败不发布结果。未调用真实 `logman start`。

## logman 参数与官方出处

先查阅 [How to capture a USB event trace with Logman](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/how-to-capture-a-usb-event-trace) 和 [logman create trace](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/logman-create-trace)，再编写 BAT。参数采用官方示例，路径与会话名改为本脚本专用值：

| 命令/参数 | 用途 |
| --- | --- |
| `create trace -n <独立会话> -o <同目录临时前缀>.etl -nb 128 640 -bs 128` | 建立 ETW 收集器；128–640 个缓冲区，每个 128 KB。 |
| `update trace -n <会话> -p Microsoft-Windows-USB-USBXHCI "(Default,PartialDataBusTrace)"` | xHCI 事件与部分传输数据。 |
| `update trace -n <会话> -p Microsoft-Windows-USB-UCX "(Default,PartialDataBusTrace)"` | UCX 事件与部分传输数据。 |
| `update trace -n <会话> -p Microsoft-Windows-USB-USBHUB3 "(Default,PartialDataBusTrace)"` | USB3 hub 事件与设备 rundown。 |
| `update trace -n <会话> -p Microsoft-Windows-USB-USBPORT` | USB2 port provider。 |
| `update trace -n <会话> -p Microsoft-Windows-USB-USBHUB` | USB2 hub provider。 |
| `update trace -n <会话> -p Microsoft-Windows-Kernel-IoTrace 0 2` | 保留同一官方示例中的内核 I/O 辅助 provider。 |
| `start -n <会话>` / `stop -n <会话>` / `delete -n <会话>` | 开始、停止并移除本次收集器。 |

Logman 可能输出带 `_000001` 后缀的文件；停止后只处理本次独立会话对应的确切路径，再保存为 `light.etl`。`Default` 包括设备 rundown；`PartialDataBusTrace` 只记录有限载荷，因此解析输出分开显示传输长度和捕获长度。[官方说明](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/how-to-capture-a-usb-event-trace#capture-filters-for-usb-30-driver-stack-events)

ETL 转换命令为 `tracerpt.exe <ETL绝对路径> -o <临时目录>/light.xml -of XML -y`，依据 [tracerpt 官方文档](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/tracerpt)。转换仅处理磁盘文件，临时输出随解析结束清理。实现前还只读查看了本机 `Get-WinEvent -ListProvider` 的 UCX、USBHUB3、USBPORT 事件模板，核对 `fid_UsbDevice`、`fid_PipeHandle`、`fid_URB_TransferData` 与 setup 字段。

Codex 信任行为已核对 [OpenAI Hooks 官方文档](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)：用户需审查并信任当前 hook 定义，变更后需要重新审查。本次没有改写信任记录，也没有写 `requirements.toml` 绕过审查。

## 使用与验证边界

初始化与卸载入口（源码与未来 frozen 构建保持同一行为）：

```text
AgentDeck.exe --init
AgentDeck.exe --uninstall
D:\conda\miniconda3\python.exe pc/agentdeck_app.py --init
D:\conda\miniconda3\python.exe pc/agentdeck_app.py --uninstall
```

抓包由用户双击 `research/capture/抓包.bat`，在 UAC 中选择“是”，按窗口说明操作。得到文件后，从工程根目录运行：

```text
D:\conda\miniconda3\python.exe research/capture/parse_etl.py
D:\conda\miniconda3\python.exe research/capture/parse_etl.py path/to/light.xml --gap 2
```

解析器仅按时间空闲推测操作分组；仅恰好六组时按六步顺序标注，否则明确提示组数不符，不强行填补。未知设备身份、未知方向不会当作目标 OUT；缺失或截断的数据明确标记。真实 Windows/驱动版本可能产生不同字段或缺少关联信息，需真实 ETL 验证后再适配；本次合成测试不证明真实灯光协议、完整载荷或实机抓包成功。

未打包 exe、未 git commit、未修改 `hub_overlay.py` 样式或固件；未打开 COM4、未上传固件，未改 `wokwi/`、`backup/`、`_rollback/`。新增脚本没有 USB/HID 打开、发送、控制传输或写键盘接口的代码。frozen CLI 与窗口交互均经替身覆盖，未用真实 exe、UAC 或真实 Codex 会话验证。
