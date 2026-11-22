# 简报：AgentDeck 交互流程竞品拆解（只调研，不改代码）

## 背景
用户想用宏键盘 + AgentDeck，不碰键鼠就能管理 agent。
- 市场层的竞品分析已经有了：`agentdeck/02-竞品分析.md`，讲的是价格和形态，不要重复。
- 这次要的是**交互层**：别人怎么走完一整个使用流程；难的几步怎么解决，还是干脆没做。
- 我们现在的键位见 `agentdeck/键位方案-v9.md`。

## 用户的使用流程（按顺序）
1. 冷启动：插键盘、开机，软件自己启动。
2. 一键唤醒或切到 Claude 桌面版、Codex。
3. 选会话（一般是最近的）。选完，文字光标要落进输入框。
4. 滚动，读 agent 的回复。
5. 回复、布置任务（以语音为主）。
6. 等待期间切走：看别的会话、微信、刷视频。
7. 回来时知道哪个 agent 在等我（通知或状态）。
8. 批准权限，包括 computer use 这类高权限申请。
9. 卡住或撞到用量上限：先停止，再召回上一条指令（像终端里按 ↑），改一改或原样重发。
10. 打断、插话：agent 干活时补充指令。
11. 旁问（by the way / side chat）：问个小问题，不打断主任务。
12. 引用 agent 回复里的某一段，回复或追问。

## 要查的产品
每个都要打开官方页面、文档或 README 核实，查不到就写"没查到"。
- **硬件**：
  - Codex Micro（OpenAI × Work Louder）
  - Logitech MX Keypad 的 Claude Code / Codex 配置
  - Elgato Stream Deck 的 Claude 页面和插件（agentsd、Claude Code Approver 等）
  - VibeKeys
  - 优篮子 AU05 Vibe Key，以及 D200 + puritysb/AgentDeck
  - claude-desktop-buddy
  - Keychron F4 HE Vibe Coding Keypad
- **软件**：
  - Happy（手机端）
  - Claude Code 官方的 Remote Control 和手机端
  - Codex 桌面版
  - Google Antigravity 的 Agent Manager
  - 终端多开工具：Claude Squad、cmux、asheshgoplani/agent-deck
- **不用键鼠的工具**：
  - Talon + Cursorless
  - Windows 语音访问（Voice Access）
  - Wispr Flow（Command Mode）
  - Homerow、Hunt-and-Peck 这类贴提示标签点选的工具
- 你认为同样相关、上面漏掉的，最多补 3 个。

## 每个产品要回答
1. **定位**，一句话：它想替代键鼠、给键鼠加速，还是让人离开电脑也能管？先引它自己的原话（不超过 15 个词），再写你的判断。
2. **覆盖**：上面 12 步里覆盖了哪几步，怎么做的，具体到按键、手势或界面。没覆盖的写"没做"。
3. **9–12 步写清楚**（召回重发、打断、旁问、引用回复）：
   - 做了，就写怎么做；
   - 没做，就写"没做"，并说明用户在这一步只能退回哪种方式：键鼠、手机还是语音。

## 另外要核实的事实（每条给出处）
- Codex CLI 和 Codex 桌面版：
  - 召回上一条
  - 打断
  - 干活时排队发消息
  - 旁问
  - 编辑上一条重发

## 输出
写到 `research/history/竞品交互拆解-2026-11-22.md`，包括：
1. **总表**：行是产品，列是 12 步。格子里写短语：✔ 加怎么做 / ✘ 没做 / ? 没查到。
2. **难点四步（9–12）逐个写**：谁做了，怎么做的，最值得我们学的是哪一种。
3. **定位归类**：替代键鼠 / 给键鼠加速 / 离开电脑也能管，各有哪些产品。
4. **对 AgentDeck 的建议**：最多 8 条，每条写清学谁、改什么键或功能、为什么。
5. **来源列表**（URL）：每条事实后面标来源编号。

## 规矩
- 必须联网查证。不能联网，就在输出文件第一行写 NO_WEB，然后停止。
- 只调研，不改任何代码和文档，上面那个输出文件除外。
- 不往键盘的 0xFF00 接口或 COM4 发东西，不动正在运行的 AgentDeck。

## 做完的标准
- 输出文件存在，总表 12 列都填了内容。
- 每条事实都有来源编号，来源能打开。
