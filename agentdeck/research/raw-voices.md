# AgentDeck 用户原声调研（raw voices）

调研日期：2026-11-17。所有引文均为原文英文，来源 URL 紧跟其后；引文均 <25 词。
引文只取自我实际读到的页面文本。

## 0. 先说结论和方法局限

**一句话结论：痛点是真的，而且已经被商业化验证；但"做一块带键盘的硬件"这条路，已经有 OpenAI（Codex Micro，$230）、Logitech（MX Keypad）、Anthropic（官方 BLE 开源规范）、Elgato（Stream Deck 插件生态）占位，并且 Claude Code 自己正在把"批准"这个动作消灭掉（auto mode 默认开启）。** 这是一个"需求真实、窗口在收窄"的赛道。

**方法局限（请如实对待）：**
- Reddit：`old.reddit.com` 被 WebFetch 屏蔽，tavily 对 Reddit 帖正文抽取返回空。所以 Reddit 部分只拿到了搜索摘要里的标题、赞数和零星评论片段，**拿不到完整评论区**。r/MechanicalKeyboards、r/macropads 没有搜到有价值的相关帖子，r/streamdeck 只看到 Reddit 帖标题。
- X/Twitter：这次没有成功检索，**本报告不含 X 的原声**。
- GitHub issue 的"赞数"来自页面上的 Reacted by 列表（只数得出下限）。
- 有几条"原声"来自厂商博客（Zentor、claudefa.st、Elgato），它们有营销动机，我已逐条标注，不当作用户证据，只当作"产品方也认为这是痛点"。
- 没有找到任何人明确说"我绝不会为这个买硬件"的第一人称帖子。反面证据主要是价格嘲讽、"这只是个宏键盘"的评价，以及 Anthropic 自己要取消批准的事实。我没有编造。

---

## 1. 痛点聚类

### 1.1 审批疲劳 / "又要把手伸回键盘说 yes"（证据最强）

| 引文 | 来源 | 信号 |
|---|---|---|
| "you have to reach back to the keyboard to say yes. Again. And again." | ClaudeButtons 作者 Marc Scibelli，https://marcscibelli.com/experiments/claudebuttons | 作者自己做了 Stream Deck 插件并"SHIPPED 2026" |
| "asks me, for the 40th time today, whether it can run a command. I glance at it, hit Allow, and keep moving." | Atomic Object, Rob Bell, 2026-07-07，https://spin.atomicobject.com/permission-fatigue-claude-code | 长文博客 |
| "you find yourself hitting "approve" the second the text appears, long before you actually could absorb what it said." | HN 用户 Kim_Bruning，https://news.ycombinator.com/item?id=50408126 | HN 跟帖 |
| "if I had to approve every single step in the process I think I'd actually go insane." | r/ClaudeCode 用户 Bed-After，https://www.reddit.com/r/ClaudeCode/comments/1xexhwf/do_you_let_claude_code_run_without_asking | 该帖为"approve 还是放行"讨论帖 |
| "Approving everything trains you to hit enter without reading" | r/ClaudeCode 用户 Far-Caramel-7463（同帖，他同时在推销自己的 OKed 产品，需打折看待） | 同上 |
| "The only key you really need is "Allow Always," but everyone jokes it's broken" | r/ClaudeAI 玩笑帖，https://www.reddit.com/r/ClaudeAI/comments/1rru8zw/just_picked_up_a_new_keyboard_cant_wait_to_write | 搜索摘要片段 |
| "you can hit them with your thumb without looking at the screen." | zephel01 用 Codex Micro 改成 Claude 控制器，https://note.com/zephel01/n/nd6b67d2d24fb?hl=en | 这是最接近"硬件确实更好"的使用体验证词 |

**量化信号：**
- Reddit 搜索摘要列出的相关帖：r/ClaudeCode "The permission system is exhausting" 76 赞 / 42 评论（https://www.reddit.com/r/ClaudeCode/comments/1x7ix85/the_permission_system_is_exhausting）；"do you --dangerously-skip-permissions or not?" 72 赞 / 188 评论；r/ClaudeAI "How to stop Claude Code from asking for permission every time?" 54 赞 / 87 评论（均来自 https://www.reddit.com/r/ClaudeAI/comments/1v9nvjn/skip_permissions_people_has_it_ever_actually 的相关帖列表）。
- Anthropic 官方：用户批准 93% 的权限提示（auto mode 工程博文，https://www.anthropic.com/research/claude-code-auto-mode），后来更新口径为 97%（The New Stack，https://thenewstack.io/claude-code-auto-mode）。
- Medium 摘要称：1,053 名付费测试者里，面对一条明显危险的命令只有 143 人拦下（https://medium.com/data-science-collective/claude-code-is-about-to-stop-asking-for-permission-90e64a2181be，二手转述，原始研究我未直接核对）。

**对产品的含义：** 痛点既是"烦"，也是"安全风险"（疲劳会让人闭眼点同意）。物理 approve 键可以解决"手够不着"，但**不能解决"不读就点"**，甚至会让它更快。这是个双刃点，见第 4 节。

### 1.2 不知道哪个 agent 在等我（第二强，且有直接的功能请求）

| 引文 | 来源 | 信号 |
|---|---|---|
| "there's no way to know which session is blocked waiting for user input" | anthropics/claude-code issue #36885，https://github.com/anthropics/claude-code/issues/36885 | 2026-03 开，后来被标 stale，"Closed as not planned" |
| "The bottleneck increasingly isn't Claude's speed — it's the human noticing that Claude is waiting." | 同上 #36885 | 同上 |
| "Claude just sits there waiting while I'm doing something else, not knowing it needs my input." | issue #13024，https://github.com/anthropics/claude-code/issues/13024 | 页面显示约 81+ 人 Reacted（10 个名字加 "71 more"），多人跟帖 "same need" |
| "The user has to keep watching the terminal to know when input is needed." | issue #45734（VS Code 扩展），https://github.com/anthropics/claude-code/issues/45734 | |
| "one of the sessions had been waiting for my command the whole time — and I didn't notice." | DEV 文章作者 Younan Nwesre，https://dev.to/younann/stop-waiting-for-claude-code-get-notified-when-your-prompt-finishes-4b4a | 个人开发者自己做了插件 |
| "instead of switching and seeing, oh, is my prompt ready?" | Dr. Thomas Albin 的 Stream Deck 插件视频（转录），https://www.youtube.com/watch?v=zNS4HtsFP3E | 1.5K 播放，他把状态做成 蓝=工作 / 橙=等你 / 绿=完成 |
| "After a day of that, you start ignoring them." | JackRostron，在 #13024 评论里谈系统通知，https://github.com/anthropics/claude-code/issues/13024 | **重要的设计反面信号：通知本身也会疲劳** |
| "a third has been sitting on a permission prompt for nine minutes while you weren't looking" | Zentor 博客（**厂商营销**），https://zentor.ai/blog/claude-code-parallel-agents | 只当参考 |

另外，issue #12048 的作者抱怨现有 `idle_prompt` 通知有误报，"I get notified immediately after Claude finishes responding"（https://github.com/anthropics/claude-code/issues/12048），也就是说**状态本身的可靠识别就是个难题**，不是把灯接上就行。

### 1.3 多终端 / 多 agent 切换成本

| 引文 | 来源 | 信号 |
|---|---|---|
| "The bottleneck stops being the model and becomes you, reading terminals." | Zentor 博客（厂商），https://zentor.ai/blog/claude-code-parallel-agents | 厂商 |
| "alt-tab between tabs hunting for the one waiting on input" | claudefa.st（博客），https://claudefa.st/blog/guide/agents/agent-view | 博客，介绍 Claude Code 自带 agent view |
| "babysitting the agents is probably not 'free' for you either" | HN 跟帖，https://news.ycombinator.com/item?id=47327559 | |
| "you need to accept that your new job is to be an agent babysitter, and audit every command." | HN 用户 Kim_Bruning，https://news.ycombinator.com/item?id=50408126 | |
| "My only option is to check each tab" 类说法没有找到，我找到的是 issue 原文："You have to manually check each tab/window." | #36885 | |
| 开发者并行跑 5–15 个 Claude Code 实例 | uncoveralpha 文章转述，https://www.uncoveralpha.com/p/anthropics-claude-code-is-having | 二手统计，非一手 |

GitKraken 的新闻稿把同一件事写成产品卖点："check the status of each agent by switching windows, over and over"（https://finance.yahoo.com/sectors/technology/articles/gitkraken-desktop-12-0-introduces-181400864.html），说明有上市公司愿意押注这个痛点。

### 1.4 语音输入 / 手部负担（证据偏弱，诚实标注）

| 引文 | 来源 | 信号 |
|---|---|---|
| "I rely on Wispr Flow for the majority of my input to Claude Code (heavy daily usage)." | issue #38620，https://github.com/anthropics/claude-code/issues/38620 | 一手用户，说明有人重度依赖语音 |
| "dictation reduces strain for anyone typing all day. For people with RSI, motor disabilities, or chronic pain" | Elgato 博客（**厂商**），https://www.elgato.com/us/en/explorer/products/stream-deck/foot-pedals-for-ai-prompting | 厂商；Elgato 把脚踏板包装成"语音 push-to-talk 触发器" |
| Claude Code 官方内置 `/voice`，按住空格说话 | https://code.claude.com/docs/en/voice-dictation | 官方已有，物理键只替代"按住空格" |
| Codex Micro 默认把最大的键设为 push-to-talk | The New Stack，https://thenewstack.io/openai-codex-micro-macropad | |

**我没有找到可靠的、第一人称的"RSI 逼我用语音控制 coding agent"的 Reddit/HN 帖子**（Reddit 抓取受限是原因之一）。RSI 在这份证据里只是厂商话术和一个功能点，不能当成已验证的购买动机。

### 1.5 快捷键记不住 / 重复动作

| 引文 | 来源 |
|---|---|
| "I stopped trying to memorize shortcuts and started memorizing finger positions." | zephel01，https://note.com/zephel01/n/nd6b67d2d24fb?hl=en |
| "The same commands, dozens of times a day." | Casey Capshaw，https://capshaw.substack.com/p/the-stream-deck-nobody-asked-for（他用 Claude Code 自己配置了 Stream Deck，并称其"saving me a few keystrokes every session"，自我评价是 "a small thing"） |
| "a large part of my job has just become clicking a few buttons." | HN 用户 Juvination，在 Codex Micro 帖下，https://news.ycombinator.com/item?id=48923079 |

---

## 2. 已经有人做了什么（需求的行为证据）

### 2.1 官方 / 大厂入场（最重要的一组）

| 名称 | URL | 规模信号 | 硬件 / 说明 |
|---|---|---|---|
| **Codex Micro**（OpenAI × Work Louder） | https://www.worklouder.cc/codex-micro ；评测 https://thenewstack.io/openai-codex-micro-macropad | 售价 $230，限量，2026-07-15 开卖；官方视频 317K 播放（https://www.youtube.com/watch?v=m8uUUUsMD3Y） | 13 键 + 摇杆 + 旋钮；**6 个 Agent Key 带灯显示每个 Codex 线程状态**（白=空闲 / 蓝=思考 / 绿=完成 / 红=出错），单击选择、双击切前台；默认有 approve/reject、push-to-talk。**这和你的概念几乎重合**。本质是 Work Louder Creator Micro 2 换皮（The New Stack 同篇）。 |
| **Logitech MX Keypad** | 视频 https://www.youtube.com/watch?v=S9bvQg7BK24（2026-10-15） | 视频摘要称"nine keys, each one a little screen"，面向开发者，带 developer kit | 9 个带 LCD 的键，主打 GitHub Copilot 等；我没拿到价格，也没验证它对 Claude Code/Codex 的状态支持 |
| **claude-desktop-buddy**（Anthropic 官方） | https://github.com/anthropics/claude-desktop-buddy | **2.7k stars，472 forks** | BLE 协议，ESP32 M5StickC Plus 为参考硬件；屏幕显示权限提示，实体键批准/拒绝。Espressif 也发了新闻稿（https://www.espressif.com/en/news/Claude_ESP32_Code） |
| **Elgato Stream Deck** 生态 | https://www.elgato.com/eu/cs/explorer/products/stream-deck/what-is-a-ai-controller | 官方已发"AI Controller"品类文章，并点名 Codex Micro 约 $230 作对比 | Marketplace 有一批付费插件：Claude Code Approver $3.99、Claude Deck Windows $1.99（"which of your Claude Code sessions … is waiting for you, and switch to it with one press"）、Claude Code Usage 等（https://marketplace.elgato.com/product/claude-code-usage-ea7abd37-ad12-473a-a9cd-ab0bfeba3e3c） |

### 2.2 个人 / 开源项目

| 项目 | URL | Stars / 信号 | 硬件 |
|---|---|---|---|
| **puritysb/AgentDeck**（注意：与你的产品同名） | https://github.com/puritysb/AgentDeck | 星数未取到；MIT；有官网、产品视频、桌面照 | Stream Deck、Ulanzi D200H/D200X、ESP32、e-ink、Pixoo 像素屏、Vobot、iOS/Android/macOS App；支持 Claude Code / Codex CLI / OpenCode / Kiro 等；有语音键 |
| **darkmatter2222/AgentDeck** | 见 YouTube 视频 https://www.youtube.com/watch?v=NTWLbLbJiO0 | 星数未取到 | Stream Deck Mini，USB HID，最多 6 个并行 agent（当前只支持 OpenCode）。**第二个叫 AgentDeck 的项目** |
| **paultyng/agentsd** | https://github.com/paultyng/agentsd | 11 stars，5 forks | Stream Deck 插件，会话状态着色、批准/拒绝、dial 切换会话；基于 Claude Code HTTP hooks |
| **ThomasAlbin 的 Stream Deck 插件** | 视频 https://www.youtube.com/watch?v=zNS4HtsFP3E | 视频 1.5K 播放；星数未取到 | 一键一会话，蓝/橙/绿，等待 5 分钟开始脉动 |
| **ClaudeButtons** | https://marcscibelli.com/experiments/claudebuttons | 官网 claudebuttons.com | Stream Deck 插件，approve/deny 物理键 |
| **claude-buddy-pico** | https://github.com/amargandhi/claude-buddy-pico | 28 stars | Raspberry Pi Pico 2 W + 2.8" 屏 + 3D 打印外壳，一键批准一键拒绝，自带电池 |
| **ClaudeMicro**（zephel01） | https://note.com/zephel01/n/nd6b67d2d24fb?hl=en | 日文博客，MIT 配置 | 把 Codex Micro 改成控制 Claude |
| **Claudinho** | https://emergent.sh/news/claudinho-claude-code-mascot-esp32-brings-ai | 2026-11-03 发布，来自一篇新闻稿式文章，我没核对仓库 | ESP32 + 事件 hooks 做 Claude Code 桌面吉祥物 |
| **buddy 端口族** | GitHub topic 页 https://github.com/topics/desk-pet?l=c%2B%2B&o=desc&s=updated | 至少 5 个 fork：xiaozhi-cube、Heltec、Cardputer、M5StickC Plus S3、GeekMagic SmallTV（"permission prompts answered with the button on top"） | 全是 ESP32 / RP2040 小屏 |
| **Claude-Code-Usage-Monitor ESP32 CYD** | https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/issues/198 | 2026-04 showcase issue | 约 £15 的 ESP32 触屏，点按可把终端窗口切到前台 |
| Reddit showcase 帖（标题，未能读正文） | https://www.reddit.com/r/ClaudeCode/comments/1re40d2/i_turned_my_stream_deck_into_a_ai_agents_control ；https://www.reddit.com/r/codex/comments/1uzfb3c/i_recreated_the_codex_micro_controls_on_a_regular ；https://www.reddit.com/r/ClaudeCode/comments/1w2amwd/i_built_a_status_board_for_claude_code_and_codex（"keyboard F-row, Stream Deck, or a tiny always-on-top window"） | 赞数未取到 | Stream Deck+、复刻 Codex Micro、键盘 F 行 |
| 纯软件替代 | OKed（Telegram 批准，https://www.reddit.com/r/ClaudeCode/comments/1xexhwf/do_you_let_claude_code_run_without_asking ）、claude-beacon（https://www.reddit.com/r/ClaudeCode/comments/1xwdw6e/i_built_claude_beacon_to_help_you_see_which_claude）、RepoYard、悬浮气泡通知 | | 说明同一痛点也在被**纯软件**解决 |

**解读：** 2026 年有两类人在做：（a）把 Stream Deck 变成 agent 遥控器的个人开发者；（b）用 ESP32 做"桌面小屏 + 批准键"的创客，且 Anthropic 官方还推了这个玩法。需求是真实的；同时 **DIY 价格锚点极低（约 $30 的 ESP32），大厂方案 $230**。

---

## 3. 反面证据（尽量诚实）

### 3.1 "这只是个宏键盘，凭什么这个价"

- "This is just a Macropad, right? All of the smarts are on the PC side. So why is it so expensive?" — HN，https://news.ycombinator.com/item?id=48923079
- "This is the lamest possible implementation, exactly what I would expect from openAI." — HN 用户 mrnotcrazy，同帖
- "I struggle to justify the money on this." — HN 用户 freedomben，同帖（另外嫌仅支持 Windows/Mac）
- "This gives companies a physical thing to buy to demonstrate they are fully AI-enabled" — HN 用户 ex-aws-dude，同帖（讽刺意味）
- "yolo on a keyboard button? I'm cringing." — PCMag 视频下 Facebook 评论，https://www.facebook.com/PCMag/videos/the-codex-micro-made-in-collaboration-with-work-louder-is-openais-new-keyboard-d/1783869049461934 （嫌"一键批准"本身不安全）
- zephel01 自己把价差摆出来："One side sells dedicated hardware for $230, and the other side publishes the specifications" 给 DIY（https://note.com/zephel01/n/nd6b67d2d24fb?hl=en）
- Elgato 自己的营销直接打 Codex Micro 价格："priced relatively high (OpenAI's Codex Micro costs around $230)"（https://www.elgato.com/eu/et/explorer/products/stream-deck/heres-how-developers-are-speeding-up-ai-coding）

### 3.2 审批本身正在被官方消灭

- Anthropic：auto mode 从 2026-08-14 起对 Pro/Max/Team 成为默认（https://thenewstack.io/claude-code-auto-mode）。官方自己说用户批准 97% 的提示。
- 文档：自 v2.1.283 起交互式终端和 VS Code 默认 auto mode（https://claudecodeguide.dev/docs/foundations/permissions）。这个来源是第三方指南，我没在官方文档里核对版本号。
- Anthropic 官方文字："Auto mode … a middle ground between manual review and no guardrails."（https://www.anthropic.com/research/claude-code-auto-mode）。

这意味着你的 approve/deny 键的使用频率正在被官方压低。**但**：

- auto mode 仍会在分类器拦截时退回人工（"After three consecutive blocks, or twenty in a single session, auto mode hands control back to the user"，The New Stack 同篇）；企业版默认关闭。
- 用户社区里有人觉得 auto mode 反而更爱拦："it's been refusing actions or asking for approval far more often"（Claude Community Facebook 群帖，https://www.facebook.com/groups/claudecommunity/posts/1147888511085146，片段）。
- HN 上也有"自治还远"的声音："You must suffer the questions and approvals."（https://news.ycombinator.com/item?id=47387434）；"mid-job blockers that need human input are more common than you'd expect"（https://news.ycombinator.com/item?id=47435275）。

所以"审批会消失"我不认为已经成立，但**方向是对的**：批准键应当不是核心卖点。

### 3.3 官方自己在补"状态可见"

- Claude Code 已有 agent view（`claude agents`，一屏列出所有会话并标注谁在等你，https://claudefa.st/blog/guide/agents/agent-view），桌面版有系统 toast（issue #45734 提到 "Claude Code Desktop already shows system toast notifications"）。
- 通知类 issue（#36885、#12048）被关闭或判重；官方用 hooks 把缺口交给社区解决，这对做外设的人是好消息（hook 接口稳定），但也说明官方不会替你做。
- Codex 桌面应用本身被 OpenAI 称作 "command center"（https://www.cnbc.com/2026/02/02/openai-codex-app-apple-computers.html），软件层的竞争还会继续。

### 3.4 其他风险

- 软件替代品便宜甚至免费：Stream Deck 插件 $1.99–$3.99，Telegram/Slack 审批，RepoYard 一类 App。
- 官方 BLE 规范让 DIY 极其容易：Anthropic 的做法等于"把规格公开，让创客去做"，压低了你的差异化空间。
- **通知疲劳**（见 1.2 的 JackRostron 引文）：状态灯做不好会被忽略。
- Linux 用户被 Codex Micro 排除（freedomben 的评论），而 Claude Code 用户里 Linux/WSL 占比不小；这既是反面证据也是缺口。
- 重名：至少有两个现成的 **AgentDeck**（puritysb、darkmatter2222），其中一个已经覆盖 Stream Deck + ESP32 + e-ink + 语音。

---

## 4. 对产品功能与定位的含义

1. **需求成立，别再用"有没有人要"当主论点。** 证据：官方 issue 80+ 反应、Anthropic 官方 BLE 规范 2.7k stars、OpenAI 亲自下场做 $230 硬件、Elgato 把它当品类。可以把"大厂都在验证"写进路演，但同时必须回答"你比它们强在哪"。
2. **核心价值从"approve 键"移到"状态 + 跳转"。** 审批在被 auto mode 压缩，而"哪个 agent 在等我、一键切过去"依然没被官方解决（只有软件 agent view）。每个会话一键、状态灯/小屏、按下即聚焦对应终端窗口，是最稳的价值。Codex Micro 的 6 个 Agent Key 已经做了这一点，但**只服务 Codex**。
3. **跨 agent 是唯一清晰的结构性差异。** Codex Micro 绑 Codex，claude-desktop-buddy 绑 Claude，Stream Deck 插件各绑一家。用户同时跑 Claude Code、Codex、Cursor、Gemini CLI 才是你的场景；中立、统一状态协议（hooks 适配层）才是护城河，而不是键帽。AgentDeck(puritysb) 已经在做软件层的这件事，需要看清它的定位再决定是合作还是差异化。
4. **approve 键要配"安全设计"，否则会放大风险。** 做成：只对"低风险/已读过摘要"的提示给快速批准；危险命令在小屏上高亮并要求长按或双键确认。把"防止闭眼点同意"作为卖点，反而把审批疲劳的安全争议变成优势（HN 的 Kim_Bruning、Atomic Object 都在讲这个点）。
5. **别只做通知，做"被动提醒 + 可静音/可聚合"。** 通知疲劳是真实风险（"you start ignoring them"）。状态要从 hooks 精确识别（`PermissionRequest`、`Notification`、`Stop`、`Elicitation`），#12048 说明 `idle_prompt` 有误报。
6. **价格带：** DIY 约 $30（ESP32），Stream Deck 软件插件 $2–4，Codex Micro $230。建议把定价放在 Stream Deck 之下或之上有明确理由；若是 ESP32 级硬件，BOM 低，$60–120 区间有空间，但要有**开箱即用 + 跨 agent + 跨平台（含 Linux/Windows）**。
7. **voice/push-to-talk 和 screenshot-to-agent 键是锦上添花。** Claude Code 已内置 `/voice`，Wispr Flow 等也有用户；RSI 证据弱，不要作为主卖点。screenshot-to-agent 我没找到用户原声证据，需要补做访谈再决定是否保留。
8. **转轮滚动 agent 输出**：这次没有找到用户对"用滚轮看 agent 输出"的明确需求。zephel01 提到旋钮用来调 reasoning effort；Stream Deck 快捷键配置里有 dial 绑定权限模式（Shift-Tab）和历史。旋钮更适合"切会话 / 调 effort / 切权限模式"而不是滚动。
9. **名字：** 两个现成 AgentDeck 项目，路演前必须查商标/GitHub 占用情况，必要时换名或加限定词。
10. **平台风险：** 依赖 Claude Code/Codex 的 hooks 和 Desktop BLE API，这些是"非正式支持的开发者功能"（codeongrass 对 BLE 的描述，https://codeongrass.com/blog/build-hardware-companion-claude-code-ble-api）。路线图要预留适配层。

## 5. 建议补做的调研（这次没拿到的）

- 能登录或用浏览器读完整 Reddit 评论区：r/ClaudeCode "permission system is exhausting"、r/ClaudeCode "Claude Code with Stream Deck, anyone?"、r/codex "recreated the Codex Micro controls"，找第一人称的购买意愿和价格反应。
- X/Twitter 上对 Codex Micro 和 Logitech MX Keypad 的真实反应。
- Codex Micro 买家/评测的真实使用反馈（是否真的用 Agent Key）。
- 对 5–10 个并行跑 3+ agent 的人做访谈，问"愿意为这个付多少、现在怎么解决"。
