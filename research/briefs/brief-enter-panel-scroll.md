# 简报：旋钮 4 按下 = 回车；面板登录熬过重启、不留旧窗口；滚动加诊断日志

## 1. 旋钮 4 按下要能当回车（用户原话："不要告诉我没有回车键啊"）
现状（`pc/hub_controls.py` 的 `ctx select`、`pc/hub_desktop.py` 的 `context_list`）：
- agent 层（Claude/Codex 在前台）没打开列表卡片时按下 → noop "先转旋钮选择项目"；
- chat 层（微信/飞书）→ noop "这一步还没做"；
- 发送键 `send` 只在 Claude 输入框有字时点"发送"按钮，所以 Claude 弹出提问选项、确认框时，整把键盘没有普通回车。
要改：
- **列表卡片开着**时按下：照旧确认选中项。
- **列表卡片没开**时按下：agent 层和 chat 层都向前台窗口发一次普通回车（VK_RETURN，复用 `_key` 的发键路径和它的前台窗口校验）；browser/default 层本来就发回车，保持；video 层保持空格。
- 面板键盘图和帮助里，旋钮 4 按下的说明改成"回车（列表开着时确认）"；`pc/panel.py` 里 `ctx select` 的中文标签同步改。
- 测试：agent / chat 层无卡片时按下 → 发了一次 0x0D 到前台窗口；卡片开着时按下 → 走确认，不发回车。

## 2. 管理面板：登录熬过 AgentDeck 重启；从托盘再打开时不留过期旧窗口
现状（`pc/panel.py` 的登录码/会话表、`pc/panel_launch.py` 的 `open_panel`、`pc/ui/panel.js`）：
- 会话令牌只存在内存里，AgentDeck 一重启，已开着的面板窗口就提示"登录状态过期，从托盘重新打开"。
- 重启后 `has_session()` 为假，`open_panel` 直接开新窗口，旧的过期窗口留在桌面上。
要改：
- **会话熬过重启**：会话 cookie 改为不依赖内存的签名令牌，例如 `v1.<签发时间>.<HMAC-SHA256(密钥, "panel|"+签发时间)>`。
  密钥从 `~/.agentdeck/token` 派生（例如 HMAC(token, "agentdeck-panel-v1")），有效期沿用 `SESSION_SECONDS`，比较用 `hmac.compare_digest`。
  cookie 属性（HttpOnly、SameSite=Strict、Path=/panel）和一次性登录码的流程都不变；Host/Origin 校验不变。
  `has_session()` 改为"最近签发过、且还在有效期内的会话"：记一个签发时间到 `~/.agentdeck/panel.json`，只存时间，不存令牌。
- **不留旧窗口**：`open_panel` 找到已开着的面板窗口时：
  - 有有效会话 → 激活它（现有逻辑）；
  - 没有有效会话 → 先给旧窗口发 `WM_CLOSE`（只发给 msedge.exe 且标题等于面板标题的窗口），再开新窗口。
- **页面自动恢复**：`panel.js` 收到 401 显示"登录过期"提示后，每 3 秒重试一次 API；一旦成功就收起提示、恢复正常（重启后旧窗口 cookie 仍有效时，会自己恢复）。
- 测试：签名令牌在"新的 Panel 实例"（模拟重启）里仍有效；篡改、过期、换了 token 文件都无效；
  `open_panel` 在无会话且有旧窗口时先关旧窗口再开新窗口；有会话时只激活。

## 3. 旋钮 3 滚动：加诊断日志（暂不改滚动行为）
用户报"顺时针、逆时针都在往下滚"。日志里方向码是对的（0x2D→scroll 1，0x2E→scroll -1），在 Claude 对话区用接口实测方向也对，
所以需要现场证据。要改：
- `hub_desktop.scroll` 每次被调用记一行 INFO：方向（notches 的正负）、前台窗口 exe 名 + 标题前 40 字、选中栏的矩形、指针落点。
- `hub_scroll.SmoothScroll` 一次滚动结束（速度衰减到 0）时记一行 INFO：这一轮实际发出的 wheel 总量（带正负号）和次数。
- 日志里不要出现输入框内容等隐私文本（标题截断即可）。
- 测试：日志行出现、正负号正确。

## 不要做
- 不改键位文件格式和其他键的功能；不动动画；不往 0xFF00 接口或 COM4 发东西；不写 `%APPDATA%\Claude` 和 `~/.claude` 下任何文件。

## 做完的标准
- 上面每条的测试都在；`pc/test_*.py` 全部通过（逐个用 `D:\conda\miniconda3\python.exe -X utf8` 跑；`test_verify_real_session.py` 偶发失败时单独重跑确认）。
- 列出改动文件；不要提交 git。
