# 简报：语音快捷键新增"单点"模式（给 Typeless 用）

用户的 Typeless 用大键盘的右 Alt **单点**开关：点一下开始听写，再点一下结束、文字进输入框。
宏键盘语音键（第 2 排第 3 颗，hid:0x0B，绑定 `{"down": "voice_down", "up": "voice_up"}`）现在只有两种模式：
- `hold`：按下时按住快捷键，松开时松开；
- `toggle`：按下时点一次快捷键，松开时再点一次（给 Win+H 用）。
两种都不适合单点：一次短按会"开始又马上结束"。

## 要做的
1. `pc/hub_desktop.py` 的 dictation_shortcut 新增 `mode: "tap"`（校验接受；托盘里录制/选择语音快捷键的界面也能选"单点"）。
2. `tap` 模式下：
   - `voice_down`：把所选会话的窗口调到前台（和现在一样用 `_focus`），然后点一次快捷键（down+up），**不进入"语音进行中"状态**，不起守护线程，不屏蔽其他按键；
   - `voice_up`：什么都不做；
   - 这样开始/结束完全由用户点几下决定，用户用大键盘右 Alt 停止也不会和 AgentDeck 的状态打架。
3. 右 Alt（165）的发送沿用已经加好的扫描码 + extended 标志。
4. 反馈文字：`语音键：已点一下右 Alt`（快捷键名按配置生成）。
5. Raw Input 读键时仍然拒绝（不变）。
6. 测试：tap 模式按下只发一次 down+up、松开不发任何键、不阻止随后的切会话/批准；校验接受 tap；hold/toggle 行为不变。
7. 更新 `agentdeck/使用说明书.md` 语音一节：默认 Win+H；用 Typeless 等"点一下开始、再点一下结束"的工具时，在托盘里把语音快捷键设成该键并选"单点"。PDF 用上次的命令重新生成：复制 md 到临时目录，`D:/conda/miniconda3/python.exe -X utf8 D:/desk/claudex/_reports/tools/report.py <copy>.md --css agentdeck/使用说明书.css --out agentdeck/使用说明书.pdf`。

## 做完的标准
每个 `pc/test_*.py` 单独跑都退出 0。不打包 exe，不 git commit，不碰真实的 ~/.claude、~/.codex、~/.agentdeck、计划任务、注册表、键盘 0xFF00 接口。
