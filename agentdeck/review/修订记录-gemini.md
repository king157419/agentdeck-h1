# AgentDeck 竞品与市场文档 v2 修订记录（Gemini）

> **修订角色**：AgentDeck 竞品与市场负责人  
> **修订日期**：2026-11-17  
> **对齐依据**：`research/strategy-core.md`『二点六、审稿后决策 v2（D1–D9）』及 `review/投资人审阅-gemini.md`  
> **体例说明**：三份正式文档均完整保留原有章节骨架、原有来源脚注编号（不打乱旧引用序号，新核实来源顺延追加至文末）及【估算】/【待核实】标记；凡有实质改动的小节标题后均统一加上『（v2 修订）』，未改动小节（如 `02` 中 Stream Deck 单节）保持原标题不变。

---

## 一、`02-竞品分析.md` 修订要点

1. **确立 Codex Micro 对标主线并核实硬件细节（§一、§三.1、§四、§六）**
   - 按 `strategy-core.md` §二点五及 D1/D3，将 **Codex Micro（$230）** 明确定为唯一产品形态、功能与叙事标杆。
   - **消除原【待核实】项**：经 PCMag 与 CNET 实测报道核实，确认 Codex Micro **机身确无内置麦克风**（语音键仅触发电脑端现有麦克风）；同时核实 Work Louder Creator Micro 2 官网起售价为 **$168**（附脚注 `[41]`）。
2. **补全并更正 Logitech MX Keypad（§一、§二、§三.3、§四）**
   - **消除全部原【待核实】项**：补入 **2026-09-08 独立发布**、官方零售价 **$99.99**（附赠 3 个月 Copilot Pro+）、9 颗全彩 LCD 硅胶薄膜键、**无内置麦克风 / 无旋钮**、官方原生支持 **GitHub Copilot / Claude Code / OpenAI Codex**，以及提供 **Logi Actions SDK**（Node.js / C#）（附脚注 `[43]`）。
   - 明确其 $99.99 售价对海外初创硬件的价格封顶效应，直接支撑 v2 单款定 **$99（早鸟 $79）** 的决策（D2）。
3. **更正 VibeKeys 麦克风配置与钩子集成深度（§一、§三.2、§四）**
   - **更正硬件配置**：核实官网规格表，仅 **$99 的旗舰 Max 内置麦克风并配单块小屏**，低配 **Pro（$29～39）/ Plus（$49）均无内置麦克风**（仅快捷键触发电脑听写）。
   - **更正软件集成**：纠正原稿"纯键位映射"推断，核实其开源仓库 `second-state/vibekeys_app`（`vibekeys claude`）已接入 Claude Code 的 `SessionStart`、`PreToolUse`、`Notification`、`PermissionRequest` 等钩子向 Max 推状态，并通过 `second-state/vibetty`（MQTT）做远程终端桥接（附脚注 `[42]`）。
4. **更正 Ulanzi AU05 Vibe Key 生态属性，新增 D200 + 同名免费插件分析（§一、§二、§三.7、§四）**
   - **更正 AU05 Vibe Key（SKU I018）**：删除原稿"锁死/绑定腾讯生态"的错误定性——腾讯 WorkBuddy 仅为国内联名入口，标准版海内外通售，底层走通用 **Ulanzi Studio（V3.2.0+）** 支持自由映射 Claude Code、Codex、ChatGPT、千问、豆包等（附脚注 `[44]`）；同时将 AU05 从格局图的"平台绑定型"移入"通用控制器 / 多平台 AI 键盘"。
   - **补入 Ulanzi D200 系列 + `puritysb/AgentDeck`**：补充 D200 / D200H / D200X（13～14 键薄膜 LCD，海外 $59.99～99.99，国内电商日常 ¥298～598、大促补贴低至 ¥260～290，无麦克风），并指出同名开源项目 **`puritysb/AgentDeck`** 已上架 **Mac App Store** 且作为**免费插件上架优篮子官方 `Ulanzi Studio Marketplace`（`ugc.ulanzistudio.com`）**（附脚注 `[45]`），证伪原 OEM 授权收入假设（D4）。
5. **联动调整 Keychron F4 HE 结论与更正 `claude-desktop-buddy` 覆盖范围（§三.5、§三.6）**
   - **Keychron F4 HE（$34.99）**：同步 D2 砍掉原 $59 / ¥299 Lite 款的决策，改为用免费软件兼容普通宏键盘承担低端引流。
   - **`claude-desktop-buddy`**：更正原稿"不含 Claude Code"表述——核实其通过 Claude Desktop BLE 桥接，**已支持 Claude Desktop 内的 Claude Code 与 Claude Cowork 权限提示**（仍不支持脱离 Claude Desktop 的独立终端 CLI，锁死 Anthropic 生态）。
6. **更新功能与价格对比矩阵（§四）**
   - 新增 `Ulanzi D200 + puritysb/AgentDeck` 行，订正全部对手参数。
   - 将 **AgentDeck（暂名）** 更新为 v2 单款主力方案：**¥499（早鸟 ¥399）/ $99（早鸟 $79）**、**混合结构**（3.2–3.5" 6 等分长条 IPS 屏 + 6 矮轴会话键 + 3 大机械键 + 金属滚轮）、板载 MEMS 麦、海外+国产 CLI+云端异步 agent（P1）、钩子防串窗直答+高危操作物理二次确认、控制软件免费兼容第三方外设。
7. **更正 CtrlVibe 众筹失败平台归因与预热对策（§五）**
   - 更正众筹主阵地为 **Kickstarter**（59 人支持、HK$80,514，实质失利，附脚注 `[46]`），明确 **PledgeBox 仅是赛后地址收集与履约工具**，删去"PledgeBox 平台流量小"的错误归因。
   - 对策对齐 D6/D7：先跑双平台免费软件真实留存（30～50 名重度用户 D14 留存、2,000+ WAU）与 **$1 VIP 订金预约池（≥1,500 人）** 后再开模。
8. **以 Codex Micro 为对标主线重写『威胁评估』（§六）**
   - 围绕"跨生态版 Codex Micro"生存空间重构六大威胁：将 **"$99.99 罗技 MX Keypad + Stream Deck + 优篮子 D200 免费插件截胡"** 与 **"官方默认 Auto Mode + 云端异步 agent 掏空手动审批器"** 列为双头号现实威胁（附脚注 `[47]`），逐项对齐 D1–D5 应对策略。

---

## 二、`03-差异化.md` 修订要点

1. **按 D1–D3 重写核心定位陈述（§一）**
   - 路演一句话定位更新为：**"跨所有 agent 的 Codex Micro + 高危操作的物理二次确认"**（删除原初稿"不卖更便宜的 Codex Micro"的冲突表述）。
   - 融入 D1 混合硬件形态、D2 单款 ¥499 / $99 价格卡位，以及 D3"日常低风险命令交给官方 Auto Mode，设备聚焦 `git push`、生产 `ssh/kubectl`、数据库写入、改密钥、合并 PR 等不可逆高危操作，并把槽位扩展至云端 agent（P1）"。
2. **重构 5 个差异化点，剔除站不住的论据并诚实写明可复制性（§二）**
   - **清理全部站不住的旧说法**：删去"优篮子绑定腾讯"、"6 块独立小屏"、"深圳供应链成本碾压国内对手"、"自建分类器比官方更准"、"向优篮子收 OEM 授权费"及"靠静态策略文件收团队费"。
   - **新版 5 大差异点及可复制性定级**：
     1. *全生态中立调度（海外 CLI + 国产 CLI + 云端异步 agent）*（被抄难度：**中**，大厂不愿抄，第三方需持续投入双端钩子维护）；
     2. *会话级真控制（底层钩子防串窗直答 + 板载对讲锁槽位）*（被抄难度：**中**，单点钩子易抄，双端异常边界防误报难抄）；
     3. *高危操作的物理二次确认（对齐 Auto Mode 时代的硬件 2FA）*（补入 Anthropic 官方 Auto Mode 核实数据：97% 人工盲批率、1,053 名测试者人工仅拦 13.6% vs 官方分类器拦 89%；被抄难度：**低～中**，长按交互易抄，壁垒在跨厂商安全网关与企业合规闭环）；
     4. *"长条屏 + 真机械轴 + 板载麦克风"混合结构*（被抄难度：**低 / 高可复制**，诚实写明无硬件专利，深圳大厂 6 个月可跟进开模，仅作首轮单品错位入场券）；
     5. *免费软件兼容现成外设引流 + 单款硬件与 Pro/Team 双层订阅*（对齐 D4：个人 Pro ¥19/月或 $3.99/月含懂代码函数名/文件名语音纠错、手机只读看板、云端桥接；企业 Team ¥39–59/人/月含飞书/企微/钉钉/Okta SSO、私有化合规仪表盘、MCP 白名单；删去优篮子 OEM 授权；被抄难度：**低～中高**）。
3. **重写定价阶梯为单款 ¥499 / $99 正面对标四大竞品（§三）**
   - 按 D2 砍掉原 Lite（¥299/$59）、推迟原 Pro（¥999/$199），构建"免费软件 → 单款主力硬件 ¥499/$99（早鸟 ¥399/$79）→ 个人 Pro → 企业 Team"矩阵。
   - 逐一列出对标 **Logitech MX Keypad（$99.99）**、**VibeKeys Max（$99）**、**Codex Micro（$230）**、**Ulanzi AU05 Vibe Key（¥269～299，附参照 D200）** 的价格优势与体验增量，并重申拿到深圳工厂书面 BOM 报价前不乱报毛利率的纪律（D7）。
4. **更新改名建议与商标核查提醒（§四）**
   - 详述 `puritysb/AgentDeck` 上架 Mac App Store 与优篮子商店造成的严重撞名；按 D5 **彻底删除 `Conductor Key`**，保留定名前文档写 `AgentDeck（暂名）` 的约定。
   - 列出中文首选 **点将台** 及英文候选 **Baton / HelmPad / MuxKey**，全部标注商标状态 **【待核实】**。
   - **新增 Google 检索预警**：查实 GitHub 上已存在 `mraza007/baton`、`DaveGerson/agent-baton`、`cablate/baton` 等多个 AI 编码 agent 编排项目（附脚注 `[52]`），提示若选 `Baton` 须高度警惕开源重名及 USPTO 第 9/42 类在先商标风险，而 `HelmPad`、`MuxKey` 暂无知名同类开源撞车；附 CNIPA / USPTO / 应用商店 / 域名核查清单。

---

## 三、`01-市场调研.md` 修订要点

1. **更新全球专业开发者人口至 JetBrains 2026 口径并重算 TAM / SAM / SOM（§四）**
   - 基础人口更新为 JetBrains 2026 年最新口径 **约 2,200 万职业开发者**（2024 年 1,960 万、2025 年 2,080 万，附脚注 `[22]`）。
   - 保持 40%（区间 31%～59%）agent 使用率、33% 多 agent 比例、50% 可触达假设、1%～3% 三年 SOM 份额**全部不变**，同步对齐 D2 单款标准零售价 **$99（海外）/ ¥499（国内）**，完整展示每一步算式：
     - 全球 agent 使用者：`2,200 万 × 40% = 880 万人`（区间 682 万～1,298 万）；
     - 全球 **TAM**：`880 万 × $99 ≈ 8.7 亿美元`（区间 6.8 亿～12.9 亿美元）；
     - 全球多 agent 使用者：`880 万 × 33% = 290.4 万人`（约 290 万）；
     - 全球 **SAM**：`290.4 万 × $99 ≈ 2.9 亿美元`；
     - 全球可触达（50%）：`145.2 万人，约 1.4 亿美元`；
     - 全球 **3 年 SOM（1%～3%）**：`1.45 万～4.36 万台，约 144 万～431 万美元`。
   - **附纯人口变动对照值**：在表下明确列出若维持原初稿 $115 混合均价不变、仅更新 2,200 万人口的算式结果（TAM 约 10.1 亿美元、SAM 约 3.3 亿美元、SOM 约 167 万～501 万美元），便于审阅人直观拆解人口增长（+5.8%）与单品调价（-13.9%）各自的影响。
   - **中国部分保持单独测算**：查实 940 万出处为工信部在 2024-12 武汉开放原子开发者大会公布的数据（附脚注 `[50]`），因属广义口径继续独立计算、不与全球相加；按 D2 国内单款标价 ¥499 重算得中国 **TAM 约 16.4 亿元**、**SAM 约 3.3 亿元**、**3 年 SOM 为 3,300～9,900 台（约 165 万～494 万元）**；全球+国内三年硬件 SOM 合计 **约 1.8 万～5.4 万台、约 1,200 万～3,600 万元人民币**【估算】。
2. **补齐 Cursor $4B ARR 与云端 agent 迁移趋势及其战略影响（§五、§七）**
   - 在第五节补入 **Cursor（Anysphere）年化收入突破 40 亿美元（$4B ARR，企业占比约 75%）及被 SpaceX 约 600 亿美元收购**（标明二手创投数据库与媒体报道口径，附脚注 `[51]`），以及 **Cursor Cloud Agents**、Cursor 3 `Agents Window`、GitHub Copilot coding agent（超 100 万个 PR）推动的云端异步并行浪潮（附脚注 `[52]`）。
   - 新增《深度研判：Cursor $4B ARR 与"云端 agent 迁移趋势"对我们的影响》专节及第七节风险项：剖析云端容器不触发本机终端 hook 对纯本地控制器的掏空风险，推导 D3（6 个槽位升级为"本地 CLI + 云端异步任务统一槽"，P1）与 D4（云端桥接 + 手机看板构成个人 Pro / 企业 Team 持续订阅抓手，本地硬件守住最终 `git push` / 合 PR 等高危物理确权）。
3. **同步拉齐全文用户愿付价格、中国竞品事实与路演前 6～8 周验证清单（§一、§二、§三、§六、§八）**
   - 更新用户画像愿付价格为单机 $99 / ¥499 + 个人 Pro（$3.99 / ¥19/月）+ 企业 Team（¥39–59/人/月）；
   - 更正罗技 MX Keypad（2026-09 发布，$99.99）、优篮子 AU05 非锁死腾讯、优篮子 D200 免费同名插件、CtrlVibe Kickstarter 众筹事实；
   - 将第八节"下一步验证"全面替换为 D6/D7 的 6～8 周五项硬核实测与分期交割开模触发线（WAU ≥ 2,000 且众筹锁定 ≥ ¥50 万或 $1 订金 ≥ 1,500 人）。

---

## 四、本次新增 Google 搜索核实来源汇总

| 核实事项 | 核实结论 | 附入文档的 URL |
|---|---|---|
| Logitech MX Keypad 价格、发布时间与生态 | 2026-09-08 独立发布，售 $99.99，9 键 LCD 薄膜键，无内置麦，原生支持 Copilot / Claude Code / Codex，提供 Actions SDK | https://www.logitech.com/en-us/products/keyboards/mx-keypad.html <br> https://9to5mac.com/2026/09/08/logitech-mx-keypad-99-ai-coding/ <br> https://github.com/logitech/actions-sdk-docs |
| Codex Micro 麦克风与原型机价格 | PCMag / CNET 实测无内置麦克风；Work Louder Creator Micro 2 官网 $168 起 | https://www.pcmag.com/news/i-got-my-hands-on-openais-sold-out-codex-micro-who-is-this-230-vibe-coding <br> https://www.cnet.com/tech/computing/coding-with-openais-codex-micro-keypad-the-vibes-are-bad/ <br> https://worklouder.cc/creator-micro/ |
| VibeKeys 麦克风与 Claude Code 钩子 | 仅 Max（$99）内置麦克风，Pro/Plus 无；`vibekeys_app` 已接入 Claude Code 事件钩子，`vibetty` 走 MQTT 桥接 | https://vibekeys.dev/ <br> https://vibekeys.dev/vibekeys-max <br> https://github.com/second-state/vibekeys_app <br> https://github.com/second-state/vibetty |
| Ulanzi AU05 Vibe Key 与 D200 同名插件 | AU05 走通用 Ulanzi Studio，非锁死腾讯；`puritysb/AgentDeck` 已免费上架优篮子官方插件商店及 Mac App Store | https://www.ulanzi.com/products/au05-vibe-key-ai-voice-input-keypad-i018 <br> https://docs.ulanzistudio.com/vibekey/au05 <br> https://ugc.ulanzistudio.com <br> https://github.com/puritysb/AgentDeck |
| CtrlVibe 众筹平台与成绩 | Kickstarter 主场仅 59 人支持、HK$80,514；PledgeBox 仅作履约管理 | https://www.kickstarter.com/projects/ctrlvibe/ctrlvibe-ai-workflow-console-for-coders-and-creators <br> https://www.pledgebox.com/projects/ctrlvibe-ai-keyboard-workflow-control-console-for-the-ai-era |
| `claude-desktop-buddy` 覆盖范围 | 通过 Claude Desktop BLE 桥接，支持 Desktop 内的 Claude Code 与 Cowork | https://github.com/anthropics/claude-desktop-buddy |
| JetBrains 2026 职业开发者与中国 940 万出处 | JetBrains 2026 约 2,200 万（2025 为 2,080 万）；中国 940 万出自 2024-12 开放原子开发者大会工信部披露 | https://www.jetbrains.com/lp/devecosystem-data-playground/ <br> https://finance.sina.com.cn/jjxw/2024-12-22/doc-inecywuz7462198.shtml <br> http://www.stdaily.com/index/kejixinwen/202412/1154f8f4a130424599a8039c381c8b3f.shtml |
| Cursor $4B ARR、Cloud Agents 与 Auto Mode | Cursor 2026-06 破 $4B ARR（企业占 ~75%），Cloud Agents 驱动异步云端迁移；Claude Code Auto Mode 默认开启（97% 盲批，1,053 人实验人工拦 13.6% vs AI 拦 89%） | https://dealroom.co/news/134107-cursor-tops-4b-annualized-revenue/ <br> https://cursor.com/agents <br> https://www.anthropic.com/research/claude-code-auto-mode |
| 候选英文名开源撞名初筛 | `Baton` 在 GitHub 已有多个 Claude Code / 多 agent 编排同名项目；`HelmPad`、`MuxKey` 暂无知名重名；商标均【待核实】 | https://github.com/mraza007/baton <br> https://github.com/DaveGerson/agent-baton <br> https://github.com/cablate/baton |
