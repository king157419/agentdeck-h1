### P0（真 Mac 上直接失败，或改变 Windows 行为）

#### [P0-1] 无条件导入 `ctypes.wintypes`，真 Mac 启动即崩溃
- **文件和大致位置**：`pc/hub_desktop.py` 顶层（L2–L3 `from ctypes import wintypes`），波及 `pc/hub.py` 与 `pc/hub_desktop_mac.py`（L6 `from hub_desktop import DesktopEffects`）。
- **问题**：在 macOS 原生 CPython 上只要 `import hub_desktop`（即使传了 `--no-desktop`，`hub.py` 顶层也会导入），进程立即抛出 `ValueError: _type_ 'v' not supported` 退出，根本进不了 `main()`。
- **为什么**：CPython 标准库 `Lib/ctypes/wintypes.py` 定义 `VARIANT_BOOL` 时使用了类型码 `_type_ = "v"`，而底层 `_ctypes` C 扩展仅在 Windows 编译（`#ifdef MS_WIN32`）下注册 `'v'`，非 Windows 平台导入必崩（见 [Python `ctypes` 官方文档](https://docs.python.org/3/library/ctypes.html) 与 [CPython `Lib/ctypes/wintypes.py` 源码](https://github.com/python/cpython/blob/main/Lib/ctypes/wintypes.py)）。离线测试是在 Windows Python 上靠 monkeypatch `sys.platform` 跑的，因此完全漏检。
- **建议的改法**：将 `from ctypes import wintypes` 及顶层依赖 `wintypes` 结构体/函数签名的代码放进 `if sys.platform == "win32":` 分支（同步检查 `pc/hub_hotkey.py` 中是否有顶层 Win32 类型引用）。

---

#### [P0-2] 把 `pynput.keyboard.Listener.IS_TRUSTED` 当类属性预检，真 Mac 热键 100% 永远被禁用
- **文件和大致位置**：`pc/hub_hotkey_mac.py` `PynputHotkeys._start`（L75）。
- **问题**：`if not getattr(self.keyboard.Listener, "IS_TRUSTED", True): raise OSError(...)` 在创建 `Listener` 实例之前读取**类属性**，在安装了真实 `pynput` 的 Mac 上无论是否已授予权限，都会 100% 抛出 `OSError` 禁用热键。
- **为什么**：在 `pynput` 的 macOS 实现中（见 [`pynput/_util/darwin.py` 源码](https://github.com/moses-palmer/pynput/blob/master/lib/pynput/_util/darwin.py) 与 [pynput macOS 平台限制说明](https://pynput.readthedocs.io/en/latest/limitations.html#macos)），类属性 `ListenerMixin.IS_TRUSTED = False` 是硬编码静态初值；只有在实例化 `listener = Listener(...)`、调用 `listener.start()`、后台线程运行 `_run()` 调用 [`HIServices.AXIsProcessTrusted()`](https://developer.apple.com/documentation/applicationservices/1460720-axisprocesstrusted) 之后，才会把结果写到**实例属性** `listener.IS_TRUSTED` 上。此外，macOS 10.15+ 只读监听键盘使用的是“输入监控（Input Monitoring）”权限，若只开了输入监控没开辅助功能，`AXIsProcessTrusted()` 也为 `False`，但 Event Tap 实际能工作。
- **建议的改法**：删掉启动前的类属性检查；改为创建实例后调用 `self.listener.start()` + `self.listener.wait()`，再检查 `if not self.listener.running or not self.listener.is_alive():`（此时再结合实例属性 `self.listener.IS_TRUSTED` 生成报错提示）。

---

#### [P0-3] `System Events` 进程名不匹配：Warp 100% 找不到窗口，VS Code 经常找不到窗口
- **文件和大致位置**：`pc/hub_desktop_mac.py` `APPLICATIONS`（L13–L14）、`MacWindowControl.windows`（L85–L98）、`MacDesktopEffects._focus`（L231–L232）。
- **问题**：用 `(name of p as text) is in APPLICATIONS` 过滤目标终端/编辑器，在真 Mac 上 **Warp 必败**，**官方版 VS Code 常败**。
- **为什么**：`System Events` 中 `application process` 的 `name` 取自进程可执行文件 / LaunchServices 注册名而非 `.app` 包名：
  - **Warp**：二进制为 `Warp.app/Contents/MacOS/stable`，`System Events` 返回的进程名是 **`"stable"`**（Preview 版为 `"preview"`），不是 `"Warp"`（见 Warp 官方 [warpdotdev/Warp#5143](https://github.com/warpdotdev/Warp/issues/5143)）。
  - **Visual Studio Code**：二进制为 `Visual Studio Code.app/Contents/MacOS/Electron`，在 `System Events` 中进程名经常暴露为 **`"Electron"`**（部分环境为 `"Code"`，绝不是 `"Visual Studio Code"`；见 [microsoft/vscode#46762](https://github.com/microsoft/vscode/issues/46762)）。不能简单把 `"Electron"` 或 `"stable"` 加进进程名列表，否则 Slack、Obsidian、Notion 等所有 Electron 应用都会被误匹配。
  - 其余四个核对：`Terminal` → `"Terminal"`、`iTerm2` → `"iTerm2"`、`Cursor` → `"Cursor"`、`Ghostty` → `"Ghostty"` / `"ghostty"` 进程名可匹配，但仍不如 Bundle ID 可靠。
- **建议的改法**：在 AppleScript 中优先按 `bundle identifier of p` 白名单过滤（`com.apple.Terminal`、`com.googlecode.iterm2`、`com.microsoft.VSCode`、`com.microsoft.VSCodeInsiders`、`com.vscodium`、`com.todesktop.230313mzl4w4u92`、`dev.warp.Warp-Stable`、`dev.warp.Warp-Preview`、`com.mitchellh.ghostty`），仅在 `bundle identifier` 为 `missing value` 时回退进程名；同时**删掉 `_focus` L231–L232 二次过滤 `if app in APPLICATIONS`**（否则 `windows()` 放行后，`"stable"` / `"Electron"` 又会被 Python 侧二次筛掉）。

---

#### [P0-4] 合成两次 `key code 63`（双击 Fn）在现代 Mac 上基本无法触发听写，且切走焦点时会对新窗口误发快捷键
- **文件和大致位置**：`pc/hub_desktop_mac.py` `_shortcut`（L198–L212）、`pc/hub_desktop.py` `_guard_voice`（L289）。
- **问题**：① 默认配置 `{"key_codes": [63, 63]}` 发送两次虚拟 `key code 63` 在现代 macOS（尤其是带 Globe 🌐 键的 Apple Silicon + Ventura/Sonoma/Sequoia）上通常无法触发系统听写，反而容易忽略或弹出 Emoji 选择面板；且 macOS 出厂默认关闭听写；② 当用户在语音期间切到微信/浏览器等其他窗口时，`hub_desktop.py` L289 调用 `self._voice_shortcut(self.windows())`，竟对着**新切过去的前台窗口**发送了一遍听写快捷键。
- **为什么**：① `kVK_Function = 63` 键码值虽对应 Fn，但 macOS“连按两次 Fn 启动听写”在底层监听硬件修饰键 `flagsChanged` / Apple TopCase HID 事件，往往不认 `System Events` 合成的 `key code 63`；② macOS 系统听写在焦点离开原输入框时**已自动结束**，此时向 `self.windows()`（未做应用白名单过滤的任意新前台窗口）再发一次 toggle 快捷键，若快捷键有效反而会在用户的微信/浏览器里开启听写，若切到桌面无窗口则抛异常写入 `voice.close_error`。
- **建议的改法**：① 启动听写优先通过 `System Events` 点击前台应用菜单栏开始听写菜单项（或明确要求用户在系统设置中将听写快捷键设为普通修饰键组合如 `Ctrl+Opt+Space` 并配入 `dictation_shortcut`，不要把失效的双击 `63` 当作可用默认）；② 停止听写时仅当 `self.windows()[0] == voice.handle`（焦点仍在原窗口）时发送 `Escape`（`key code 53`）或停止键，焦点已变时严禁对新窗口补发快捷键。

---

#### [P0-5] `hub_install.py` 与 `hub.py` 改变了 Windows 原有行为（违反“Windows 行为一项不变”）
- **文件和大致位置**：`pc/hub_install.py`（L18–L21, L34–L49）；`pc/hub.py`（L484–L485, L584–L586）。
- **问题**：
  1. `hub_install.py` 删掉了原本固定的正斜杠路径 `PYTHON = "D:/conda/miniconda3/python.exe"`，改用 `sys.executable`。在 Windows 上 `sys.executable` 返回反斜杠路径 `D:\conda\miniconda3\python.exe`，路径无空格时 `subprocess.list2cmdline` **不会加双引号**，生成 `D:\conda\miniconda3\python.exe D:/.../hub_relay.py --agent cc`。Claude Code 在 Windows 上通过 Git Bash（POSIX shell）执行 hooks 时，未加引号的反斜杠会被当成转义符吞掉变成 `D:condaminiconda3python.exe` 导致 hook 失败！此外，在已安装过的机器上重跑 `apply("install")` 会因斜杠差异破坏幂等性（`after_data != data`）重写配置并产生 `.bak`，用不同 Python 启动还会改掉解释器。
  2. `hub.py` L484 `if self.desktop.voice_up() is False: return {"action": command, "status": "unavailable"}` 未限定平台。如果 Windows `DesktopEffects.voice_up()` 在语音已被后台守护线程提前关闭时返回 `False`，原本 Windows 忽略返回值正常走完流程，新版会直接返回 `"status": "unavailable"`。
- **为什么**：把 macOS 适配逻辑直接侵入了 Windows 共用路径生成和返回值判断逻辑。
- **建议的改法**：① Windows 下路径统一转为正斜杠 `Path(executable).as_posix()`（与 L19 `SCRIPT = ...as_posix()` 保持一致，必要时 Windows 默认值保持兼容）；② `"unavailable"` 分支仅针对 macOS 桌面降级结果触发（例如使用专用返回值或判断 `sys.platform == "darwin"`），绝不拦截 Windows 原有返回值。

---

### P1（明显 Bug）

#### [P1-1] macOS 上 `voice` / `voice_down` 失败返回 `False` 时，`voice_active` 未回滚导致 LCD / UI 卡死在录音状态
- **文件和大致位置**：`pc/hub.py`（L572–L586）。
- **问题**：L573 先置 `self.voice_active = True`、`self.voice_target = self.selected` 并清空了所有 `pending` 请求的 `armed_at`，接着 L579 `completed = desktop.voice_down(...)` 失败返回 `False`，L581 `self._show()` 把“正在语音”画上 LCD，L585 看到 `completed is False` 直接 `return {"action": command, "status": "unavailable"}`，没有任何状态回滚。
- **为什么**：旧版依赖 `voice_down` 抛异常跳进 `except` 回滚 `voice_active`；macOS 改成返回 `False` 不抛异常后，既没进 `except` 也没启动 `_guard_voice` 回调线程，`voice_active` 永久卡死为 `True`。
- **建议的改法**：当 `completed is False` 时立即恢复 `self.voice_active = False`、`self.voice_target = None` 并重新调用 `self._show()`（或等 `voice_down` 成功后才清空 `armed_at` 并渲染激活态）。

---

#### [P1-2] 前台窗口校验比较了完整 3 元组（含动态窗口标题），Claude Code / Codex 运行时极易误判“焦点已变”
- **文件和大致位置**：`pc/hub_desktop_mac.py` `_focus`（L237 `self.windows() != window`）与 `_paste`（L246 `self.windows() != expected`）。
- **问题**：`window` / `expected` 是 `((pid, number, fallback_title), app, title)`。虽然 `handle` 里专门用了 `AXWindowNumber` 来容忍标题变化，但 L237 和 L246 直接用 `!=` 比较整个 3 元组，连实时 `title` 一起比了。
- **为什么**：Claude Code / Codex 工作时终端标题栏有高频跳动的 Braille spinner（如 `⠋` → `⠙`），或终端窗口刚获焦时自动消掉标题未读标记；两次 `osascript` 相隔 100–300ms 只要标题变一个字符，即使 `AXWindowNumber` 完全没变，也会误抛 `RuntimeError("foreground changed before paste")` 或激活失败。此外，`_focus` 末尾 L237 刚跑完一次 `self.windows()`，`_paste` 开头 L246 毫秒级紧接着又起一个 `osascript` 跑一遍，既慢又放大竞态；跨 Space 桌面空间切换动画期间无重试也会假失败。
- **建议的改法**：只比较窗口句柄 `self.windows()[0] == expected[0]`；`activate` 后加短轮询（如总计 300ms）等待窗口成为 `frontmost`；删掉 `_paste` 开头冗余的 `self.windows()`（由后面的 `guarded` 在同一次 `osascript` 内原子校验即可）。

---

#### [P1-3] 当前台应用无窗口（如 Finder / 桌面）时，`__call__()` 因 `osascript` 尾随换行符抛错并误报权限警告
- **文件和大致位置**：`pc/hub_desktop_mac.py` `MacWindowControl.__call__`（L107–L118）。
- **问题**：当 `(count of windows of p) is 0` 时脚本执行 `return ""`，真实 `osascript` 输出 `"\n"`。L113 `if output:` 为 `True`，L115 `output.removesuffix("\n")` 变成 `""` 传给 `_row("")`，触发 `ValueError: not enough values to unpack`，打印 `foreground window failed` 和辅助功能权限警告。
- **为什么**：`osascript(1)` 打印返回值时总会在 stdout 末尾追加一个 `\n`。
- **建议的改法**：改为 `line = (output or "").removesuffix("\n")`，判断 `if line:` 后再调用 `self._row(line)`。

---

#### [P1-4] 单个无标题窗口或瞬时关闭窗口会导致整个 `windows()` 枚举失败归零
- **文件和大致位置**：`pc/hub_desktop_mac.py` `WINDOW_HELPERS`（L29–L35）与 `windows`（L85–L98）。
- **问题**：① `set windowTitle to name of w as text`：macOS 上无标题辅助窗口/弹窗的 `name of w` 常为 `missing value`，在 AppleScript 中 `missing value as text` 会变成字面字符串 **`"missing value"`**；② `repeat with w in windows of p` 循环体未包 `try ... end try`，枚举期间只要任意一个窗口恰好关闭（报错 `-1728`）或某个无关窗口标题含 `\x1e`/`\x1f`，整个 `osascript` 直接报错退出，`windows()` 返回 `[]`，所有正常会话窗口全部失联。
- **为什么**：AppleScript 对 `missing value as text` 的转换规则（见 [AppleScript Language Guide — `missing value`](https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/reference/ASLR_classes.html)）及跨进程 UI 遍历的天然竞态。
- **建议的改法**：先判 `if rawTitle is missing value then set windowTitle to ""`，并在 `repeat with w in windows of p` 内层加 `try ... end try` 忽略单个异常窗口。

---

#### [P1-5] `_paste` 在无 `LANG` 环境下中文变乱码、`Cmd+V` 与后续回车存在时序竞态、非拉丁输入源下误触 `Cmd+A`
- **文件和大致位置**：`pc/hub_desktop_mac.py` `_paste`（L245–L251）、`send_key`（L185–L186）。
- **问题**：
  1. **中文乱码**：`pbcopy` 未显式传 UTF-8 环境变量。若 Hub 从 launchd、GUI 启动器或无 `LANG`/`LC_CTYPE` 环境启动（默认 `C` locale），`pbcopy` 会把 UTF-8 字节流按 MacRoman 解析，中文 prompt 和含中文路径全部变乱码。
  2. **`Cmd+V` 后紧跟回车的竞态**：`pbcopy` 本身同步写完 pasteboard 才退出，到 `Cmd+V` 之间还隔了一次 `osascript` 启动，一般**不会粘到旧剪贴板内容**；但 `guarded('keystroke "v" using command down', ...)` 投递完按键事件就立即退出，目标 Electron 应用（VS Code/Cursor）或开启 Bracketed Paste 的终端 TUI 往往还没异步读完剪贴板上屏，紧随其后的 `send_key(0x0D)`（`key code 36` 回车）就到了，会导致先发空回车、粘贴内容留在输入框未提交。
  3. **输入源陷阱**：当系统当前处于俄文、希腊文、注音等无法直接反查 ASCII `"v"` 的输入源时，`System Events` 的 `keystroke "v" using command down` 会回退为 `key code 0`（物理 `A` 键），变成 **`Cmd+A` 全选**。
- **为什么**：macOS `pbcopy(1)` 依赖 locale 环境变量决定输入编码；`CGEvent` 注入是异步投递；`keystroke` 按当前键盘布局反查虚拟键码。
- **建议的改法**：① 调用 `pbcopy` 时传入 `env={**os.environ, "LC_CTYPE": "UTF-8"}`；② 粘贴后留出 50–100ms 缓冲再发 `key code 36`（最好把粘贴 + `delay 0.08` + `key code 36` 合并进单次 `guarded` 脚本）；③ 粘贴可优先点菜单 `Edit -> Paste` 或结合 `key code 9 using command down`。

---

#### [P1-6] `MacDesktopEffects.focus()` 吞异常返回 `False`，破坏父类 `DesktopEffects` 模板方法的异常假设
- **文件和大致位置**：`pc/hub_desktop_mac.py`（L221–L222, L253–L273）与 `pc/hub_desktop.py`（L196–L220）。
- **问题**：父类 `interrupt`、`prompt`、`voice_down` 内部调用 `self.focus(session, sessions)`，预期失败时抛异常中断；但子类重写的 `focus()` 用 `_attempt` 捕获异常返回了 `False`。
- **为什么**：当窗口未匹配到时，`super().voice_down` 拿到 `window = False` 继续调 `self._voice_shortcut(False)`，真实原因（找不到窗口）被覆盖成 `"foreground changed or dictation shortcut failed"`，且 `self.windows.failure()` 被打印两次；`super().interrupt` 则把 `False` 传进 `self._key(0x1B, False)`（若父类 `_key` 未检查 `send_key` 返回 `False` 并抛错，`interrupt` 甚至会返回 `True` 假装成功）。
- **建议的改法**：父类模板方法内部调抛异常的 `_focus()`，仅在最外层公共方法包一层 `_attempt`；确认 `_key` 对 `send_key(...) == False` 抛出异常。

---

#### [P1-7] 漏掉 macOS“屏幕录制”权限静默截空图问题，`hub_doctor.py` 权限诊断与提示不完整
- **文件和大致位置**：`pc/hub_desktop_mac.py`（L11–L12, L262–L269）、`pc/hub_doctor.py`（L16, L137–L157）。
- **问题**：未开启“屏幕录制（Screen Recording）”权限时，`screencapture -x` **退出码仍为 `0`**，生成只有桌面壁纸、抹掉所有窗口的图片，Hub 却返回 `"status": "sent"`；同时 `PERMISSION_HINT` 和 `doctor()` 只提了“辅助功能 / 自动化”，漏了截图必需的“屏幕录制”和热键必需的“输入监控”。
- **为什么**：macOS 10.15+ TCC 对未授权 `screencapture` 采用静默去窗口化而非报错退出；可用 macOS 原生 C API [`CGPreflightScreenCaptureAccess()`](https://developer.apple.com/documentation/coregraphics/3656524-cgpreflightscreencaptureaccess)（通过标准库 `ctypes` 加载 `CoreGraphics` 即可无弹窗只读检测）。
- **建议的改法**：在 `hub_doctor.py` 中用 `ctypes` 调用 `CGPreflightScreenCaptureAccess()` 和 `AXIsProcessTrusted()` 做精确只读探测；在 `_screenshot` 校验权限或在权限提示中补全“屏幕录制”与“输入监控”。

---

#### [P1-8] `PynputHotkeys` 的 `self.held` 易因系统吞 key-up 永久卡死，且 `register` 未校验键码上下界
- **文件和大致位置**：`pc/hub_hotkey_mac.py` `register`（L38–L44）、`_press` / `_release`（L53–L70）。
- **问题**：① macOS 在 `Cmd+Tab`、锁屏、系统截图快捷键或终端 `sudo` 开启 `SecureEventInput` 时常吞掉 `on_release` 事件，一旦键留在 `self.held` 里，主键会因 `if key in self.held: return` 永久失灵，修饰键会导致 `modifiers_down()` 永久为 `True`；② `"f%d" % (binding.vkey - 0x7C + 13)` 未检查 `0x70 <= binding.vkey <= 0x83`，且 MacBook 内置键盘无物理 F13–F20 键。
- **建议的改法**：`register` 先校验 `binding.vkey` 范围（若支持字母/数字键补充 `KeyCode` 映射）；触发时结合 Quartz 当前修饰键物理状态或超时清理，避免 `self.held` 单次丢包后永久死锁。

---

### P2（改进建议）

#### [P2-1] `activate` 先存窗口引用再激活存在 z-order 漂移，且 Electron 后台窗口可能懒加载 AX 树
- **文件和大致位置**：`pc/hub_desktop_mac.py` `activate`（L127–L150）。
- **问题**：① `set end of targets to contents of w` 在 `System Events` 中通常得到基于当前索引的对象引用（如 `window 2`），随后执行 `tell application id appID to activate` 若改变窗口顺序，`perform action "AXRaise" of targetWindow` 可能抬错窗口；② VS Code / Cursor 默认懒加载无障碍树（见 [Electron Accessibility 文档](https://www.electronjs.org/docs/latest/tutorial/accessibility)），未开启无障碍支持时后台窗口有时枚举不全。
- **建议的改法**：先 `activate` 应用，再在 `System Events` 中按 `_matches("w", handle)` 重新定位目标窗口执行 `AXRaise`；在 `doctor` 或文档中提示 VS Code/Cursor 用户可设 `editor.accessibilitySupport: "on"`（或通过 AX API 对目标 PID 设 `AXManualAccessibility = true`）。

#### [P2-2] 单次动作串行跑 4–5 个 `osascript`，总耗时与阻塞风险偏高
- **文件和大致位置**：`pc/hub_desktop_mac.py` `script` / `_focus` / `_paste` / `_screenshot`。
- **问题**：虽然单个子进程设了 `TIMEOUT = 3`，但一次 `screenshot` / `prompt` 串行调用 4–5 次 `osascript`（正常冷启动合计 0.5–1.2s，遇首次 Automation 弹窗超时最坏可叠到 12–15s）；且通过 `-e` 传大段脚本不如 stdin 干净。
- **建议的改法**：合并连续的 AppleScript 调用，改用 `["osascript", "-"]` 从 `input=` 传入脚本，并为单次高层动作加总超时保护。

---

### 五个重点项专项核查汇总

1. **AppleScript 字符串转义（`literal()`）**：**转义本身安全，无注入或语法错误**。`osascript` 走列表参数不经 shell，且按 [AppleScript Language Guide — Text](https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/reference/ASLR_classes.html) 双引号字面量无变量插值，只认 `\\`、`\"`、`\r`、`\n`、`\t`；`literal()` 先替 `\` 再替 `"` 顺序正确，中文、引号、反斜杠均安全。真正的坑在读取端：`name of w as text` 会把无标题窗口的 `missing value` 变成 `"missing value"`（P1-4），以及无窗口时 `osascript` 输出 `"\n"` 导致 `_row("")` 报错（P1-3）。
2. **System Events 进程名**：`Terminal`（`"Terminal"`）、`iTerm2`（`"iTerm2"`）、`Cursor`（`"Cursor"`）、`Ghostty`（`"Ghostty"`/`"ghostty"`）能对上；**`Warp` 写错了（真实是 `"stable"`）**，**`VS Code` 漏了常见真名（真实常为 `"Electron"`）**，必须改用 `bundle identifier` 匹配并删掉 `_focus` 里的二次名称过滤（P0-3）。
3. **粘贴时序、键码 36/63、双击 Fn 听写**：`pbcopy` 同步退出后再起 `osascript` 按 `Cmd+V`，**不会粘到旧剪贴板**，但 **`Cmd+V` 后紧跟回车（`key code 36`）太快会导致异步粘贴未完成就先提交空行**，且缺 `LC_CTYPE=UTF-8` 时中文会乱码（P1-5）；`key code 36`（Return）和 `53`（Escape）正确；`63` 虽是 Fn 键码，但**合成双击 Fn 触发听写在现代真 Mac 上基本不可行**，且切走焦点时对新窗口发快捷键是错的（P0-4）。
4. **改变 Windows 行为的地方**：有两处——`hub_install.py` 把正斜杠固定路径改成带反斜杠的 `sys.executable`（在 Git Bash hook 下会吞反斜杠失败并破坏配置幂等性），以及 `hub.py` 未分平台拦截 `voice_up() is False`（P0-5）。
5. **测试是否只是在断言自己写的字符串**：**是的，非常明显**。离线测试在 Windows Python 上改 `sys.platform` 跑，所以漏掉了真 Mac 顶层 `import wintypes` 必崩（P0-1）；fake `Listener` 没复刻真实 `pynput` 类属性 `IS_TRUSTED = False`，漏掉了热键 100% 启动报错（P0-2）；fake `run` 喂的是自己写的 `"Warp"`、无尾随 `"\n"` 的空串和静止不变的窗口标题，漏掉了 `"stable"`/`"Electron"` 进程名、无窗口误报错、以及标题 spinner 跳动导致 `self.windows() != expected` 失败等全部真机故障模式。

---

### 总体结论

**现在不能拿去真 Mac 上试**：一启动就会在 `from ctypes import wintypes` 直接崩溃退出，就算绕过也会立刻撞上 `pynput` `Listener.IS_TRUSTED` 恒为 `False`、Warp/VS Code 认不出窗口、`voice` 失败卡死 LCD 状态和双击 Fn 听写失灵；请先把上述 5 个 P0 和 P1-1～P1-5 修完后再上真 Mac 实测。
