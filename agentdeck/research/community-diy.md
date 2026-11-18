# 社区与个人 DIY：AI 编码 agent 的硬件控制和状态提示

调研日期：**2026-11-18**。依据 `research/brief-community-diy.md`，评估对象为本项目暂名 AgentDeck 的 **4×4 键盘 + RGB + 浮窗** 第一版。本次只做公开资料调研，没有安装外部项目或验证其实际硬件。

**最重要的发现：这个方向已有直接竞品。** [VibeDeck](https://getvibedeck.com/) 已把多 agent 状态、Stream Deck 实体键、审批和顶部浮窗放在一起；[Agent F-Row](https://github.com/timeToy34/agent-frow) 则已有 Windows 普通 RGB 键盘、Stream Deck 和置顶浮窗。另有两个同名项目：功能广泛的 [puritysb/AgentDeck](https://github.com/puritysb/AgentDeck)，以及尚未制造的 [Brillar0101/agentdeck](https://github.com/Brillar0101/agentdeck)。不能把“跨 agent + 灯 + 按键 + 浮窗”直接写成独有差异。

## 口径与证据边界

- 主表收录 **23 个独立项目/个人改造案例**。所有引用链接均在本次调研中成功取得正文或由 GitHub 连接器读取对应公开资源；只有搜索摘要、403/412、超时或空页面的结果不进入主表。失败线索在末尾写“未找到”，不附未核实的可点击链接。
- “支持”表示作者当前文档的声明，**不表示本次实测通过**。状态观察、额度显示、会话跳转和审批回答分别写明；计划中的功能不算已支持。设计原型、闭源独立插件也明确标注。
- GitHub 星数、fork 数取本次连接器返回的仓库 API 元数据；社区数字取实际打开页面可见值。均为 **2026-11-18 检索所得快照**，可能有缓存，不代表下载量、活跃用户或付费需求。未能读到的数字写“未找到”，不拿搜索摘要补齐。
- 时间优先使用作者原帖/商店版本日期。仓库日期明确标作“建仓 / 最近推送”，不把建仓当首发，也不把最近推送当全部功能的上线日。

## 项目表

“平台”同时说明资料来源和运行环境；“硬件插件”指社区软件复用现成设备，并非作者制造了整台硬件。

| 项目名 | 链接 | 平台 | 形态（硬件 / 软件） | 支持哪些 agent | 关键做法与已知限制 | 热度 | 时间 |
|---|---|---|---|---|---|---|---|
| 01. AgentDeck（puritysb，与本项目同名） | [仓库](https://github.com/puritysb/AgentDeck)；[项目站](https://puritysb.github.io/AgentDeck/) | GitHub；Mac 原生应用，Windows/Linux CLI；手机及多种桌面设备 | 软件 + Stream Deck/优篮子插件 + ESP32/墨水屏/LED 屏 | Claude Code；Codex CLI；Codex Desktop 在 macOS 观察、Windows 验证待完成；OpenCode；Kiro 为延迟观察；Antigravity 被动观察；OpenClaw 实验、Hermes 只读预览 | 一个本地 daemon 对接多个显示/控制端；会话、等待请求、用量、时间线及水族箱。仅有真实控制通道的会话能回答/打断，其他只显示。README 列优篮子 D200H/D200X LCD 键；D200X 编码器未支持。演示含虚构活动，不能据此认定全部场景已实测 | **301★ / 60 forks** | 建仓 2026-02-20 / 最近推送 2026-11-17 |
| 02. VibeDeck（Inventive Hill） | [官网](https://getvibedeck.com/)；[Elgato 商店](https://marketplace.elgato.com/product/vibedeck-claude-code-agents-86b9312b-a7ae-4ea9-83c0-76c119ec2dba)；[兼容表](https://getvibedeck.com/compatibility) | 独立开发者商店产品；macOS 13+ Apple Silicon / Windows 10+ x64；Stream Deck 7.1+ | 硬件插件 + 原生浮窗；付费，未找到插件源码 | 作者宣称 15 种、Windows 14 种，包括 Claude Code、Codex、Cursor、Copilot CLI、Antigravity、OpenCode、Pi、Gemini CLI 等；**审批仅 Claude/Codex/OpenCode/Pi，且有接入条件** | 一会话一键；顶部 screen card 显示请求/选项，可鼠标或实体键回答；临时答案 profile；三连按停止当前 turn；用量/语音。商店当前 33 actions。部分 agent 实际 runtime 验证仍待完成，不能理解为 15 家均已实测、均可审批 | 下载/评分/点赞/评论 **未找到**；官网 $19 一次性，价格不当热度 | 商店当前 **2.0.0.2，2026-11-09** |
| 03. Agent F-Row | [仓库](https://github.com/timeToy34/agent-frow) | GitHub；Windows，兼顾 WSL agent；Corsair/Keychron/Stream Deck | 软件托盘/置顶浮窗 + RGB 硬件联动 | Claude Code、Codex；CLI/桌面/IDE 随接入方式不同 | 每会话固定 lane、等待时长、RGB 状态、按键定位窗口/tab；核验聚焦后用方向键/Enter 回答。**不是所有回答都走请求级审批 API**；README 明示 Codex 不显示 Error，回答后 Waiting 清除可能延迟 | **6★** | 建仓 2026-08-19 / 最近推送 2026-10-26 |
| 04. Jetstream | [仓库](https://github.com/pimmesz/jetstream) | GitHub；macOS 12+，Stream Deck 7.1+ | 硬件插件 | Claude Code 状态/审批；**Codex 仅额度表** | 每项目一键、跳转、Approve/Deny、停止当前 turn；处理最老待审批，约 90 秒未回答退回原生提示。文字输入仍到 Claude 回答；未支持 Windows | **0★ / 0 forks** | 建仓 2026-07-16 / 最近推送 2026-10-12 |
| 05. Codex Macropad Companion | [仓库](https://github.com/suregoodru/codex-macropad) | GitHub；macOS 13+；Ergohaven M4CR0Pad v3 | 硬件伴侣软件 + 状态屏/RGB | Codex | hooks + 现有 Raw HID/VialRGB；显示阶段、项目、耗时、任务数，等待优先于完成/工作；退出恢复 RGB。无需修改键盘固件；仅该设备验证，未找到通用 QMK 兼容保证 | **2★ / 0 forks** | 建仓 / 最近推送均 2026-08-11 |
| 06. 0P_Micr0Pad | [仓库](https://github.com/random-knights/micr0pad) | GitHub；Windows；Work Louder Codex Micro / Creator Micro 2 | 硬件插件 + 浏览器配置 | 作者经 Herdr 接入 Claude Code、Codex、Gemini、Grok、HF、Ollama；逐家实测证据未找到 | 六个 agent 槽，一 agent 一键；底部灯条显示最急状态；厂商 Raw HID JSON-RPC。文档验证设备为 Codex Micro v0.4.1，不能因依赖包跨平台就写成全平台已验证 | **2★ / 0 forks** | 建仓 2026-09-02 / 最近推送 2026-10-21 |
| 07. Beacon | [仓库](https://github.com/angaziz/beacon) | GitHub；macOS 13+ hub + Waveshare ESP32-S3 2.16″ AMOLED；预编译版 Apple Silicon | 硬件屏 + 菜单栏 | **Claude Code：额度/会话/审批；Codex：仅额度** | BLE 配对、逐会话显示、终端跳转、屏上批准/拒绝；问题需回 Mac 输入；区分 loading/live/stale/offline。作者称端到端已工作，仍是 early prototype | **25★ / 2 forks** | 建仓 2026-06-05 / 最近推送 2026-11-05 |
| 08. claude-monitor | [仓库](https://github.com/icefoxj/claude-monitor) | GitHub；Windows + M5Stack AtomS3R / Tab5 | ESP32 硬件状态屏 | Claude Code；另读 Windows Claude Desktop 通知 | hooks → PowerShell daemon → USB；小屏取最急状态，大屏每会话一格；工作/审批等待/提问/错误分开，主机静默显示失联。Linux/macOS daemon 未验证；部分进程观察仅 Windows | **5★ / 0 forks** | 建仓 2026-09-10 / 最近推送 2026-11-18 |
| 09. claude-status | [仓库](https://github.com/DGPRoman/claude-status) | GitHub；Linux + ESP32-C3，0.42″ OLED | 硬件提示屏/灯 | Claude Code，含 VS Code 扩展 | USB/Wi-Fi，多会话聚合，等待优先、等待数量角标。**BOOT 键只表示“已看到”、让闪灯安静，不批准工具调用** | **0★ / 0 forks** | 建仓 2026-07-24 / 最近推送 2026-07-30 |
| 10. Lloyd Pager 3000 | [仓库](https://github.com/danielbowne/claude-pager) | GitHub；ESP32-S3 3.5″ 触屏、Wi-Fi/MQTT；主机兼容矩阵未找到 | 硬件寻呼器 | Claude Code | Stop 显示 YOUR TURN；PreToolUse 发请求，触屏批准/拒绝；任务/模型/分支/context；Docker Mosquitto broker。**其 PreToolUse 接管方式不等于只在原生权限弹窗时触发** | **4★ / 0 forks** | 建仓 / 最近推送均 2026-02-13 |
| 11. claude-esp32-dashboard | [仓库](https://github.com/luc4scatto/claude-esp32-dashboard) | GitHub；macOS/Windows 主机 + ESP32-S3 480×480 触屏 | 硬件触控台 | Claude Code | 多机器/多会话、LAN 发现；statusline + hooks；屏上审批、选择题、plan；权限/问题 27 秒、plan 87 秒后退回终端。界面意大利语 | **0★ / 0 forks** | 建仓 / 最近推送均 2026-10-30 |
| 12. Siminnn 的 TC002 AI 工作台 | [少数派原文](https://sspai.com/post/118939) | 少数派；优篮子 TC002 + 电脑本地程序，同一 Wi-Fi | 个人硬件改造 + 网页工作台 | **作者跑通 Claude Code、Kimi Code；Codex 未跑通** | 屏幕 CC/CX/KM 三栏字母 + 状态方块，也试了像素宠物；同状态重复推送会重置动画。电脑休眠即不更新，时钟重启需重推；不应把文章开头“三家展示”当三家接入成功。个人实现源码未找到 | 页面 **3 评论、3 位充电**；点赞数未找到 | 文章 **2026-11-12** |
| 13. agentdeck（Brillar0101，与本项目同名） | [仓库](https://github.com/Brillar0101/agentdeck) | GitHub；RP2040 / CircuitPython | **硬件设计原型** | 已写 Claude Code hooks bridge；其他 agent 完整接入未找到 | 13 热插拔键、逐键 RGB、旋钮、五向摇杆；六个 agent 键 + 批准/拒绝。README 明示 **尚未制造，固件未上板验证**，不是可用成品 | **0★ / 1 fork** | 建仓 2026-07-23 / 最近推送 2026-09-02 |
| 14. ClauDeck（onavascuez） | [官网](https://claudeck.dev/)；[商店](https://marketplace.elgato.com/product/claudeck-2ed8dd1e-1a28-4442-b5df-7d2e16d4f6d1)；[支持仓库](https://github.com/onavascuez/ClauDeckWeb) | 个人产品；原生 macOS 12+/Windows 10+，Stream Deck 7.1+；不支持 WSL/SSH/容器 | 硬件插件；**插件闭源** | Claude Code | 一会话一键、工具/子 agent/context、审批/多选题/终端定位；90 秒未答回原生提示。Lite 仅额度，高级控制为 Pro；公开 MIT 仓库是网站/支持，并非插件源码 | 插件下载/评分 **未找到**；支持仓库 **0★ / 1 fork**，不是用户量 | 商店 **1.1.1，2026-09-15** |
| 15. AgentPet | [仓库](https://github.com/ntd4996/agentpet) | GitHub；macOS 13+/Windows 10/11/Linux | 软件浮宠 + 菜单栏 + 通知 | Claude/Codex/Gemini/OpenCode/Factory：工作/等待/完成；Cursor/Windsurf/Antigravity/Copilot/Kiro/Pi：仅工作/完成 | 每项目宠物、等待数、状态计时、原生通知；完成任务/用量驱动养成。**各家等待检测能力不同**；支持通用命令 wrapper | **406★ / 74 forks** | 建仓 2026-05-31 / 最近推送 2026-11-12 |
| 16. CC Lights | [仓库](https://github.com/andyiac/cc-lights/)；[V2EX 原帖](https://v2ex.com/t/1226660) | GitHub/V2EX；macOS 11+ | 软件菜单栏 | 当前 README：Claude Code、Codex、OpenCode、pi、Hermes | 每会话一盏灯，等待 30 秒后慢闪；点击定位 Terminal/iTerm2/Ghostty/cmux；hooks/plugins 写本地 JSON。原帖有多灯挤满菜单栏、闪烁晃眼、跨工具接入诉求 | **9★**；V2EX **14 回复 / 4,198 浏览** | 建仓 2026-06-03 / 最近推送 2026-11-03；原帖 2026-07-12 |
| 17. Code Light AI | [当前仓库](https://github.com/cuihp/code-light-ai)；[V2EX 原帖](https://v2ex.com/t/1216229) | GitHub/V2EX；macOS/Linux/Windows，Windows 需 Git Bash | 软件托盘 + 像素猫浮宠 | Claude Code、Codex CLI | hooks → 每会话 JSON → 每秒扫描，错误/等待优先。**文档把等待 30 秒改工作、工作 60 秒改完成；这是超时推测，不是真实完成证据**。旧 code-light 链接已重定向到当前仓库 | API **21★**；V2EX **1 回复 / 1,760 浏览** | 建仓/原帖 2026-05-28；最近推送 2026-07-22 |
| 18. Agent Signal Bar Windows | [仓库](https://github.com/ridyang/Agent-Signal-Bar-Windows) | GitHub；Windows 原生托盘移植 | 软件托盘/诊断 | Claude Code、Codex、自定义脚本 | 多会话红黄绿聚合；Codex Desktop 读日志，其他用 hook；stale 状态、hook 健康诊断；等待/错误不被普通工作事件盖掉 | **4★** | 建仓 / 最近推送均 2026-06-05 |
| 19. Dashbar | [仓库](https://github.com/stevenmckinnon/dashbar) | GitHub；macOS 14+ | 软件菜单栏 + 窗口 + notch island | Claude Code、Codex、Gemini CLI、Antigravity、OpenCode、Copilot；进程发现与控制深度不同 | needs-you 优先；快捷键跳最久等待会话；额度/子 agent/项目。可选 Claude PermissionRequest 桥，在菜单栏/island 一次批准或拒绝，未处理退回终端 | **3★** | 建仓 2026-11-06 / 最近推送 2026-11-18 |
| 20. agentop | [仓库](https://github.com/sacx/agentop) | GitHub；Linux X11/Wayland、polybar/i3bar | 软件托盘 + TUI | Claude Code、Codex、Gemini、agy、OpenCode、Hermes | 忙/等待数量、点击终端、完成通知。**Claude 读会话状态，其余用 CPU≥5%/子进程启发式**，不能一概称精确识别审批等待 | **1★** | 建仓 2026-11-08 / 最近推送 2026-11-15 |
| 21. claude-notify（ddaikodaiko） | [仓库](https://github.com/ddaikodaiko/claude-notify) | GitHub；macOS/Linux/Windows 桌面 + 手机 ntfy/webhook | 软件完成通知 | Claude Code | Stop hook 读 transcript，通知附编辑文件数/命令数摘要；可用 ntfy 或自托管。**只证实完成通知，审批通知/回答未找到** | **6★** | 建仓 2026-04-05 / 最近推送 2026-11-03 |
| 22. teleclaude | [仓库](https://github.com/fgrebenac/teleclaude) | GitHub；Mac/Linux 主机 + Telegram | 软件手机界面/通知 | Claude Code | 每个 Telegram forum topic 绑定项目与持久会话，多项目并行、工具/子 agent 视图、Allow/Deny 按钮、重启恢复。作者个人日用；依赖 Claude 内部实现，升级兼容性有风险 | **17★** | 建仓 2026-10-22 / 最近推送 2026-11-03 |
| 23. HeyAgent CLI | [当前仓库](https://github.com/gergomiklos/heyagent)；[Product Hunt](https://www.producthunt.com/products/heyagent)；[作者发布帖](https://www.indiehackers.com/post/launching-heyagent-on-product-hunt-today-4277b24cce) | GitHub/Product Hunt；本机 CLI + Telegram，手机配对 | 软件手机桥接 | **当前 v2：Claude Code、Codex**；Gemini 已接入证据未找到 | 原版做完成/权限通知；当前 README 已改双向 Telegram、切换 agent、排队与停止。**默认 provider 启动会绕过权限/沙箱，不能当成安全审批范本**。PH 的 email/WhatsApp 描述和 Codex coming-soon 是旧版，不当当前能力 | **94★**；PH **13 points / 5 followers** | 建仓/作者发布 2025-09-07；最近推送 2026-05-28 |

### 容易被旧摘要误导的几处

- **VibeDeck**：搜索摘要仍有 1.0.4 / 2026-10-23 / 30 actions；实际打开的商店正文为 **2.0.0.2 / 2026-11-09 / 33 actions**，采用后者。[版本记录](https://www.getvibedeck.com/releases/)也记录了 screen card。兼容表混有后续 2.1 的 WSL/SSH 信息，不能据此断言当前商店 2.0 全部具备。
- **Beacon、Jetstream**：都有 Codex 字样，但前者是 Codex 额度，后者是 Codex usage gauge，不能写成 Codex 状态和审批已完整支持。[Beacon](https://github.com/angaziz/beacon)、[Jetstream](https://github.com/pimmesz/jetstream)。
- **Code Light、CC Lights、HeyAgent**：分别存在仓库改名/增加 agent、支持范围扩展、产品从通知器转向 Telegram 桥接的变化。当前支持范围采用主表仓库正文；历史帖只用于日期、反馈和热度。
- **“硬件按钮”不等于“审批按钮”**：claude-status 的 BOOT 只消除提醒；Codex Macropad 是状态显示；Brillar AgentDeck 尚未制造。把这些混算成“可用审批硬件”会高估竞争成熟度。

## 用户原话：10 条短摘录

保留原语言，**每条不超过 25 个字符，包含空格和标点**；短摘录的指代在上下文列解释。包含普通使用者与制作者自述，明确区分；这些是个案，不是代表性调查，也不说明问题在最新版仍未修复。

| # | 原话 | 谁 / 时间 / 样本性质 | 出处与上下文 |
|---|---|---|---|
| 1 | “check each tab/window.” | sohil404；2026-03-21；GitHub 需求提出者 | [Claude Code #36885](https://github.com/anthropics/claude-code/issues/36885)：同时开多个会话，必须逐个查看哪个在等批准或回答。 |
| 2 | “就是切走忘记及时切回来” | qdcanyun；2025-10-10；VibeJetty 制作者自述 | [V2EX 原帖](https://www.v2ex.com/t/1164258)：不是反复回来查看，就是切走后忘记；想让完成/授权通知带任务内容，并能点回会话。 |
| 3 | “一直闪烁，有点晃眼” | pxiphx891；2026-07-13；独立评论者 | [CC Lights 原帖第 7 回复](https://v2ex.com/t/1226660)：同一评论还要求跨工具接入，并担心十个会话占满菜单栏。 |
| 4 | “Too many approval gates” | Fragrant-Shine7024；2026-03-09；Reddit 评论者 | [具体评论](https://www.reddit.com/r/ClaudeCode/comments/1rowglj/comment/o9hgosb/)：担心审批门过多让无人值守失去意义；关键是别频繁打断。 |
| 5 | “I didn’t really read it.” | Rob Bell；2026-07-07；开发者使用自述 | [Permission Fatigue 原文](https://spin.atomicobject.com/permission-fatigue-claude-code/)：多次弹窗后形成点 Allow 的惯性，这句指没有认真读命令。 |
| 6 | “Which tasks failed?” | yaco；2026-09-16；Codex 用户需求帖 | [用任务板替代宠物的请求](https://community.openai.com/t/feature-request-replace-codex-pet-with-a-codex-task-board/1397992)：想看 Running/Needs Me/Review/Failed 及 repo、分支、PR；这是需求，未发现已实现证据。 |
| 7 | “doesn't show the progress” | notconfusing；2026-06-15；Codex 宠物体验帖 | [原帖](https://www.reddit.com/r/codex/comments/1u6nytz/design_thoughts_on_the_pet/)：肯定常驻提醒的价值，但认为宠物动画不足以解释后台进展。 |
| 8 | “I love the pet.” | Organic-Parsley-486；所属帖 2026-06-15，评论精确日期未找到；正面用户评论 | [具体评论](https://www.reddit.com/r/codex/comments/1u6nytz/comment/ortxj43/)：喜欢宠物作为可爱的会话管理与提醒方式；保留正面反馈，避免只挑抱怨。 |
| 9 | “too big and annoying” | SenecioNemorensis；所属帖 2026-08-12，评论精确日期未找到；停用宠物的评论者 | [具体评论](https://www.reddit.com/r/codex/comments/1vmd1cg/comment/p3ahil4/)：尺寸与干扰是停用原因，不能据此推断所有人都不喜欢宠物。 |
| 10 | “最后还是字母加状态灯最清楚” | Siminnn；2026-11-12；TC002 改造者自述 | [少数派原文](https://sspai.com/post/118939)：低分辨率下，多家 logo 不易读，最后选字母加状态方块。 |

另有两类反馈与第一版交互直接相关：

- **完成信号也可能漏发。** [r/ChatGPTCoding 的多 agent 实践帖](https://www.reddit.com/r/ChatGPTCoding/comments/1wxe9b3/three_things_i_changed_today_running_several/)记录：任务已在聊天中结束，但 watcher 读取的状态文件没更新，作者约 25 分钟后才发现。提醒系统本身要能显示失联/状态不一致，不能只设计正常动画。
- **浮层交互会造成误切窗口。** [Codex 宠物焦点问题帖](https://community.openai.com/t/pet-overlay-treats-press-and-release-as-a-click-and-unexpectedly-focuses-codex/1393843)报告按住/拖动后松开被当成点击；[r/OpenAI 的菜单位置讨论](https://www.reddit.com/r/OpenAI/comments/1v0kerb/anybody_hates_the_pet_button_location/)则报告查看额度时误点宠物。这支持区分拖动与执行、保持布局稳定；不据此判断问题已修复与否。

## 对 AgentDeck 的结论

以下是根据上述案例作出的产品判断，**不是已被这些项目证明的付费需求或性能结论**。

### 直接竞品与软件替代

| 类别 | 优先关注 | 对本项目的含义 |
|---|---|---|
| 最直接：现有键盘 + 状态 + 操作 + 浮窗 | **VibeDeck、Agent F-Row** | 已覆盖第一版的大部分表面功能。VibeDeck 还有请求卡片；F-Row 已覆盖 Windows 普通 RGB 键盘。要比较安装、可靠性、中文请求可读性和会话定位，不能只比较键数。 |
| 直接：本地 hub + 多家 agent + 多终端控制 | **puritysb/AgentDeck** | 不只是一个优篮子插件，已经把硬件、手机、桌面和 CLI 放在同一状态模型里；也是明显命名重合。是否构成商标冲突未调研，不能下法律结论。 |
| 直接：单家 agent 的物理审批/会话操作 | **ClauDeck、Jetstream、claude-esp32-dashboard、Beacon** | “按键批准”“一个会话一个键”“超时回终端”已有实现；跨家支持仍须逐项比较，不能因都有 Codex 字样就认为审批能力相同。 |
| 邻近：灯光/RGB/小屏观察 | **Micr0Pad、Codex Macropad、claude-monitor、claude-status、TC002 改造** | 说明余光查看与复用现成硬件的做法可行，但大多没有完整请求级审批，或只验证少量设备。 |
| 免费/低门槛软件替代 | **AgentPet、CC Lights、Code Light AI、Dashbar、agentop** | 用户可以先用浮宠、菜单栏、notch 或托盘；仅提供“谁在等我”不足以解释新增一块硬件的价值。 |
| 远离桌面时的替代 | **claude-notify、teleclaude、HeyAgent** | 手机通知/会话桥接能覆盖离桌需求。第一版可先做好桌面闭环，不必因此扩大为远程控制产品。 |
| 早期设计竞品 | **Brillar0101/agentdeck** | 逐键 RGB、专用批准/拒绝、多个 agent 键的设计已有人公开；仍未打板，不能与运行中的产品同等看待。 |

### 值得借鉴进 4×4 + RGB + 浮窗的做法

1. **固定物理位置，浮窗处理紧急排序。** 参考 F-Row 的稳定 lane：同一会话保留同一键位，不因新事件不断重排。最急请求可以在浮窗置顶，同时闪对应的物理键；会话多于槽位时用页码/溢出提示，不静默覆盖。
2. **灯回答“哪里需要我”，浮窗回答“为什么、准备做什么”。** 参考 VibeDeck 的 screen card：浮窗显示 agent、项目、会话、原始问题或完整命令、等待多久、允许/拒绝结果。RGB 配文字/符号，等待灯亮不能被另一会话的普通工作事件抹掉。
3. **先选会话，再处理具体请求。** 会话选择和批准分别表达；同一请求应有稳定身份，过期/已处理的请求不得因键位复用被再次批准。若某适配器只能切窗口/按 Enter，明确标成该能力，不能包装成钩子直答。F-Row 的焦点核验和 Jetstream 的请求队列都值得对照。
4. **把审批失败路径一起设计。** 参考 Jetstream/ClauDeck 的限时回原生界面；明确区分“放弃设备接管，交回终端”与“自动允许”。暂停提示、拒绝请求、打断当前 turn 是三种不同动作；claude-status 的确认已看到也应单独命名。
5. **状态要有新鲜度和来源。** 显示最后更新时间、离线/过期/未知。日志静默、CPU 降低不能自动等价于等待批准；Code Light 的超时改完成尤其不宜照搬。DONE 表示本回合结束，验收通过要另有证据。
6. **减少批准疲劳，同时减少灯光疲劳。** 普通工作以稳定/低亮灯表现；需要人时再慢闪，可调亮度/静音/暂缓提醒。重复通知合并，已读与已处理分开。物理按钮让重复同意更顺手，并不会自动解决“没读就批”的问题。
7. **浮窗以可读、克制为先。** 宠物有人喜欢、有人停用；第一版优先原文请求、等待数量和可靠跳转，可缩小、移动、隐藏。动画作为可选呈现；拖动不执行点击，更新不改变用户准备按的位置，也不强抢焦点。
8. **复用设备，但逐型号验证双向能力。** Codex Macropad/Micr0Pad 各有实际验证型号和不同协议。不能从“宏键盘能输出快捷键”推断“电脑能独立控制 16 颗 RGB”。先列出所选 4×4 设备是否可读按键、可逐键写灯、是否影响正常键盘输入，再决定兼容承诺。

这些案例没有证明“4×4”优于其他布局，也没有证明用户会为额外硬件付费。更有价值的第一版验证是：三家以上 agent 并行时，用户能否可靠找到正在等人的具体会话、读完请求并处理，且安装和使用比现成软件替代更省事。

建议用真实日常任务比较 VibeDeck/F-Row 与本项目：首次安装到收到有效状态的时间、等待到响应时间、漏报/误报次数、错误跳转或过期审批次数、每天实际使用次数。先验证闭环质量，再决定是否扩大按键数量、语音或宠物功能。

## 检索覆盖、未找到与可追溯限制

| 检索范围 | 本次结果 |
|---|---|
| GitHub | 主表多数项目；读取仓库正文、当前 README 及 API 元数据。零星数仍如实列零；未安装运行，仓库存在不代表功能已通过实测。 |
| Reddit：r/ClaudeAI、r/ClaudeCode、r/codex、r/olkb、r/esp32、r/ChatGPTCoding、r/OpenAI | 找到宏键盘、Busylight、宠物、多 agent 状态与漏报反馈。另可打开 [Codex 宏键盘的 r/olkb 原帖](https://www.reddit.com/r/olkb/comments/1vo885t/i_turned_my_macropad_into_a_codex_status_display/)及 [ESP32 墨水屏额度改造帖](https://www.reddit.com/r/esp32/comments/1w4ew64/esp32_eink_dashboard_for_claude_and_codex_usage/)。后者是额度显示，未扩写成审批设备。 |
| Reddit：r/MechanicalKeyboards、r/streamdeck | 检索了 Claude/macropad/status/approve；本次未找到额外可独立核实并入表的原始案例。Stream Deck 案例用原作者仓库/商店核实，不冒称来源于这两个板块。 |
| Reddit Kuando Busylight 热帖 | [原帖可打开](https://www.reddit.com/r/ClaudeAI/comments/1xcdwdx/i_got_tired_of_checking_whether_claude_code_needs/)，可读工作/等待/空闲灯色及多会话讨论；作者开源仓库、可靠精确日期、正文可见票数 **未找到**。不采用搜索摘要的数千票，未列入主表。 |
| V2EX | Code Light、CC Lights、VibeJetty 的作者帖可读；有独立用户谈闪烁、泛用接入与菜单栏容量。VibeJetty [产品站](https://www.vibejetty.com/)也可打开，但首发为 2025，主表优先其他 2026 项目。 |
| 少数派 | TC002 2026-11-12 个人实操原文已读并入表。另检索到 post/105621 的手机 Bark 通知、post/118437 的 CodexBar，但正文重试超时；可核实正文/当前热度 **未找到**，不据摘要补条目。 |
| Product Hunt | HeyAgent 产品页及 maker/用户讨论可读，13 points、5 followers。与名为 HeyAgent.live 的社交代理产品不同；旧 PH 功能不能替代当前仓库说明。 |
| X/Twitter | 检索 Claude Code/ESP32/macropad/pager。找到 JeandeBaill 的 Claude Pager 状态号 2099443428987658415，但原帖 403。可核实原帖正文与互动数 **未找到**；二手汇编不作原作者证据，不入主表。主表 Lloyd Pager 是另一位作者，不混为一个项目。 |
| 小红书 | 检索 Claude Code + 键盘/宏键盘/状态灯；可公开读取且可归属具体项目的笔记、作者及互动数 **未找到**，不编笔记链接。 |
| B 站 | 检索到“你用claude不会还在打字吧？？？”（BV1VwAhzPE5d），打开返回 412；可核实视频正文、作者源码和播放/点赞数 **未找到**，不把摘要里的四键/OLED/语音配置当已核实项目。 |
| Hackaday / Hackaday.io | 检索 Claude Code + status/light/硬件；本次未找到可核实、符合 agent 状态/控制主题的独立原始案例。没有用泛 AI 生成硬件或普通计时器凑数。 |
| 优篮子插件商店 | puritysb README/项目站列出 D200H/D200X 插件及商店入口，但 contentView/1239890184745660416 本次无法取得正文；商店实际安装量、评分 **未找到**。主表仅按作者文档写接入声明，不把商店上架/下载视为独立核实。 |
| QMK / RP2040 / ESP32 | 找到现有 Raw HID/VialRGB 键盘接入、RP2040 设计原型和多个 ESP32 实物项目；任意 QMK 4×4 均可接入、任意成品宏键盘可逐键回写 RGB 的证明 **未找到**。 |

检索词主要组合：`Claude Code / Codex / Gemini / Cursor` + `status light / macropad / approve / permission / waiting / Stream Deck / ESP32 / RP2040 / QMK / tray / notification / pet`，中文补 `状态灯 / 宏键盘 / 批准 / 等待 / 浮窗 / 手机通知`。平台通过站点限定和原帖追溯交叉检索，时间优先 2026；“未找到”只描述本次公开可访问证据，不表示该平台或功能不存在。
