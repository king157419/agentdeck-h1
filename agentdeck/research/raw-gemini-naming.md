# 品牌命名与中美商标/生态撞名初筛报告（Gemini）

- **调研日期**：2026-11-17
- **产品定位**：面向开发者的桌面多 AI Agent 硬件控制器（带状态条形屏的机械按键/滚轮外设 + 跨平台守护软件 + 个人 Pro / 团队版 SaaS 订阅）
- **目标商标类别**：
  - **中国（CNIPA）**：第 9 类（核心群组 `0901` 计算机外设/键盘/可下载软件、`0908` 麦克风）+ 第 42 类（核心群组 `4220` 软件开发/SaaS 云计算服务、`4209` AI 技术研究）
  - **美国（USPTO）**：International Class 009（计算机硬件外设、键盘、可下载软件）+ Class 042（SaaS、PaaS、AI 软件技术服务）
- **核查声明（重要）**：
  1. 本报告基于 **Google 公开网页检索**（涵盖 USPTO 公开聚合索引 Justia / Trademarkia、企业工商公开报道、GitHub、Apple App Store 及公共域名索引）完成，**仅作为早期命名淘汰初筛（Preliminary Knock-out Screening），不能替代官方商标库全量检索及法律意见**。
  2. 严格遵循实证原则：**不编造任何商标注册号/申请号**；中国商标网（CNIPA）因官方库需实名登录交互查询且存在动态反爬限制，Google 公开静态页面未披露具体注册号的均如实标注**“未找到”**；域名未见公开建站且无法通过搜索确认实时 WHOIS 归属的均标注**“未见活跃建站（精确注册状态未知）”**。
  3. 正式定名、开模丝印、上线众筹及递交商标申请前，**必须委托中国备案商标代理机构及美国执业商标律师（US Licensed Trademark Attorney）进行正式全量检索（Full Clearance Search，含普通法未注册在先使用排查）**。

---

## 一、 现有 5 个候选名撞名排查总览表

| 候选名 | 类型 | 中美第 9/42 类商标公开冲突 | 同名产品 / 开源 / 商店冲突 | `.com` / `.cn` / `.dev` 占用 | 风险评级 | 一句话结论 |
|---|---|---|---|---|---|---|
| **AgentDeck**<br>*(现用暂名)* | 英文 | 精确同名未见美标注册，但直撞海盗船/Elgato **STREAM DECK** 及 Valve **STEAM DECK** 第 9 类核心商标 | **极严重**：GitHub 至少 4 个同名 AI Agent 工具；`puritysb/AgentDeck` 已占 App Store、Google Play、Elgato 及优篮子商店 | `.com`/`.cn`/`.dev` 未见建站索引，但 `.co`/`.site`/`.org` 已被占用 | **高（极高）** | 同赛道开源与商店完全撞车 + 大厂 `-Deck` 商标异议高危，**必须更换** |
| **Baton** | 英文 | 美标第 9/42 类已有多枚 **BATON** 申请/注册（如 Serial `99679424`、`86969000` 等） | **极严重**：海外已有同名多 AI 编程 Agent 并行编排桌面端 `getbaton.dev`，App Store 有 `Baton - Claude Code & Codex` | `.com` 已建站（Baton Market）；`.dev` 生态已被开发者工具占用；`.cn` 未知 | **高** | 与海外多 AI 编程编排器 100% 撞名且通用词美标拥挤，**建议淘汰** |
| **点将台** | 中文 | Google 公开页未见具体注册号（未找到），但多家同名科技公司及存续软件大概率已布局第 9/42 类 | **较重**：GitHub 已有同名 AI Agent 编排器 `codex-cc-orchestrator`；另有 TimeTec 点将台云考勤、西部证券“点将台”AI 投顾模块 | `.com` / `.cn` 均已被注册持仓（未见活跃头部科技官网）；`.dev` 未知 | **中高** | 国内企业字号、SaaS 考勤与开源 Agent 项目多重撞名，**建议改用低冲突变体** |
| **HelmPad** | 英文 | 精确同名 `HELMPAD` 未找到注册；但 Linux 基金会在第 9 类持有核心注册商标 **HELM**（Reg `5253796`） | 无同名科技产品；但英语中 `helm pad` 是船用驾驶台防滑脚垫的通用商品名 | `.com` / `.cn` / `.dev` 均未见活跃科技建站（精确 WHOIS 未知） | **中** | 存在 `HELM` 第 9 类近似引证风险，且海外搜索首屏全是船用泡沫脚垫 |
| **MuxKey** | 英文 | 精确同名 `MUXKEY` 未找到注册；近似前缀有 **Mux, Inc.** 第 42 类 `MUX`（Serial `99679661`）及 **MuxLab** 第 9 类商标 | 无同名商业产品或 App；但国内高校体系结构课（一生一芯）Verilog 模板模块名为 `MuxKey` | `.com` / `.cn` / `.dev` 均未见活跃建站（精确 WHOIS 未知） | **低—中** | **原候选名中最干净**，极客味足，仅需正式核验 `MUX` 前缀近似度 |

---

## 二、 现有 5 个候选名逐一深度排查与风险分析

### 1. 现用暂名：`AgentDeck`

1. **已有同名或近似商标（公开记录）**
   - **精确同名商标**：USPTO 公开索引（Justia / Trademarkia）及中国公开网页检索中，**未找到** `AgentDeck` 或 `Agent Deck` 在第 9 类或第 42 类的已注册商标记录。
   - **高危近似商标（第 9 类硬件控制器核心壁垒）**：
     - **`STREAM DECK`**：权利人为 **Corsair Memory, Inc.（美商海盗船 / Elgato 母公司）**，覆盖第 9 类桌面按键控制器硬件与配套配置软件（公开可查申请记录包括 USPTO Serial No. `97327361` 等系列家族商标，检索入口：[USPTO Trademark Search](https://tmsearch.uspto.gov/)）。由于本产品直接服务同一用户群且免费软件兼容 Stream Deck，使用 `AgentDeck` 销售自有硬件极易触发 Corsair 以商标近似混淆（Likelihood of Confusion）发起异议或平台投诉。
     - **`STEAM DECK`**：权利人为 **Valve Corporation**，覆盖第 9 类便携式计算机与第 28 类游戏控制器硬件（USPTO Serial No. `90827161`，马德里国际注册号 `1621539`，公开记录参考：[Justia Serial 90827161](https://trademarks.justia.com/media/image.php?serial=90827161)）。
2. **同名产品 / 公司 / 开源项目（AI、开发者工具、外设领域）**
   - **同赛道重度撞车（均聚焦 AI Coding Agents 管理与硬件面板）**：
     1. **`puritysb/AgentDeck`**：开源本地看板与物理控制面板，支持 Claude Code / Codex / OpenCode，原生适配 Stream Deck、ESP32 屏幕、墨水屏及移动端，并已上架优篮子与 Elgato 插件市场（GitHub：[puritysb/AgentDeck](https://github.com/puritysb/AgentDeck)，文档站：[puritysb.github.io/AgentDeck](https://puritysb.github.io/AgentDeck/)）。
     2. **`asheshgoplani/agent-deck`**：基于 Go + tmux 的多 AI 编程智能体（Claude、Gemini、Codex、OpenCode）终端会话管理器（GitHub：[asheshgoplani/agent-deck](https://github.com/asheshgoplani/agent-deck)）。
     3. **`a-streetcoder/agent-deck`**：macOS 原生多 AI 编程 Agent、Prompt 与 Skills 项目级管理应用（GitHub：[a-streetcoder/agent-deck](https://github.com/a-streetcoder/agent-deck)，官网：[agentdeck.site](https://agentdeck.site/)）。
     4. **`brushknight/agents-deck`**：同类多 Agent 可视化监控开源仓库（GitHub：[brushknight/agents-deck](https://github.com/brushknight/agents-deck)）。
   - **跨行业同名平台**：`agentdeck.co` 为面向房产经纪人（Real Estate Agents）的 AI 自动化工作流与 CRM 商业平台。
3. **域名占用情况（`.com` / `.cn` / `.dev`）**
   - **`agentdeck.com`**：Google 搜索无页面索引（`site:agentdeck.com` 为 0 结果），未见活跃建站，精确注册归属未知（但近似域名 `agentdeck.co`、`agentdeck.site`、`agentdeck.org` 均已建站占用）。
   - **`agentdeck.cn`**：Google 无索引，精确注册归属未知。
   - **`agentdeck.dev`**：Google 无公开页面索引，精确注册归属未知。
4. **App Store / GitHub 撞名情况**
   - **Apple App Store**：已被 `puritysb` 同名应用占用——[AgentDeck Dashboard (id6742716174)](https://apps.apple.com/app/agentdeck-dashboard/id6742716174)。
   - **Google Play / Elgato Marketplace**：已被占用——Google Play 包名 `com.puritysb.agentdeck`（[Google Play 链接](https://play.google.com/store/apps/details?id=com.puritysb.agentdeck)），Elgato 插件商店亦已上架同名插件（[Elgato Marketplace](https://marketplace.elgato.com/)）。
   - **GitHub**：如上所述，至少 4 个高度重合的活跃仓库。
5. **风险评级与理由**：**高风险（极高）**
   - **理由**：同赛道软硬件开源项目已抢先完成全渠道（GitHub + iOS/macOS App Store + Google Play + Elgato 商店 + 优篮子商店）命名卡位，继续沿用不仅面临 App Store 审核重名拦截和 SEO 完全失焦，还会招致开发者社区“商业公司抢占开源项目名称”的舆论反噬，同时背负海盗船 `STREAM DECK` 第 9 类硬件商标维权风险。**路演前必须换名。**

---

### 2. 英文候选：`Baton`

1. **已有同名或近似商标（公开记录）**
   - **USPTO 第 9 / 42 类同名商标（公开可查记录）**：
     - **`BATON`**（申请人：**Bracket Company, Inc.**）：2026-03-03 提交，覆盖 **Class 009**（可下载计算机软件/加密钱包软件）及 Class 036，Serial No. `99679424`（公开链接：[Trademarkia - BATON 99679424](https://www.trademarkia.com/baton-99679424)）。
     - **`BATON`**（申请人：**Baton LLC**）：覆盖软件通信应用相关类别，Serial No. `86969000`（公开检索入口：[Justia Trademarks](https://trademarks.justia.com/)）。
     - **其他存续软件品牌商标**：金融分布式账本软件商 **Baton Systems**（[batonsystems.com](https://www.batonsystems.com/)）及音视频 AI 自动质检软件商 **Interra Systems**（旗下核心软件产品名为 **BATON**）均在企业软件领域长期使用该标识（具体注册号在 Google 静态摘要中未直接暴露，需在 [USPTO Trademark Search](https://tmsearch.uspto.gov/) 内核查）。
   - **中国 CNIPA 第 9 / 42 类**：Google 公开网页**未找到**静态公开的具体注册号记录（注：手电筒大厂傲雷 Olight 旗下经典产品线名为 Baton，主要在第 11 类，但大厂常在第 9 类电池/充电器/智能控制做防御注册，需进 CNIPA 核实）。
2. **同名产品 / 公司 / 开源项目**
   - **同赛道直接竞品撞名（致命冲突）**：
     - **Baton（`getbaton.dev`）**：由挪威 **Tafjord Invest AS** 开发的桌面应用程序，核心功能正是**“通过 git worktrees 并行运行、监控和编排多个 AI 编程 Agent（Claude Code、Codex、Cursor 等）”**（官网：[getbaton.dev](https://getbaton.dev/)）。与本产品的软件定位及目标受众完全重合！
     - **Baton（`trybaton.dev`）**：面向 CLI 与多 AI 编程助手的 `Baton.md` 规则与上下文同步开发者工具（官网：[trybaton.dev](https://trybaton.dev/)）。
   - **其他知名科技产品与公司**：
     - **ConductorOne Baton**：知名开源身份治理与权限审计 CLI 框架（GitHub：[ConductorOne/baton](https://github.com/ConductorOne/baton)）。
     - **Baton AI**：由 Pear VC / Lobby Capital 投资的企业级 AI 部署与 POC 自动化平台（官网：[getbaton.ai](https://getbaton.ai/)）。
     - **Baton Corporation**：知名区块链基础设施开发公司（官网：[batoncorporation.com](https://www.batoncorporation.com/)）。
   - **键盘外设领域**：未发现主流客制化或量产机械键盘直接命名为 `Baton`。
3. **域名占用情况（`.com` / `.cn` / `.dev`）**
   - **`baton.com`**：**已明显被占**，现为中小企业估值与并购交易平台 Baton Market 官网（[baton.com](https://www.baton.com/)）。
   - **`baton.cn`**：Google 索引为 0 结果，未见知名建站，精确注册归属未知（单单词 `.cn` 通常早已被注册）。
   - **`baton.dev`**：**已被占用**（关联开发者与 QA 工具集生态，且同赛道竞品已启用 `getbaton.dev` 与 `trybaton.dev`）。
4. **App Store / GitHub 撞名情况**
   - **Apple App Store（重度撞名）**：
     - [Baton - Claude Code & Codex (id6735626960)](https://apps.apple.com/app/baton-claude-code-codex/id6735626960)（开发者工具，直接点名 Claude Code 与 Codex！）
     - [Baton: API Client (id6738317772)](https://apps.apple.com/app/baton-api-client/id6738317772)（支持 MCP 与 AI Agent 的 Git 原生 API 客户端）
     - 另有 `Baton Agent`、`baton. - the handoff timer` 等多款同名应用。
   - **GitHub**：`ConductorOne/baton` 及大量 `baton-*` 仓库占据搜索前列。
5. **风险评级与理由**：**高风险**
   - **理由**：“指挥棒（Baton）”是所有做多 Agent 编排的开发者最容易想到的第一个英文单词，导致 `getbaton.dev`、`trybaton.dev` 以及 App Store 上的 `Baton - Claude Code & Codex` 已经扎堆抢占同一细分人群；叠加通用英文单词在 USPTO Class 9/42 的高驳回率与 `.com`/`.dev` 域名缺失，**建议直接放弃**。

---

### 3. 中文候选：『点将台』

1. **已有同名或近似商标（公开记录）**
   - **中国 CNIPA 第 9 / 42 类**：Google 公开网页**未找到**具体商标注册号静态记录（需登录 [中国商标网 sbj.cnipa.gov.cn](https://sbj.cnipa.gov.cn/) 核查）；但公开工商报道与企业信用平台检索显示，国内有多家以“点将台”为商号的存续科技及投资公司，且在多类别做过商标申请，第 9 类（0901）与第 42 类（4220）存在较高的在先权利阻塞概率。
   - **美国 USPTO 第 9 / 42 类**：未找到“点将台”汉字或拼音 `Dianjiangtai` 的美国商标记录。
2. **同名产品 / 公司 / 开源项目**
   - **AI 与开发者工具领域（直接撞名）**：
     - **点将台：可迁移的 Agent 分层协作编排器（`codex-cc-orchestrator`）**：GitHub 上已存在的开源项目，主打多 AI Agent（Codex / Claude Code）任务派发、会话续跑与独立审查（GitHub：[xiangshazaosha/codex-cc-orchestrator](https://github.com/xiangshazaosha/codex-cc-orchestrator)）。
     - **点将台 · PoE 交易市集助手**：开发者 `ZuiDaPanda` 发布的浏览器扩展插件。
     - **阿里/淘宝内部技术架构代称**：早期技术博客公开披露淘宝曾将底层个性化内容分发系统命名为“点将台”。
   - **商业软硬件产品与同名科技公司**：
     - **TimeTec 点将台云系统系列**（跨国厂商 TimeTec Computing / FingerTec）：长期在华销售软硬件结合的“点将台云考勤系统、点将台云门控系统、点将台云访客系统”（官网：[timeteccloud.com](https://www.timeteccloud.com/) / [fingertec.com](https://www.fingertec.com/)）——注意其“考勤门禁终端硬件 + 云端 SaaS”正好横跨第 9 类与第 42 类！
     - **同名科技公司**：**四川点将台科技有限公司**（2016 年成立，官网 `http://www.scdjt.cn/`，企业库参考 [企查查](https://www.qcc.com/)）、**河南点将台网络科技有限公司**（2019 年成立）、**兰州点将台科技产业发展有限公司**等。
3. **域名占用情况（`dianjiangtai.com` / `.cn` / `.dev`）**
   - **`dianjiangtai.com`**：公开记录显示历史上曾被注册使用，目前无活跃头部科技站点，处于停放/待售或隐私持有状态。
   - **`dianjiangtai.cn`**：公开记录显示已被注册持有，未见活跃商业建站。
   - **`dianjiangtai.dev`**：Google 无索引，未见公开项目占用（精确状态未知）。
4. **App Store / GitHub 撞名情况**
   - **Apple App Store**：无独立以“点将台”为主标题的头部 App，但**西部证券官方 App** 将核心智能投顾与 AI 策略模块命名为“点将台 / 点将台 3.0”（[App Store 西部证券 id1051515473](https://apps.apple.com/cn/app/id1051515473)）。
   - **GitHub**：已有 `xiangshazaosha/codex-cc-orchestrator`（AI Agent 编排器）及 `lizyChy0329/sanguosha-voice`（三国杀点将台）。
5. **风险评级与理由**：**中高风险**
   - **理由**：“点将台”画面感极佳，但正因为属于大众熟知的古典成语式名词，不仅在国内已被多家科技公司注册为企业字号、被 TimeTec 用作软硬件云考勤品牌，甚至在 GitHub 的 Codex/Claude Code 编排小圈子里也已被抢先用作项目名。若在 CNIPA 第 9/42 类核查出在先注册（极大概率），将无法作为核心主商标获准注册，仅适合退居宣传口号（Slogan：“开发者的桌面 AI 点将台”），不建议作为唯一主品牌裸奔。

---

### 4. 英文候选：`HelmPad`

1. **已有同名或近似商标（公开记录）**
   - **精确同名商标**：USPTO 公开索引（Justia / Trademarkia）及中国公开网页检索中，**未找到** `HELMPAD` 或 `HELM PAD` 在第 9 类或第 42 类的申请或注册记录。
   - **核心近似商标（第 9 类重点引证风险）**：
     - **`HELM`**：权利人为 **The Linux Foundation（Linux 基金会）**，覆盖 **USPTO Class 009**（计算机软件，即云原生领域家喻户晓的 Kubernetes 包管理器 Helm），Serial No. `86959819`，**Registration No. `5253796`**（公开链接：[Justia - HELM 86959819](https://trademarks.justia.com/869/59/helm-86959819.html)、[Trademarkia - HELM 86959819](https://www.trademarkia.com/helm-86959819)）。
     - *商标法理提示*：在 USPTO 审查中，`Pad` 在键盘/控制器外设与平板配件上具有较强的商品描述性（Descriptive）。将他人已在第 9 类开发者软件上注册的强显著性商标 `HELM` 直接加上描述词构成 `HelmPad`，存在被审查员援引 Section 2(d) 判定与 `HELM` 构成近似混淆的中等风险。
2. **同名产品 / 公司 / 开源项目**
   - **AI、开发者工具、键盘外设领域**：未找到名为 `HelmPad` 的软硬件产品或开源项目。
   - **传统实体行业通用词冲突（SEO 噪音）**：在英语航海与游艇配件行业，**“helm pad”是标准通用产品名称**，指铺设在船长舵台（Helm）下方的 EVA 防滑减震泡沫脚垫（主要品牌包括 DEKit [dekit.com](https://dekit.com/)、Deckpad [deckpad.com](https://deckpad.com/) 等）；另有传统家居衬垫厂商 *Helm Pad Company*（[helmpadcompany.com](https://helmpadcompany.com/)）。
3. **域名占用情况（`.com` / `.cn` / `.dev`）**
   - **`helmpad.com`**：未见主流科技产品建站索引（精确 WHOIS 归属未知，需防传统船用脚垫商或米农持有）。
   - **`helmpad.cn` / `helmpad.dev`**：Google 均无页面索引，未见明显占用（精确状态未知）。
4. **App Store / GitHub 撞名情况**
   - **Apple App Store**：无名为 `HelmPad` 的应用（但开发者分类下有知名上架工具 **Helm for App Store Connect**，开发商 Modum B.V.）。
   - **GitHub**：无知名活跃同名仓库。
5. **风险评级与理由**：**中风险**
   - **理由**：虽然精确同名在科技圈空白，但面临双重掣肘：一是开发者心智与第 9 类商标已被 Kubernetes `HELM` 牢牢占据；二是海外买家在 Google 搜索 `HelmPad` 时满屏皆是游艇防滑脚垫，品牌早期需要额外花费营销成本洗刷品类认知。

---

### 5. 英文候选：`MuxKey`

1. **已有同名或近似商标（公开记录）**
   - **精确同名商标**：USPTO 公开索引（Justia / Trademarkia）及中国公开网页检索中，**未找到** `MUXKEY` 或 `MUX KEY` 在第 9 类或第 42 类的注册或申请记录。
   - **前缀近似商标记录（需在正式检索中评估共存空间）**：
     - **`MUX`**（申请人：**Mux, Inc.**，知名开发者视频 API 平台 [mux.com](https://www.mux.com/)）：2026-03-03 新递交 **Class 042** 商标申请（涵盖使用人工智能的 SaaS 及 PaaS 软件服务），Serial No. `99679661`（公开归档参考：[Justia 2026-03-03 Filing Log](https://trademarks.justia.com/dates/2026/march/3)）。
     - **`MUXLAB` 及关联标识**（申请人：**MuxLab Inc.**）：专业音视频矩阵、KVM 延长器及控制软件硬件厂商，持有 **Class 009** 控制管理软件及硬件相关申请（如 Serial No. `90854598`，参考：[Justia Serial Block 90854500-90854599](https://trademarks.justia.com/serials/90854500-90854599)）。
     - *商标法理提示*：`MUX` 在电子工程与计算机领域是“多路复用器（Multiplexer）”的公认技术缩写，单一词根垄断力弱于臆造词；合成词 `MuxKey` 用于桌面多 Agent 物理切换键盘时，与视频流 API（Mux, Inc.）及机房广播级 AV 延长器（MuxLab）在具体商品功能上存在一定抗辩区分空间。
2. **同名产品 / 公司 / 开源项目**
   - **商业产品与公司**：AI、开发者工具、客制化键盘领域均**未找到**名为 `MuxKey` 的商业公司或硬件产品。
   - **开源与高校教学代码重名**：在国内著名的开源芯片教学项目**“一生一芯”（OSCC / 南京大学计算机系统基础实验）**及众多学生同步到 GitHub 的数字逻辑仓库中，`MuxKey` 与 `MuxKeyWithDefault` 是标准 Verilog 键值多路选择器模块名（参考：[一生一芯讲义 ysyx.oscc.cc](https://ysyx.oscc.cc/)）。此外，英语搜索 `"Mux key"` 会部分命中 `Mux.com` 的 API Token 密钥文档，以及汽车领域的五十铃牧游侠（Isuzu MU-X）车钥匙（MU-X Key）。
3. **域名占用情况（`.com` / `.cn` / `.dev`）**
   - **`muxkey.com` / `muxkey.cn` / `muxkey.dev`**：Google 检索均无活跃商业建站索引（未明显被占，精确注册状态未知）。
4. **App Store / GitHub 撞名情况**
   - **Apple App Store**：未找到同名应用（搜索结果仅自动纠错至无关的 `Mickey` 类娱乐应用）。
   - **GitHub**：无名为 `MuxKey` 的独立头部开源工具产品，仅散见于上述 CPU 实验课 Verilog 代码片段。
5. **风险评级与理由**：**低—中风险**
   - **理由**：在全部 5 个原有候选名中，**`MuxKey` 是唯一没有同赛道竞品撞名、没有应用商店重名、且极具硬核开发者共鸣（`tmux` 终端多路复用文化 + 硬件多路切换按键）的名字**。唯一扣分项是对非极客略显硬核（偏极客缩写），且需由美国律师确认 `Mux, Inc.` 第 42 类新申请是否会对我方第 42 类 SaaS 服务构成引证障碍。

---

## 三、 新增 5 组中英配对候选名提案与初步撞名排查

结合产品战略内核——**“一个人同时指挥 3～10 个 AI Agent + 长条屏与滚轮切会话 + 高危操作物理二次确认”**，遵循**“短（中文 2～3 字、英文 7～8 字母双/三音节）、好读易拼、避开 `-Deck` 与 `Conductor Key`、兼顾中美商标显著性”**四大原则，提出以下 **5 组全新中英配对候选名**，并逐一完成同等颗粒度的 Google 初筛：

### 新候选总览对比表

| 编号 | 中文名 | 英文名 | 音节与读音 | 核心隐喻（「指挥多个 AI」） | 商标/开源/App Store 初筛 | 域名公开占用 | 初步风险 |
|---|---|---|---|---|---|---|---|
| **N1** | **驭阵** | **ReinPad** | 2 字 / 双音节 `/reɪn pæd/` | 战车御手执六辔驾驭群马（多 AI）+ 关键时刻勒缰防失控（物理确权） | 中美第 9/42 类、GitHub、App Store **全线未见同名冲突** | `.com`/`.cn`/`.dev` 均未见活跃建站 | **低** |
| **N2** | **帅台** | **CueDial** | 2 字 / 双音节 `/kjuː daɪəl/` | 元帅指挥台 + 舞台总监给多路角色发入场信号（`Cue`）+ 右侧滚轮（`Dial`） | 商标、App Store、GitHub 工具均干净（仅一篇 CV 论文用作基准缩写） | `cuedial` 与 `shuaitai` 的 `.com`/`.cn`/`.dev` 均无建站索引 | **低** |
| **N3** | **挥键** | **TaktPad** | 2 字 / 双音节 `/tækt pæd/` | 交响乐指挥棒划出的拍点（`Takt`）+ 指挥之键，零冲突平替 `Baton` | 中美第 9/42 类、GitHub、App Store **全线未见同名冲突**（已避开 `TaktKey`） | `.com`/`.cn`/`.dev` 均无建站索引 | **低** |
| **N4** | **点兵台** | **SquadKey** | 3 字 / 双音节 `/skwɒd kiː/` | 一字平替“点将台”保留军阵神韵 + 按键调度 6 人 AI 特遣小队（`Squad`） | 中美第 9/42 类、GitHub、App Store **均未见同名冲突** | `squadkey.com` 在经纪平台待售（无竞品建站），其余无索引 | **低** |
| **N5** | **司阵** | **MusterKey** | 2 字 / 三音节 `/ˈmʌstər kiː/` | 掌管智能体阵列 + 英语 *Muster* 双关“点兵集结”与 *Pass muster*“审批放行” | 中美第 9/42 类、App Store、商业公司 **全线未见同名冲突** | `musterkey` 与 `sizhen` 的 `.com`/`.cn`/`.dev` 均无建站索引 | **低** |

---

### 新候选逐一排查详情

#### N1. 『驭阵』 / `ReinPad`
- **命名阐释**：`Rein` 源自英语核心习语 *"take the reins"*（执掌大权/手握缰绳）。中国古代御手驾驶驷马/六马战车称为“执辔驭阵”——6 个会话键恰似手中的 6 根缰绳，既能指挥多匹千里马（Claude Code、Codex、Cursor、Qwen Code 等）并驾齐驱，又能在 AI 准备执行 `git push` 或生产库写入时“一指勒缰”（高危物理二次确认）。中英文意象 100% 咬合，短促有力，母语者零理解门槛。
- **公开商标记录**：USPTO 公开库（Justia / Trademarkia / [USPTO Trademark Search](https://tmsearch.uspto.gov/)）第 9/42 类**未找到** `ReinPad`（及近似变体 `ReinKey`）的申请或注册记录；中国公开网页检索第 9/42 类**未找到**“驭阵”已注册知名核心商标记录（需在 [中国商标网](https://sbj.cnipa.gov.cn/) 最终核验）。
- **同名产品 / 公司 / 开源项目**：全球 AI、开发者工具、键盘外设领域均**未找到** `ReinPad` 或“驭阵”同名商业产品与头部公司。
- **域名情况**：`reinpad.com`、`reinpad.cn`、`reinpad.dev` 及 `yuzhen.dev` 在 Google 均无建站索引（未明显被占，精确注册状态未知；双拼 `yuzhen.com`/`.cn` 通常有米农持仓但无知名科技官网）。
- **App Store / GitHub**：Apple App Store 与 GitHub 均**未找到**同名应用或公开仓库（搜索结果仅偶见比利时地名小学 *De Reinpad*，与科技完全无关）。
- **风险评级**：**低风险**。

#### N2. 『帅台』 / `CueDial`
- **命名阐释**：在交响乐与剧院调度中，导演/指挥向多工位下达精准切入指令叫 **Give a Cue**（比“发宏命令”更高级、更符合 Agent 自主干活只需人类关键点拨的趋势）；**Dial** 直接锚定机身右侧标志性的金属滚轮编码器。中文**『帅台』**将三字“点将台”浓缩为两字，气势不减且现代感更强，完美绕开“点将台”的历史包袱。
- **公开商标记录**：USPTO 第 9/42 类公开索引**未找到** `CueDial` 申请或注册记录（注：剧场管理软件领域有近似词 `CueCall` [cuecall.app](https://cuecall.app/)，但行业与词尾不同）；中国公开检索第 9/42 类**未找到**“帅台”核心科技商标冲突记录。
- **同名产品 / 公司 / 开源项目**：无名为 `CueDial` 或“帅台”的科技公司或硬件产品（仅在 [arXiv](https://arxiv.org/) 一篇多模态视觉语言模型学术论文中将评测基准缩写为 `CueDial`，不构成商业软件或商标冲突）。
- **域名情况**：`cuedial.com`、`cuedial.cn`、`cuedial.dev` 以及 `shuaitai.com`、`shuaitai.cn`、`shuaitai.dev` 在 Google 检索中均返回 0 页面索引，未见明显占用（精确注册状态未知）。
- **App Store / GitHub**：Apple App Store 与 GitHub 均**未找到**同名商业应用或主流开源项目。
- **风险评级**：**低风险**。

#### N3. 『挥键』 / `TaktPad`
- **命名阐释**：若团队非常喜欢原候选 `Baton` 的“乐团指挥家”叙事，`TaktPad` 是最佳无冲突升级版——`Takt` 在音乐中指指挥棒挥出的“拍点”，在现代工程中指协同多条流水线步调的“节拍时间（Takt Time）”。中文**『挥键』**取“指挥之键、挥斥方遒”，自带键盘外设品类联想，两字极易传播。*(注：排查中已主动排除了 `TaktKey`，因微软商店已有一款日本开发者发布的机械键盘音效模拟软件名为 `TaktKey`，改用 `TaktPad` 后彻底干净。)*
- **公开商标记录**：USPTO 第 9/42 类公开索引**未找到** `TaktPad` 或冲突性 `TAKT` 软件注册记录；中国公开检索第 9/42 类**未找到**“挥键”强冲突商标记录。
- **同名产品 / 公司 / 开源项目**：AI、开发者工具、外设领域均**未找到**同名产品或公司（工业制造领域偶见德语 *Kontaktpad* 触点焊盘或节拍模拟概念如 [taktstorm.dev](https://taktstorm.dev/)，非同名品牌）。
- **域名情况**：`taktpad.com`、`taktpad.cn`、`taktpad.dev` 及 `huijian.dev` 在 Google 均无索引页面（未明显被占，精确注册状态未知；`huijian.com`/`.cn` 双拼多为早期个人持仓，无头部科技建站）。
- **App Store / GitHub**：Apple App Store 与 GitHub 均**未找到** `TaktPad` 或“挥键”同名应用/项目。
- **风险评级**：**低风险**。

#### N4. 『点兵台』 / `SquadKey`
- **命名阐释**：若创始人希望在国内市场保留最直观的古典沙场调度画面感，将“点将台”微调一字为**『点兵台』**（韩信点兵，多多益善——正好对应“Agent 越多越需要它”），即可甩开西部证券、TimeTec 云考勤及 GitHub 同名编排器的历史包袱。英文配对 **`SquadKey`**（战术小队之键），8 字母双音节，海外开发者一眼秒懂是管理一队 AI Agents 的按键外设。
- **公开商标记录**：USPTO 第 9/42 类公开索引**未找到** `SquadKey` 申请或注册记录；中国公开检索第 9/42 类**未找到**“点兵台”被大厂或知名科技企业注册的公开记录。
- **同名产品 / 公司 / 开源项目**：未找到名为 `SquadKey` 或“点兵台”的科技公司、外设产品或 AI 软件。
- **域名情况**：`squadkey.com` 目前已被注册并在域名经纪平台 Atom 挂牌待售（[squadkey.com](https://www.squadkey.com/)，无实体竞品业务建站，可通过经纪议价收购或启用 `.dev`）；`squadkey.cn`、`squadkey.dev` 及 `dianbingtai.com`、`.cn`、`.dev` 在 Google 均无建站索引（精确注册状态未知）。
- **App Store / GitHub**：Apple App Store 与 GitHub 均**未找到**同名应用或活跃仓库。
- **风险评级**：**低风险**（仅需评估 `squadkey.com` 二手购入预算，或直接使用 `squadkey.dev` / `getsquadkey.com`）。

#### N5. 『司阵』 / `MusterKey`
- **命名阐释**：英语单词 **Muster** 是英文世界里与中文“点将/点兵”最严丝合缝的对应词——*"muster the troops"* 意为“点名集结并调遣部队”，而固定搭配 *"pass muster"* 意为“通过检阅、审查合格放行”，一词双关覆盖**“多 Agent 点名跳转”**与**“高危命令审查放行”**！中文**『司阵』**意为“执掌智能体大阵”（相较于谐音“指令”的“执令”，“司阵”不会在 CNIPA 实质审查中因谐音计算机通用词“指令”而被质疑缺乏显著性）。
- **公开商标记录**：USPTO 第 9/42 类公开索引**未找到** `MusterKey` 申请或注册记录；中国公开检索第 9/42 类**未找到**“司阵”商业商标冲突记录。
- **同名产品 / 公司 / 开源项目**：无名为 `MusterKey` 或“司阵”的商业产品或科技公司（GitHub 上仅有单个 Claude Code 社区技能库 [ChiShengChen/shikigami](https://github.com/ChiShengChen/shikigami) 在文案设定中提及“司阵”阵法词汇，并非独立品牌名）。
- **域名情况**：`musterkey.com`、`.cn`、`.dev` 及 `sizhen.com`、`.cn`、`.dev` 在 Google 均无建站索引（0 结果，精确注册状态未知）。
- **App Store / GitHub**：Apple App Store 无 `MusterKey` 或独立“司阵”App；GitHub 无 `MusterKey` 仓库。
- **风险评级**：**低风险**。

---

## 四、 综合推荐排序与定名决策建议

### 1. 新旧候选合并推荐排序（从最推荐到最不推荐）

1. **🥇 第一名：`驭阵 / ReinPad`**（新提案 N1｜低风险）
   - **推荐理由**：战略契合度满分。唯一同时把**“多路并行控制（执六辔驾群马）”**和**“高危操作物理拦截（勒缰防失控）”**融进一个 7 字母双音节英文词 + 2 字中文名的方案；中美公开商标、GitHub、App Store、域名全线干净，无论是对硅谷投资人/Kickstarter 用户还是国内极客都极具辨识度。
2. **🥈 第二名：`帅台 / CueDial`**（新提案 N2｜低风险）
   - **推荐理由**：硬件交互特征最鲜明（`Cue` 点拨指令 + `Dial` 金属滚轮），且两字“帅台”气场极强又干净，完美解决“点将台”撞名痛点。
3. **🥉 第三名：`挥键 / TaktPad`**（新提案 N3｜低风险）
   - **推荐理由**：优雅继承原候选 `Baton` 的“乐团指挥”高级隐喻，彻底避开 `Baton` 的重灾区撞名；中文“挥键”直指键盘外设品类，传播成本极低。
4. **第四名：`点兵台 / SquadKey`**（新提案 N4｜低风险）
   - **推荐理由**：最贴近创始人原意“点将台”的安全平替版，军阵调度感直白易懂（仅注意 `squadkey.com` 为经纪待售域名）。
5. **第五名：`司阵 / MusterKey`**（新提案 N5｜低风险）
   - **推荐理由**：英语文化双关极妙（点兵集结 + 检阅放行），命名空间极度干净，略逊于前三名仅在于英文为 9 字母三音节，略长一拍。
6. **第六名（原候选英文最优）：`MuxKey`**（原候选｜低—中风险）
   - **推荐理由**：若必须在原有候选池中选英文名，**只能选 `MuxKey`**。它在硬核 CLI/tmux 开发者中有天然亲切感，可搭配新中文名（如**『驭阵 MuxKey』**或**『帅台 MuxKey』**），但递交第 42 类前务必核查 `Mux, Inc.` 新申请商标（Serial `99679661`）的引证边界。
7. **第七名：`HelmPad`**（原候选｜中风险）—— 受制于 Linux 基金会第 9 类 `HELM` 注册商标及船用防滑垫 SEO 污染，不作为首选。
8. **第八名：『点将台』**（原候选｜中高风险）—— 建议降级为中文副标题或产品宣传语（如：“**驭阵 ReinPad —— AI 时代的桌面点将台**”），既借用国民词汇心智，又不把主商标暴露在驳回与侵权风险下。
9. **❌ 淘汰：`Baton`**（原候选｜高风险）—— 与 `getbaton.dev` 及 App Store `Baton - Claude Code & Codex` 正面撞车。
10. **❌ 淘汰：`AgentDeck`**（现暂名｜极高风险）—— 4+ 个同名开源项目 + 双端应用商店已被占 + 海盗船 `STREAM DECK` 商标雷区，路演及众筹前务必完成切换。

---

## 五、 下一步行动：如何在 CNIPA 与 USPTO 官网自行精确检索（实操手册）

选定 **2～3 组最终入围名**（例如首选 `驭阵 / ReinPad`、备选 `帅台 / CueDial` 与 `MuxKey`）后，创始人可在委托代理机构前，花 30 分钟按以下官方步骤做一次零成本精确摸底：

### （一）中国国家知识产权局商标局（CNIPA 中国商标网）精确检索步骤

> **官方唯一免费入口**：[https://sbj.cnipa.gov.cn/](https://sbj.cnipa.gov.cn/)（点击首页**“商标网上查询”**；首次使用需按页面提示通过“国家知识产权公共服务平台”完成免费实名注册并登录，切勿轻信搜索引擎广告位的收费代查网站）。

#### 第 1 步：锁定本产品的核心“国际分类”与“类似群组号”
中国商标审查严格按《类似商品和服务区分表》的**类似群组**判定近似，漏查群组会导致严重误判。本产品必查群组如下：
- **第 09 类（硬件外设 + 本地客户端软件 + 内置麦克风）**：
  - **`0901` 群组（最核心，必查）**：涵盖计算机键盘（`090537`）、计算机外围设备（`090590`）、已录制的计算机程序（`090373`）、计算机软件（已录制）（`090591`）、可下载的计算机应用软件（`090717`）。
  - **`0908` 群组（因含按住说话麦克风，建议必查）**：涵盖麦克风（`090351`）、扬声器/音频外设。
- **第 42 类（个人 Pro 云桥接 + Team 版 SaaS 仪表盘与私有化服务）**：
  - **`4220` 群组（最核心，必查）**：涵盖软件即服务（SaaS）（`420220`）、计算机软件设计（`420139`）、平台即服务（PaaS）、云计算（`420229`）、计算机硬件设计与开发。
  - **`4209` 群组（建议补充）**：涵盖技术研究、人工智能领域的研究与咨询。
- *(可选防御核查)*：**第 35 类**（`3501` 线上广告、`3503` 替他人推销/软硬件电商零售）。

#### 第 2 步：执行“商标近似查询”（排查驳回风险的核心步骤）
登录进入系统后，点击左侧/顶部的 **【商标近似查询】**，切忌只查“完全相同”：
1. **查中文候选名（如 `驭阵`、`帅台`、`点兵台`、`点将台`）**：
   - **国际分类**：先填 `09`，**类似群**：填 `0901;0908`（查完一遍后，把分类改为 `42`，类似群改为 `4220;4209` 再查一遍）。
   - **查询方式**：选择 **“汉字”**。
   - **查询类型勾选**：不要只看完全匹配，务必依次测试**“精确”**、**“字头”**、**“包含”**以及**“同音字/形近字”**（例如查“驭阵”时，同步输入“御阵”“域阵”测试同音近似；因为中文两字商标若读音完全相同且字义相近，审查员常判近似驳回）。
2. **查英文候选名（如 `ReinPad`、`CueDial`、`TaktPad`、`MuxKey`）**：
   - **国际分类与类似群**：同上（`09` 类的 `0901;0908` 与 `42` 类的 `4220;4209`）。
   - **查询方式**：选择 **“英文”**。
   - **分段拆词检索（关键防漏技巧）**：CNIPA 英文审查中，若他人已注册核心词头（如 `REIN`、`TAKT`、`MUX`），你加上通用后缀 `PAD` / `KEY` 仍可能被驳回。因此必须分三次输入检索内容：
     - 第一次输全称：`reinpad`
     - 第二次输核心前缀（选“字头”或“精确”）：`rein`
     - 第三次输去元音/近音变体：`rainpad`（排查读音完全一致的英文词）。

#### 第 3 步：用“商标综合查询”核实命中的在先商标生死状态
如果在第 2 步看到相同或近似记录，**不要立刻放弃**，记下它的**申请号/注册号**，切到 **【商标综合查询】** 查看详情与 **【商标流程】**：
- 若状态显示 **“商标已无效”**、**“驳回待复审（且已逾多年无后续）”**、**“期满未续展”**，则已丧失在先权利障碍；
- 若显示 **“注册”** 且核定使用商品包含 `0901` 计算机软件/外设，但注册已满 **3 年** 且对方公司已吊销或从未实际使用，可通过代理机构评估“撤三”（连续三年不使用撤销）策略；
- 若显示 **“等待实质审查”**、**“初审公告”** 或近三年内刚获准 **“注册”**，则属于实打实的硬障碍，直接换名最快、最省钱。
- **注意盲期**：CNIPA 存在约 **1～3 个月的申请录入盲期**（刚交上去的申请查不到），早定名早递交是唯一解法。

---

### （二）美国专利商标局（USPTO Trademark Search）精确检索步骤

> **系统更新重要提示**：老牌的 **USPTO TESS 系统已于 2023 年 11 月 30 日永久退役下线**！目前官方唯一检索系统为新版云端 **USPTO Trademark Search**，官方直达网址：[https://tmsearch.uspto.gov/](https://tmsearch.uspto.gov/)（无需注册登录，海外网络环境下直接免费访问）。

#### 第 1 步：掌握新版字段语法规则（Expert Field Tag Syntax）
新版系统废除了旧版 TESS 的 `[comb]`、`[ic]` 方括号语法，改为**“大写字段代码 + 英文冒号”**（冒号后不留空格），布尔连接词 **`AND` / `OR` / `NOT` 必须全部大写**，检索词用小写即可：
- `CM:` —— **Combined Mark（组合商标检索字段，最推荐）**：自动同时匹配商标字面文字（Wordmark）、**官方伪标拆词（Pseudo Mark，极其重要！例如系统会自动把 `ReinPad` 拆成 `rein pad` 甚至同音词 `rain pad`）**以及翻译词。
- `IC:` —— **International Class（国际分类，必须写三位数字）**：如 `IC:009`、`IC:042`，多类合并写 `IC:(009 042)`。
- `CC:` —— **Coordinated Class（协同关联类别，比 `IC:` 更严谨）**：USPTO 审查计算机软硬件时，常跨第 9 类与第 42 类互查（第 9 类下载软件与第 42 类 SaaS 互为强关联商品），用 `CC:(009 042)` 可一次性网罗所有关联引证类目。
- `GS:` —— **Goods & Services（具体商品/服务描述）**：用于过滤同在第 9 类但毫不相干的商品（如第 9 类里的潜水镜、灭火器）。
- `LD:` —— **Live / Dead（有效状态）**：`LD:true` 仅看有效在审/已注册商标；`LD:false` 看已死/放弃商标。

#### 第 2 步：直接复制以下 4 条检索式逐一实测（以 `reinpad` 为例，替换词根即可）

打开 [https://tmsearch.uspto.gov/](https://tmsearch.uspto.gov/)，在顶部主搜索框直接粘贴运行：

1. **全库有效同名与伪标排查（不限类别，先看全局干不干净）**：
   ```text
   CM:reinpad AND LD:true
   ```
2. **正则通配符排查包含关系（防止 `ReinPadPro`、`MyReinPad` 漏网）**：
   ```text
   CM:/.*reinpad.*/ AND LD:true
   ```
3. **主词根 + 关联类别抗近似压力测试（模拟美国审查员最严苛的拆词检索逻辑）**：
   ```text
   CM:rein* AND CC:(009 042) AND GS:(keyboard* OR keypad* OR peripheral* OR controller* OR "artificial intelligence" OR "software") AND LD:true
   ```
   *(实操要点：把 `rein*` 换成 `takt*`、`cue*`、`squad*`、`muster*`、`mux*`，观察命中的在先有效商标是否聚焦在键盘外设或 AI 开发工具上。)*
4. **查看死标历史（排雷“为什么别人没注册下来”）**：
   ```text
   CM:/.*baton.*/ AND IC:(009 042) AND LD:false
   ```
   *(若发现大量同行申请某词后处于 Dead / Abandoned，点击结果右侧的 **TSDR (Documents)** 打开历史 `Non-Final Office Action`，就能直接看到当年 USPTO 审查员是用哪条法律或哪枚大厂商标驳回它的！)*

#### 第 3 步：定名锁死后的动作清单（路演前 1～2 周内可闭环）
1. **域名先行锁死（成本最低，仅几十美元）**：确定最终 1 个主选名后，**当天立即在 Cloudflare Registrar / Porkbun（海外 `.com`、`.dev`）及阿里云万网（国内 `.cn`）买下对应域名**，切勿在未买域名前把新名字发到公开社交媒体或第三方免费查名工具上（谨防域名抢注机器人嗅探）。
2. **开源与社媒账号占位**：同步注册 GitHub Organization、X（Twitter）Handle、Product Hunt、微信公众号/B 站同名账号。
3. **委托代理机构正式检索与递交申请**：
   - **中国（CNIPA）**：采用“先申请原则（First-to-File）”，建议以国内主体第一时间提交第 9 类 + 第 42 类文字商标（中英文分开单独提交，切勿把中英文拼在一张图里合交——合交一旦其中一部分近似就会整体被驳回，且使用时不能拆分排版！）。
   - **美国（USPTO）**：采用“使用在先原则（First-to-Use）”，在产品尚未正式向美国消费者发货前，可委托美国执业律师按 **Section 1(b) Intent-to-Use（意向使用）** 基础率先提交申请锁住优先权日（Priority Date），待众筹发货拿到真实美国订单与产品实拍图（Specimen）后再补交使用声明（Statement of Use）拿证。
