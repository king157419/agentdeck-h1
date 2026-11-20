# 简报：管理面板（方案 A）

用户选了方案 A：会话在左、键盘实物图在右，点一颗键在右边改它的功能。视觉规格：`agentdeck/mockups/panel.html` 的第一个方案（配色、字号、圆角、间距照搬；图上的会话数据是示例，面板里一律用真实数据）。键位语义见 `agentdeck/键位方案-v9.md`，在 v9 第一步完成之后做。

## 技术路线（不新增要下载的依赖）
- 面板是一个本地网页，由 hub 现有的 HTTP 服务（`pc/hub.py` 的 HubServer，127.0.0.1:47800）提供：`GET /panel` 返回页面，静态文件放 `pc/ui/`（panel.html、panel.css、panel.js，原生 JS，不用框架，不走 CDN），打包时加进 agentdeck.spec 的 datas（目标目录 `ui`）。
- 用 Edge 的应用模式打开成独立窗口：从注册表 `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe`（再查 HKCU）拿路径，运行 `msedge.exe --app=<url> --window-size=1180,760`；找不到 Edge 就用默认浏览器打开。同一时间只开一个（已开着就把它调到前台，按窗口标题 "AgentDeck" 找）。
- **鉴权**：面板不能拿到 hub 的 token。托盘点"管理面板"时，hub 生成一次性登录码（60 秒有效、只能用一次），URL 写成 `http://127.0.0.1:47800/panel#code=<码>`（放在 # 后面，不会发给服务器、不进日志）；页面 JS 读到后 `POST /panel/login`，hub 换成 HttpOnly、SameSite=Strict、Path=/panel 的会话 cookie，并用 history.replaceState 去掉 #。之后所有 `/panel/api/*` 请求只认这个 cookie，并检查 Origin（若有）必须是 `http://127.0.0.1:47800`，POST 必须是 JSON。现有带 token 的接口不变。
- 数据刷新：页面可见时每 600 毫秒 `GET /panel/api/state`（不可见时暂停）。返回：设备连接、读键方式、拦截批准模式、当前层、会话列表（按最近活动；标题、agent、项目、状态、最近活动时间、等批准时的工具名和命令首行）、键位（物理布局 + 每个层的绑定 + 中文功能名）、最近按键（环形缓冲，带递增序号、物理位置名、结果三类之一和文字）。
- "Claude 里正打开"标记：只在面板可见时，后台线程每 3 秒用现有 claude_uia 读一次当前会话；面板关了就停。

## 页面内容（方案 A）
- 顶栏：AgentDeck；设备状态胶囊（"宏键盘已连接 · USB 直读" / "宏键盘未连接"）；"拦截批准"分段按钮（自动 / 总是 / 从不，调现有 hold 动作）。
- 左栏"最近活动"：每行 色点 + 标题 + "Claude · 项目 · 状态" + 多久以前；Claude 当前打开的那个打标签"Claude 里正打开"；等批准的行展开黄色块：命令首行 + "批准""拒绝"两个按钮（走和按键同一条批准路径，只作用于这一条请求）；点一行 = 跳到这个会话（现有 show 路径）。没有会话时显示一句"还没有 agent 会话"。
- 右侧：键盘实物图（按 hub 里的 KEY_ROWS / KNOBS 画 4 个旋钮 + 5×4 键，每颗键上写当前层的功能名；空键灰色）；图上方一排层切换（Agent / 聊天 / 浏览器 / 视频 / 默认，默认选当前层），切换只影响图上显示和编辑，不改变真实的当前层；**按下实体键时图上对应的键亮 0.6 秒**（用最近按键缓冲），旁边显示这次的结果文字。
- 点一颗键 → 右侧详情：键名和位置（"第 2 排第 1 颗"）、当前功能、可选功能列表（单选）、"恢复默认"。规则：第 3–5 排和 R5C4 是固定键，详情里显示锁和一句"固定键，任何应用里都不变"，不能改；第 1 排可选"打开某个应用"（Claude/Codex、微信、飞书、浏览器、自定义 exe 路径）；第 2 排和旋钮 4 按当前选中的层改（可选列表：提示模板、各快捷键动作、空）。保存写用户的 `~/.agentdeck/hub_keys.json`（标记为用户改过，以后升级不覆盖），立即生效。
- 浅色/深色跟随系统（prefers-color-scheme）。窄于 900 像素时上下排。

## 托盘
- 菜单第一项"管理面板"（默认项，双击托盘图标打开）。去掉旧的"状态""键位"两项（对应的 Tk 窗口代码先保留，不再从菜单进入）。

## 测试
- 一次性登录码：过期、重复使用、错误码都拒绝；cookie 属性正确；没有 cookie / Origin 不对 / 非 JSON 的请求拒绝；带 token 的老接口不受影响。
- `/panel/api/state` 结构；按键缓冲的序号；键位编辑：固定键拒绝修改、按层写入、恢复默认、写入后用户文件不被自动升级覆盖。
- Edge 路径查找和"已开着就激活"的分支（用假的注册表/进程）。
- 用内置浏览器或 headless 方式渲染 /panel 截图检查一次（放 research/history/panel-a-*.png），不要求自动化 UI 测试。

## 做完的标准
每个 `pc/test_*.py` 单独跑都退出 0（test_focus_lock.py、test_verify_real_session.py 偶发失败可重跑一次）。在 `research/history/panel-a-results.md` 写结果。说明书加一节"管理面板"，PDF 按老命令重新生成。不打包 exe，不 git commit，不碰真实的 ~/.claude、~/.codex、~/.agentdeck、计划任务、注册表写入、键盘 0xFF00 接口。
