# 简报：relay 记下 agent 所在的顶层窗口（F1 的 relay 部分）

只改 `pc/hub_relay.py` 和 `pc/test_hub_relay.py`，别的文件一律不动（另一个 agent 正在改 pc/ 里其它文件）。
不要 build，不要启动 dist 里的 exe，不要 git commit / checkout / reset，不要写真实的 `~/.claude`、`~/.codex`、`~/.agentdeck`。

## 要做什么

在 `pc/hub_relay.py` 加一个函数 `find_agent_window(pid=None, *, processes=None, windows=None, started=None, max_depth=12)`：

1. `processes`：pid -> (ppid, exe 文件名)。默认用 `CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS)` + `Process32FirstW/NextW`（PROCESSENTRY32W，用 ctypes，注意结构体字段和 64 位对齐，`dwSize` 要先填）建表。
2. `started`：可调用，pid -> 进程启动时间（可比较的数字），拿不到返回 None。默认用 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `GetProcessTimes` 取 creation FILETIME。
3. `windows`：pid -> [hwnd, ...]。默认 `EnumWindows` 一次，只收 `IsWindowVisible(h)`、`GetWindow(h, GW_OWNER)==0`、`GetWindowTextLengthW(h)>0` 的顶层窗口，用 `GetWindowThreadProcessId` 分组，保持枚举顺序（Z 序，第一个就是最上面的）。
4. 从 `pid`（默认 `os.getpid()`）开始往父进程走，最多 `max_depth` 层。每走一步要求父进程启动时间早于（<=）子进程启动时间；拿不到时间或父比子新就停（防 PID 复用）。父进程不在表里、ppid 为 0 或等于自己也停。
5. 不包括 relay 自己：从父进程开始检查。第一个在 `windows` 里有窗口的祖先，返回 `{"hwnd": int, "pid": int, "exe": str}`（取它的第一个 hwnd）。都没有返回 None。
6. 非 win32 直接返回 None。整个函数包在 try/except 里，任何异常都返回 None，绝不能影响 hook。

接入 `relay()`：

- 只在普通事件（不是 PermissionRequest，也不是 `--gate`）上调用，而且放在 `hub_status` 判断之后（hub 已死的快速失败路径不能变慢，现有 `test_gate_failure_path_is_fast_and_light` 必须继续过）。
- 结果是 dict 时，放进转发给 hub 的普通事件 body：字段名 `agentdeck_window`。`_body()` 的 slim 分支要带上这个字段（`ORDINARY_KEYS` 里加 `"agentdeck_window"` 即可，前提是你把它写进 event）。PermissionRequest 和 gate 仍按原始字节转发，不加这个字段。
- 允许测试注入：`relay()` 加关键字参数 `window_finder=None`，默认用 `find_agent_window`；`connection_factory` 被注入时（单元测试）如果没给 `window_finder`，不要去查真实窗口（返回 None 即可），免得现有测试变慢或依赖桌面。

## 做完的标准

1. `pc/test_hub_relay.py` 新增测试（用假的 processes/windows/started，不碰真实系统）：
   - 链路 relay(100) → bash(90) → claude(80) → pwsh(70) → OpenConsole(60，无可见窗口) → WindowsTerminal(50，有窗口 0x1234)，断言返回 WindowsTerminal 的 hwnd/pid/exe。
   - 某一层父进程启动时间比子进程晚时停止往上走，返回 None（或返回更近的那个有窗口的祖先，按你的实现写清楚）。
   - 超过 max_depth 停止；进程表里出现环（pid 指回自己或互相指）不死循环。
   - 普通事件的转发 body 里有 `agentdeck_window`；PermissionRequest 的 body 仍是原始字节、没有这个字段；window_finder 抛异常时 hook 照常转发、退出码 0。
   - 在本机真实跑一次默认实现：`find_agent_window()` 不抛异常，返回 None 或合法 dict（hwnd 为正整数）。
2. 计时：写一个一次性脚本放 `research/time_relay_window.py`，起一个假的 HTTP hub（随机端口，临时 home 里放 token 和 hub.json），用 `subprocess` 跑 `D:\conda\miniconda3\python.exe pc/hub_relay.py --agent cc --port <port> --home <tmp>` 各 50 次（一组带窗口查找，一组用环境变量或参数关掉它——你可以加一个只供测试的环境变量 `AGENTDECK_NO_WINDOW=1`），打印两组耗时中位数和差值。要求差值中位数 ≤ 30 ms。把打印结果贴在最终回复里。
3. 依次运行并贴出结果：`D:\conda\miniconda3\python.exe pc/test_hub_relay.py`、`pc/test_hub_nonce_integration.py`、`pc/test_hub_fixes.py`，全部 OK。
4. 最终回复写清：改了哪些函数、真实机器上 `find_agent_window()` 从你的 shell 里返回了什么、计时数字。
