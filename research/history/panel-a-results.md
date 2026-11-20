# 管理面板（方案 A）结果

按 `research/briefs/brief-panel-a.md` 完成。没有 git commit，没有打包 exe，没有碰真实的 ~/.claude、~/.codex、~/.agentdeck、计划任务、注册表写入和键盘 0xFF00 接口。

## 做了什么
- **本地网页**：hub 的 HubServer 在 `/panel` 提供页面（`pc/ui/panel.html|css|js`，原生 JS，无框架、无 CDN，配色/圆角/间距照搬 `mockups/panel.html` 方案 A，跟随系统浅/深色，窄于 900 px 上下排）。
- **鉴权**：托盘点"管理面板"生成一次性登录码（60 秒、一次性，连续猜错 5 次所有未用的码作废），URL 为 `http://127.0.0.1:47800/panel#code=<码>`；页面 `POST /panel/login` 换 HttpOnly + SameSite=Strict + Path=/panel 的 cookie，并 `history.replaceState` 去掉 `#`。`/panel/api/*` 只认 cookie，另检查 Host 必须是 `127.0.0.1:<端口>`、Origin（若有）必须是 `http://127.0.0.1:<端口>`、POST 必须是 `application/json`。原有带 token 的接口原样不变（cookie 不能当 token 用）。
- **数据**：页面可见时每 600 ms `GET /panel/api/state`（不可见暂停）：设备连接/读键方式、拦截批准模式、当前层、会话（标题/agent/项目/状态/多久以前/等批准的工具名和命令首行）、物理布局、5 个层各自的绑定和中文功能名、最近按键环形缓冲（递增序号、物理位置名、success/noop/error、文字）。"Claude 里正打开"由后台线程每 3 秒用现有 `claude_uia`（经 `current_session_title`）读一次，页面 4 秒没来取数据就自己停。
- **页面**：顶栏（设备胶囊、拦截批准 自动/总是/从不）；左栏最近活动（点一行跳会话，等批准的行展开黄色块和"批准""拒绝"，走和按键同一条 `Hub.action` 批准路径，带 request_id + nonce，只作用于这一条，高危请求仍要点两次）；右侧键盘图（4 旋钮 + 5×4 键、层切换只影响显示、按键亮 0.6 秒并在下方给出结果文字）；点键看详情和改键，固定键显示锁。
- **改键**：第 1 排可选 Claude/Codex、微信、飞书、浏览器、自定义 exe 路径（hub 新增 `app exe:<路径>` 动作，按文件名找已开着的窗口，不启动程序）、空；第 2 排和旋钮 4 按层改（提示模板、快捷键动作、列表动作、空）；第 3–5 排、R5C4、旋钮 1–3 锁死，服务端也拒绝（403）。保存写 `<home>/.agentdeck/hub_keys.json`，加 `"user_modified": true`，`upgrade_keymap` 看到它就不再覆盖；`USBKeys.reload` 让改动立即生效。"none" 绑定表示空（lookup 返回 None）。
- **托盘**：菜单第一项"管理面板"（默认项，双击托盘图标打开），去掉"状态""键位"两项（Tk 窗口代码和浮窗右键菜单里的入口保留）。Edge 应用模式启动（注册表 HKLM 再 HKCU 的 App Paths，`--app=<url> --window-size=1180,760`），没有 Edge 用默认浏览器；已开着（Edge、标题 "AgentDeck"）且还有有效登录就调到前台；没有有效登录则开新窗口。
- **打包**：`agentdeck.spec` 把 `pc/ui/*` 放进 datas（目标目录 `ui`），并加了 `panel`、`panel_launch` 到 hiddenimports；`panel.ui_dir()` 源码时用 `pc/ui`，冻结时用 `sys._MEIPASS/ui`。

## 改动的文件
- 新增：`pc/panel.py`、`pc/panel_launch.py`、`pc/ui/panel.html`、`pc/ui/panel.css`、`pc/ui/panel.js`、`pc/test_panel.py`、本文件、`research/history/panel-a-light.png`、`panel-a-dark.png`。
- 修改：`pc/hub.py`（HubServer 带 Panel、`/panel` 路由、`Hub.note_key` 按键缓冲、`USBKeys.parse/reload`、`none` 绑定、`app exe:`）、`pc/hub_desktop.py`（`_app_target` 支持 exe）、`pc/agentdeck_app.py`（托盘菜单、`open_panel`、upgrade 保护）、`pc/test_agentdeck_app.py`（菜单断言跟着改）、`agentdeck.spec`、`agentdeck/使用说明书.md`（新增"管理面板"一节、改了几处旧的托盘说法）、`agentdeck/使用说明书.pdf`（已按老命令重新生成，15 页）。

## 测试
`pc/test_panel.py`（27 条）：登录码过期/重复/错误码/猜错作废；cookie 属性；无 cookie、伪造 cookie、Origin 不对、Host 不对、非 JSON 一律拒绝；老 token 接口不受影响；页面静态文件和 CSP；state 结构、层标签、"Claude 里正打开"标记与读取线程只在页面取数据时运行；按键缓冲序号和三类结果、USBKeys 物理按键进缓冲；批准/拒绝只作用于指定请求、过期 nonce 409；点会话走 focus 路径；固定键 403、按层写入、恢复默认、非法功能 400、写入后用户文件不被升级覆盖；Edge 路径查找、已开着就激活、无登录时开新窗口、无 Edge 回退浏览器（全用假的注册表/进程/窗口）；冻结时的 ui 目录、spec 里的 ui 打包、托盘菜单第一项。

每个 `pc/test_*.py` 单独运行（`D:\conda\miniconda3\python.exe -X utf8 <file>`，在 pc 目录下），全部退出码 0（含 test_focus_lock、test_verify_real_session，一次通过，没有重跑）。

## 截图（headless Edge，临时 home 的一次性 hub，随机端口，假会话）
- `research/history/panel-a-light.png`
- `research/history/panel-a-dark.png`（`--force-dark-mode`）

另用内置浏览器在同一个临时 hub 上点过：登录后地址栏的 `#code` 被去掉、点第 2 排键右侧出现选项、选"发“提交”"后保存并立即生效、点第 3 排键显示锁。

## 没做到 / 需要你确认
- 实际开 Edge 应用窗口、双击托盘图标、"已开着就调到前台"在真机上的表现：只用假对象测过，没真开。
- 按下真实实体键时图上亮 0.6 秒：缓冲和前端逻辑测过，真机上没按过。
- 第 2 排的"聊天"层"下一个未读"仍是 v9 未做的功能，面板如实显示功能名但按下是"这一步还没做"。
- 自定义 exe 只会找已经开着的窗口，不会替你启动程序（brief 没要求启动）。
- 浮窗右键菜单里"状态""键位"入口保留（语音快捷键设置现在只能从那里进），brief 只要求去掉托盘菜单里的两项。
- 没有单独存"点选一颗键后的详情"截图（无头截图不能点击）。
