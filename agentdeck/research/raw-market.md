# AgentDeck 市场调研原始资料 (raw-market)

调研日期：2026-11-17。方法：WebSearch + WebFetch + tavily。
可信度标记：**[P]** = 已打开一手页面核对；**[S]** = 只见二手/聚合站转述，未核对一手；**[E]** = 我自己的估算，附算式。
总体提醒：2026 年的很多数字来自聚合站（getpanto、fourweekmba、dealroom 等），ARR 是年化 run-rate，不是审计收入。落到路演 PPT 之前，带 [S] 的数字要回到原始新闻再核一次。

---

## 1. 开发者人口与 AI 使用率

| 指标 | 数值 | 时间 | 可信度 | 来源 |
|---|---|---|---|---|
| GitHub 开发者总数 | 1.8 亿+；过去一年新增 3620 万（+23%） | 2025-10-28（2026-02-28 更新） | P | [1] |
| SlashData 全球开发者 | 4840 万（另一版本 4720 万） | 2025 Q3 / Q4 | S | [2] |
| JetBrains 全球专业开发者 | 约 2080 万 | 2025 | S | [3] |
| 使用或计划使用 AI 工具（SO 全体受访者） | 84%（上年 76%）；每天用 47.1%（专业开发者 50.6%） | SO 2025 调查 | P | [4] |
| 使用 AI agent（SO 2025） | 30.9%（日用 14.1%，周用 9%，月用或更低 7.8%） | 2025 | P | [4] |
| 使用 AI agent（SO 2026 四月 pulse，样本 1,100） | 59%，日用 37% | 2026-04 调研，2026-05-27 发布 | P | [5] |
| 多 agent 使用结构（同上 pulse） | 单 agent 69%，多个分工 agent 17%，多个重叠/协同 agent 16%；68% 偏好单 agent | 同上 | P | [5] |
| SO 2026 主调查：编码 agent 谁最多 | Claude Code 66%，GitHub Copilot 59%；AI 使用者中 66% 用 coding agent；用 AI 助手/agent 的人 73% 日用。（Codex 29.5%、Cursor 25.5% 只见二手转述） | 2026-10-06 | P（66/59/73）/ S（Codex、Cursor） | [6] |
| SlashData：使用 AI 辅助工具 | 两年内 61% 升至 79%；42% 在编码环境里用 AI 开发工具或 agent | 2026 Q1 波 | S | [2] |
| JetBrains：专业开发者工作中用 Claude Code | 39%（2026-05~07），2026-01 是 18%；美国 47% | 2026-08-18 | P | [7] |
| JetBrains：Codex / Copilot / Cursor 工作使用率 | Codex 3%→16%；Copilot 29%（一年前）→21%；Cursor 18%→12% | 2026-01 至 2026-07 | P | [7] |

读法与口径提醒：
- SO 的 59% 是 1,100 人的小样本 pulse，志愿填问卷的人偏爱 AI，会高估。JetBrains 的 39% 是"工作中用 Claude Code"，口径不同，两者不能相加。
- 可以放进 PPT 的区间：**专业开发者里用 coding agent 的比例，保守取 31%（SO 2025 全体），乐观取 59%（SO 2026 pulse）**。

---

## 2. AI 编码 agent 的采用与收入

| 产品 | 最新数字 | 时间 | 可信度 | 来源 |
|---|---|---|---|---|
| Claude Code | run-rate 收入超 25 亿美元，自 2026 年初翻了一倍多；周活用户自 1 月 1 日翻倍；Anthropic 没有公布绝对用户数 | 2026-02-12（Anthropic 官方） | P | [8] |
| Claude Code（早期节点） | 约 5 亿（2025-09）→ 10 亿（2025-11） | 2025 | S | [9] |
| Claude Code（后期） | 约 80 亿（2026-05），仅一个聚合源，未见 Anthropic 原话 | 2026-05 | S（弱） | [10] |
| Anthropic 全公司 run-rate | 140 亿（2026-02，官方）；300 亿（2026-04）；470 亿以上（2026-05，转述 Series H） | 2026 | P（140 亿）/ S（其余） | [8][10] |
| Cursor (Anysphere) | 年化收入 1 亿（2025-01）→ 10 亿（2025-11）→ 20 亿（2026-02）→ 30 亿（2026-04 下旬）→ 40 亿以上（2026-06 初，约 75% 来自企业）；内部预测 2026 年底 60 亿以上 | 2025-2026 | S | [11] |
| Cursor 融资与收购 | 2025-11 Series D 23 亿美元、估值 293 亿；2026-06-16 SpaceX 宣布以全股票方式收购 Anysphere（报道称 600 亿），Wikipedia 称 2026-08-14 完成。聚合站之间互相矛盾 | 2026 | S（弱） | [11] |
| OpenAI Codex | 周活：2026-02 不到 100 万；2026-04-21 超 400 万；2026-06-02 超 500 万（OpenAI 披露，知识工作者约占 20%）；2026-07-21 Codex 加 ChatGPT Work 合计约 1000 万周活 | 2026 | S | [12] |
| GitHub Copilot | 付费订阅者超 470 万，同比 +75%（2026-01 财报）；后续季度口径互相矛盾，没找到最新确认数。Octoverse：约 80% 新 GitHub 开发者首周就用 Copilot；Copilot coding agent 在 2025-05~09 间创建 100 万以上 PR | 2026-01 / 2025-10 | S（470 万）/ P（Octoverse） | [1][13] |
| Gemini CLI | 2025-10 Google 称超 100 万开发者采用（上线三个月内）；2026-05-19 Google 称社区"数百万用户"，同时宣布迁移到 Antigravity CLI，2026-06-18 起终止面向个人用户的服务 | 2025-10 / 2026-05 | S | [14] |
| Windsurf / Cognition | 2025-07 被 Cognition 收购时约 8200 万美元 ARR、350+ 企业客户；Windsurf 编辑器 2026-06-02 改名 Devin Desktop；Cognition 的 2026 ARR 说法冲突（约 4.92 亿 vs 约 9 亿） | 2025-2026 | S | [15] |

小结：Claude Code、Codex、Cursor 三家都已是十亿美元以上级别的年化收入，增速在 2026 年继续加快。Gemini CLI 被 Google 自己并入 Antigravity，说明"终端 agent"这个品类在大厂内部也在重组，AgentDeck 不要绑死某一家 CLI，要做成跨 agent 的。

---

## 3. 多 agent 并行 / 编排趋势

| 证据 | 内容 | 时间 | 可信度 | 来源 |
|---|---|---|---|---|
| 公司产品动作：Cursor 3 | 官方 changelog 称 Agents Window 可以"在本地、worktree、云端、远程 SSH 并行跑很多 agent"；3.2 加入 worktree 和 /multitask 并行子 agent | 2026-04-02 / 2026-04-24 | S（搜索摘要引用，未单独打开） | [16] |
| 公司产品动作：Claude Code | 官方文档被转述为推荐用 git worktree 开多会话 | 2026 | S | [17] |
| 个人工作流：Claude Code 作者 Boris Cherny | 本地终端同时跑 5 个 Claude，另有网页端 5 到 10 个，用系统通知提醒谁在等输入；自称丢弃 10%~20% 会话 | 2026-01 | S | [18] |
| 调查：SO 2026-04 pulse | 33%（17% + 16%）的 agent 使用者使用多个 agent；多 agent 使用者日用率 85% / 77%，高于单 agent 的 54% | 2026-05-27 | P | [5] |
| 调查：监督需求 | 60% 阻止 agent 做未经批准的系统改动；63% 很少或从不让 agent 完全自动运行。**这直接说明"批准/拒绝/打断"是高频动作** | 同上 | P | [5] |
| 社区文章 | worktree 在约 12 个月内成为 AI 编码的标准做法；"大多数开发者同时跑 2 到 5 个 agent" 这句没有引用来源，只能当弱证据 | 2026-04 | S（弱） | [19] |
| 反面意见 | 更多 agent 不等于更快，人工审查才是瓶颈；68% 偏好单 agent | 2026 | S / P | [5][19] |

读法：**没有找到一份正式调查直接给出"同时跑 N 个 agent 的开发者占比"。** 目前最硬的数字是 SO pulse 的 33% 多 agent，加上 Cursor 3 的产品形态变化。PPT 里要写成"约三分之一的 agent 使用者已在用多 agent 配置（SO 2026-04，n=1,100）"，不要写得更满。

---

## 4. 周边硬件市场

| 指标 | 数值 | 时间 | 可信度 | 来源 |
|---|---|---|---|---|
| Corsair 总收入 | 约 14.7 亿美元（FY2025，+12%） | 2025 | S | [20] |
| Corsair 游戏及创作者外设分部（Elgato 在此分部内，不单独披露 Stream Deck） | 4.72 亿美元（FY2025，+4%） | 2025 | S（PC Gamer 转述） | [20] |
| 该分部 2026 Q2 | 同比 +13%；Elgato Marketplace 总收入与交易量上半年同比各增超 100% | 2026-08-06 | S | [21] |
| Stream Deck 生态上半年增速 | "超 100%"，仅见第三方摘要，不是 Corsair 披露的美元数 | 2026 H1 | S（弱） | [21] |
| Stream Deck MK.2（15 键）官方定价 | 149.99 美元；促销价低至 119.99 | 现价 | S | [22] |
| Stream Deck +（带旋钮） | 标价 199.99 美元，Best Buy 挂价 157.99 | 现价 | S | [22] |
| 机械键盘市场规模 2025 | 各机构区间约 15 亿到 29 亿美元（Reportprime 15.4 亿；360iResearch 16.7 亿；Knowledge Sourcing 20.5 亿；Straits 23.0 亿；Emergen 28.3 亿）。定制机械键盘细分 6 亿美元（Credence）。年复合增速 7%~15% | 2025 | S（市场报告，口径差异大） | [23] |
| macro pad 单独的市场规模 | **没找到任何可信报告**，估计属于机械键盘的小细分 | — | — | — |
| 众筹：Keyboardio Model 01 | 65.2 万美元，2,073 人 | 约 11 年前 | S | [24] |
| 众筹：Prolo Ring（键盘用户光标与宏控制） | 48.4 万美元，2,865 人（活动期 2025-10-15 至 11-18，数字仍在变） | 2025-11 | S | [24] |
| 众筹：Decokee Quake（桌面 AI copilot） | 27.9 万（货币未确认，Kicktraq 常用 HK$），829 人 | 年份未确认 | S（弱） | [25] |
| 众筹：Virtusx Phronesis（AI 语音机械键盘） | 约 5.8 万（Kicktraq），335 人，2025-09-16 至 11-05 | 2025 | S | [25] |
| 众筹：**CtrlVibe**（AI 工作流控制台：拨轮切换 AI 工具、拨杆管权限、9 个机械键、语音提示，面向 coder） | HK$80,514（约 1.0 万美元，[E] 80,514 ÷ 7.8 ≈ 10,300），59 人，目标 HK$10,000，成功；2025-07-30 至 09-13 | 约 2025 | P（PledgeBox 页面） | [26] |
| 众筹：M5Stack StackChan（AI 桌面机器人） | 358 万美元，4,142 人 | 2025-2026 | S | [25] |

**直接竞品警告：CtrlVibe 做的就是 AgentDeck 的概念（拨轮切工具、权限拨杆、语音）。** 它只筹到约 1 万美元、59 位支持者，说明：这个概念已经有人试过；早期需求验证很弱，但也还没有出现头部玩家。路演里要主动讲清区别（比如每键小屏显示 agent 状态、对 Claude Code / Codex / Cursor 的真实集成深度）。

**愿意付费的价格锚点：** Stream Deck 15 键 149.99 美元、带旋钮款 199.99 美元，正好卡在 AgentDeck 的 99~199 美元目标区间。**开发者生产力硬件的专项付费意愿调研，没有找到。** 这是数据缺口，建议自己做 50~100 人的小问卷或预售页。

---

## 5. 中国视角

| 指标 | 数值 | 可信度 | 来源 |
|---|---|---|---|
| 中国软件开发者总数 | 约 940 万。出处是 2025-01 媒体转述工信部数据；知乎和魔搭（ModelScope）2025-10 白皮书也出现"940 万"，两者可能同源，也可能指"AI 开发者"，口径存疑。没找到国家统计局或 GitHub 的独立数字 | S | [27] |
| Trae（字节） | 注册开发者超 600 万（近 200 个国家，字节 2025 年度报告）；月活约 160 万（2025 年底） | S | [28] |
| 中国 AI 编程市场份额（IDC 2025） | 阿里 47.6%，智谱 11.5%；有开发者质疑 Trae 不在前五，口径存疑 | S | [28] |
| 腾讯内部 CodeBuddy | 腾讯 85% 程序员使用（内部数字，不代表公开用户数） | S | [29] |
| 通义灵码、Kimi Code、DeepSeek 作为编码 agent 的用户数 | **没找到可引用数字** | — | — |
| JetBrains：Cursor 在中国的采用率 | 28%（2026-01）降到 16%（2026-05~07），是全球降幅最大的地区 | P | [7] |
| ChinaTalk / ChinAI 观点 | 国内模型的编码工具更容易访问，但中国开发者仍愿意绕路用 Claude Code 等海外工具 | S（观点） | [30] |
| 深圳宏键盘供应链 | Alibaba 上有大量 1 件起订的现成 macro pad 挂牌：RGB 热插拔款约 5.4~33 美元，旋钮款约 9.9~26.8 美元，13 键定制键帽款约 11.5~16.4 美元，最低端 3~3.8 美元。这些是零售挂牌价，不是量产 OEM 报价 | S（弱） | [31] |

结论与缺口：
- 深圳供应链优势有方向性证据（成品 macro pad 成本低、起订量低），但**没有可靠的"带小屏 + 旋钮 + 定制 PCB"量产成本**。BOM 要自己向 3~5 家工厂拿 500 / 1,000 / 3,000 台的报价，PPT 里不要写没有来源的毛利率。
- 对 AgentDeck 的含义：中国开发者基数大（约 940 万，口径存疑），但国内主流编码工具（Trae、灵码、CodeBuddy）多为 IDE 插件形态，快捷键和本地事件接口与 CLI agent 不同，需要单独适配。

---

## 6. TAM / SAM / SOM（全部为我的估算，假设写明）

基础人口取 JetBrains 的"全球专业开发者约 2080 万"[3]，不取 SlashData 的 4840 万（后者含业余爱好者、学生）。价格取 149 美元（与 Stream Deck MK.2 的 149.99 对齐）。

| 层级 | 定义 | 算式 | 结果 |
|---|---|---|---|
| 全球专业开发者 | JetBrains 口径 | 20.8M | 2,080 万人 |
| agent 使用者 | 保守 31%（SO 2025）/ 基准 40% / 乐观 59%（SO 2026 pulse） | 20.8M × 0.31 / 0.40 / 0.59 | 645 万 / 832 万 / 1,227 万 |
| **TAM（人人买一个）** | 基准 agent 使用者 × 149 美元 | 8.32M × 149 | **约 12.4 亿美元**（区间 9.6 亿~18.3 亿） |
| 多 agent 使用者 | 取 SO pulse 的 33%（17% + 16%） | 8.32M × 0.33 | 约 275 万人 |
| **SAM** | 多 agent 使用者 × 149 美元 | 2.75M × 149 | **约 4.1 亿美元** |
| SAM 中可触达部分 | 假设：桌面办公、愿为外设付费、非必须走国内渠道，约 50%（**纯假设，无来源**） | 2.75M × 0.5 | 约 137 万人，约 2.0 亿美元 |
| **SOM（3 年）** | 假设占可触达人群 1%~3%（对照：CtrlVibe 约 59 位支持者，Prolo Ring 约 2,865 位，说明众筹冷启动量级是百到千台） | 1.37M × 1% / 3% = 1.4 万 / 4.1 万台；× 149 | **约 200 万 / 610 万美元** |

关键敏感性：
- 最大不确定量是"多 agent 比例 33%"，来自 1,100 人的 pulse，且偏向热衷 AI 的受访者；如果真实只有 15%，SAM 约减半。
- agent 使用者增速很快（SO 从 31% 到 59%，JetBrains 的 Claude Code 从 18% 到 39%），所以 TAM 在往上走；但"愿意买外设"的比例没有数据。
- 参照物：Stream Deck 只是 Corsair 4.72 亿美元外设分部里的一部分，整个"控制台类外设"全球量级大约是几亿美元，AgentDeck 的 SOM 几百万美元是合理量级，不要写成上亿。

---

## 7. 投资人兴趣（2024~2026）

| 公司 | 融资 | 时间 | 类别 | 可信度 | 来源 |
|---|---|---|---|---|---|
| Hark | 7 亿美元以上 A 轮，估值 60 亿 | 2026-05 | AI 原生个人硬件 | S | [32] |
| Sandbar | 2,300 万美元 A 轮（Adjacent、Kindred 领投）；此前 300 万 pre-seed 与 1,000 万 seed，累计约 3,600 万 | 2026-03 | AI 语音戒指 | S | [33] |
| Pocket | 1,100 万美元 | 未确认 | AI 记录设备 | S | [33] |
| Taya | 500 万美元 seed | 2026 | AI 首饰 | S | [33] |
| Aina | 550 万美元 seed | 2026-07-17 | AI 原生硬件界面 | S | [33] |
| 光帆（Guangfan）科技 | seed 累计近 3 亿元人民币（约 4,360 万美元） | 2026 | AI 耳机 | S | [33] |
| Lingverse | 2,900 万美元 Pre-A | 2026 | 模块化可穿戴 | S | [33] |
| Positron AI / SiMa.ai | 2.3 亿美元（估值超 10 亿）/ 1.5 亿美元（估值 14.5 亿） | 2026-02 / 2026-09 | AI 芯片，非消费外设 | S | [32] |

读法：2026 年 AI 硬件资金集中在**可穿戴/个人设备和芯片**，**没有找到"开发者外设"类的融资案例**。这对 AgentDeck 有两面：没有先例可比（估值难锚定）；也说明赛道空白。PPT 里建议诚实写成"AI 硬件热度高，但开发者 agent 控制外设尚无融资先例"，把 Hark、Sandbar 当作"资本愿意给 AI 硬件下注"的旁证，不当作同类对标。

---

## 8. 没找到 / 需要补的

1. "同时运行 N 个 agent" 的正式调查占比。
2. 开发者购买生产力外设的付费意愿数据。
3. Stream Deck 单品销量与收入（Corsair 不披露）。
4. 带屏幕/旋钮宏键盘的深圳量产报价（需要自己询价）。
5. Trae、通义灵码、Kimi Code、DeepSeek 的编码 agent 官方用户数。
6. Cursor 2026 年 6 月以后的收入与收购细节、Cognition 2026 ARR 的一手来源（目前互相矛盾）。
7. Claude Code 2026-02 之后的官方收入数字。

---

## 来源清单

1. GitHub Octoverse 2025（2025-10-28）：https://github.blog/news-insights/octoverse/octoverse-a-new-developer-joins-github-every-second-as-ai-leads-typescript-to-1/
2. SlashData：https://www.slashdata.co/developer-population ；https://www.slashdata.co/post/14-software-developer-trends-insights-you-need-to-know-in-q1-2026
3. JetBrains 全球专业开发者约 2080 万（页面直接抓取被 403，数字来自搜索摘要）：https://jetbrains.com/zh-cn/lp/devecosystem-data-playground
4. Stack Overflow Developer Survey 2025 AI 章节：https://survey.stackoverflow.co/2025/ai
5. Stack Overflow Blog, Agents on a leash（2026-05-27）：https://stackoverflow.blog/2026/05/27/agents-on-a-leash-agentic-ai-remains-mostly-monitored-at-work
6. Stack Overflow Blog, 2026 survey results（2026-10-06）：https://stackoverflow.blog/2026/10/06/the-results-of-the-2026-developer-survey-are-here/ ；Codex、Cursor 比例见 https://visualstudiomagazine.com/articles/2026/10/06/stack-overflow-2026-survey-vs-code-leads-visual-studio-takes-third.aspx
7. JetBrains Research, AI coding agent adoption（2026-08-18）：https://blog.jetbrains.com/research/2026/08/18/ai-coding-agent-adoption-2026
8. Anthropic Series G 公告（2026-02-12）：https://www.anthropic.com/news/anthropic-raises-30-billion-series-g-funding-380-billion-post-money-valuation
9. Claude Code 早期节点（聚合）：https://fourweekmba.com/ai-claude-code-run-rate-agentic-layer/ ；https://www.mindstudio.ai/blog/claude-code-2-5-billion-annualized-revenue-terminal-tool
10. Claude Code 约 80 亿、Anthropic 470 亿（聚合，弱）：https://www.claudeainews.com/news/anthropic-47b-revenue-run-rate-claude-code
11. Cursor 收入与融资（聚合）：https://dealroom.co/news/134107-cursor-tops-4b-annualized-revenue/ ；https://en.wikipedia.org/wiki/Cursor_(company) ；https://letsdatascience.com/blog/cursor-2-billion-funding-round-50-billion-valuation
12. Codex 周活：https://constellationr.com/insights/news/openai-touts-broadening-codex-usage-5-million-weekly-active-users ；https://www.unite.ai/openai-says-codex-and-chatgpt-work-hit-10-million-users/ ；https://codex.danielvaughan.com/2026/04/29/codex-four-million-users-growth-gpt-5-2-codex-aws-partnership/
13. GitHub Copilot 付费订阅 470 万（2026-01 财报转述）：https://itbrief.co.uk/story/github-copilot-surges-as-agent-hq-targets-ai-ecosystem
14. Gemini CLI 迁移 Antigravity CLI（2026-05-19）：https://virtualizationreview.com/articles/2026/05/19/google-moves-gemini-cli-into-antigravity-cli-as-agent-platform-expands.aspx ；https://www.techradar.com/pro/google-is-making-gemini-cli-users-switch-to-its-new-antigravity-2-0-so-what-will-it-mean-for-you
15. Windsurf / Cognition：https://sacra.com/research/cognition ；https://www.verdict.co.uk/cognition-ai-acquire-windsurf/ ；https://cryptobriefing.com/cognition-900m-arr-800m-cash-burn/
16. Cursor 3 changelog：https://cursor.com/changelog/3-0 ；https://infoq.com/news/2026/04/cursor-3-agent-first-interface/
17. Claude Code 多会话 worktree（转述）：https://developer.upsun.com/posts/ai/git-worktrees-for-parallel-ai-coding-agents ；https://www.mindstudio.ai/blog/parallel-agentic-development-git-worktrees/
18. Boris Cherny 工作流：https://venturebeat.com/technology/the-creator-of-claude-code-just-revealed-his-workflow-and-developers-are ；https://developers.slashdot.org/story/26/01/06/2239243/creator-of-claude-code-reveals-his-workflow
19. 并行 agent 社区综述：https://codex.danielvaughan.com/2026/04/11/agentmaxxing-parallel-multi-cli-orchestration/ ；https://www.tembo.io/blog/multi-agent-ai-coding-workflows
20. Corsair FY2025：https://www.businesswire.com/news/home/20251104273608/en ；PC Gamer 外设分部转述：https://www.pcgamer.com/hardware/corsair-has-managed-to-successfully-navigate-a-constrained-global-semiconductor-market-to-secure-supply-for-memory-as-its-pc-gaming-hardware-profits-jump-60-percent-in-a-year
21. Corsair 2026 Q2（2026-08-06）：https://secure.businesswire.com/news/home/20260806457257/en/Corsair-Reports-Strong-Second-Quarter-2026-Profit-Growth-and-Cash-Generation
22. Stream Deck 价格：https://www.lttstore.com/products/elgato-stream-deck-mk-2 ；https://www.digitalcitizen.life/elgato-stream-deck-mk2-119-99-amazon-deal/ ；https://bestbuy.com/product/elgato-stream-deck-studio-controller-with-customizable-touch-strip-and-dials-black/J39QHT7G34
23. 机械键盘市场规模：https://straitsresearch.com/report/mechanical-keyboard-market ；https://www.knowledge-sourcing.com/resources/press-releases/mechanical-keyboard-market ；https://www.credenceresearch.com/report/custom-mechanical-keyboard-market ；https://www.emergenresearch.com/industry-report/mechanical-keyboard-market
24. 众筹 Keyboardio / Prolo Ring：https://www.backerkit.com/projects/keyboardio/the-model-01-an-heirloom-grade-keyboard-for-seriou/backers/7992993 ；https://www.backerkit.com/projects/prolo/prolo-ring-precision-control-for-keyboard-power-users
25. 众筹 Decokee / Virtusx / StackChan：https://www.kicktraq.com/projects/decokee/decokee-quake-the-ultimate-desktop-ai-copilot/ ；https://kicktraq.com/projects/phronesis/virtusx-phronesis-ultimate-ai-mechanical-keyboard-with-voice/ ；https://www.backerkit.com/projects/m5stack/stackchan-the-first-co-created-open-source-ai-desktop-robot
26. CtrlVibe（竞品）：https://www.pledgebox.com/projects/ctrlvibe-ai-keyboard-workflow-control-console-for-the-ai-era
27. 中国开发者约 940 万：https://www.itiger.com/hans/news/1160903841 ；https://m.thepaper.cn/newsDetail_forward_30035216
28. Trae 与 IDC 份额：https://news.qq.com/rain/a/20251229A065ZX00 ；https://www.jiemian.com/article/14788309.html
29. 腾讯 CodeBuddy：https://www2.yicaiglobal.com/news/chinas-tencent-mulls-workflow-changes-as-85-of-its-programmers-use-codebuddy-ai-coding-assistant
30. ChinaTalk / ChinAI：https://www.chinatalk.media/p/what-are-chinese-people-vibecoding ；https://chinai.substack.com/p/chinai-367-claude-codes-future-in
31. 深圳宏键盘 Alibaba 挂牌：https://www.alibaba.com/price-comparison/12-key-macropad ；https://electronics.alibaba.com/product/hot-keys
32. AI 硬件融资：https://pulse2.com/hark-700-million-series-a-raised-for-personalized-ai-and-hardware-platform/ ；https://siliconangle.com/2026/02/04/positron-ai-raises-230m-1b-valuation-build-energy-efficient-ai-accelerator-hardware/ ；https://siliconangle.com/2026/09/28/physical-ai-custom-chip-producer-sima-ai-raises-150m-at-1-45b-valuation/
33. 可穿戴/个人 AI 硬件融资：https://www.uctoday.com/devices-workspace-tech/sandbar-ai-voice-note-taking-ring/ ；https://pulse2.com/pocket-raises-11-million-to-expand-personal-ai-assistant-device/amp/ ；https://pulse2.com/taya-5-million-seed-funding/amp/ ；https://india.entrepreneur.com/?p=97928 ；https://amp.kr-asia.com/chinas-guangfan-positions-ai-wearables-as-the-next-computing-platform
