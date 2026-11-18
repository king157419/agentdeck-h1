# 简报：开源社区 / 个人玩家做的 agent 硬件和状态提示（调研）

## 为什么

大厂产品（Codex Micro、罗技 MX Keypad、优篮子 Vibe Key）迭代慢。创始人要看个人玩家和开源社区在做什么：
它们更能说明真实需求、最新玩法，也可能是直接竞品或可借鉴的设计。

## 查哪里

Reddit（r/ClaudeAI、r/ChatGPTCoding、r/OpenAI、r/MechanicalKeyboards、r/streamdeck、r/esp32、r/olkb）、
X / Twitter、小红书、GitHub、Hackaday、Product Hunt、V2EX、少数派、B 站。时间优先 2026 年。

## 查什么

围绕"多个 AI 编码 agent（Claude Code、Codex、Cursor、Gemini 等）"的：

1. DIY 宏键盘 / 批准键 / 打断键（QMK、ESP32、RP2040、Stream Deck 插件、优篮子插件）
2. 状态灯 / 状态屏 / 桌面摆件（agent 在跑、在等你、出错）
3. 软件形态的状态提示：托盘、浮窗、菜单栏、任务看板、手机通知（含 Codex 宠物的用户反馈）
4. 用户抱怨和需求原话：等待提示、批准疲劳、多 agent 管理

## 交付

`agentdeck/research/community-diy.md`：

- 一张表：项目名 / 链接 / 平台 / 形态（硬件 or 软件）/ 支持哪些 agent / 关键做法 / 热度（星数、点赞、评论数）/ 时间。至少 15 条，只收真实能打开的链接。
- 5–10 条用户原话（每条注明出处链接，不超过 25 字的摘录）。
- 结论：哪些做法值得借鉴进 AgentDeck，哪些是直接竞品，对"4×4 键盘 + RGB + 浮窗"第一版的启示。
- 查不到、打不开的如实写"未找到"，不编造。
