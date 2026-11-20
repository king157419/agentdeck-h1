# 简报：AgentDeck 界面美化

用户原话："这个界面太丑，请一个美工 agent 美化一下。"并给了设计原则：

> 我要把它做得像 Linear 的官网或者苹果备忘录一样干净：目标简单、架构简单、设计简单、实现简单。
> 砍掉标语、提示文字和次要标签。如果一个页面非得靠这些东西才看得懂，那就去改布局。
> 每个决定都要同时提升用户体验（UX）、开发者体验（DX）和智能体体验（AX），而且不能弄坏任何东西。

## 范围（都在 `pc/`，Tkinter + pystray）
- 浮窗：`hub_overlay.py`（深色，会话行 + 待批命令 + 按钮）。
- 托盘程序的窗口：`agentdeck_app.py` 里的首次引导、键位图、诊断、各类提示框（现在是 Tk 默认灰底控件，最丑）。
- 托盘图标：`agentdeck_icon.py`。

## 要求
1. 先截图现状：写一个离屏脚本把每个窗口用假数据渲染出来，用 PIL ImageGrab 存到 `research/ui/before/`。改完同样存 `research/ui/after/`。
2. 一套主题：新建 `pc/agentdeck_theme.py`，集中放颜色、字体（中文 Microsoft YaHei UI，西文 Segoe UI）、间距、圆角替代方案。所有窗口都从这里取，不再到处写色值。
3. 去掉默认灰色 Tk 外观：自己画的扁平按钮、统一留白、清楚的层级（一个主操作，其余弱化）。系统 messagebox 能换就换成同风格的小窗。
4. 删字：说明性长句、重复标签、"（只读）"这类次要信息能删就删，靠布局让人看懂。状态颜色保持现有含义（运行绿、待批琥珀、完成蓝、出错红、空闲灰）。
5. 不加任何新动画，不改现有动画的节奏。不改功能、不改按键逻辑、不改 hub 行为。
6. 托盘菜单文字也按同一原则精简，但菜单项和它们的功能保持不变（另一项任务刚加了"所有项目启用"和"单个项目"子菜单，保留）。

## 完成标准
- `D:\conda\miniconda3\python.exe` 跑 `pc/test_agentdeck_app.py`、`pc/test_hub_app_support.py`、`pc/test_hub.py`、`pc/test_ui.py` 全过（测试若断言了旧文案，按新文案改断言，不许删测试）。
- `research/ui/before/` 和 `research/ui/after/` 各有每个窗口一张图。
- 结果写进 `research/ui-polish-results.md`：改了哪些文件、每个窗口改了什么、测试输出摘要。
- 不打包 exe，不提交 git。
