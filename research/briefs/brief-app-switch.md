# 简报：旋钮 1 在 Claude 桌面版里切会话 + 按键反馈写明是哪颗键 + Typeless 右 Alt

背景：用户的会话全在 Claude 桌面版的同一个窗口里，现在的"切槽位"只是把这个窗口调到前台，看起来什么都没发生。
官方文档（code.claude.com/docs/en/desktop.md）：桌面版 `Ctrl+Shift+]` / `Ctrl+Shift+[` 切到下一个 / 上一个会话。
现在 AgentDeck 读键方式是 USB 直读（接口 0 已装 WinUSB），按键不会漏进窗口。

实测键位（`pc/hub_keys.json` 的 `_instructions` 已按此写好）：
- 旋钮 1：逆时针 S（hid:0x16），顺时针 F（hid:0x09），按下 L（hid:0x0F）
- 旋钮 2：逆时针 P（hid:0x13），顺时针 R（hid:0x15），按下 Q
- 旋钮 3：- / =，按下 V
- 旋钮 4：[ / ]，按下 C
- 20 颗键的行列见 `_instructions`

## 要做的

1. **新动作 `app next` / `app prev`**（`pc/hub.py` 的动作校验和分发 + `pc/hub_desktop.py`）：
   - 目标窗口：所选会话的 hwnd，前提是它的 `window_exe` 是 claude.exe；否则找 claude.exe 的可见顶层主窗口（标题 "Claude"）。
   - 用 `deck_windows` 现有的 activate 把它调到前台，再用 SendInput 发 `Ctrl+Shift+]`（next，VK_OEM_6）或 `Ctrl+Shift+[`（prev，VK_OEM_4）。按下顺序 Ctrl、Shift、键；松开顺序反过来；中途失败也要把修饰键松开。
   - 语音进行中拒绝（和其他动作一致）。找不到 Claude 窗口时返回错误，反馈文字"没找到 Claude 桌面版窗口"。
   - Raw Input 读键时拒绝（加进 `RAW_INPUT_BLOCKED`），因为字母会先漏进输入框。
   - 不改所选槽位（浮窗里的选中会话不变）。
   - 反馈文字：`Claude：下一个会话` / `Claude：上一个会话`。
2. **默认键位 v7**：`hid:0x09` → `app next`，`hid:0x16` → `app prev`（其余不变）。没改过的 v6 文件自动升级，留 `hub_keys.json.bak-v6`；改过的不动。照 v6 那次的升级写法（V6_CHANGED 等）和测试。
3. **按键反馈写明是哪颗物理键**：浮窗上每次按键的反馈前面加上控件名，例如"旋钮 1 顺时针 → Claude：下一个会话"、"第 2 排第 1 颗 → 已批准"。从实测键位生成一张 键码→名字 表（一个键码对应两个位置的，比如 P 是第 5 排第 4 颗也是旋钮 2 逆时针，就两个都写，"第 5 排第 4 颗 / 旋钮 2 逆时针"）。app.log 的按键行也带上这个名字。
4. **语音快捷键支持右 Alt**：用户的 Typeless 用"右 Alt"触发。确认 `config.json` 里写 `{"dictation_shortcut": {"key_codes": [165], "modifiers": [], "mode": "hold"}}`（165 = VK_RMENU）能通过校验；发送时右侧修饰键（VK_RMENU、VK_RCONTROL、VK_RSHIFT 不需要、VK_RWIN）要带 KEYEVENTF_EXTENDEDKEY 和正确的扫描码（右 Alt = 0x38 + extended），这样低级键盘钩子看到的是真的右 Alt。托盘"键位/语音快捷键"录制界面录到右 Alt 时也要存成 165。
5. 更新 `pc/hub_keys.md`、`pc/hub_README.md`、`agentdeck/使用说明书.md` 里对应的键位说明（旋钮 1 改为 Claude 里切会话；旋钮 2 是浮窗里切选中会话；按住第 2 排第 3 颗 = 语音，默认 Win+H，可改成 Typeless 的右 Alt）。说明书 PDF 按上次的命令重新生成：复制 md 到临时目录，`D:/conda/miniconda3/python.exe -X utf8 D:/desk/claudex/_reports/tools/report.py <copy>.md --css agentdeck/使用说明书.css --out agentdeck/使用说明书.pdf`。

## 做完的标准
- 每个 `pc/test_*.py` 单独跑都退出 0；新增测试覆盖：app next/prev 发出的按键序列（含失败时松开修饰键）、目标窗口选择、Raw Input 拒绝、v6→v7 升级与备份、反馈里的控件名、右 Alt 的 extended 标志。
- 不重新打包 exe（我来打包），不 git commit，不碰真实的 ~/.claude、~/.codex、计划任务、注册表 Run、键盘的 0xFF00 接口。
