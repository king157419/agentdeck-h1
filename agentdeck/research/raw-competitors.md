# AgentDeck 竞品原始调研（raw-competitors）

调研日期：2026-11-17。方法：WebSearch + WebFetch。每条事实后附来源编号 [S#]，见文末来源表。
标记：【已验证】= 抓到页面原文；【二手】= 只见于聚合/博客；【未证实】= 未能核实，不要在 pitch 里当事实用。

---

## 0. 结论先行

1. **Codex Micro 是真的，且已经验证了"AI agent 实体控制器"这个品类有人买**：OpenAI 与 Work Louder 联合，$230，2026-07-15 发售，约 12 小时售罄，二手炒到 $450~$1,850（Fortune）[S1][S2]。
2. **但舆论对"贵 + 只支持 Codex + 本质是 Work Louder Creator Micro 2 换皮"很不买账**（HN 306 分 / 253 评论，以怀疑和调侃为主）[S4][S3]。这是 AgentDeck 的切入口：便宜、多 agent、真的能控电脑、有麦克风。
3. **价格带已经被打穿**：VibeKeys $39/$49/$99（含麦克风、旋钮、Claude Code/Cursor/Codex/Gemini CLI）[S8]；Keychron F4 HE 键盘 $34.99（4 键，无麦克风，有 Codex/Claude 预设）[S9]。AgentDeck "低于 $230"这个定位**不够**，真正的对手价是 $35~$100。
4. **Anthropic 官方开了 BLE 硬件接口**（claude-desktop-buddy，2.7k stars，实验性，需开 Developer Mode）[S10]。这既是机会（可作为 BLE 状态灯环的官方通道），也是风险（官方随时可能推出自己的设备）。
5. **软件侧已经很拥挤**：cmux 28.8k stars [S14]、Vibe Kanban 28.7k stars（但已宣布 sunset）[S15]、Happy 24.7k stars [S13]、Claude Squad 8.8k [S16]、Conductor 融资 $22M [S18]。硬件要靠"物理按键的确定性/不用切窗口/语音按住说话"差异化，而不是和它们比功能。

---

## 1. Codex Micro（最重要）

| 项目 | 内容 | 来源 |
|---|---|---|
| 是什么 | OpenAI 的首款硬件，一个 Codex 专用宏键盘，型号 kbd-1.0-codex-micro | [S1][S5] |
| 谁做的 | OpenAI 与 Work Louder 联合设计，通过 OpenAI Supply Co 销售 | [S1][S5] |
| 价格 | $230（Work Louder 自家同类 Creator Micro 2 约 $174，来自 HN 评论，【二手】） | [S1][S4] |
| 发售日 | 2026-07-15（部分媒体写 07-16）；Fortune 称约 12 小时售罄 | [S2][S1] |
| 规格 | 13 个低矩阵键 + 摇杆 + 一个 reasoning-level 旋钮；上 6 键显示最多 6 个 Codex 线程状态（空闲到出错变色），下 6 键为 接受/拒绝改动、push-to-talk、新建对话 等快捷键；蓝牙或 USB-C；Mac/Windows | [S3][S5] |
| 注意 | "push-to-talk"键是触发电脑端语音，**HN 评论称设备本身无麦克风无扬声器**【二手】 | [S3][S4] |
| 供货 | 限量，数量未披露；Work Louder 联创 Mike Di Genova："限量库存，但他们买了很多" | [S2] |
| 二手 | eBay 最高挂 $1,850；上线一周约 $800~$1,000；7/27 约 $450 | [S2] |
| 口碑 | 见下 | [S3][S4][S2] |

**口碑要点（来自 HN 与 VKTR、Fortune，均已抓取）**
- 贵：有人指出 $18 带旋钮的可编程键盘、$130 带 LCD 键的 Stream Deck、$20~40 DIY 宏键盘。Reddit 有人称其"像恶作剧而非真产品"（经 VKTR 转述）[S3][S2][S4]。
- 换皮：多人说就是 Creator Micro 2 贴牌 [S4]。
- 只围绕 Codex，不描述其他编码工具支持 [S3]。
- 平台：仅 Windows/macOS，闭源，Linux 用户不满 [S4]。
- 有人认为 ChatGPT 手机 App 的 Codex 监控更好用 [S3]。
- 正面：灯光状态好看，"多 agent 切换用实体控制面板"有人认可 [S4]。
- 弱点对 AgentDeck 的意义：**需求被验证 + 痛点集中在价格/封闭/单一厂商/无麦克风**。
- 【未证实】部分博客称它能模拟 Claude Code 的批准快捷键（dailyaiworld 等），无官方来源，不要引用。

---

## 2. Elgato Stream Deck 家族

| 型号 | 美国售价（2026-10/11 聚合站） | 备注 | 来源 |
|---|---|---|---|
| Stream Deck MK.2 | $149.99（也见 $119.99 促销） | 15 个 LCD 键 | [S6] |
| Stream Deck + | $179.99（首发 $199.99） | 8 LCD 键 + 4 旋钮 + 触摸条 | [S6] |
| Stream Deck Neo | $99.99 | 8 键 | [S6] |
价格来自单一聚合站 frontdeskreview，【二手】，上架前请到 Elgato 官网复核。

**AI/Claude 相关**
- Elgato 官方页 "Control Claude with Stream Deck"：Claude Code Shortcut Profile（57 个斜杠命令、ESC ESC 回退、4 旋钮控权限模式/历史/滚动/缩放）；Claude Code Usage 插件（显示花费、套餐额度、会话倒计时，仅 Windows）；价格页面未写 【已验证】[S7]。
- 社区插件：
  - paultyng/agentsd：macOS 专用，Claude Code HTTP hooks 驱动，**键位显示会话状态，可批准/拒绝/总是允许，切换会话，中断**（11 stars）[S11]。——这和 AgentDeck 核心功能几乎一致，证明 Stream Deck 现有硬件已可 DIY 出来，是最直接的"替代品"。
  - JulienCr/streamdeck-claude：只显示状态不批准（7 stars）[S12]。
  - alejandrosnz/claude-deck（显示用量）、verygoodplugins/streamdeck-mcp 见 [S6b]（搜索结果，未抓取详情，【二手】）。
- 销量/营收：**Corsair 不单独披露**。Elgato 属 "Gamer and Creator Peripherals" 分部，FY2025 该分部增长 4%，公司总收入 $1,472.5M；称 Elgato Marketplace 活跃用户超过 200 万；无 Stream Deck 单位销量 【已验证无披露】[S17]。
- 对 AgentDeck 的弱点：没有麦克风、没有截图/Ctrl 专用键、无 agent 原生状态环；需要用户自己装插件+配 hooks；Windows/macOS 依赖 Elgato 软件；价格 $100~$180。

---

## 3. AI-agent 专用硬件与相邻硬件

| 名称 | URL | 价格 | 形态 | 对 AI agent 做什么 | 热度信号 | 对比 AgentDeck 的弱点 | 来源 |
|---|---|---|---|---|---|---|---|
| VibeKeys（Pro/Plus/Max/VibeBuddy） | vibekeys.dev | Pro $39，Plus $49，Max $99，VibeBuddy $69，免运费 | 6 键 + 导航旋钮，Max 有 TFT 状态屏、Claude Code 远程模式；Pro/Plus 带语音输入 | Claude Code/Cursor/Codex/Gemini CLI/OpenCode/Copilot；开源（Rust 固件+vibetty 服务+CLI） | Show HN 有帖；Indie Hackers 有页；官网无销量/众筹数据 | **最直接的价格对手**。单键无屏（Max 为整体状态屏而非逐键屏），无截图键，无灯环；是否能真正按会话切换待核实 | [S8] |
| Keychron F4 HE 8K Vibe Coding Keypad | yankodesign 报道 | $34.99 | 4 个可编程键，磁轴，每键 RGB | Codex 与 Claude 预设；无麦克风 | 大厂入局，Launcher 软件 2026-11-09 计划发布（beta） | 只有 4 键，无屏幕，无语音，无状态反馈 | [S9] |
| Work Louder Creator Micro 2 | worklouder.cc（未抓取） | 约 $174（HN 评论，【二手】） | 13 机械键 + 旋钮 + 摇杆 + 触摸 | Codex Micro 的原型 | 见 Codex Micro | 非 agent 专用；口碑一般（HN 有负面购买体验，【二手】） | [S4] |
| Anthropic claude-desktop-buddy | github.com/anthropics/claude-desktop-buddy | 开源（ESP32 / M5StickC Plus 约 $20~30，价格【未证实】） | 桌宠，A 键批准 B 键拒绝 | Claude 桌面应用通过 BLE 显示权限请求；需开 Developer Mode；官方声明非正式产品功能 | 2.7k stars / 473 forks | 屏幕小，只有 2 键，只针对 Claude 桌面应用；但**是 BLE 灯环/状态的官方参考协议** | [S10] |
| Gavel | github.com/etalli/Gavel | DIY（RP2040 Zero） | 3 个物理键 | Allow once / Always / Reject，模拟 USB 键盘，hooks 控制 LED 按风险分类 | 1 star | 极小众，说明 DIY 需求存在 | [S19] |
| claude-macropad | github.com/pickypg/claude-macropad | DIY | QMK 键盘（NuPhy Air75 V2）hooks 驱动灯效 | 状态色，支持 Codex CLI | 未抓取详情 | 搜索结果摘要，【二手】 | [S20] |
| Logitech MX Creative Console | logitech.com | 首发 $199.99，常见促销 $160 | 9 LCD 键 + 旋钮 + 翻页键 | 无官方 AI agent 集成，搜索未发现 Claude Code 集成 | — | 偏设计/视频，无 agent 状态 | [S21] |
| Razer Stream Controller / X | razer.com | 原版首发约 $270（促销 $200），X 为 $149.99 | LCD 键 + 旋钮 | 无 AI 集成 | — | 同上；Loupedeck 软件支持 | [S22] |
| Mountain DisplayPad | mountain.gg | MSRP $109.99（有地区 $169 / "normally $199"，来源冲突），一个经销商称已停产【未证实】 | 12 LCD 键 | 无 AI 集成 | — | 同上 | [S22] |
| AliExpress 廉价 OLED 宏键盘 | — | — | — | **未检索到具体产品页，【未证实】**，需后续补查 | — | — | — |
| Rabbit R1 / AI Pin | — | — | 手持/佩戴式 AI 设备 | 与"控制电脑里多个 agent"的场景不同，非直接竞品（未做检索，仅为定位说明） | — | — | — |

---

## 4. 软件竞品

| 名称 | URL | 价格 | 形态 | 解决的痛点 | 热度信号 | 说明 / 弱点 | 来源 |
|---|---|---|---|---|---|---|---|
| cmux | github.com/manaflow-ai/cmux | 开源，主体 GPL-3.0，服务端 BSL 1.1 | macOS 终端（Ghostty 内核），竖向标签 | agent 需要你时蓝圈+通知、跳到最新未读（Cmd+Shift+U）、`cmux notify` 接 hooks | 28.8k stars / 2.7k forks | 只管"看见"和"切换"，不管批准按键；仅 macOS | [S14] |
| Happy（Happy Coder） | github.com/slopus/happy | 开源 MIT | iOS/Android/Web + CLI + 中继 | 手机端监控与控制 Claude/Codex 等，权限请求推送，端到端加密 | 24.7k stars / 2.1k forks | 手机 App 解决"离开电脑"，AgentDeck 解决"坐在电脑前"；可以互补 | [S13] |
| Vibe Kanban | github.com/BloopAI/vibe-kanban | 免费开源 | 看板式 agent 管理 | 并行 agent 任务编排 | 28.7k stars / 3.1k forks；**README 称 sunsetting** | 已进入 sunset，社区继续维护情况不一（来源冲突）【二手】 | [S15] |
| Claude Squad | github.com/smtg-ai/claude-squad | 开源 | 终端 TUI | 管理多个 AI 终端 agent（Claude Code/Codex/OpenCode/Amp） | 8.8k stars / 637 forks | 无物理键 | [S16] |
| Crystal → Nimbalyst | github.com/stravu/crystal | 开源已弃用 | 桌面 App | 并行 worktree 会话 | 3.1k stars；2026-02 弃用并入 Nimbalyst | 弃用，说明该赛道淘汰快 | [S17b] |
| Conductor | conductor.build | 免费 / BYOK（来自二手来源） | macOS 原生 App | 并行 agent + worktree + diff 审查 | 官方博客称 $22M Series A（2026-03-30），投资方 Spark、Matrix；第三方日期不一 | 与 Melty Labs 的关系【未证实】 | [S18] |
| Omnara | github.com/omnara-ai/omnara | Apache-2.0 | 托管 agent 平台 | 自托管 managed agents | 3.4k stars | 资金情况未查到 | [S23] |
| Sculptor / Terragon / Warp agent mode | — | — | — | **本次搜索未检索到有效结果，【未证实】** | — | 需补查 | — |
| Claude Code hooks 通知器 / 手机批准 | — | — | — | agentsd、Gavel 等 hooks 方案已存在（见上） | — | Claude Code 原生 hooks 即可驱动硬件，AgentDeck 应基于 hooks 而不是自造协议 | [S11][S19] |

---

## 5. 综合对比表（AgentDeck 视角）

| 产品 | 价格 | 实体键 | 逐键屏 | 麦克风 push-to-talk | 多厂商 agent | 批准/拒绝 | 状态指示 | 开源 |
|---|---|---|---|---|---|---|---|---|
| Codex Micro | $230 | 13 键 + 旋钮 + 摇杆 | 否（6 键 RGB 状态） | 键位有，设备无麦【二手】 | 仅 Codex | 是 | 6 线程颜色 | 否 |
| VibeKeys Max | $99 | 6 键 + 旋钮 | 否，整体 TFT | 有（Pro/Plus/Max） | 是 | 是 | TFT | 是 |
| VibeKeys Plus | $49 | 6 键 + 旋钮 | 否 | 有 | 是 | 是（映射） | 无 | 是 |
| Keychron F4 HE | $34.99 | 4 键 | 否 | 无 | 预设 | 是（映射） | 键 RGB | 否 |
| Stream Deck MK.2 / + | $150 / $180 | 15 / 8 + 4 旋钮 | 是 | 无 | 靠插件 | 靠插件（agentsd） | 靠插件 | 插件开源 |
| Claude Desktop Buddy | 开发板约 $20~30【未证实】 | 2 键 | 小屏 | 无 | 仅 Claude 桌面 | 是 | 屏幕+LED | 是 |
| AgentDeck（计划） | < $230 | 键 + 旋钮/滚轮，Ctrl，截图键 | 是 | 是 | 是 | 是 | BLE 灯环可选 | 待定 |

---

## 6. 对 pitch 的建议（基于证据，非事实）

- **差异化点能从证据里站住的**：(a) 逐键屏 + 真多 agent 会话映射（VibeKeys/Keychron 都没有）；(b) 内置麦克风 push-to-talk（Codex Micro 被批无麦；Keychron 无麦）；(c) 截图键直发 agent；(d) 跨 agent、开放（Codex Micro 被批闭源、仅 Codex）。
- **定价风险**：不能只说"比 Codex Micro 便宜"。VibeKeys $39~$99 才是真实价格锚点。建议定价论证必须回答"为什么比 VibeKeys Max $99 多出的部分值得"。
- **平台风险**：Anthropic/OpenAI 自己做硬件或官方 BLE 接口（S10）；Elgato 若官方出 agent 批准插件，则 Stream Deck 是最大替代。
- **需补查**：Warp / Sculptor / Terragon；AliExpress 廉价 OLED 宏键盘；Reddit 具体讨论串；VibeKeys 真实销量与 Show HN 反馈；Work Louder 官网信息。

---

## 来源列表

- [S1] Letsdatascience：OpenAI releases $230 Codex Micro keyboard with Work Louder — https://letsdatascience.com/news/openai-releases-230-codex-micro-keyboard-with-work-louder-24c2f6e4 （搜索摘要，未抓全文）
- [S2] Fortune 2026-07-27，Codex Micro 12 小时售罄、eBay 转售 — https://fortune.com/2026/07/27/openai-first-hardware-device-micro-codex-keyboard-sold-out-12-hours-reselling-on-ebay-premium/
- [S3] VKTR：OpenAI's $230 Codex Micro Is a Keyboard in Search of a Purpose — https://www.vktr.com/ai-platforms/openais-230-codex-micro-is-a-keyboard-in-search-of-a-purpose/
- [S4] Hacker News，Codex Micro（306 分 / 253 评论）— https://news.ycombinator.com/item?id=48923079
- [S5] OpenAI Supply Co 产品页（直接抓取返回 403，信息来自搜索摘要）— https://openai.com/supply/product/codex-creator-micro ；合作页 https://openai.com/supply/co-lab/work-louder/
- [S5b] Tom's Hardware（仅抓到标题：13 低矩阵键 + 摇杆 + RGB）— https://www.tomshardware.com/peripherals/keyboards/openais-first-hardware-device-is-an-rgb-macropod-codex-micro-features-13-low-profile-keys-and-a-joystick-for-controlling-ai-coding-agents ；Axios（403）https://axios.com/2026/07/15/openai-keyboard-codex-agents
- [S6] Elgato 价格聚合（单一来源）：https://frontdeskreview.com/product/stream-decks/elgato-stream-deck-mk2/ ，https://frontdeskreview.com/product/stream-decks/elgato-stream-deck-plus/ ，https://frontdeskreview.com/product/stream-decks/elgato-stream-deck-neo/
- [S6b] claude-deck 与 streamdeck-mcp 搜索结果：https://awesome.ecosyste.ms/projects/github.com%2Falejandrosnz%2Fclaude-deck ，https://glama.ai/mcp/servers/verygoodplugins/streamdeck-mcp
- [S7] Elgato：Control Claude with Stream Deck — https://www.elgato.com/explorer/products/stream-deck/control-claude-with-stream-deck-for-faster-workflows/
- [S8] VibeKeys 官网 — https://vibekeys.dev/ ；Max 页 https://vibekeys.dev/vibekeys-max ；Indie Hackers https://www.indiehackers.com/product/vibekeys ；Show HN 镜像 https://hackernews-dynamic.seasondata.workers.dev/news/48209853（未能打开，证书错误）
- [S9] Yanko Design：Keychron F4 HE 8K Vibe Coding Keypad $34.99 — https://www.yankodesign.com/?p=658087
- [S10] Anthropic claude-desktop-buddy — https://github.com/anthropics/claude-desktop-buddy ；CNX Software 报道 https://www.cnx-software.com/2026/05/16/anthropics-open-source-claude-desktop-buddy-turns-esp32-s3-devices-into-interactive-ai-desk-companions/
- [S11] paultyng/agentsd — https://github.com/paultyng/agentsd
- [S12] JulienCr/streamdeck-claude — https://github.com/JulienCr/streamdeck-claude
- [S13] slopus/happy — https://github.com/slopus/happy
- [S14] manaflow-ai/cmux — https://github.com/manaflow-ai/cmux
- [S15] BloopAI/vibe-kanban — https://github.com/BloopAI/vibe-kanban
- [S16] smtg-ai/claude-squad — https://github.com/smtg-ai/claude-squad
- [S17] Corsair FY25 财报 — https://www.businesswire.com/news/home/20260212080218/en/Corsair-Reports-Strong-Revenue-and-Profit-Growth-for-4Q25-and-FY25
- [S17b] stravu/crystal — https://github.com/stravu/crystal
- [S18] Conductor $22M Series A 官方博客 — https://www.conductor.build/blog/series-a
- [S19] etalli/Gavel — https://github.com/etalli/Gavel
- [S20] pickypg/claude-macropad — https://github.com/pickypg/claude-macropad （仅搜索摘要）
- [S21] Logitech MX Creative Console 价格：https://www.neowin.net/deals/logitech-mx-creative-console-is-down-to-the-lowest-price/ ；https://techpowerup.com/326917/logitech-launches-mx-creative-console-redefining-digital-creation-and-unleashing-your-creative-potential
- [S22] Razer / Mountain：https://windowscentral.com/gaming/the-razer-stream-controller-x-is-brand-new-and-a-lot-cheaper-than-razers-first-attempt ；https://www.engadget.com/the-razer-stream-controller-is-down-to-its-all-time-low-price-143755384.html ；https://frontdeskreview.com/product/stream-decks/mountain-displaypad/
- [S23] omnara-ai/omnara — https://github.com/omnara-ai/omnara
