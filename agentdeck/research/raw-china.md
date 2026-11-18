# AgentDeck 中国市场原始调研（raw-china）

调研日期：2026-11-17。方法：Tavily 搜索 + WebFetch 抓取原文。每条事实后标 [编号]，编号对应文末来源表。
可信度标记：【已核】=抓到原文；【搜索摘要】=只见搜索摘要，未抓全文；【未核】=二手/低可信；【未找到】=没查到，不编造。

---

## 0. 最重要的 6 个发现（给路演用）

1. **国内已有直接竞品：优篮子 Ulanzi × 腾讯 WorkBuddy 的 Vibe Key，售价 269–299 元**（6 键+旋钮+麦克风，CNC 铝壳，2026-09 InfoQ 评测）。它是"语音+确认/拒绝+旋钮"，**没有逐会话状态屏/灯反馈**。这是我们最近的价格锚点和差异化切口。[1][2][3]
2. **Codex Micro 在国内媒体被报道为"约 1500 元"**（虎嗅/APPSO 标题；由 US$230 折算，非国内官方售价）。国内评价是"硬件无新东西、信仰税、本体就是 Work Louder 现成的 Creator Micro"，同时承认"多 agent 并行才有价值"。[4][5][6]
3. **国产 CLI/IDE 几乎都有 hooks，且含 PermissionRequest 事件**：CodeBuddy（27 事件）、Qwen Code（23 事件）、Kimi Code CLI（20 事件，PermissionRequest 不能阻断）。意味着 AgentDeck 的"批准键"可以做成多 agent 通用适配层，不只绑 Claude Code。[7][8][9]
4. **国内开发者大量通过"Anthropic 兼容端点"把 Claude Code 接到 GLM / Kimi / DeepSeek / MiniMax 上**，Claude Code 本身是国内 B 站教程热门内容。[10][11][12]
5. **摩点上唯一一个 AI 键盘类项目 AuraFlow Tap 筹到 26.1 万元 / 557 人（目标 1 万）**；但同类"AI+概念"硬件大量失败，结论是"AI 两个字不卖钱，具体玩法才卖钱"。[13][14]
6. **国内一级市场对 AI 硬件很热但偏好"出海、DTC、大疆/华为系团队、能讲订阅/数据飞轮"**；同时有投资人明确说"AI 硬件短期是主题，长期未必最好"。纯"外设"叙事需要靠软件/订阅/出海补强。[15][16][17]

---

## 1. 国内 AI 编程 Agent / CLI：规模与 hooks 对接能力

| 产品 | 形态 | 规模/数据（注明口径） | hooks / 集成接口 | 可信度 |
|---|---|---|---|---|
| 字节 Trae（国内版 trae.cn / 国际版 trae.ai）| IDE + SOLO + CLI；2026-06 SOLO 升级为 TRAE Work | 2025 年报：总注册 600 万+，月活 160 万，近 1000 亿行代码（自报）[18][19]；Trae 官方文档有 Hooks 配置参考，并支持"导入 Claude Code hooks"[20] | IDE 有 hooks.json（PreToolUse/PostToolUse 已确认）[20]；**是否有 PermissionRequest 类事件：未核**；Trae CLI 的 hooks：**未找到** | 规模【搜索摘要】；hooks【搜索摘要，事件表未抓到】 |
| 阿里 通义灵码 / Qoder | 插件 + AI IDE | 插件下载 2000 万+、1 万+企业接入（2025-07，阿里自报）[21] | 灵码本身 hooks：未找到 | 【搜索摘要】 |
| 阿里 Qwen Code（开源 CLI，Gemini CLI 分叉）| CLI/桌面/IDE 插件 | GitHub 30.5k stars、3.5k forks [22] | **有 hooks，23 个事件，含 PermissionRequest（"权限弹窗出现时"）、Notification、Stop；支持 command/HTTP hook** [8] | 【已核】 |
| 腾讯 CodeBuddy（CLI 名 CodeBuddy Code）| 插件 + IDE + CLI；另有 WorkBuddy | 腾讯自报内部超 90% 工程师使用（知乎综述转述）[23]；国内版支持 DeepSeek [24]；"四分天下"份额数字（CodeBuddy 28% 等）来源是自媒体综述，**不可信** [25] | **有 hooks，27 个事件，含 PermissionRequest、Notification、Stop、Elicitation** [7] | hooks【已核】；份额【未核】 |
| 月之暗面 Kimi Code / Kimi CLI | CLI + VS Code + 桌面；ACP 协议 | 订阅 ¥99/199/699/1399 每月（Plus/Pro/Max/Ultra）[26]；用户数：**未找到**；官方称兼容 Claude Code/OpenCode 等第三方工具 [27] | **有 hooks，20 个事件，含 PermissionRequest（等待用户批准前触发，不能阻断）、PermissionResult、Interrupt、SessionHeartbeat、Notification** [9] | 【已核】 |
| 智谱 GLM Coding Plan / ZCode / CodeGeeX | 订阅套餐，支持 Claude Code、Codex、Trae、CodeBuddy、OpenCode 等 20+ 工具 | Lite ¥118/月（季付折后 ¥94.4）、Pro ¥538、Max ¥1078 [28]；2026-02 GLM-5 发布同日涨价 30% 起并"上线即售罄" [29]；用户数 15 万为自媒体综述，**不可信** [25] | 智谱自身无独立 agent hooks 的证据；通过 Claude Code 等客户端接入 | 价格【已核】 |
| DeepSeek | 只提供模型/API | 提供 Anthropic 兼容端点，国内教程大量"Claude Code 接入 DeepSeek/GLM/Kimi" [10][11]；V4 Flash 被论坛认为按量最便宜 [30] | 无自家 CLI（未找到） | 【搜索摘要】 |
| MiniMax | 模型 + Coding Plan（后改 Token Plan）+ MiniMax Code/Agent | Coding Plan 升级为 Token Plan（含 M2.7 + 多模态额度）[31]；自家 CLI/hooks：**未找到** | 同上 | 【搜索摘要】 |
| 对照：Claude Code | 海外 | hooks 参考文档含 PermissionRequest 等 [32] | 已有 | 【搜索摘要】 |

**对 AgentDeck 的含义**
- "批准/拒绝键"在 CodeBuddy / Qwen Code / Kimi CLI 上都有可挂的 hook 点；其中 Kimi 的 PermissionRequest **不能阻断**（只能通知，不能代答），Qwen/CodeBuddy 的是否可代答需要实测（文档只写触发时机，**未核**）。
- Trae 是国内用户量最大的一档，但 hooks 事件表我没抓到，**必须实测**后再对外承诺"支持 Trae"。
- 国内 Claude Code 用户很多是"Claude Code 客户端 + 国产模型"组合，AgentDeck 只要做 Claude Code hooks 就覆盖这批人。
- 注意：国内用 Codex 需要境外支付绕路（V2EX 帖，土区 Apple ID 约 80 元/月等）[33]，Codex Micro 在国内的天然用户基数小于 Claude Code。

---

## 2. 国内开发者对 Codex Micro 与"vibe coding 键盘"的反应

| 事件/观点 | 内容 | 来源 |
|---|---|---|
| 国内媒体定价 | 虎嗅（转 APPSO）标题称"1500 块的 AI 监工外设"；腾讯新闻同样写 1500 元。US$230 折算，非国内官方价 | [4][5] |
| 国内评价 | "单论硬件没什么新东西，本体是 Work Louder 现成的 Creator Micro……230 美元里有一部分是信仰税"；但"一半输入设备、一半仪表盘"，"操作对象从软件变成干活的 AI 本身" | [4] |
| 发烧友观点 | 有键盘爱好者说一个不到十分之一价格的宏键盘就能复刻快捷键；Stream Deck 是替代；作者玩笑说想买 9.9 元拼多多山寨试试 | [5] |
| 使用门槛 | 报道称价值在"同时跑 4–5 个 agent"时才显现，单会话时像贵的宏键盘；已有摇杆故障反馈 | [5] |
| 官方可得性 | OpenAI 中文区页面（zh-Hans-CN）显示价格 US$230、状态"缺货"[34]；Work Louder 官网标 sold out [35]；**是否向中国大陆发货：未核**；**闲鱼/淘宝转卖价：未找到** | [34][35] |
| 国内"自己造" | 虎嗅报道一位海外网友用 Elgato Stream Deck+（US$179.99）+ 第三方插件（US$27）复刻；开源项目 Codex Deck/OpenMicro/ThreadDeck/OpenDeck 等出现；GitHub 有 codex-micro-stream-deck-emulator | [36][37] |
| 国内个人作品（与我们同类） | ① 知乎"Vibe Coding Keyboard - Claude code 专用键盘外设"（2026-04）：拿国产带屏键盘改刷固件，ESP32 方案，做了 cc patch + 远程服务 + bridge + 固件；作者吐槽海外同类 pre-order $69 纯键盘 [38]；② 歸藏（@op7418）用 M5Paper 做 Claude Code"AI 硬件监工"：多会话 dashboard + 物理键审批 + 蓝牙远程，称"rm -rf、git push --force 按物理按钮更慎重" [39]；③ B站/YouTube"工科男孙老师"开源 vibe coding 键盘（2026-06）[40] | [38][39][40] |
| 国内搜索"Codex Micro 平替/山寨" | 未发现成型量产山寨；"平替"主要指 Stream Deck 类或普通宏键盘。**未找到 Codex Micro 的 1688/拼多多山寨链接** | — |

---

## 3. 国内硬件对标与价格

| 产品 | 价格（RMB 或原币） | 说明 | 来源/可信度 |
|---|---|---|---|
| **Ulanzi 优篮子 Vibe Key（AU05，键盘麦）** | **¥269–299**（InfoQ）；台湾店 NT$1,549 | 6 键+旋钮+全向麦克风，CNC 铝壳，MagSafe 磁吸，佳达隆矮轴可热插拔，300mAh，Dongle 连接；Ulanzi Studio 配置；与腾讯 WorkBuddy 联名；官方文档称"Vibe Coders 效率工具"，语音靠绑定第三方输入法快捷键；灯光有"工作模式"反馈设备/AI 协作状态 | [1][2][3][41] 【已核】 |
| 厂商拆解 | 主体为深圳市唯迹科技股份有限公司（Ulanzi 母公司）；无线音频 SoC + 驻极体麦；无显示屏 | 说明该竞品没有屏幕，BOM 偏低 | [3]【已核】 |
| Ulanzi D200 / D200H / D200X（国产 Stream Deck 类）| 海外官网 D200 US$59.99；D200H US$69.99；D200X US$99.99（13–14 LCD 键）| **国内淘宝/京东售价：未找到**（搜索未返回价格）| [42][43]【已核（海外价）】 |
| Elgato Stream Deck+ | US$179.99（8 LCD 键+4 旋钮+触摸条）| 复刻 Codex Micro 的参照 | [36] |
| 淘宝"带屏幕机械键盘"类 | 例：镜也 DM104pro 全键带屏幕机械键盘套件 ¥239；OMO100pro 三模客制套件 ¥299；LEOBOG Hi75C ¥279 | 这类是"屏幕做装饰/显示 GIF"，不是逐键状态屏；屏幕不对接 agent | [44]【搜索摘要，淘宝榜单页】 |
| 淘宝"带屏宏小键盘"列表 | 页面只给出商品名（如 TP15U 语音数字小键盘），**未抓到价格** | — | [45]【未核】 |
| Keychron F4 HE 8K "Vibe Coding Keypad" | US$34.99（4 键，缺货预订）| 海外；国内京东/天猫价**未找到** | [46] |
| VibeKeys | Plus US$49 / Max US$99（Max 带 TFT 状态屏、麦克风、Claude Code 远程模式，3D 打印按单生产）| 海外 | [47] |
| PicoKey（SIKAI 思凯）| 语音+Yes/No+旋钮小键盘，有线/2.4G 两版；官网文章未抓到售价 | 无蓝牙、需 Windows 改键 | [48]【售价未找到】 |
| 洛斐 Loupedeck / 国内 Keychron 官方店 | **未找到** | — | — |
| Codex Micro | US$230；国内报道折约 ¥1500 | — | [4][34] |

**价格带结论（仅基于上表）**：国内已有 ¥269–299 的"AI 编程语音/确认键"，¥239–299 的带屏装饰键盘，海外 US$35–99 的 vibe 键盘；¥1500 是 Codex Micro 的国内媒体换算价。**AgentDeck 若带逐会话状态屏，定价落点必须有解释（见下面的缺口）**。

---

## 4. 国内众筹基准

| 平台/项目 | 金额 / 人数 | 备注 | 来源 |
|---|---|---|---|
| 摩点 AuraFlow Tap（AI 潮玩音乐键盘，光律）| 目标 1 万元 → **¥261,044.64（2610%），557 支持者**（摩点首页另一时点 ¥241,577/517 人）| 具体玩法（"把音乐玩在手里"），与 PANDAER×灌篮高手联名 | [13][49] |
| 摩点 奕时光便携麻将机 | ¥1,353,096（902%），803 人 | 科技类金额榜靠前 | [13] |
| 摩点 Fingersonic 口袋吉他 | ¥257,781（516%），1212 人 | — | [13] |
| 摩点 AI 随身专注主理人 Reppo | ¥40,003（400%），171 人 | — | [13] |
| 摩点 AI 智能气味播放器 | ¥62,448（624%），114 人 | — | [13] |
| 摩点失败案例（2025-11 至 2026-10）| 随身星座 AI 伙伴、念芯戒指、AI CARD、AI 智能眼镜（克雷默）、小喜财掌上机器人等均"未达筹资目标" | 大量"AI+概念"失败 | [14] |
| 人人都是产品经理实测（AI 刷 44 个众筹项目）| 结论：**"AI 两个字本身不卖钱"，说清具体玩法的卖得动；买断、非订阅是 Kickstarter 热评点** | 样本小、作者自述 | [50] |
| 平台生态 | 京东众筹 2022 年已停运；小米有品众筹、造点新货（原淘宝众筹）、摩点仍在 | 以该文为准 | [50] |
| 小米有品众筹具体金额 | **未找到** | — | — |

**对 AgentDeck 的含义**：国内键盘类众筹的合理锚点是"数十万元/数百人"量级（AuraFlow Tap 是唯一搜到的键盘类成功样本，且偏娱乐潮玩，不是开发者场景）；开发者硬件的国内众筹先例**未找到**，不能外推。

---

## 5. 2025–2026 国内 AI 硬件投资环境

### 5.1 融资事件（均为公开报道，金额以报道为准）

| 公司/事件 | 轮次与金额 | 投资方 | 来源 |
|---|---|---|---|
| OdyssLife（AI 项链，Odyss N1）| 约 2 亿元天使轮（2026-03）| 红杉中国、Monolith 领投；线性资本、Creekstone 跟投 | [51] |
| 跃然创新（AI 玩具 BubblePal）| 报道于 2026-03 月报（轮次见原文）| 见原文 | [51] |
| 无界方舟（AI 硬件 OS "EVA OS"）| 连续两轮 Pre-A，1 年内累计 4 轮、数亿元（2026-04）| 韶音、国瑞源基金、恒松资本、上海天使会 | [52] |
| 它石智航（具身）| 2025-07 天使+ US$1.22 亿 | 美团战投领投；线性资本等老股东 | [53] |
| 斜跃智能（家庭机器人）| 2026-09 数亿元天使+ | 线性资本、钧山、弘颐、隐山 | [54] |
| 烨知心 Yeats.AI（端侧 NPU）| 2026-09 Pre-A | 深创投、和利、TCL 创投、中科创星 | [54] |
| 智谱 | 2026-09 约 US$50 亿（配售+可转债）| 上市公司公告 | [54] |
| 总量 | 2026-01 国内 AI 领域投融资 240 起、披露 187.68 亿元；其中具身 25 起 | 烯牛数据/极新 | [55] |
| **桌面开发者外设类融资** | **未找到** | — | — |

### 5.2 投资人公开表态（各自原话摘要，非对 AgentDeck 的评价）

| 机构/人 | 表态要点 | 来源 |
|---|---|---|
| 红杉中国 张涵 | "AI 硬件公司可讲用户增长、数据飞轮、订阅服务、生态协同的故事"；2025 年深圳出手最积极之一；决策快（接触到 TS 最快 2–3 天），用过桥贷款抢项目 | [15] |
| 高瓴 | 深圳智能硬件"美元基金一来估值几个月翻倍"（高瓴投了智能办公椅"清闲"）；人民币基金决策 1 个月至 4–6 个月，抢不过美元基金 | [15] |
| 深圳投资圈共识 | 创业者多来自大疆/华为/小米，做 DTC 品牌而非贴牌 | [15] |
| 阿尔法公社 许四清 | 2025 最突出风口之一是智能硬件，"出海表现非常好"；偏好行业老兵+学界团队；绝大多数项目第一轮投 | [16] |
| 英诺基金 周全 | 布局 AI 2C 智能硬件；偏爱"AI 原生年轻人" | [16] |
| 线性资本 | 多次出现在 AI 硬件/具身投资方名单（见 5.1）；**线性资本自身公开表态：未找到** | [51][53][54] |
| 奇绩创坛 | 投了"数智起点"等早期公司（2026-03）；**对硬件的公开表态未找到** | [51] |
| 真格 戴雨森 | 2026 关键词"The Year of R（回报/研究）"；2025 年自己聊 150 个项目只投 2 个（播客简介）；对硬件无具体表态 | [56] |
| 某投资人（原文未在片段中标注姓名）| "AI 硬件，短期可能是主题，但长期未必是最好的"；"最好的主题一定是 AI 应用" | [17]【出处人物未核】 |
| 小米/顺为、联想之星 | **未找到** | — | — |

### 5.3 政策

| 政策 | 内容 | 与我们的相关性 | 来源 |
|---|---|---|---|
| 深圳市工信局智能终端产业发展扶持计划（操作规程，2025-04 解读）| 重点含智能手机、电脑、平板、可穿戴、VR/AR、全屋智能、大模型一体机及"其他创新型消费电子终端"；方向含：AI 终端技术攻关（按核定投入 15%，最高 2000 万）、公共服务平台（50%，最高 300 万）、**"人工智能消费终端爆款单品奖励"**（金额本次未抓到）；均为事后奖补 | 桌面 AI 控制器是否属"创新型消费电子终端"需向主管部门确认，**未核**；爆款奖励门槛高 | [57] |
| 国补（2026）| 手机、平板、智能手表手环、**智能眼镜**四类，≤6000 元补 15%，单件最高 500 元 | **不含键盘/外设**，不能用来给 AgentDeck 做国补定价 | [58] |
| 深圳龙岗 AI 眼镜专项（2026-08 施行）| 技改每企每年最高 2000 万、480 亿产业基金等 | 只针对 AI 眼镜，非我们品类 | [59] |
| 北京经开区信创措施 | AI 终端首试首用单项目最高 3000 万 | 地域/品类是否适用：**未核** | [60] |

---

## 6. 深圳供应链（本次证据不足的部分，如实标注）

| 项目 | 已找到的证据 | 未找到 |
|---|---|---|
| 竞品 BOM 线索 | Ulanzi Vibe Key：铝合金 CNC、300mAh 电池、无线音频 SoC，无屏幕；主体深圳唯迹科技 [3] | 实际出厂成本 |
| 机械轴/键帽零售价 | 知乎客制化指南：佳达隆轴约 ¥1.40/颗，TTC 金粉轴约 ¥4.75/颗（零售，2022 年文章）[61] | 批量价 |
| 键盘套件零售参考 | 淘宝榜单：¥239–459 套件（带屏装饰款 ¥239）[44] | — |
| OEM MOQ（普通机械键盘）| HAVIT 的 OEM 指南称"MOQ 超 500 时禁用 ABS 键帽"、PBT 双色注塑多约 20% 成本（工厂自述，营销文）[62] | 带屏键帽专项 MOQ |
| 显示模组供应商（可作为询价名单，**不是推荐**）| 深圳华之晶（LCD/OLED/TFT 模组，定制，宝安/东莞）[63]；鑫洪泰（TFT/OLED/定制盖板）[64] | 报价、起订量 |
| **"屏幕键帽"（逐键 LCD/OLED 键帽）模组**：厂家、单价、MOQ、交期 | **未找到**。可对照的是 Stream Deck 类产品（Ulanzi D200 等）本身就是深圳制造 | 需要直接向 Ulanzi 同类供应商/显示模组厂询价 |
| 供应链速度 | 36 氪：深圳"货架上的爆款多由本地供应链几天内打样迭代而成" [15] | 具体天数 |

**建议**：路演里不要写"屏幕键帽 BOM $X"这类数，直到拿到至少 2 家的书面报价。

---

## 7. 国内开发者硬件 GTM 渠道（证据）

| 渠道 | 证据 | 来源 |
|---|---|---|
| B站 | Claude Code 教程大热（页面可见 15.7万、8.8万、7.2万播放等量级的合集）；"工科男孙老师"开源 vibe coding 键盘视频 | [65][40] |
| 腾讯系/厂商联名 | Ulanzi × WorkBuddy 联名，InfoQ 做评测，是国内"AI 外设"的现成发行模板 | [1] |
| 媒体 | 虎嗅/APPSO/36氪/凤凰网/腾讯新闻均快速跟进 Codex Micro（2026-07-15 至 07-24）| [4][5][66] |
| 知乎 / V2EX / CSDN / 掘金 | Codex 购买、Claude Code 接国产模型、AI 编程横评在这些站点是高频话题 | [10][33][67] |
| 小红书 | 蒲公英是平台官方品牌合作平台，收佣金；本次**未找到**键盘类 KOL 报价 | [68] |
| 摩点 | 键盘类成功样本 AuraFlow Tap，见第 4 节 | [13] |
| 京东/天猫 | 京东众筹已停；Ulanzi 等通过京东/天猫旗舰店卖，本次**未抓到具体页面** | — |
| 少数派 | **未找到**与 vibe coding 键盘相关的文章 | — |

---

## 8. 信息缺口清单（需要人工补）

1. 闲鱼/淘宝上 Codex Micro 的真实转卖价、OpenAI 是否向大陆发货。
2. Ulanzi D200 系列、Vibe Key 的京东/天猫实际成交价与销量。
3. "屏幕键帽"模组的真实报价、MOQ、交期（至少 2 家书面）。
4. Trae IDE/CLI hooks 的完整事件表与 PermissionRequest 是否可代答；Qwen Code、CodeBuddy 的 PermissionRequest 是否可返回 allow/deny。
5. 小红书/B站键盘类 KOL 报价；小米有品众筹的键盘/外设金额。
6. 红杉/真格/奇绩/线性对"开发者外设"的具体态度（需要实际约访，网上没有）。
7. 深圳"爆款单品奖励"具体额度与门槛。

---

## 来源列表

1. InfoQ：实测 Vibe Key（Ulanzi × 腾讯 WorkBuddy，¥269–299），2026-09-16 — https://www.infoq.cn/article/joXcPA6XF1QWgik9OALj
2. Ulanzi Studio 文档：Vibe Key AU05 教程 — https://docs.ulanzistudio.com/vibekey/au05
3. 我爱音频网：Vibe Key 拆解 — https://www.52audio.com/archives/1794308264984.html
4. 虎嗅（APPSO）：Codex 首款硬件发布，1500 块 — https://www.huxiu.com/article/4875636.html
5. 腾讯新闻：Codex 键盘第一波上手 — https://news.qq.com/rain/a/20260724A0AOOJ00
6. 百度百科：kbd-1.0-codex-micro — https://baike.baidu.com/item/kbd-1.0-codex-micro/68270902
7. CodeBuddy 文档：Hooks（27 个事件）— https://www.codebuddy.cn/docs/cli/hooks
8. Qwen Code 文档：hooks.md（23 个事件）— https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/hooks.md
9. Kimi Code 文档：Hooks（20 个事件）— https://www.kimi.com/code/docs/kimi-code-cli/customization/hooks.html
10. CSDN：给 Claude Code 换个引擎 GLM 接入 — https://blog.csdn.net/Rabbit_QL/article/details/160338380
11. 智谱 BigModel：GLM Coding Plan — https://bigmodel.cn/glm-coding
12. 腾讯云 CodeBuddy 发布（国内版支持 DeepSeek）— https://hk.finance.yahoo.com/news/%E9%A8%B0%E8%A8%8A%E7%99%BC%E5%B8%83ai%E7%B7%A8%E7%A8%8B%E5%B7%A5%E5%85%B7codebuddy-%E5%9C%8B%E5%85%A7%E7%89%88%E6%94%AF%E6%8C%81deepseek-071619353.html
13. 摩点科技众筹（成功项目列表）— https://zhongchou.modian.com/technology/top_time/success
14. 摩点科技众筹（最新上线，含失败项目）— https://zhongchou.modian.com/technology/top_time/all/7
15. 36 氪：深圳投资人，难进"大疆圈" — https://m.36kr.com/p/3667290634232709
16. 界面新闻：投资人把脉 2026 — https://m.jiemian.com/article/13827260.html
17. Founder Park/出海："中国 AI 投资人：练习时长两年半" — https://letschuhai.com/b3fe83ea
18. 极客公园/腾讯新闻：TRAE 年报 600 万 — https://news.qq.com/rain/a/20251229A065ZX00
19. AIbase：Trae 月活 160 万 — https://news.aibase.com/zh/news/24099
20. Trae 文档：Hooks（含导入 Claude Code hooks）— https://docs.trae.ai/ide/automate-actions-with-hooks 、 https://docs.trae.ai/ide/hook-configuration-reference
21. 量子位：通义灵码 2000 万下载 — https://www.qbitai.com/2025/07/313038.html
22. GitHub：QwenLM/qwen-code — https://github.com/qwenLM/qwen-code
23. 知乎：国内编程智能体牌桌 — https://zhuanlan.zhihu.com/p/2055380544410727228
24. 同 12
25. 微博长文：AI 编程市场格局（"四分天下"份额，低可信）— https://weibo.com/ttarticle/x/m/geoshow/id/2309405342771723764144?domain=local
26. Kimi 编程套餐指南（¥99–1399）— https://www.kimi.com/resources/coding-plan
27. Kimi Code 社区倡议 — https://www.kimi.com/help/kimi-code/community-guidelines
28. 同 11（BigModel 价格页）；另见 https://bigmodel.cn/claude-code
29. 智通财经：智谱 Coding Plan 涨价上线即售罄 — https://cn.investing.com/news/stock-market-news/article-3215317
30. GitHub awesome-coding-plan 价格对比 — https://github.com/mahonzhan/awesome-coding-plan
31. 汇港通讯：MiniMax Coding Plan 升级 Token Plan — https://hk.finance.yahoo.com/news/minimax%E5%85%A8%E7%90%83%E9%A6%96%E7%99%BC%E6%94%AF%E6%8F%B4%E5%85%A8%E6%A8%A1%E6%85%8B%E6%A8%A1%E5%9E%8B%E8%A8%82%E9%96%B1%E8%A8%88%E5%8A%83-maxclaw%E6%8E%A5%E5%85%A5%E5%BE%AE%E4%BF%A1-050302686.html
32. Claude Code Hooks 文档 — https://code.claude.com/docs/en/hooks
33. V2EX：Codex 现在该咋买 — https://www.v2ex.com/t/1212309
34. OpenAI Supply × Work Louder 中文页（US$230，缺货）— https://openai.com/zh-Hans-CN/supply/co-lab/work-louder
35. Work Louder 官网 Codex Micro（sold out）— https://www.worklouder.cc/codex-micro
36. 虎嗅：1500 元的 Codex 键盘卖断货，这小哥反手自己造了一台 — https://www.huxiu.com/article/4877076.html
37. GitHub：codex-micro-stream-deck-emulator — https://github.com/mpociot/codex-micro-stream-deck-emulator
38. 知乎：Vibe Coding Keyboard - Claude code 专用键盘外设 — https://zhuanlan.zhihu.com/p/2015244868490900434
39. 歸藏（@op7418）：我给 Claude Code 做了个 AI 硬件监工 — https://x.com/op7418/article/2046045574118691143
40. 工科男孙老师：【开源】我制作了一个 vibe coding 键盘 — https://www.youtube.com/watch?v=bkjVOC4Kp1I
41. 台湾店 Ulanzi AU05 Vibe Key（NT$1,549）— https://www.enjoyphoto.com.tw/shop/ulanzi-%E5%84%AA%E7%B1%83%E5%AD%90-ulanzi-au05-vibe-key-keyboard-microphone-vdrcuzau05
42. Ulanzi D200H 官网（US$69.99/99.99）— https://www.ulanzi.com/products/d200h-deck-dock
43. Ulanzi Stream Deck 系列页（D200 US$59.99）— https://www.ulanzi.com/collections/stream-deck
44. 淘宝客制化键盘套件榜（含 ¥239 带屏款）— https://www.taobao.com/list/product/top-rated/%E5%AE%A2%E5%88%B6%E5%8C%96%E9%94%AE%E7%9B%98%E5%A5%97%E4%BB%B6.htm
45. 淘宝：带屏宏小键盘（仅商品名）— https://guangtao.taobao.com/product-f0e36d83f7fd19a59e759e6ba969a42677b926611bbd1e15ce506e5c8fee14ed.html
46. Keychron F4 HE 8K Vibe Coding Keypad — https://www.keychron.com/products/keychron-f4-he-8k-vibe-coding-keypad
47. VibeKeys Max — https://vibekeys.dev/vibekeys-max.html
48. PicoKey 有线 vs 2.4G（SIKAI）— https://www.sikaiglobal.com/post/vibe-coding-keypad-wired-2-4g-zh
49. 摩点首页（AuraFlow Tap ¥241,577/517 人时点）— https://modian.com/home
50. 人人都是产品经理：先去众筹网站看了一圈 — https://www.woshipm.com/ai/6476674.html
51. Agent500：2026 年 3 月 AI 投融资月报 — https://zhuanlan.zhihu.com/p/2027082709755786949
52. 无界方舟 Pre-A（ChainCatcher）— https://cryptorank.io/zh/news/feed/751a2-2256271
53. 财联社：它石智航 1.22 亿美元天使+ — https://www.cls.cn/detail/2080243
54. 园区世界：投融资周报 2026 年 9 月 3 期 — https://www.parkworld.net/post/8df1755389eaf34
55. 钛媒体/极新：2026 年 1 月 AI 投融资 — https://www.tmtpost.com/7864513.html
56. 张小珺播客：真格戴雨森（视频简介）— https://www.youtube.com/watch?v=EosO2Qd35Cw
57. 深圳市工信局：智能终端产业发展扶持计划操作规程解读 — https://www.sz.gov.cn/zfgb/zcjd/content/post_12115066.html
58. 财联社：2026 国补首次纳入智能眼镜 — https://cn.investing.com/news/stock-market-news/article-3146005
59. 观研报告：AR/智能眼镜政策（含深圳龙岗）— https://www.chinabaogao.com/zhengce/202611/824120.html
60. 东方财富转述：端侧 AI 硬件与补贴（北京经开区 3000 万）— https://www.haiai123.com/zh-cn/hot/7501
61. 知乎：客制化机械键盘入门（轴体价格）— https://zhuanlan.zhihu.com/p/511184119
62. HAVIT：机械键盘 OEM 采购指南（工厂营销文）— https://havitsmart.com/zh/blogs/havit-%E9%9F%B3%E9%A2%91%E4%B8%AD%E5%BF%83/%E6%89%B9%E5%8F%91-%E6%9C%BA%E6%A2%B0-%E9%94%AE%E7%9B%98-oem-%E9%87%87%E8%B4%AD-%E6%8C%87%E5%8D%97-2026
63. 深圳华之晶：OLED 显示屏 — https://www.hzjlcd.com/oled_c5
64. 鑫洪泰：定制显示/盖板 — https://cn.display-lcd.com/solution.html
65. B站：Claude Code 教程合集 — https://www.bilibili.com/video/BV17faR6PE3E
66. 凤凰网：OpenAI 首款联名硬件 Codex Micro — https://tech.ifeng.com/c/8uko8JgQNQr
67. 掘金：2026 七款主流 AI 编程工具横评 — https://juejin.cn/post/7629169106097782822
68. 时代周报：小红书笔记付费（含蒲公英平台说明）— https://cn.investing.com/news/stock-market-news/article-3154760
