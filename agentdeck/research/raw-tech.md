# AgentDeck 技术调研（raw-tech）

调研日期：2026-11-17。标注"[估算]"的数字是调研者的推算，没有来源，用于量级判断，报价前必须找供应商确认。其余事实都带 URL。查不到的地方明确写"未查到"。

---

## 1. Agent 集成面：硬件按键能不能不模拟键盘、直接回答权限请求？

**结论：能。** Claude Code 和 Codex CLI 都有 `PermissionRequest` hook，hook 返回 `allow`/`deny` JSON 就等于回答了权限弹窗，不需要往终端里注入按键。Cursor 和 Gemini CLI 的 hook 只能做"预先拦截/放行"，没有"替用户回答弹窗"这一层，需要折中方案。

### 1.1 能力对比表

| 工具 | 触发"需要批准"的事件 | 能否由 hook 返回 allow/deny | 阻塞等待时长 | 来源 |
|---|---|---|---|---|
| Claude Code | `PermissionRequest`（"When a tool call needs a permission decision"）；`Notification` 的 matcher `permission_prompt` 只能通知，不能决策 | 能。`hookSpecificOutput.decision.behavior = allow/deny` | command/http hook 默认 timeout 600 秒 | https://code.claude.com/docs/en/hooks |
| Claude Code（另一条路） | `-p` 非交互模式 + `--permission-prompt-tool`（MCP 工具）或 Agent SDK 的 `canUseTool` 回调 | 能，由宿主程序回答 | 未设 `--permission-prompts none` 时一直等宿主回答 | https://code.claude.com/docs/en/headless |
| Codex CLI | `PermissionRequest`（"runs when Codex is about to ask for approval"）；另有 `PreToolUse`、`Stop` 等 | 能，同样的 `hookSpecificOutput.decision` 结构；多个 hook 时"any deny wins" | 文档未写超时；示例里的 hook 配 `timeout = 30` | https://learn.chatgpt.com/docs/hooks （旧地址 developers.openai.com/codex/hooks 308 重定向到此） |
| Codex CLI `notify` | 只有 `agent-turn-complete` | 否，仅通知 | - | https://learn.chatgpt.com/docs/config-file/config-advanced |
| Cursor | `beforeShellExecution`、`beforeMCPExecution`、`preToolUse` 等 | 能返回 `permission: allow/deny/ask`，但这是"策略拦截"，`ask` 是回到 Cursor 自己的弹窗 | 文档摘录未给出 | https://cursor.com/docs/hooks |
| Gemini CLI | `BeforeTool`、`Notification` 等 | `BeforeTool` 可返回 `decision: "deny"`（`block` 为别名）；未查到 `ask`。`Notification` 仅观测，"cannot block alerts or grant permissions automatically" | 默认 60000 ms | https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/index.md ，https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md |

### 1.2 Claude Code：PermissionRequest hook

配置位置 `.claude/settings.json` 等。hook 类型除 `command` 外还有 `http`（POST 事件 JSON 到 URL，响应体用同样的输出格式），这对 AgentDeck 很关键：桌面 daemon 可以直接起一个本地 HTTP 服务当 hook 接收端。

输入（stdin 或 HTTP body），原文示例：

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../00893aaf-....jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "PermissionRequest",
  "tool_name": "Bash",
  "tool_input": { "command": "rm -rf node_modules", "description": "Remove node_modules directory" },
  "permission_suggestions": [
    { "type": "addRules", "rules": [{ "toolName": "Bash", "ruleContent": "rm -rf node_modules" }],
      "behavior": "allow", "destination": "localSettings" }
  ]
}
```

输出 allow（文档示例带改写输入）：

```json
{ "hookSpecificOutput": { "hookEventName": "PermissionRequest",
  "decision": { "behavior": "allow", "updatedInput": { "command": "npm run lint" } } } }
```

输出 deny：`behavior: "deny"`，可带 `message`（告诉 Claude 原因）和 `interrupt`（true 则停掉 Claude）。文档给的字段表如此；deny 的完整样例是按字段表推出的形状。

关键规则（同一页）：
- deny/ask 规则依然生效，"allow"不会覆盖匹配的 deny 规则。
- hook 以 exit 2 退出但没有 `decision` 对象时，权限流程不变，stderr 被丢弃。也就是说 PermissionRequest 不能靠 exit code 拒绝，必须输出 JSON。
- hook 超时或失败时，输出被丢弃，回到正常弹窗。这是天然的 fail-safe：设备离线就退回终端手动确认。

其他事件：
- `Notification` 输入含 `message`、可选 `title`、`notification_type`（`permission_prompt`、`idle_prompt`、`auth_success`、`elicitation_dialog` 等）。示例：`{"hook_event_name":"Notification","message":"Claude needs your permission","notification_type":"permission_prompt"}`。该 hook 不能阻止或修改通知。来源同 https://code.claude.com/docs/en/hooks
- `Stop`：Claude 结束回复时触发，输入含 `last_assistant_message`（用于屏幕显示"完成"和摘要）。
- `SessionStart`：matcher 为 `startup/resume/clear/compact/fork`，输入含 `source`、可选 `model`。
- `PreToolUse`：输入含 `tool_name`、`tool_input`、`tool_use_id`；输出 `permissionDecision` 为 `allow/deny/ask/defer`。

### 1.3 Claude Code headless / Agent SDK

- `claude -p "..."` 非交互；`--output-format stream-json` 流式输出每个事件；`--allowedTools` 预批准。
- 非交互模式下需要批准的调用默认被拒，除非有 `PermissionRequest` hook 或 `--permission-prompt-tool` 来批准。`--permission-prompts none` 则一律拒绝。
- Agent SDK（Python/TypeScript）有 `canUseTool` 回调，适合"AgentDeck 自己拉起 agent 并接管批准"的场景，但用户已经在终端里跑的会话还是得靠 hook。
- 来源：https://code.claude.com/docs/en/headless

### 1.4 Codex CLI

PermissionRequest 输入含通用字段（`session_id`、`transcript_path`、`cwd`、`hook_event_name`、`model`）加 `turn_id`、`tool_name`（`Bash`、`apply_patch` 或 `mcp__server__tool`）、`tool_input`（`command`）、`tool_input.description`、`permission_mode`。

```json
{ "hookSpecificOutput": { "hookEventName": "PermissionRequest", "decision": { "behavior": "allow" } } }
{ "hookSpecificOutput": { "hookEventName": "PermissionRequest", "decision": { "behavior": "deny", "message": "Blocked by repository policy." } } }
```

注意：`updatedInput`、`updatedPermissions`、`interrupt` 是保留字段，文档写明"fail closed today"，不要返回。无 hook 决策时走正常批准流程。来源：https://learn.chatgpt.com/docs/hooks

hook 可配在 `hooks.json` 或 `config.toml` 的 `[hooks]` 表；项目级 hook 只有在 `.codex/` 层被信任时才加载。`approval_policy` 取值 `on-request`、`never` 或 `{ granular = {...} }`（granular 含 `sandbox_approval`、`rules`、`mcp_elicitations`、`request_permissions`、`skill_approval`）；`untrusted` 已不再支持。`notify = ["python3", "/path/notify.py"]` 只发 `agent-turn-complete`，JSON 字段 `type`、`thread-id`、`turn-id`、`cwd`、`input-messages`、`last-assistant-message`。来源：https://learn.chatgpt.com/docs/config-file/config-advanced

### 1.5 Cursor 和 Gemini CLI 的缺口

- Cursor：hook 配置在 `~/.cursor/hooks.json` 或项目 `.cursor/hooks.json`。`beforeShellExecution` 输入 `command`、`cwd`、`sandbox`，输出示例 `{"permission":"ask","user_message":"...","agent_message":"..."}`。exit 2 等价 deny。无效 JSON 会阻断动作；其他退出码视为 hook 失败、默认放行，可设 `failClosed: true`。来源：https://cursor.com/docs/hooks 。可行做法：hook 脚本阻塞等设备按键，再输出 allow/deny，把"hook 当成审批人"。是否有 hook 超时上限，摘录里未查到。
- Gemini CLI：hook 在 `settings.json`（项目 `.gemini/settings.json`、用户 `~/.gemini/settings.json`），只支持 `type: "command"`。stdout 必须只含 JSON，否则默认 Allow。`BeforeTool` 的 deny 需要 `reason`。来源同 1.1 表。可用 `BeforeTool` 阻塞等待设备按键，同样是"hook 当审批人"。

### 1.6 MCP

Claude Code 的 `--permission-prompt-tool` 接受 MCP 工具，可由外部 MCP server 回答权限（见 1.3）。MCP 本身是"agent 调用工具"的协议，不是"工具反向控制 agent"的通道，所以 AgentDeck 作为 MCP server 只能暴露"让 agent 主动问用户"之类的工具，不能替代 hook。

### 1.7 推荐集成架构

```
agent(Claude/Codex/Cursor/Gemini)
   └─ hook(command 或 http) ──> AgentDeck daemon(本机 127.0.0.1)
                                    └─ USB/BLE ──> 设备(屏幕显示 tool_name + command 摘要，等按键)
   <── allow/deny JSON ────────────────┘   (超时 => 不输出 => 回退原生弹窗)
```

---

## 2. 主机侧架构

| 方案 | 要点 | 来源 |
|---|---|---|
| QMK Raw HID | 默认 usage page `0xFF60`、usage `0x61`；报文固定 `RAW_EPSIZE`，当前 32 字节，双向都必须是 32 字节；回调 `raw_hid_receive`，发送 `raw_hid_send`。传图需要自己分包。 | https://docs.qmk.fm/features/rawhid |
| 复合 HID（键盘+厂商 raw HID） | 一个 USB 设备暴露标准键盘接口加 vendor-defined 接口，系统键盘驱动照常工作，daemon 只管 vendor 接口。上述 QMK Raw HID 即此形态。 | 同上 |
| WebHID | Chrome/Edge 89 起支持；`navigator.hid.requestDevice({filters})`，`device.sendReport(reportId, data)`；Chromium 有内置黑名单，第三方指南称通用键盘、鼠标、FIDO 认证器被拦（未能在 Chromium 原文确认，WICG `blocklist.txt` 为准）。所以 vendor usage page 的 raw HID 可用，键盘接口不可用。Firefox 不支持（仅第三方指南陈述）。 | https://developer.chrome.com/docs/capabilities/hid |
| 桌面 companion daemon | 必需。hook 要求本机进程回答，浏览器页面做不了常驻接收端。Rust/Tauri/Electron 皆可；Electron 内的 HID 同样受 Chromium 黑名单影响，可用 `disable-hid-blocklist` 覆盖。 | https://ayakael.net/mirrors/electron/raw/commit/2ea569e0d271bdd1b4e5b629133aec703ad8a3b2/docs/tutorial/devices.md |
| Stream Deck SDK 插件 | 插件需 Node.js 24+，目录 `*.sdPlugin` 内有 `manifest.json`，源码 TypeScript，`./src` 为 Node 环境，另有 HTML property inspector；插件与 Stream Deck 软件通过 WebSocket API 通信（页面只提到链接，细节未读到）。键图标最低 72x72（官方帮助），高 DPI 版 144x144（第三方转述）。HID 协议文档给 15 键系列。 | https://docs.elgato.com/streamdeck/sdk/introduction/getting-started ，https://help.elgato.com/hc/en-us/articles/360028237271-Elgato-Stream-Deck-Customizing-Key-Icons ，https://docs.elgato.com/streamdeck/hid/module-15_32 |
| macOS 权限 | 来源均为社区而非 Apple 官方：发送事件（CGEventPost）对应"辅助功能"，监听事件（CGEventTap/IOHIDManager）对应"输入监控"；10.15.6 起 CGEventTapCreate 两者都要；撤销辅助功能时若有活动 event tap 会造成系统输入卡死的报告。 | https://developer.apple.com/forums/thread/820594 ，https://developer.apple.com/forums/thread/844416 ，https://instagit.com/AprilNEA/OpenLogi/what-macos-tcc-permission-checks-are-required-for-input-monitoring-and-accessibility-grants/ |
| Windows SendInput 与 UIPI | 只能向同级或更低完整性级别的进程注入输入；被 UIPI 拦截时 `GetLastError` 和返回值都不报错（静默失败）；`uiAccess="true"` 可绕过，但需要代码签名且安装在 Program Files 或 Windows 目录。 | https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-sendinput ，https://en.wikipedia.org/wiki/User_Interface_Privilege_Isolation |
| Linux uinput | 内核模块，往 `/dev/uinput` 写 ioctl 建虚拟输入设备（`UI_DEV_SETUP`、`UI_DEV_CREATE`），按 `struct input_event` 写事件；官方建议用 libevdev 封装。节点权限要求该页未写。 | https://www.kernel.org/doc/html/latest/input/uinput.html |

**对 AgentDeck 的含义：** 批准键走 hook（1.7），完全绕开 SendInput/uinput/macOS 辅助功能。只有 Ctrl 键、截图键、PTT 之后"往焦点窗口打字"这类功能才需要模拟输入，并且受 UIPI（管理员终端里会失效）和 macOS 权限约束。设备本身若枚举成标准 HID 键盘，则这些键由设备直接发，不经过主机注入，反而没有权限问题。

---

## 3. 硬件

### 3.1 MCU

| MCU | USB device | BLE | 参考价 | 说明 |
|---|---|---|---|---|
| ESP32-S3 | 原生 USB（二手博客称支持 HID/CDC） | BLE 5.0 + Wi-Fi | ESP32-S3-WROOM-1 模块，LCSC 1 片约 $5.2（N4R2、N16R8），100+ 约 $3.4-3.6（N8R8，缺货时的参考价）；DigiKey 意大利站 N16R8 1 片 €5.67、650+ 约 €3.86 | 带预认证模块；SPI 屏多，需要 PSRAM 做图像缓冲则选 R2/R8 |
| RP2040 | 有 | 无（需外挂） | 博客称约 $0.70/片，未能在官方页面确认 | 无射频，认证最简单，LED/按键定制多；PolyKybd 类项目在用 |
| nRF52840 | 有 | 原生，低功耗强 | 博客称 $3-5，未在 DigiKey 确认 | 电池供电/BLE 为主时最佳，Wi-Fi 没有 |

MCU 对比来源（二手博客，需官方 datasheet 复核）：https://predictabledesigns.com/esp32-vs-stm32-vs-nrf52-vs-rp2040-which-is-best-f ，https://thinkrobotics.com/ar/blogs/learn/rp2040-vs-esp32-which-is-better-complete-comparison-guide-2025 。价格：https://www.lcsc.com/product-image/C2913203.html ，https://www.digikey.it/en/products/detail/espressif-systems/ESP32-S3-WROOM-1-N16R8/16162642

**倾向（[估算]）：** 原型阶段 ESP32-S3（USB + BLE + Wi-Fi 一颗搞定，状态环用 BLE）；量产若坚持低成本可评估 RP2040 + 独立 BLE 模块，但 BOM 和认证两边都更复杂，不一定划算。

### 3.2 单键屏

| 方案 | 参数 | 价格/来源 |
|---|---|---|
| 0.85" IPS，GC9107，128x128，SPI（Waveshare 同款） | 显示区 15.21x15.21 mm | Waveshare 版 Abra US$12.51；DisplayModule 同类 0.85" 128x128 IPS SPI 面板 US$4.90 起（有量大折扣）。https://abra-electronics.com/opto-illumination/lcds-and-displays/lcd-oled-displays/0.9-2.3/waveshare-26117-0-85inch-lcd-display-module-ips-panel-128128-resolution-spi-interface-65k-colors.html ，https://www.displaymodule.com/products/0-85-128-x-128-all-view-ips-tft-spi |
| 0.42" OLED，72x40，PolyKybd | 每键一块，SPI 连接，透明键帽；Split72 DIY 套件约 $200（含 72 键） | https://www.hackster.io/news/polykybd-gives-every-key-its-own-oled-display-80d5687421a2 ，https://www.techspot.com/news/98321-polykybd-mechanical-keyboard-tiny-oled-keycaps-easy-customization.html |
| Art Lebedev Optimus Maximus | 1U 键 20.2x20.2 mm，每键一块 OLED，历史参照 | https://deskthority.net/wiki/Optimus_Maximus |
| 0.66"/0.96" 64x64 彩色 OLED（SSD1331/SSD1357 类） | 本次检索未找到 LCSC/淘宝具体型号与价格 | 未查到；需补查 |
| Stream Deck 类（LCD 在键帽后面） | Classic 键图 72x72 | iFixit 拆解指向 Stream Deck Classic 拆解，未给 LCD 驱动 IC 或 BOM：https://www.ifixit.com/Teardown/Elgato+Stream+Deck+Classic+Teardown/194063 |

**屏幕是 BOM 大头：** 6 块屏，每块 $5-12 即占 $30-70，要靠量大议价或直接找面板厂定制。Stream Deck 拆解的 BOM、LCD 控制器型号：未查到。

### 3.3 金属滚轮/编码器、PTT、ASR

- 水平金属滚轮/编码器：本次检索没有定位到具体物料（如 Alps EC11 系列、Bourns、滚轮式机械编码器）和价格，未查到，待补。
- PTT 麦克风：硬件上是 MEMS 麦克风（I2S/PDM）或直接走主机的麦克风；录音在电脑端做更省 BOM。具体型号价格未查。
- 本地 ASR：sherpa-onnx 支持 Windows，流式模型为 Zipformer（含 20M 参数的小模型）；Whisper 本身不是流式，要滑窗分块，精度下降；第三方基准里 whisper.cpp Small 在某设备上 RTF 1.933（慢于实时），列名不清，仅作参考。来源：https://github.com/k2-fsa/sherpa-onnx ，https://k2-fsa.github.io/sherpa/onnx/ ，https://voiceping-landingpage-prod.pages.dev/en/blog/research-offline-speech-transcription-benchmark/ 。云 ASR 价格未查。

---

## 4. 粗略 BOM 与认证

以下 1k/10k 数字是 **[估算]**，仅基于上文有来源的单价（ESP32-S3 模块、0.85" 面板）加上经验量级，其余料号没有来源，必须以供应商报价替换。

| 项 | 1k 台 [估算] | 10k 台 [估算] | 依据 |
|---|---|---|---|
| ESP32-S3 模块 | $4.0 | $3.2 | LCSC/DigiKey 阶梯价（见 3.1） |
| 6 块彩色屏 + FPC | $36 (≈$6 x6) | $24 (≈$4 x6) | DisplayModule 0.85" $4.90 起（3.2）；定制/大量更低，无来源 |
| 6 个机械轴/按键 + 2 个批准键 + 截图/PTT/Ctrl | $8 | $5 | 无来源 |
| 水平金属滚轮 + 编码器 | $6 | $4 | 无来源 |
| MEMS 麦克风 + 功放（如需） | $1.5 | $1 | 无来源 |
| BLE 状态灯环（WS2812 类）+ 电池/充电 | $3 | $2 | 无来源 |
| PCB + SMT + 连接器 + 被动件 | $8 | $5 | 无来源 |
| 外壳 | CNC 铝约 $25-40；注塑约 $3-6（另加模具 $8k-30k） | CNC $15-25；注塑 $2-4 | 无来源，需打样报价 |
| 包装、线材、装配 | $4 | $3 | 无来源 |
| 合计（CNC 外壳 / 注塑外壳） | 约 $95-110 / 约 $70-80 | 约 $65-75 / 约 $50-55 | 汇总估算 |

认证（有来源的部分）：

| 项目 | 费用 | 来源 |
|---|---|---|
| Bluetooth SIG 资格认证（2026-03-01 起 Adopter Full 档） | $12,000；Contributing Adopter 年费 $3,500，首次资格认证 33% 折扣后 $8,000；同一设计后续提交不再收资格费 | https://www.bluetooth.com/fee-schedule/ |
| FCC（有意辐射器） | 实验室测试蓝牙设备 >$3,000；TCB 费 $1,000-$3,000（单射频新授权）；总额区间 $8,000-$20,000+（实验室/指南站，营销性质）；使用预认证模块（ESP32/nRF52840）可降 60-80%（同一来源陈述） | https://compliancetesting.com/fcc-certification-faqs/fcc-certification-cost/ ，https://markready.pages.dev/guides/fcc-certification-cost |
| CE/RED | 未找到可靠价格，需实验室报价 | 未查到 |

BQB 费用见上表 Bluetooth SIG 部分（BQB 即该资格认证流程，由 SIG 收费，另可能有 BQE/测试实验室费用，未查到）。

---

## 5. 安全：能批准 agent 工具调用的设备有什么风险

威胁与对策（Claude Code 官方安全页给了产品侧背景；设备侧的威胁分析是基于该背景的推演，已标注）：

| 风险 | 说明 | 缓解 |
|---|---|---|
| 提示注入诱导危险命令 | 官方称提示注入"override or manipulate an AI assistant's instructions"，并建议审核建议命令、避免把不受信内容直接送给 Claude，"no system is completely immune"（https://code.claude.com/docs/en/security）。设备一键批准会放大"没细看就按"的风险。 | 屏幕必须显示完整命令（或摘要加危险高亮）；对 `rm`、`curl|sh`、写 `.git/hooks`、改 settings 等规则命中则禁用一键批准，需长按加二次确认 |
| 误触/连点批准 | 官方承认"prompt fatigue"，并提供按命令白名单缓解 | 批准键长按 600ms 以上；独立于其他键；每次请求单次有效，不支持"一直允许" |
| 批准错对象 | 多 agent 并行时，屏上批准的是哪个会话容易错 | 每键绑定会话名/颜色，批准时屏幕显示 `cwd` 和 `tool_name` |
| 无关或过期请求被批准 | 按键到达时请求已超时、被取消 | daemon 为每个请求发 nonce；设备回复必须带 nonce；超时即作废 |
| 本机其他进程冒充设备或 hook | 本地 HTTP hook 接收端被其他进程调用 | 监听 127.0.0.1 加随机端口加 bearer token（Claude Code http hook 支持 `headers` 与 `allowedEnvVars`，见 https://code.claude.com/docs/en/hooks ）；USB 设备端用配对密钥签名 |
| BLE 被劫持/重放 | 状态环或按键走 BLE 时 | 使用 LE Secure Connections 配对、加挑战应答；批准路径优先走 USB |
| 设备离线 | hook 阻塞等待 | 超时或失败时 hook 无输出，Claude Code 回到原生弹窗（该行为见 1.2，timeout 输出被丢弃）；永远 fail-closed 不要 fail-open |
| 全局 deny 规则 | 批准不应覆盖企业策略 | PermissionRequest 的 allow 不会覆盖 deny 规则（官方文档，1.2）；Codex 多 hook "any deny wins"（1.4） |
| 工作区自带 hook | 恶意仓库可通过 `.claude/settings.json` 里的 hook 运行代码（官方页：`-p` 会话不弹信任对话框，仓库文件可运行内容见 permissions 文档） | AgentDeck 的 hook 装在用户级配置，不装在项目里，且检查冲突 hook |
| 沙箱 | 批准通过的 Bash 可写用户账号能写的任何位置（官方页） | 推荐配合 Claude Code sandbox 和容器，设备只做批准层不做边界 |

---

## 6. 未查到的缺口（后续补查）

- Claude Code `Stop` hook 的完整输入示例（只确认含 `last_assistant_message`）。
- Cursor hook 的超时、`preToolUse` 输出 schema 细节；Gemini CLI `BeforeTool` 的 `ask` 是否存在。
- Stream Deck WebSocket 协议细节、LCD 控制器 IC、整机 BOM。
- 0.66"/0.96" 64x64 彩色 OLED 的具体料号和价格；金属滚轮/编码器物料；MEMS 麦克风物料。
- RP2040、nRF52840 官方价格；CE/RED 测试价格；注塑模具和 CNC 打样报价。
- macOS 权限的 Apple 官方文档（目前只有论坛和第三方）。

## 主要来源清单

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/security
- https://learn.chatgpt.com/docs/hooks
- https://learn.chatgpt.com/docs/config-file/config-advanced
- https://cursor.com/docs/hooks
- https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/index.md
- https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md
- https://docs.qmk.fm/features/rawhid
- https://developer.chrome.com/docs/capabilities/hid
- https://docs.elgato.com/streamdeck/sdk/introduction/getting-started
- https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-sendinput
- https://www.kernel.org/doc/html/latest/input/uinput.html
- https://www.bluetooth.com/fee-schedule/
- https://www.lcsc.com/product-image/C2913203.html
- https://www.hackster.io/news/polykybd-gives-every-key-its-own-oled-display-80d5687421a2
