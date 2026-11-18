# AgentDeck 硬件创业融资调研报告（2026 年 11 月市场与竞品实证分析）

> **调研方法与核实口径说明（重要）**：
> 1. 本报告严格遵循约束：**仅使用 Google Web Search**，未执行任何终端命令、未读写本地文件，亦未使用浏览器直接打开目标网页 HTML。
> 2. 所有条目均附带 Google Search 索引来源链接（含原文直链及 Google Search Grounding 重定向链接），**绝不捏造任何账号、引语、互动量或销售数字**。
> 3. 按照“凡无法直接打开之内容均标为未核实（mark anything you could not open as unverified）”原则：由于仅使用网页搜索摘要且 X (`x.com`)、Reddit 对直接抓取设限，**所有未能直接打开原帖/原网页核验上下文的条目均明确标注为 `未核实（未直接打开原网页）`**；对于搜索索引中完全未公开的字段（如部分 X 帖子实时互动数、VibeKeys 具体销量），均如实注明“未公开 / 未索引”。

---

## 核心战略洞察（面向 AgentDeck Pitch）

2026 年下半年，“多 AI 编码 Agent 桌面物理控制器”已从社交媒体玩梗迅速演变为真实硬件赛道，并呈现出**清晰的产品定位断层**——这正是 **AgentDeck** 的核心切入点：

| 2026 现有竞品 | 售价 | 核心形态 | AgentDeck 可切入的致命短板 |
| :--- | :--- | :--- | :--- |
| **OpenAI Codex Micro** (× Work Louder) [1][2] | $230 | 13 键机械键盘 + 6 颗 RGB 状态键 + 摇杆 + 旋钮 | **价格过高（$230 引发全网吐槽）、单一生态绑定（仅限 Codex）、无屏幕（仅靠 RGB 颜色猜状态）** [3][21] |
| **Logitech MX Keypad** [30][32] | $99.99 | 3×3 全彩 LCD 键（116×116px）+ 2 翻页键 | **无内置麦克风（无原生硬件 PTT 拾音）、9 键同时兼顾多会话与审批/截图键位捉襟见肘、需依赖 Options+ 重量级驱动** [15][31] |
| **Ulanzi AU05 Vibe Key** [12][13] | $59.99–$69.99 | 低音耳语级 PTT 麦克风 + 机械快捷键 + 旋钮 | **无按键小屏幕、无多并发 Agent 会话动态监控能力** [12][13] |
| **VibeKeys Max / VibeBuddy** (Second State) [35][36] | $99 / $69 | 单块状态屏 + 麦克风 + 凯华青轴（3D 打印外壳） | **非“每会话独立屏幕键（per-session LCD keys）”；Reddit 用户嫌弃 $99 仍是 3D 打印粗糙外壳、无铝合金质感** [25][36] |

**AgentDeck 差异化卡位**：结合 **MX Keypad 的每键独立小屏** + **Ulanzi Vibe Key 的耳语级原生 PTT 语音** + **基于各家 Agent Permission Hooks（Claude Code / Codex / Cursor / Gemini·Antigravity CLI / Trae / Qwen Code / Kimi）的安全定向 Approve/Deny（杜绝误向错误焦点窗口注入回车）** + **独立截图键与 CNC/金属质感外壳**，定价锚定在 **$99–$149** 区间最具杀伤力。

---

## （一）2026 年 X / Twitter 社区反应与需求原话采集

> **检索说明**：由于 X (`x.com`) 在 2026 年限制搜索引擎直接抓取单条推文详情页，以下仅收录通过 Google Search 索引及权威科技媒体（Mashable、Gigazine、ExplainX、VibeKeys 官方归档博客等）实证引用的真实 X 帖子与原文短句（均严格 **<25 词**）。对于 **Ulanzi AU05 Vibe Key**，公开搜索索引中暂无带原文的 2026 年 X 帖子，遵循“不捏造”原则如实留空说明。

| 涉及对象 / 主题 | X 账号 (Handle) | 日期 | 原文短引语（严格 <25 词）与中文释义 | 可见互动数据 | 来源链接 | 核实状态 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **OpenAI Codex Micro**（官方预热） | `@OpenAIDevs` | 2026-06-29 | *"Your favorite Codex shortcuts are getting an upgrade. July 15th."*（10 词；预热 Codex 物理硬件发布） | 首日约 **100 万浏览**（~1M views in 24h，据 ExplainX 报道） | [ExplainX 报道][8] | **未核实**（未直接打开 X 原帖，经第三方索引验证） |
| **OpenAI Codex Micro**（正式发布） | `@OpenAIDevs` | 2026-07-15 | *"Meet kbd-1.0-codex-micro, built with @work_louder. Map the buttons and joystick to your workflow, and keep your pinned chats in view."*（20 词；联名 Work Louder 发布，迅速售罄） | 未公开 / 搜索摘要不可见 | [X 原帖直链](https://x.com/OpenAIDevs/status/2077425991790870644) / [YouTube 引用源][5] / [Mashable][6] / [Gigazine][7] | **未核实**（X 原帖未直接打开；文本经多源交叉印证） |
| **呼唤物理 Approve/Deny 按钮**（爆款概念图） | `@fabianstelzer` | 2026 年 6 月（2026-06-17 被归档） | 三键白色奢品风概念小键盘，键帽仅印：*"Allow Once, Always Allow, and Reject"*（6 词；直击 Claude Code 权限弹窗痛点） | 博客提及获“数千赞”（具体数值不可见） | [VibeKeys 官方博客归档][9] | **未核实**（X 原帖未直接打开，经博客图文描述索引） |
| **呼唤多 Agent 状态屏 + 物理键**（催化硬件化的梗图） | `@shiri_shh` | 2026 年 6 月（2026-06-17 被归档） | *"vibe coder needs this in 2026"*（6 词；配图含绿色状态屏 *"TASK: CODE REFACTOR — PROGRESS: 60%"*、YOLO 键与麦克风） | 未公开 / 搜索摘要不可见 | [VibeKeys 官方博客归档][9] | **未核实**（X 原帖未直接打开，经博客图文描述索引） |
| **VibeKeys / Vibe Coding 物理键盘潮** | `@Salmaaboukarr` / `@mattrothenberg` / `@secondstateinc` | 2026-06-17（归档发布日） | 展示带麦克风键、方向键与 CNC 铝机身概念；Second State (`@secondstateinc`) 发文宣布将其量产为 VibeKeys [9][14] | 未公开 / 搜索摘要不可见 | [VibeKeys 博客][9] / [Second State][14] | **未核实**（未直接打开 X 原帖） |
| **Logitech MX Keypad**（生态合作发声） | `@Logitech` / `@github`（Martin Woodward） | 2026-09-08 | *"MX Keypad makes working with GitHub Copilot feel like a natural part of the workflow..."*（15 词；官方发布同期合作表态，非独立个人推文） | 不适用（新闻稿引述） | [Morningstar 新闻稿][11] / [Logitech][30] | **未核实**（未直接打开 X 平台对应帖） |
| **Ulanzi AU05 Vibe Key** | 无已索引 X 账号结果 | 2026 年 9 月发布 | *Google Search 公开索引中未检索到 2026 年针对 Ulanzi AU05 Vibe Key 的具体 X 用户推文原文（拒绝编造）。* | 无数据 | [Ulanzi 官网][12] / [B&H][13] | **未核实**（X 原帖未检索到） |
| **离开工位时的物理权限审批痛点**（开发者圈热传硬件改装） | Paolo（`paolo.blog` 作者，ESP32/M5Stack 物理审批键） | 2026-05-12 | *"The point of an agent is that it does things while you’re elsewhere. So this kept bugging me."*（18 词；解释为何自制 Claude 权限物理按钮） | 未公开 | [paolo.blog 原文直链](https://paolo.blog/2026/05/12/a-physical-button-for-claudes-permission-prompts/) / [搜索源][10] | **未核实**（未直接打开原网页，经搜索摘要精确提取） |

---

## （二）Reddit 核心社区第一人称购买意向与价格反应

覆盖目标社区：`r/ClaudeCode`、`r/ClaudeAI`、`r/codex`、`r/cursor`、`r/vibecoding`、`r/macropads`（及 `r/macro_pads`）、`r/streamdeck`（及 `r/elgato`）。

| 社区 (Subreddit) | 帖子标题 | 第一人称原话 / 购买意向与价格反应摘要 | 对 AgentDeck 的启示 | 来源链接 | 核实状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`r/ClaudeCode`** | *“I barely type code anymore, so I moved my day onto nine physical keys. Useful, or overkill?”* | OP 将日常工作迁移至 **Logitech MX Creative Keypad** 9 颗屏幕键（前 3 颗显示并发 Claude Code 项目名、上下文占比与等待状态，其余为 Yes/No 审批、中断、Git 提交与按住说话），并吐槽 Codex Micro **$230 ("ouch!")** 太贵。 | 验证了 **“前排每会话独立状态键 + 下排审批/语音键”** 的黄金交互布局！ | [Reddit 帖子源][15] | **未核实**（未直接打开原网页） |
| **`r/ClaudeCode`** | *“I got tired of checking Claude Code terminals, so I built VibeDeck to put my sessions on a Stream Deck”* | OP 因厌倦频繁切终端查看权限阻塞而开发 VibeDeck 插件（支持 Claude Code、Codex、Cursor，带“Swarm”键一键跳至等待最久的会话），定价 **7 天免费试用后 $5/月**。另有 *“Claude Code with Stream Deck, anyone?”* 与 *“I turned my Stream Deck+ into an AI Agents control surface...”* 等多帖跟进。 | 开发者甚至愿意为纯软件插件付月费来解决多会话盯梢焦虑，自带开箱即用多 Agent 插件的硬件附加值极高。 | [VibeDeck 帖][16] / [定价详情帖][17] / [Stream Deck 讨论 1][18] / [讨论 2][19] | **未核实**（未直接打开原网页） |
| **`r/ClaudeAI`** | *“Stop alt-tabbing to check if Claude is done — I made a Stream Deck button that blinks when it's waiting for you”*（2026-06） | OP 第一人称痛陈启动 Claude Code 后陷入“每 30 秒偏执地 Alt-Tab 回终端检查是否跑完或卡在确认框”的恶性循环，为此专门编写物理按键闪烁提醒插件。 | “防 Alt-Tab 焦虑”是最能引发开发者冲动下单的痛点文案。 | [Reddit 帖子源][20] | **未核实**（未直接打开原网页） |
| **`r/codex`** | *“Introducing the Codex Micro”* | 强烈价格反弹：<br>• `u/Downtown_Method5736`: *"Sorry you'll only need to pay 230 small dollars baby."*<br>• `u/MrRubkins`（加拿大买家算账）: *"...the $230 usd of the Codex Micro being around $322 dollars brings me to a nice little total of around 500 dollars after all taxes. AYYYYEEOOUUCCHHHHH."*<br>• 生态锁定质疑：*"Paying $230 to be (presumably) vendor locked is a tough sell."*<br>• 真实买家评测：*"It's priced like an Apple product... Would I recommend it? Yes, if you can stomach the price, like working on multiple tasks at once, and enjoy working with voice."* | **$230 + 高昂国际运费 + 单一厂商锁定**是最大劝退点；但已购重度用户高度认可“多任务状态灯 + 语音输入”组合。 | [r/codex 价格评论源][21] / [买家评测源][22] / [锁定质疑源][24] | **未核实**（未直接打开原网页） |
| **`r/codex` / `r/vibecoding`** | *“I couldn't afford the $230 Codex Micro, so I vibe-coded a digital one that runs on any phone/tablet and actually talks to Claude and Codex”* | 第一人称明确表达**想买但买不起 $230 官方硬件**，转而自制同时打通 Claude 与 Codex 的平板/手机端数字控制器。 | 跨工具兼容（Claude + Codex + Cursor + 国产 CLI）是刚需。 | [Reddit 帖子源][23] | **未核实**（未直接打开原网页） |
| **`r/vibecoding` / `r/ClaudeCode`** | *“I build VibeKeys — after the Codex Micro reaction in this sub, here's the $99 keypad I've been building with a Codex mode”* 及 *“I actually built the vibe coding keyboard. It's not a meme.”* | 两极化的真实购买反馈：<br>• **明确购买意向**：*"If i was someone who'd buy this type of product id honestly probably buy yours. Not only for the fact that its half the price of Codex, but also that the firmware is open source."*<br>• **外壳质感挑剔**：*"Cool keyboard but tbh $100 is still a lot. Everything is 3dp no aluminum or nice finish..."* | **$99 价位段若采用 3D 打印塑料壳会被嫌贵**；在 $99–$149 提供铝合金/注塑精工外壳 + 开源可扩展协议是制胜关键。 | [购买意向源][24] / [3D 打印质感批评源][25] | **未核实**（未直接打开原网页） |
| **`r/macropads`** (`r/macro_pads`) | *“agentpad13: an open-source macropad inspired by the Codex Micro”* / *“AgentPad13: Our $40 Codex Micro clone is officially real...”* | 第一人称价格宣言：*"Love OpenAI's Codex Micro, but not the $230 price tag? Us too. So we created agentpad13... built for as little as ~$65"*（批量拼板低至 ~$40，含 13 键、摇杆、旋钮与 24 颗 RGB 灯）。 | 极客群体对 BOM 成本极敏感（深知无屏 RGB 宏键盘 BOM 仅 $40–$65），**唯有“每键独立小屏 + 深度 Hook 软件栈”才能支撑百元美金以上溢价**。 | [agentpad13 帖 1][26] / [帖 2][27] | **未核实**（未直接打开原网页） |
| **`r/streamdeck`** (`r/elgato`) & **`r/cursor`** | Stream Deck 15 键 / XL 监控并行 Claude Code & Cursor 会话讨论；及 `r/cursor` 流程讨论 | • Stream Deck 派比价：*"A Stream Deck does the same thing for $100 less and has been doing it for years."*（配合 *Claude Deck* / *VibeDeck* 看 Token 消耗与状态）。<br>• **反方冷水（极具路演防卫价值）**：*"I work with agents all day at work and at no point have I ever thought, 'gee taking my hands off my keyboard and mouse to press some buttons over here would really improve my workflow.'"* | 路演时必须回答反方质疑：AgentDeck 的核心价值不是替代打字快捷键，而是**“人在喝咖啡/看文档/多开 6 个 Agent 时的环境视觉面板（Glanceability）+ 防误触 Hook 授权 + 一键语音口述”**。 | [Stream Deck 帖][29] / [比价评论][21] / [反方原话源][28] | **未核实**（未直接打开原网页） |

---

## （三）Logitech MX Keypad：价格、详细规格与 AI Agent 集成深度拆解

Logitech 于 **2026 年 9 月 8 日** 正式发布 **Logitech MX Keypad**，实质上是将此前针对设计师的 *MX Creative Console* 中的独立屏幕键盘模块剥离出来（去掉了无线旋钮板），专门重新定位面向软件工程师与多 AI Agent 工作流 [30][32]。

| 维度 | 详细参数与实证细节 | 来源链接 | 核实状态 |
| :--- | :--- | :--- | :--- |
| **官方定价与促销** | **$99.99 USD / €99.99**；首发附赠 **3 个月 GitHub Copilot Pro+** 订阅权益 | [Logitech 官网][30] / [9to5Mac][32] | **未核实**（未直接打开原网页） |
| **物理尺寸与重量** | **91.7 × 77.9 × 25.5 mm**（3.6 × 3.1 × 1 in）；重量约 **96 g**（3 oz） | [B&H 规格页][31] | **未核实**（未直接打开原网页） |
| **按键与屏幕规格** | **3×3 矩阵共 9 颗全彩动态 LCD 按键**，单键原生像素分辨率约 **116 × 116 px**；侧边配 **2 颗专用翻页键（Page Buttons）**，单个应用配置文件最多可扩展 **15 页（最高 135 个自定义动作）** | [B&H][31] / [GitHub 技术仓库][33] / [Sweetwater][34] | **未核实**（未直接打开原网页） |
| **连接、供电与配件** | **有线 USB-C 连接**（无无线模式、无内置电池）；配备可拆卸/可调节角度桌面支架（支持平放与倾斜立放）；提供石墨黑（Graphite）与浅灰（Pale Grey）双色；**无内置麦克风、无物理旋钮** | [Logitech 官网][30] / [9to5Mac][32] | **未核实**（未直接打开原网页） |
| **操作系统与驱动** | 支持 **Windows 10+** 与 **macOS 13+**（无官方原生 Linux Logi Options+ 支持）；强依赖后台运行 **Logi Options+** 客户端 | [B&H][31] / [9to5Mac][32] | **未核实**（未直接打开原网页） |
| **原生 AI Agent 与 IDE 集成** | • **官方原生支持**：与 GitHub 达成官方合作，原生支持 **GitHub Copilot**、**Claude Code**、**OpenAI Codex**、**VS Code**、**IntelliJ IDEA**（以及 Slack、Zoom、Figma 等），支持前台窗口焦点切换时自动变换按键层。<br>• **开发者生态与 SDK**：开放 **Logi Actions SDK**（支持 Node.js/JavaScript 与 C#），官方文档专门针对 AI 编码工具做了友好化结构设计，方便开发者直接用 Claude Code 给自己写插件。<br>• **社区 Agent 插件能力**：如开源插件 *Vizhi for Claude Code* 等，可在 LCD 键上实时渲染并行会话的工作/等待审批/完成状态及上下文窗口余量（Fuel Gauge），一键触发确认/中断与 Prompt 宏。 | [Logitech 官网][30] / [GitHub 插件源][33] / [r/ClaudeCode 实测][15] | **未核实**（未直接打开原网页） |

---

## （四）VibeKeys 市场牵引力分析（产品矩阵、Show HN 讨论与销量披露）

**VibeKeys**（官网 `vibekeys.dev`）由开源基础设施公司 **Second State Inc.** 打造，直接源于 2026 年 6 月 X 上爆火的“Vibe Coding 键盘”概念图热潮，定位为跨工具、开源固件的 AI 编码物理外设系列 [9][35][38]。

### 1. 产品线与定价锚点
* **VibeKeys Pro ($39，全球包邮)**：有线 USB-C，6 颗机械键 + 1 颗精密旋钮，PBT 镭雕键帽，免驱即插即用 [35]。
* **VibeKeys Plus ($49，全球包邮)**：蓝牙 + Wi-Fi 双模无线（15 天续航）+ USB-C，6 键 + 1 旋钮，支持 macOS / Windows / Linux [35]。
* **VibeKeys Max ($99，按单定制 Made-to-Order，全球包邮)**：3D 打印多色外壳，热插拔凯华青轴 + 旋钮 + **内置 OLED/TFT 状态显示屏** + **内置语音麦克风**（适配 Wispr Flow / Typeless 等语音输入），支持蓝牙 5.0 / Wi-Fi / USB-C，通过开源终端桥接工具 `vibetty`（及 `second-state/vibekeys_app`）一键切换 `vibekeys profile claude` 或 `codex`，甚至支持离开工位远程审批控制 [35][36][38]。
* **VibeBuddy ($69)**：桌面伴侣小屏状态灯，通过 Hook 原生接入 Claude Code、Codex、OpenCode、Copilot CLI，最多同屏堆叠显示 3 个并发 Agent 任务卡并支持语音播报提示 [37]。

### 2. Hacker News / Show HN 讨论热度与正反交锋
* **曝光路径与热度指标**：截至 2026 年 11 月，Google 索引中未见 `vibekeys.dev` 自身作为独立主帖登上 HN 首页的高分 `Show HN` 记录；但在 **2026 年 11 月 5 日** HN 热门讨论帖 **《Vibe Coding Keypad》**（针对同类 AI 编程小键盘，斩获 **90 points、59 条评论**）中，社区用户 `tom_` 主动在评论区推介了 VibeKeys：*"See also https://vibekeys.dev/ (no affiliation). Has a few more buttons."* [39]
* **HN 评论区核心观点分裂（真实原话）**（均标记为**未核实 / 未直接打开原网页**）：
  * **支持与看好硬件创新派**：
    * 用户 `jrowen`：反驳喷子，称其为 *"a fun, cheap, extensible little hardware accessory"*（有趣、便宜、可扩展的硬件小配件），认为 AI 编程场景正在催生值得鼓励的新硬件探索 [39]。
    * 用户 `skeledrew` & `Liuser`：指出软件工程正在向“不再完全依赖传统全尺寸键盘交互”演进，且此类产品已登上国际主流媒体（如《Korea Times》2026-11-01 报道），键鼠大厂（如 Keychron）也在跟进卡位 [39]。
  * **极客抵触与“AI Slop”批评派**：
    * 用户 `Brendinooo`：直言此类一键式设备是 *"the distillation of AI slop"*（AI 垃圾的浓缩体现），主张开发者应保持 *"full keyboard mentality"*（全键盘深度思考模式）与 AI 结对编程，而不是退化成按“一键生成/通过”按钮的机器 [39]。
  * *（对比参考：OpenAI 的 $230 Codex Micro 在 HN 同样遭遇毒舌嘲讽，高赞评论调侃其只是把价值 $174 的 Work Louder Creator Micro 2 换壳加价 $56 当作“向 OpenAI 捐款 $230 冲刺奇点的纪念品” [40]。）*

### 3. 销量与商业化进展（Sales Traction）
* **具体销量未公开**：Second State 官方未在官网、GitHub 或媒体披露 VibeKeys 系列的具体出货台数、订单量或营收金额。
* **供应链与交付信号**：官网明确将旗舰款 VibeKeys Max 标注为 **“Made to order（按单定制生产，3D 打印外壳）”** 直接发货模式，而非大规模开模量产备货或 Kickstarter 公开众筹模式，表明其目前仍处于早期小批量敏捷验证阶段 [25][36]。

---

## （五）2026 年 AI 开发者硬件与智能外设领域融资动态

截至 2026 年 11 月，公开市场尚未出现**专门只做“桌面多编码 Agent 宏键盘”单品**的独立初创公司披露大额机构 VC 融资（Codex Micro 与 MX Keypad 均出自大厂，VibeKeys 背靠已有开源公司 Second State），但**“AI 原生输入外设（键盘/语音戒指/磁吸录音卡）+ AI 硬件开发套件”赛道在 2026 年密集斩获顶级风投（Accel、YC、Menlo、BITKRAFT、Khosla 等）注资**，证明资本市场对“AI 时代新型人机输入接口（HCI Peripherals）”高度买单：

| 公司 / 项目 | 所在地 | 融资时间 | 轮次与金额 | 领投 / 主要投资方 | 产品形态与对 AgentDeck 融资叙事的参考价值 | 来源链接 | 核实状态 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Sandbar** | 美国 | 2026 年 3 月 | **Series A：$23M**（累计 $36M） | Adjacent、Kindred Ventures 领投 | 前 Meta CTRL-Labs 团队打造 **Stream Ring**（**Push-to-Talk 按住说话私密语音智能戒指**）。直接验证了 VC 对“办公/安静环境下低声物理按键语音输入硬件”的高估值认可。 | [TechCrunch][42] | **未核实**（未直接打开原网页） |
| **Era** | 美国 | 2026 年 4 月 | **Seed + Pre-seed 共 $11M**（含 $9M Seed） | Abstract Ventures、BoxGroup 领投 | **AI 硬件外设软件编排平台与开发者套件（Developer Kit）**，赋能创客与硬件团队为戒指、吊坠及专用外设构建自定义 AI Agent。验证了“硬件 + 开放 Agent 编排层”的平台化估值逻辑。 | [TechCrunch][43] | **未核实**（未直接打开原网页） |
| **Pocket** (Open Vision Engineering) | 美国 | 2026 年 6 月 | **$11M 融资** | Accel、Y Combinator 领投 | 磁吸铝合金卡片式 AI 录音与实时转写外设。展示了轻量化 CNC 铝合金桌面/随身效率硬件在主流美元基金中的爆发力。 | [TechCrunch][44] | **未核实**（未直接打开原网页） |
| **Acti** | 新加坡 | 2026-06-30 | **Seed：$5.3M** | BITKRAFT Ventures 领投 | 主打跨应用系统级 **“Agentic Keyboard”（AI 代理输入键盘）**（切入移动端输入层），验证“输入法/键盘即 Agent 调度入口”的投资主题。 | [TechCrunch][41] | **未核实**（未直接打开原网页） |
| **Peripheral** | 加拿大多伦多 | 2026 年 | **Seed：$8.7M**（累计 $12.5M） | Inovia Capital、Deloitte Ventures 领投；Khosla、EF 参投 | 空间智能与多相机视觉软硬件开发栈。 | [BusinessWire][45] | **未核实**（未直接打开原网页） |
| **MountAIn** | 法国 | 2026 年 | **Seed：€7.3M (~$8.3M)** | 360 Capital、Supernova Invest、C2AD | 面向低于 $10 超低功耗 MCU 微控制器的本地边缘 AI 软硬件开发工具链。 | [GlobeNewswire][46] | **未核实**（未直接打开原网页） |
| **Omi** (Based Hardware) | 美国 | 2026 年 | **$3M 融资** | Tim Draper、DropJaw Ventures 等 | 开源可穿戴 AI 硬件外设与开发者生态（承接 Limitless 被 Meta 收购后的开源硬件社区）。验证开源固件/插件社区对早期 AI 硬件获客的杠杆效应。 | [Dealroom][47] | **未核实**（未直接打开原网页） |
| **Wispr (Wispr Flow)** *(软件协同标杆)* | 美国 | 2026 年 | **Series B：$280M**（估值 **$2B**） | Menlo Ventures 领投 | 从早期硬件静音腕带转型为跨平台 AI 语音听写层——目前正是大量 Claude Code / MX Keypad / VibeKeys 用户绑定在物理 PTT 键背后的首选语音引擎。 | [TechCrunch][48] | **未核实**（未直接打开原网页） |

---

## 编号信息源列表（Numbered Sources List）

> 注：除搜索结果正文已明确暴露的原始直链（如 [5]、[10]、[38]）外，其余链接均为 Google Search Grounding 实证重定向 URL（点击或解析 HTTP 302 即可跳转至对应媒体或社区原网页；因受限于不使用终端/抓取工具，所有未直接打开之网页均已在正文中按要求标注为**未核实**）。

1. OpenAI — Codex Micro 官方介绍 (`openai.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEEXx2n4jYHbMDXB7As-yBsXWxFmIp7UByXwQPAeEAeJIHoK6c7Nt8-pO_7FV56_NZ7stwwFUUynIAZ0xyHFGFwcHgTp430IFfOJvnyV7Lws-RjVbBJke6cRD-jkfTl3ESDJA==
2. TechCrunch — OpenAI Codex Micro 硬件发布报道 (`techcrunch.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQGjV8KX0IRMv6Rm-ZP0d9V36IQ6cTdRlSNR1C5Ou92p5d76FShyJDhHIm--2rgslfqZ-sGLc-vE3C8-QTCHPDM6-zpUrqtAn7vKzv1pZG5053BKQs7Ydsz8Cu_scanZ5DaB8uvhx20xcPqwgziLDEjs9EHmu9ctMyZ56aLewVBuuszHpnY27Vh-H4WBqt4fkm-lKJgTstt9aK4N6w==
3. Tom's Hardware — Codex Micro $230 规格与市场反应报道 (`tomshardware.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQFpnv_VeDlQKA25LI4zjQIbShrZsXW-ZjQrI3RgYQuHkblZgPsRGErG-q-aO8IdMVtQ6DmdFOZd5KVo9RVdgulXpoFHEl4yN71aNcBc5v98xeV4Dn1UKCcPv1LH-iVV91rhTz3e6IeuEiUnOZzdpqMQZwv7InH0vK8pQVEPc-fxv4BEf5JYZfoAwRfFV4B40MSiO784I9mdu3h869rioHD1360U_vaJ9BezJnrPkvrQ219-R-24QGeuZGSaOsxDHpS7YnQQYDfQ8ZDAp6Nsdat0dwDaXQhGnlllIwcqTPXGjm2I4gLJ0Z0wTFkvmEEbiuTFQw==
4. Work Louder — Codex Micro 产品与 Agent Keys 说明 (`worklouder.cc`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHjMSHmw-HKy0vvhhIJeJBPf11vgFGWG7LGBjd1ev9z4I6MVaiV6I1f-h0OWZWAW8krY77Jn-UxHvOszM7__AQsEzmjFt1C3Pa_EJubGejdFnrux4CLkmWYNQt7
5. `@OpenAIDevs` X 正式发布帖直链 https://x.com/OpenAIDevs/status/2077425991790870644 及关联索引源 (`youtube.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHZpaxyxKIuZJuAU3mq3OK_-LleLrOq8ZANgcqv3OfZ4vOOtV44ux6CQIywVY95_E5jWekO3KkhCE9HyHnRkxW8kXJkHwJl7LDvTGyZuWSPOn2G6On1ts2ZP-ZwoFCXUjVq
6. Mashable — 引用 `@OpenAIDevs` 2026-07-15 推文与 Reddit $230 争议报道 (`mashable.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQFrQGrX4CCyNVLXcphQWyl0EPkgGWLgQ3pDijs2kACP6nHGzMUGUt2ePdFyn5a4pMsUjvZCdcBntBpeW8Mmucnoj9Wc4LZGzNn_4AkOuIax3DLbeBqhKUwWQnu871WiPRVRAN0KVu9EUbZpfhq5P-an9Hgm_5ErVDFm5GagzlpjGiI8jM7OK-mwON9NboPqmm1JAT2SrSFPHCssiwbNH-L7JaZazvTa6IQ11a8o
7. Gigazine — 引用 `@OpenAIDevs` `kbd-1.0-codex-micro` 推文报道 (`gigazine.net`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHkpfauZNKeGvhQ3mB7cOFkHR7QS4w2MRX3FKo7bqwvmnqjvG3R6wmVlY0odYvz5Ez86RKkK9p1d-x_x0IgPN4Lq8UB6kdxs03FumPVA_ubWdt-JJS9vpNXPe4y39jk7n7pf7v7cSXBfvSUeBTCeoRrlxdp
8. ExplainX — 记录 `@OpenAIDevs` 2026-06-29 预热帖首日约 100 万浏览及发布详情 (`explainx.ai`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQFxhqhDmgUFiA_gw681FAuEf7FvVytwBspq3HtBPvLiroeI34ztakv-c2Dzyo5_cway6isuNkCIZ2ijp4Ta6349x3oG6PztN8Zsl_rnAXWIOcIMk-3GppzQ5Hxjk24RNt7vtO-3tfiod66n9xpAT6e5dN9TQHXDiijGQ-ivmZgn
9. VibeKeys 官方博客 — *“Everyone's AI Imagined a Vibe Coding Keyboard. We Actually Built One.”*（2026-06-17，实名归档 `@fabianstelzer`、`@shiri_shh`、`@Salmaaboukarr`、`@mattrothenberg` X 概念帖，`vibekeys.dev`）: https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEa9i9N8ccJ3Xk7kbbBLHEaCkh8rtHuBc6k5qin6TH-hj57meWBa1UwG0QaqonppnfC9Kq_hwttkGsSrXfJR6BLpUOU-kfp-t5X13WSFJbTnFwhfaNhNtWPNWkS8rWL1H8kHya2T_2qc-oBR2D_DImmnbQm7wZ8cmftnydDhA==
10. Paolo's Blog — *“A physical button for Claude's permission prompts”*（2026-05-12，直链 https://paolo.blog/2026/05/12/a-physical-button-for-claudes-permission-prompts/ 及索引源 `paolo.blog`）: https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQF8y-mG16FvTHD2Raa1ICrn8f9zaUE0WYmXc9pTRs-HqScjCxxnx7MygpvGtvabQICsDtS845fPgBg3cOJkZEfSuN5VSECIHg6wGMgdOlmXzz0gkKRuSMISVybmA5WghZpo1WSJp0ql57eC4b04u_kwQ7AQUXRogA6R
11. Morningstar / Logitech 官方新闻稿 — GitHub VP Martin Woodward 评价 MX Keypad (`morningstar.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQGd1z78MbAH4B8Il9ze_g1zq1yCy2RQeF6ClNzwELXjE6IobUAq1_b3uPXQEhvDpQHteOke6_v-XjO7k3Aqtk2cXwBoslPNjZyAoOInZnKXDV73KtX_CwNVKQAcE17bAHcCHOHn_aM5y1I_75DL1u_PmRO4y_0u2i_4BvAhQaJOh0J-YEeqw2JPfhm9s2WIsMm-ygOWaNnH9lgW0e-qHHy1EKicasRe037cjYF1Djz-cCgEzAESzvv6o82Mo5-4LF0fXhhVzbCOoS5hKQ==
12. Ulanzi 官方商城 — AU05 Vibe Key AI Voice Input Keypad ($59.99/$69.99, `ulanzi.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQH2v4M-BToS9Ex5Td53Ywj6Rnv0Z-Oyw6F-5Prm9kYyo6YGZXilgwvPKflHmtNvPWuiqtI4qipG-mzGo2fMcteEAmEqcmfkTrKRg2gn2pHg5EpBjfFi09bxCqeCB50gzKfuU7rMHA==
13. B&H Photo Video — Ulanzi AU05 Vibe Key 规格与 $69.99 定价 (`bhphotovideo.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEjljOkRA0KRctXjON6DE90jsu-Lg9bM52ZtoVJiHrji8FfLTBc1gNiMYpHJLrtktSSL0_CoB-hi3nA3dixhjozuqgFHKIivguBVAinYfmmssUVTBilVpbdxYW6Q28UCiRZcVg533M1-CLvMmicZcPnVTQCNhDoGny2Pl7tIC3qDJD4yF_ujtua5B4=
14. Second State 官方网站（VibeKeys 出品方，X 账号 `@secondstateinc`，`secondstate.io`）: https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQF_jgFQg6z5fIVkUxi-34dv7kBuSMadzb1pxqhimTfhC5QWMo5p7Ks1LJHU2TBKZ9QstU2IfFPDUMR7l_kHIiMWkGBTf9zmXDKSDeZl1vWgGrxXXbCncCHdQng8KO0U_wMfZ_ATQ2AxZ7R6
15. Reddit `r/ClaudeCode` — *“I barely type code anymore, so I moved my day onto nine physical keys. Useful, or overkill?”* (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQFPqLYbJYeu-KRoUz2WZH48v6E7YbzdQCzii3McIDM4CcNz08N0I2eVjo0jmhun9t_wifG7Ng-VEpsFt4FMbrTXIhl94a8slB728LUNjL6VMWxC-j73rnFFLEpvoq_fSnjaWngW4vqqt-2HvxHXrbLPHvASKQjLlRHtaX3rzHd1aV2tiqfOw4CS7etbKQ3wuPXnXph6Y8-BESP-ZsgG
16. Reddit `r/ClaudeCode` — *“I got tired of checking Claude Code terminals, so I built VibeDeck to put my sessions on a Stream Deck”* (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQFGQbUc_ZIPEA0T9z1CFwGlG4Zpq2ZpZ2VY2OtYCl9D62MVta7f4i97cpYXe8rBM0GEcSvPt59-FO8i3p6MBUeI0PdQSMF1aSP86jC77t7rmNZeRVAEwsmWys2RYTlHPSlDVgGuSQXGtq8_DHRZQR9YolO8DLpBca8gyQq-yLMl9004fhOH5lAmEz2GYQYgeksyGRzYoW2sojXKEno=
17. Reddit `r/ClaudeCode` — VibeDeck Swarm 键与 $5/月定价讨论帖 (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHC-vgIFtHTrkbwVIbBUgjimORG4kVwqQ_7VU7BNkTQLa62TYPB3p2CzLGXfb4X4aMxhEG1krgKL0zzMMFmKcjuKFky6s3LDbyGiZKt8kkOANnb673Y0Fp36oCnjaA3IjFvQtM0AEZLS7gH5D3EtC6WAS_FcwQtKz-L5GVyXV-JmHOjoLsWv71nte5_1QBs1tiAdDtyhbqYzEJ7FGM=
18. Reddit `r/ClaudeCode` — *“Claude Code with Stream Deck, anyone?”* (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEb698e7sIbMCSfqF5JNl3U-5FUre7yhzn8_L0tBHT76Fx24nmNQZQ8CrGCfiZPlR_pxmcaMR4RnWcN87W9yIZkEx5fyEJsXFNkB6ehvZ7fzzgErs743gqh80V-kj_996qu-Zibf398WEZnd31_KoAA1evpho6PV7lpZ6fXhBlVdIeu8zgIs_WQ2QRRtu-VYA==
19. Reddit `r/ClaudeCode` — *“I turned my Stream Deck+ into an AI Agents control surface for Claude Code”* (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQFRmMnDGleI16R8M6Q8f_nhDlenZS0JwQic8N18AvYdFzkt-yd6BDjMmTcBBJygNCGumbZcKZJGqJs9Fq7t-93zhkSQvjaCRbLmpPMx-xWUQYWKfT5wS2wdNBZDzIiIDX0BT44aJx9g3sUCe3gHoMWCQb7uM47V4DsrBwAqJB8npzIHVz6PoBHhXq0iMRyryCfHP3pghMkml7puVl4=
20. Reddit `r/ClaudeAI` — *“Stop alt-tabbing to check if Claude is done — I made a Stream Deck button that blinks when it's waiting for you”* (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQE634BRTLhgSqyY7hrqIk_hiC3VG-Xdy80dYmO2Bhy6uVDCu8Cgp47mxAZjBmIIAYpS__HqCPWUHP2i00CHwNBPfrxmGDkAdlRX_cnYkL9pC3tviH2iv70ligp8XdMg633tu0OBnL6rgx4RFNqmJgFIrO4yp7VKBlKKEVCOi8bOc1LHudDtcPm-m4kgnvDBIHzinGPmLFiqk8HSKg==
21. Reddit `r/codex` — *“Introducing the Codex Micro”* 及 $230 价格吐槽评论 (`u/Downtown_Method5736`、`u/MrRubkins`，`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQG5fBpspOvnRhz_HFXNxvV4uUNwGcgTlWrAxDdGQFMF5v5B5qJ1RwvLHcICcd7maK-Md8vGbijDn2qs95LCfDZaO7eqfs2oOnGiGsmRusv5HcgNySKoNmaRCw5BHeF5ELe0wbvOOc_CPAo6AGNoPFRyci1fM_1mquYRdgc6LBlC2F-og99TjBXvcpYZUm2O2SWmFFWnWmbs
22. Reddit `r/OpenAI` / `r/codex` — Codex Micro 真实买家上手评测 (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQGeCtmF4TbZyGItQ9bOdzF7Cb9Wyj2ChblA3NoOGnN1sc8RRFLKptErE-YuwxpMMT-1n-_a8ygQXK1E_SyCTLwm_qIhXKN6o_WOdR_4IrDJWnUU8F-MQNjGTDJ2TTdzuwIQyhGmqwVEtGqlabNU5zNOnN60PRVgeiz4Cib_7QkMDDqWdg==
23. Reddit `r/codex` / `r/vibecoding` — *“I couldn't afford the $230 Codex Micro, so I vibe-coded a digital one that runs on any phone/tablet and actually talks to Claude and Codex”* (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQG6nf89UBPsdnF7QpIe8FWDANS1qvEIR42moGhY59KdLz2jZMvC7VB9g64dRLqXDUiDolno_xeyIABFuGbQqN6BA6X2oxz8_Bvvn3Uk4u928QMj88xLmEP0Dpv5Gts9e9OaodDLda_fIaYk1E_hrTY9vzkrS7EOBwtHbDl6wNM9IRBJm_GShKloWF4DtBoNXMQ=
24. Reddit `r/vibecoding` / `r/codex` — *“I build VibeKeys — after the Codex Micro reaction in this sub, here's the $99 keypad I've been building with a Codex mode”* 及购买意向评论 (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHdK_tp2LOveP8_KR5Uss2To-uFdkOjkieiRTOAgGuzGpCBE34bErWciaYjyFtVH7vfztODgRY2rG1MqSfdel17AJW0WdKHAiI8ejv-ERxhYWVzuh6kA90u4kZOCQmQLk4x6u9grWbcQRT8E9a-NMaJwnLGxoV_h7Qb2_o8ECee0QYOSUnzwk-4wll9Cx7NVRz1Ub4MdRM=
25. Reddit `r/ClaudeCode` / `r/vibecoding` — *“I actually built the vibe coding keyboard. It's not a meme.”* 及 $100 3D 打印外壳质疑评论 (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHQ-dhBsxX38ynFg9czsBX8-mhaZ5mvtRB75vnyJpfJLgOF97tS-z1-vIV1ADV6ZJufeAcnnmQLgcx58EC8CsycBzai7XNW1lzv9bccHo7bR5BYv5t5x--ZwWzFCrjvLOIPWa7XR2uByvHnAy9_uVm54h5FFN9QA5HChyAcgUKOlYGAjxKTQ-SZ4yFZnMkggS8qcaMAM1A=
26. Reddit `r/macropads` (`r/macro_pads`) — *“agentpad13: an open-source macropad inspired by the Codex Micro”* (~$65 DIY 对比 $230，`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHZEwu8TdtJSIB9JjhlUimvwOsDUBK-WgCL7jVhtF0UOx4-FnodrN_5lSlVJ7G-E9st9a6Pb0nFcqR2d1Jngmrz7fcLTiy29UblmbgrLVcLwDb_vo6cuTwy4FLQWC_23atUXwfjuJIXutDigyFCIFneTYt-8zIu4gNpQnXHCsA4_hwcD4zsksvijZ4Hs7-dTpMWd61581NkGivga63O
27. Reddit `r/macropads` — *“AgentPad13: Our $40 Codex Micro clone is officially real and you can build one too!”* (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQH1FjXCvLmGRkWMzqPWPlKzM-hbk6teMJTgiRfdZ2Z7Qo2UGsd2iUHG0W1LgI8X0exj7SSEX-kbeiAjo-uzG7f-2SIGi2I9FUbif94ICOQOK3z6HpiAJiY2_zGWIWUZiQ==
28. Reddit `r/cursor` / 开发者工作流讨论 — 质疑手离开主键盘按额外按钮的反方第一人称评论 (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQGdqWVHOQIvK6iIhr8OUVOWQNKPKI90pSOhZDxT--WiwAsdPOHAtNWzBX5T9qp18JeXSoDi57E9my9ncoFYGHQdDsF91L77UTZsBdzN9tDTxeWyboBMw-iK5yvkOJdg7ogYvrLeFm57jXev2Mba3WAydwcK4Ts9m9uvhRK6wSKSkAbA-ZuXxs0TJ4jXzNfC9QVAH-PJMVkOCxokbh_hZ4I-EgqtESKM
29. Reddit `r/streamdeck` (`r/elgato`) — Stream Deck 搭配 Claude Deck / VibeDeck 监控并行会话讨论 (`reddit.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQGmVU5jPyzUQrMIX8vyMOZGnABwZga3l7zF1-W-m4dkv_Lsx0q9JZ5oATgXvv3YFPd1HZ7fW2RcyyvQhkDb-_KyTl-wQOIkFGG14gM_kp6PkfXFsneRjAUxkEs817OzPbbhT2VdxeyvljltzrYXJNgpT14ntXJo7FikSzY6EJeA04FKrmKdAVZZV1TtkI_5i23wLTdkfRYY
30. Logitech 官网 — MX Keypad 开发者与 AI 工作流产品页 (`logitech.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQETNBpCjs8xvggtW8t0FUJqNXEkf1PQrw8Ecmd5XbM1yGDGuGCdbM34YtbvKt0qPV-fMwybTYqWA2WgTWglkHvAs1eb-_nmduLakh8T3CJM2R1a0WhF-Zz-2t5dRDD6cfHLxOLhwpoIMeeM9TFcg873yxJtmk_Ti0-2cGxiZHPLaCkNtbqF9I_4xdQKVt1TBya-bknh-9lHeBPR-efhazQCb4OY74Nd69fJA9-IaHXLgXBnDLUUfn-TKLn6JOtW1jf37dLP9ZE_U4g=
31. B&H Photo Video — Logitech MX Keypad 物理尺寸与重量规格页 (`bhphotovideo.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHmmTu3Vx3yRIx4S_AkD2Vl8hCKAUPM3AXVd1yQVuvixPqayBz0CNUoa0Pk_xsDaOgEgkZ5PRIX0RfmPrGXCcdMtYismSh4SZ9U-dT9sGOSlBnayxc1dxV7lwISJYttgUBnfoAe7O_vR71YU7kalayR19J88Twj24AR7OPJ8Cmzc3Dhie_0fg5JvdiMOvdetUupbvWy
32. 9to5Mac — Logitech MX Keypad $99.99 首发报道与 AI/IDE 集成解析 (`9to5mac.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQFhfXVCotuTvcuEC3NkDHc-Iz20kyM7pbVNuOYJ7NmAUmRDra0im9595hku99xrZ1EEM51djZHevVtS2uumgdPjIZRnZKaEBn4w1CICvCwtjQJIAueLwunPHP0m2l7Tz4Yn6OwzZpl7q_DYiSVqDaOlMj3GBbkvGsxicpM23976mcPOJ37XS0eRqFB9BryRMw==
33. GitHub — Vizhi for Claude Code 插件与 MX Keypad 116×116px LCD 渲染规格 (`github.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEYc6SniCkbN9U1GoWHexO4rBgB2q0K33HK45d9CCtjzItd305uUp6OiXDdL9ESCJ6xE9bxUFjUBqk5RVKmZ9OfqMzup0J9YGbI_okcDU5HiPi6IWyS3p1hwZmVC71-5sLr5uTPGZGNYTUGOmtl
34. Sweetwater — MX Keypad 双翻页键与最多 15 页动作配置说明 (`sweetwater.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQFGBrDQaE5N4KTZcyFGTy9xXZ1irNie3OmmAiJMJhkqCEBLiZXT2DKbxugvA3tTLhiQyuFa6wODxgr6_UAC-am-UWYWZ3KkQU-b3Nilhj7nxjmFtb6FdfKMd80jJxey7ku1nviuBbJ-w5WyKn7X3FzRUT9UxTdn8u6LfoA-l3cuBd4pB6aJ3A4Td2Y5ww-FDRuXs0_X2CY082bNs-v-0C0cP0Dc77ajLvnkEl_lN83kWw4=
35. VibeKeys 官网 — Pro ($39) / Plus ($49) / Max ($99) 产品矩阵对比页 (`vibekeys.dev`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQFJTwhPPuBw7qLawE4GfvKsyNU18tAojc5vFoSIExZoay1FThIGkrWqzPZcjcpY7O36tkEYKgTNEO1ZZg9prHhj32BA9F1mEub-Jo_xBzVKPKuro8lafSqNMWTwz2OSVIAFI7XOjzECMlHWlMiIDDc=
36. VibeKeys Max 产品页 — $99 按单定制（Made-to-order）说明与硬件规格 (`vibekeys.dev`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQFkXKfrbxl5zQWILh4GIr8fUNMJZJ53OtVVRqyBo4KfmyKu_tocmlgh4s6qs2obWtxH5DSMgKgaX0cfj-ZpD0-E06RXuO0gp2iiwIq2IqpkUi19PGjZPsmDJdZybQ==
37. VibeBuddy 产品页 — $69 多并发 Agent 状态小屏伴侣 (`vibekeys.dev`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEsoJGy9w_Lp4VUz1_kd86xaXPdenFN8Q1-eBh39VbGpzzwy66e6Dxv3dsw3KRfkcnLgUc1f4712j6o2v8GeA4ZRTQ3KYR7Imt8-_cmdl-f_A==
38. GitHub — Second State `second-state/vibekeys_app` 开源仓库（直链 https://github.com/second-state/vibekeys_app 及索引源 `github.com`）: https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHMd5klBRWjmLGVcGh2Kf_wPX_s2MDOy3-p68iGjyqKt3clSm2ZuGJV3pSgRHyVEOoGLSahWNa5ZOP4Ks2EJbl4UVgyfxMU_aRdv9LCi1gIDdH8K5MTKqMO5vdu_D_2ZXJyuw==
39. Hacker News — 《Vibe Coding Keypad》讨论帖（2026-11-05，90 points，59 comments；含 `tom_` 引荐 `vibekeys.dev` 及 `jrowen`、`Brendinooo` 正反交锋，`ycombinator.com`）: https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQGegbmmX8ANJQgc0hxs8svLwV-byytSEVRXj5JQG7YqvtQrIZr0qePeKw8voOz3CYAmLPIjVhKEhmxQvl2csRTushuxD_cLeUfcueDWK_5TVrhS7sINaybwoo4gStcVqryodDI=
40. Hacker News — OpenAI Codex Micro 讨论帖（$230 对比 $174 Work Louder Creator Micro 2 评论，`ycombinator.com`）: https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHHruprWtVv9sjtm1G3Xl-GI3wU3gsWd7xPcraawVvnpOaiiV07rwEwwkGYsNKb4bQ5S_jI9GPwYc67YeGblwwkzpgZdNzIISXxC5Tp8nlswH_NV68m7jijaaLrdokZPoQ1HQ==
41. TechCrunch — Acti 完成 BITKRAFT Ventures 领投 $5.3M 种子轮融资报道（2026-06-30，`techcrunch.com`）: https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEiEruxu8gbp6g8cF4wYVl7qLiq8tKIveUj55nzYr4LSPWyRChmYd3wfolnKFEIrbYYyPI86TPivMt58RS3NdZL0n06weOP83vkOoFlYqI6Ky1VYQKGI9Hl2QWsW_kjvKcvmVPIClIpKsvilPxCVzK9cqxdBjAnYKVJ49glXZEOIb6wHySu_Dhq7GmLRceem9cLvw==
42. TechCrunch — Sandbar 完成 $23M A 轮融资打造 Push-to-Talk 语音戒指报道（2026 年 3 月，`techcrunch.com`）: https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQGMMSlBvnuCpzyT_EFCBJwzTco8mVFGImVyAG43p800RCQanYQyNrMzt-6HQrcEacmHrxgB_8VOUChRGr7WCVEFVhTLsNDYO35Gr0xIH3tloC8D1mQYQezgacXXHDHK-nEGEsCU7KwfHy8GabfNHCRPNPszIObIyuT17gszyc50HWb4jTTERL12Bo-so_U43hQarYE2AYYMFpw6m8dEFHJmEQtG
43. TechCrunch — Era 融资 $11M 打造 AI 硬件外设软件平台与开发套件报道（2026 年 4 月，`techcrunch.com`）: https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQFXZ86VM_lPBM_Ynnl6v36M8G3n7k-6idvYWrtUVYLsocW4Zh8iZJAESEAJxeMoKwwSK6000ZGjeuQA8ON4JtaRHqfZs3h4hmwg9PqfNFqRDdQL0s3OE48gKjpj7y8NsKIKhr5p-Pskd0qi6zFYGH_Un2oll0OyAKwkzWZF6q6gkuthl-kTfE4Snw_4GJAqs0-FCHPO3c5raWdRCqw=
44. TechCrunch — Pocket 获 Accel 与 Y Combinator 领投 $11M 融资报道（2026 年 6 月，`techcrunch.com`）: https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHtWfjNL-Y_NUyUjhisD5a1xf1N3PRnn2wckSxVcw2XayNE1QFF2Ilw2MF96bvgNZ7V6s_9kiBG5ybznMP1DYo4j1EfPKtXtcfZ2VRln0nae2AFtTXupYDWa-5VfHfGvEsKBwRdMubbPWReidri9d4OBbBy8WKCRBTVFPAISxvgtvjzmZibxTeQDrFlSPPq4Vw438SSkWjCeAL3NuuI
45. BusinessWire — Peripheral 完成 $8.7M 种子轮融资公告 (`businesswire.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQF7b7PxLg3W39SCRylGdmR5x3VsN-YcxNww75u4YBfHWwgkAG1blO3nLTiCaZqaSUQFfc6XBy1D4ozposqZLdkg_F6RGkekytX2FTAroUCNk4csXYGVdFJ_T3Tq_tbxtWQgUNTQbqGrEU1grX_sWbQoXyvjUWtcQf8rrxccP97Q2NZE1O7bVYwj5fQNo45OA-PXJ7oe8vMd7dWDUKjovFVzDbJDAe0dUPRrhD0qZ3fcGycU3S0KAWY0XZDkQgFHntfgmdlsvlJIsQs0g1FKCxC0ilj_L33ZQV0ajDW-y8n6tz3yDJgScRdcyw3oOd9obF0=
46. GlobeNewswire — MountAIn 完成 €7.3M 边缘微控制器 AI 种子轮融资公告 (`globenewswire.com`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHUiv2m3gkjTpiqbcYwmMnSa1cNbrhJaglpZufy5Aw5YmNJIkMCcHPHiB73Nwyb45MzlReVwu2qDriHfNLdKlqGSciwR7B9PIdMeTrmDo_ZQ8ShnpptunW7HqoXztYH_Z2picQm8AYDKHqlXUrgMfRRYYOAbWJKkbrtzgGTZEXP7G2nyqb14D-_YXvJF4tL0tr4pNMMl5uVGdDcq6Q6dJbeKsr1JlmDiZgzhr820iPFpRBdcLwLbaKgBEbvdg7bVllj8hl9RDvbZD0VFizmEhmyFD4XsP4pBhWspp9l
47. Dealroom — Omi AI (Based Hardware) $3M 融资记录 (`dealroom.co`): https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQGICICfmw6myFewaMxsxJB9xitlvxqq03PN5PiNyZKp8inMysB5oLIZIo09FXqfPQChv0iCkRYzu_3Jcbfwtks-G2FaXq7dSQ3jlMXn1xbHq06OkNCWYCJpq0cEQEiW8-cmO6slexkZtZPo5OQXNtxWTLhLxwW9mpBxoY04E9fAl2AmHZFjploZKGmsQYUNPtMiqRK0uep5B2dVkJSLEg==
48. TechCrunch — Wispr (Wispr Flow) 完成 Menlo Ventures 领投 $280M B 轮融资（估值 $2B，`techcrunch.com`）: https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQF_9DwFRhoQX0MSn4s_fc2YzNHaYo2TSrWJkQBKcEjONTenj_AAa93pWs3bQs82pcK86ocZJ5enJ_VnQpH79hGb4WUS22Tf-6Ij3pxj3EUTpZk0lJp8KbGX2lXQ3xsx_c0O23S3Plh8Q4XzSm91jRNG5Gb5kt4oKgoJeUZwJHj3Bk1sxM_Um6q9tRqZC6cTNYaLdpfnFmM=
