# 简报：语音键可以改成调用 Typeless（或任何语音输入软件的快捷键）

## 背景
现在 Windows 上的语音键（H，按住）是：先把对应会话窗口切到前台，再发 Win+H（系统听写），松开时再发一次。
用户日常用 Typeless 做语音输入，希望这颗键直接触发 Typeless。Typeless 靠全局快捷键工作，不需要 API。
macOS 那边已经有 `dictation_shortcut` 配置（`hub_desktop_mac.py`），Windows 还写死在 `_voice_shortcut` 的 Win+H。

## 要做
1. Windows 端（`pc/hub_desktop.py`）支持 hub 配置里的 `dictation_shortcut`，格式和 mac 对齐，再加一个 `mode`：
   - `"toggle"`（默认，等于现在的 Win+H 行为）：按下发一次组合键，松开再发一次；
   - `"hold"`：按下时把组合键按住不放，松开时释放（适配"按住说话"类软件）。
   没配置时保持 Win+H toggle，现有行为不变。
2. 托盘"设置"或"键位"里加一项"语音快捷键"：点了之后让用户在键盘上按一次 Typeless 的快捷键录下来，再选"按住说话 / 按一下开始、再按结束"，存进配置立即生效。界面文字尽量少。
3. 安全不变：语音期间仍然不允许批准；窗口丢失 / 超时照常收尾；hold 模式在任何异常、超时、设备拔出时都必须发出按键释放，不能让修饰键卡住。
4. 所有按键发送都只在目标窗口仍在前台时进行（沿用现有的 expected 检查）。

## 硬约束
- 不读写真实 `~/.claude`、`~/.codex`；测试用替身，不真的发系统按键。
- 不 git commit。可以打包，但打包前确认 AgentDeck.exe 没在运行，打包后不要启动它。

## 完成标准
- 现有 `pc/test_*.py` 全过 + 新测试（toggle / hold、卡键防护、配置读写、默认行为不变）。
- 结果写 `research/voice-shortcut-results.md`。
