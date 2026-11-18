# 简报：修 macOS 适配的审查问题（第二轮）

审查原文：`research/review-gemini-hub-macos.md`（Carbon 审，Claude 已核实 P0-5 两处属实）。先读它，按编号修。

## 必修
- **P0-1** `hub_desktop.py` 顶层 `from ctypes import wintypes` 及依赖它的顶层定义，放进 `sys.platform == "win32"` 分支；同查 `hub_hotkey.py`、`hub.py` 的顶层 Win32 引用。加一个测试：在子进程里把 `ctypes.wintypes` 的导入设为抛 `ValueError`，`import hub` / `import hub_desktop_mac` 仍成功。
- **P0-2** `hub_hotkey_mac.py`：删掉启动前读类属性 `Listener.IS_TRUSTED` 的检查；改为 start 后检查实例状态。fake Listener 要复刻真实 pynput 的类属性 `IS_TRUSTED = False`。
- **P0-3** 按 bundle identifier 白名单匹配窗口（审查里列的 ID），`missing value` 时回退进程名；删掉 `_focus` 里按进程名的二次过滤。测试用真实进程名 `stable`、`Electron`。
- **P0-4** 默认听写快捷键不再用合成双击 Fn：改为必须在配置里给出快捷键，没配就返回不可用并在日志/doctor 里提示怎么设。焦点已离开原窗口时，不向新窗口补发任何快捷键。
- **P0-5** Windows 行为必须和改动前一致：
  1. `hub_install.py` 全局模式下，python 路径要和旧版一样是正斜杠（`as_posix()`），在已经装过的机器上重跑 install 不产生任何改动；
  2. `hub.py` 的 `voice_up() is False → unavailable` 只对 macOS 后端生效。
  对比 `_rollback/hub-pre-mac/` 写回归测试，证明 Windows 下生成的钩子命令和 voice 流程与旧版逐字节相同。
- **P1-1** voice_down 返回 False 时回滚 `voice_active` / `voice_target` 并重绘。
- **P1-2** 前台校验只比较窗口句柄，不比较标题；activate 后短轮询（≤300 ms）。
- **P1-3** osascript 输出带尾随换行时，空结果不报错。
- **P1-4** 无标题窗口 `missing value` 当作空串；枚举循环里单个窗口出错跳过。
- **P1-5** `pbcopy` 传 `LC_CTYPE=UTF-8`；粘贴和回车放进同一个 osascript，中间 `delay 0.08`。

## 选修（时间够就做）
P1-6、P1-7（doctor 里补"屏幕录制""输入监控"的提示即可，不必调 C API）、P1-8。P2 不做。

## 做完的标准
- 改前备份到 `_rollback/hub-mac-fix1/`。
- `pc/test_hub*.py` 全部、`pc/test_ui.py`、`pc/test_daemon.py`、`pc/test_pc.py`、`research/selftest_hub_replay.py` 全过，Python 用 `D:/conda/miniconda3/python.exe`。
- 汇报：逐条写修了没有、怎么修的、对应测试名；没修的写原因。不要启停正在运行的 hub，不要改 `~/.codex`、`~/.claude`。
