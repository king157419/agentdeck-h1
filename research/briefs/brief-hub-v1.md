# 简报：AgentDeck Hub v1 —— 按键直接控制 agent（不再模拟键盘去批准）

背景：产品方向已改为"按键控制电脑上的所有 agent"。批准/拒绝改为直接回答 agent 的 `PermissionRequest` 钩子（Claude Code 与 Codex 官方支持；钩子超时或失败会自动退回终端原生提示）。
钩子格式见 `agentdeck/research/raw-tech.md` 第 1.2、1.4 节（已核对官方文档摘录）。

## 要做的东西（全部新文件，放在 `pc/`，不要改动 deck.py / daemon.py 的现有行为）

### 1. `pc/hub.py` —— 常驻中枢进程
- 本地 HTTP 服务，只监听 `127.0.0.1`，端口默认 47800（`--port` 可改）。
- 鉴权：首次启动在 `%USERPROFILE%\.agentdeck\token` 生成随机 token；除 `GET /health` 外，所有请求都必须带头 `X-AgentDeck-Token`。
- 接口：
  - `POST /event?agent=cc|cx` —— 收钩子事件 JSON。
    - 普通事件（SessionStart / UserPromptSubmit / PreToolUse / PostToolUse / Notification / Stop / SessionEnd）：更新会话表，立即返回 `{}`。
    - `PermissionRequest`：登记一条待批请求，**阻塞等待**按键决定，最多 `--approve-timeout` 秒（默认 110）。
      - 批准：返回 `{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}`。
      - 拒绝：返回 `decision.behavior="deny"`，带 `message`：`"Denied from AgentDeck"`。
      - 超时：返回 `{}`，agent 会退回终端提示。
      - 对 Codex **不要**返回 `updatedInput`、`updatedPermissions`、`interrupt`。
  - `GET /state` —— 会话表与待批队列的 JSON（调试和以后的界面用）。
  - `POST /action` —— body `{"action": "...", ...}`，与物理按键走同一条动作路径（测试、Stream Deck 等其他输入都用它）。
- 会话表：
  - 键为 `(agent, session_id)`；
  - 字段：cwd、项目名、状态（think/tool/wait/done/idle/error）、待批请求（id、tool_name、命令摘要、风险等级、创建时间）、最后更新时间、**稳定槽位号 1..6**（按首次出现分配，会话结束后释放）。
  - 状态推导：UserPromptSubmit/PreToolUse→think 或 tool，PermissionRequest→wait，Stop→done，SessionEnd→移除。
- 风险分级 `classify(tool_name, tool_input) -> "low"|"high"`：
  - 以下命令为 high：`rm -rf`、`Remove-Item -Recurse`、`del /s`、`rmdir /s`、`git push --force`/`-f`、`git reset --hard`、`git clean -f`、`curl|wget … | sh/bash/iex`、`sudo`、`format`、`mkfs`、`dd if=`、`chmod -R 777`、写入 `~/.ssh` / `.env`、`DROP TABLE`。
  - 其余为 low。规则写成可配置列表。
- 动作（`actions.py` 或写在 hub 内，纯逻辑，可注入替身）：
  - `slot N`：选中槽位 N 的会话，把它的窗口切到前台（复用 `deck_windows.WindowControl` 和 daemon 的标题匹配），LCD 切到该会话。
  - `cycle ±N`：在有会话的槽位间循环。
  - `approve`：
    - 作用对象是**当前显示中的那条待批请求**。新请求到达且当前没有正在显示的请求时，自动显示最早的一条。
    - low 风险单击即可；high 风险要在 1.5 秒内按两次，第一次只在 LCD 显示 `HOLD! press again`。
    - 返回值必须包含请求 id。
  - `deny`：拒绝当前显示的请求。
  - `interrupt`：有待批请求时 deny 它；没有时把该会话窗口切前台并发一次 Esc。
  - `voice`：把选中会话的窗口切前台，再发 Win+H（Windows 语音输入）。
  - `screenshot`：
    - 用 PIL `ImageGrab` 截全屏，存到 `%USERPROFILE%\.agentdeck\shots\时间戳.png`；
    - 把选中会话窗口切前台，通过剪贴板粘贴文件路径，不按回车。
  - `prompt NAME`：
    - 把选中会话窗口切前台，粘贴模板文本并回车；
    - 模板在 `pc/hub_prompts.json`，先给"继续 / 跑测试 / 总结进度 / 提交"四条，中英文都要。
- 显示：
  - 通过现有 `agent_lcd.send` 往 1602 发 `set <key> wait <name>` 和 `focus <key>`。
  - 会话 key 要和 `agent_lcd.hook_line` 的命名完全一致（`cc-`/`cx-` + session_id 去掉横线后的前 6 位），这样和现有钩子显示不冲突。
  - 发 focus 时用 `focus_lock` 互斥，并 touch `daemon.DECK_HOLD`，避免和 daemon 抢屏。
  - LCD 不在时，hub 照常工作，只记日志。
- 输入：
  - `--backend usb` 时复用 `deck_usb.USBInput` 读宏键盘，按 `pc/hub_keys.json` 把按键映射到动作。
  - 先沿用 `deck_map.json` 里已知的物理键码：E/B/Ctrl+Z/G/Ctrl+F/Space/H/L 和旋钮码，映射到 slot 1..3、approve、deny、interrupt、voice、screenshot、cycle。映射表要写明"哪个物理键 → 哪个动作"。
  - `--backend none` 时只开 HTTP。

### 2. `pc/hub_relay.py` —— 钩子转发脚本（给 command 型钩子用）
- 从 stdin 读事件 JSON，读 token 文件，POST 到 hub（`--agent cc|cx`），把响应体原样打印到 stdout。
- hub 不在、超时或出错时，**什么都不打印、exit 0**，agent 走原生流程。
- 连接超时 0.5 秒；PermissionRequest 读超时 = approve-timeout + 5 秒。

### 3. `pc/hub_install.py` —— 安装 / 卸载钩子
- `install`：
  - 往 `~/.claude/settings.json` 和 `~/.codex/hooks.json` **追加** PermissionRequest 钩子（以及 hub 需要的状态事件钩子），命令为 `D:/conda/miniconda3/python.exe <abs>/pc/hub_relay.py --agent cc|cx`。
  - Claude 的 PermissionRequest 钩子 timeout 设 120 秒；Codex 设 120。
  - 先备份原文件到 `*.bak-agentdeck-<时间>`；幂等，重复安装不会重复添加。
  - 不要删除或改动已有的 agent_lcd 钩子。
- `uninstall`：只删掉自己加的条目。
- `--dry-run`：打印将要写入的 diff。
- 写之前先读 Codex 官方钩子格式（项目里 `~/.codex/hooks.json` 已有 agent_lcd 的条目，照它的结构写）。

### 4. 测试 `pc/test_hub.py`（离线，全部注入替身，不碰串口/窗口/网络之外的东西）
至少覆盖：
- PermissionRequest 阻塞，approve 后返回 allow；deny 返回 deny 带 message；超时返回 `{}`。
- high 风险需要两次按键；两次间隔超过 1.5 秒要重新计。
- 两个会话同时待批：先到先显示；批准一个后自动显示下一个；不会批到别的会话。
- token 缺失或错误返回 401；只绑 127.0.0.1。
- relay 在 hub 不在时静默 exit 0。
- install 幂等、uninstall 只删自己的、dry-run 不写文件（用临时目录模拟 home）。
- 槽位稳定：会话增减时已有会话的槽位号不变。
- 会话 key 命名与 agent_lcd 一致。

## 验收
- `python pc/test_hub.py` 全部通过，现有测试（test_ui/test_daemon/test_pc/test_deck*/test_focus_lock）全部仍通过。
- 不要真的执行 install，不要碰 COM4，不要发真实按键（沙箱里也做不到）；真机和真实 Claude 会话的端到端测试由 Claude 主会话负责。
- 汇报：文件清单、每个接口的一句话说明、全部测试输出。
