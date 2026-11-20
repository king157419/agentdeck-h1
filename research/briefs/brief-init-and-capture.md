# 简报：一键初始化 + 一键抓灯光包

## A. 一键初始化（给最终用户）
用户反馈：不能让每个用户都手动勾配置、装钩子。目标是"双击 exe → 点一次按钮 → 能用"。

1. `pc/agentdeck_app.py` 新增 `init_all(home)`：全局启用钩子（复用 `global_action` 的逻辑：先备份、换掉旧版钩子、`hub_install.apply("install", home=...)`）+ 打开开机自启。函数可重复调用，结果一致。
2. 首次运行（prefs 里没有 `initialized`）只弹一个窗口：一行字 + 一个"开始使用"按钮。点了就跑 `init_all`。跑完后，如果检测到装了 Codex（`~/.codex` 存在），只再显示一句"在 Codex 里输入 /hooks，信任一次"；没装 Codex 就直接关窗。原来的三步引导删掉。窗口样式复用 `agentdeck_theme.py`（之后还会整体换成网页界面，这里别花时间做样式）。
3. 命令行：`AgentDeck.exe --init` 静默执行 `init_all`，打印结果后退出；`AgentDeck.exe --uninstall` 卸掉全局钩子、关闭开机自启后退出。非 frozen 时 `python pc/agentdeck_app.py --init` 行为一样。
4. Codex 官方规定新钩子必须由用户在 `/hooks` 里信任一次（按钩子哈希记录），**不要**去写 Codex 的信任记录或 requirements.toml 绕过它。

## B. 一键抓灯光包（Windows 自带 USB ETW，不装 Wireshark）
目标：用户双击一个 bat → 点 UAC "是" → 在 CXT Hub 里改 6 次颜色 → 回到窗口按回车 → 得到 `research/capture/light.etl`。

1. `research/capture/抓包.bat`：自提权（没管理员权限就用 PowerShell `Start-Process -Verb RunAs` 重启自己）。用 logman 按微软文档《How to capture a USB event trace with Logman》开 USB 跟踪：provider 包括 Microsoft-Windows-USB-USBXHCI、Microsoft-Windows-USB-UCX、Microsoft-Windows-USB-USBHUB3（都带 `Default,PartialDataBusTrace`），以及 USBPORT、USBHUB。窗口里用中文写清楚要改的 6 步（第 1 颗键红→绿→蓝、第 2 颗键红、亮度最低→最高，每步停 3 秒），按回车后停止跟踪，输出到同目录 `light.etl`。provider 名和参数先查官方文档再写，不要凭记忆。
2. `research/capture/parse_etl.py`：读 `light.etl`，筛出 VID 4132 / PID 2107 设备的 OUT 方向（主机→设备）传输和 SET_REPORT 控制传输，按时间打印"时间、端点或接口、长度、十六进制数据"，并把相邻 6 组操作按时间分组。可以用 `tracerpt` 转 XML 后解析，或用纯 Python 的 ETL 解析库。依赖要写进脚本开头的注释。
3. 这一步**只录不发**：任何脚本都不许往键盘写数据，尤其是 0xFF00 厂商接口。

## 硬约束
- 测试用临时 home，绝不读写真实 `~/.claude`、`~/.codex`、注册表 Run 键（用替身）。
- 不打包 exe、不 git commit、不改 `hub_overlay.py` 样式。
- 没有真实 etl 文件，`parse_etl.py` 就做到能跑通 `--help` 并对一个合成小样例做单元测试即可，在结果里写明"未用真实抓包验证"。

## 完成标准
- 现有 `pc/test_*.py` 全过，新增 init 相关测试。
- 结果写进 `research/init-capture-results.md`：改了什么、测试输出摘要、bat 用到的 logman 参数及官方文档出处。
