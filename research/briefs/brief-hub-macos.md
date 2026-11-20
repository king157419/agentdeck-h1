# 简报：Hub macOS 适配（第一版，无法在本机实测，先做到离线测试全过）

先读 `pc/hub_README.md`、`pc/hub_desktop.py`、`pc/hub_hotkey*.py`、`pc/hub_overlay.py`。目标：Windows 上的行为一项都不变，macOS 上 hub 也能跑起来。

## 要做的
1. `hub_desktop` 按平台分发：Windows 走现有实现；macOS 新增一个后端（`hub_desktop_mac.py`），用 `osascript` / `screencapture` / `pbcopy`，**不引入第三方依赖**：
   - 聚焦会话窗口：用 System Events 按窗口标题包含项目名来匹配 Terminal、iTerm2、Visual Studio Code、Cursor、Warp、Ghostty 的窗口，`AXRaise` 并 `activate`。匹配规则复用 Windows 版的标题匹配逻辑。
   - Esc（interrupt）、粘贴并回车（prompt 模板）：先用 `pbcopy` 写剪贴板，再用 System Events 发 `keystroke "v" using command down`，最后 `key code 36`。
   - 截图：`screencapture -x <path>`，然后把路径粘贴进会话。
   - 语音：按下时聚焦目标窗口，再触发系统听写，快捷键做成可配置，默认按两下 Fn，如果做不到就用 System Events 发 `key code 63` 两次；守护目标窗口的逻辑复用 v1.2 的轮询。
   - 每个 osascript 调用设 3 秒超时；失败时只写日志，不抛异常。第一次失败时提示用户去"系统设置 → 隐私与安全性 → 辅助功能 / 自动化"给权限。
2. 热键后端：macOS 上，如果装了 `pynput` 就用它注册 F13–F20 等热键（映射和 Windows 一致）；没装就打印提示并禁用热键，不要报错退出。
3. `hub_doctor` 在 macOS 上额外检查：osascript 能不能用、辅助功能权限（用一次无害的 System Events 调用来探测）。
4. `hub_install`：路径分隔符、python 路径在 macOS 上要能用。默认用 `sys.executable`，可以用参数覆盖。
5. README 加 "macOS（未实测）" 一节：权限设置步骤、已知限制。

## 测试
离线测试，注入假的 `subprocess.run`：
- 断言生成的 osascript 文本和参数正确；
- 平台分发正确；
- 没有 pynput 时能降级；
- 失败只记日志。

现有全部测试必须通过，`research/selftest_hub_replay.py` 也要全部 PASS。备份到 `_rollback/hub-pre-mac/`。汇报：改动文件、测试输出、需要在真 Mac 上验证的清单。
