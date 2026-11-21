# 简报：旋钮 3 滚到了隐藏的浏览器面板上，要改成滚对话区

## 现场证据（2026-11-21 02:19–02:20，`~/.agentdeck/logs/app.log`，logger `agentdeck.hub.scroll`）
- 方向是对的：notches=+1 → wheel_total 约 -117（往下），notches=-1 → wheel_total 约 +117（往上）。
- 但每次都滚在 `rect=[1033, 158, 2553, 1380] point=(2537, 769)`。
- 用 UIA 只读查了 Claude 窗口（hwnd 329892），能滚动的大块元素有两个：
  1. 对话区：Group，`[10,45,2160,1370]`，ClassName 里有 `epitaxy-own-scroll-layer`，VerticalViewSize 7.2%（真能滚）。
  2. Claude 内置浏览器面板的页面：Document（RootWebArea），`[1033,158,2553,1380]`，VerticalViewSize 99.9%（几乎没东西可滚）。
     它所在的子窗口 `Chrome_RenderWidgetHostHWND`（72878268）`IsWindowVisible` = 0，**面板已经关了，UIA 还在报旧坐标**。
- `valid_panes` 按左边排序后，`PaneSelection.snapshot` 对 claude.exe 默认选 `len(panes)//2` → 两块时选第 2 块 = 这块隐藏的浏览器页面。
  于是滚轮落在 x=2537，在对话区（右边界 2160）外面，用户看到的就是"上下滚都不对"。
- 另外：某个窗口第一次滚时还没有缓存，用整窗矩形兜底，落点是窗口右边缘往里 16 像素（日志里 point=(2553, 690)），也在对话区外面。

## 要改
1. **`pc/claude_uia.ps1` 的 `Get-ScrollPanes`**：只返回用户真的看得见、真的能滚的块。
   - 丢掉 `VerticalViewSize >= 99` 的（没东西可滚）。
   - 丢掉 `IsOffscreen` 为真的。
   - 丢掉宿主窗口不可见的：从元素往上走（RawViewWalker），找到第一个 `NativeWindowHandle != 0` 的祖先，
     如果它不是顶层窗口本身且 `IsWindowVisible` 为假，就丢掉（这条专治已关闭的浏览器面板、隐藏的 WebContentsView）。
   - 把矩形裁到顶层窗口的可见范围内（和宿主子窗口的矩形取交集），裁完太小（< 窗口面积 4%）就丢掉。
   - 每块多带一个 `chat` 布尔值：ClassName 含 `epitaxy` 的为真（Claude 对话区）。
   - 脚本保持纯 ASCII。
2. **`pc/claude_uia.py` 的 `panes`**：把 `chat` 字段透传（不认识的字段照旧保留）。
3. **`pc/hub_scroll.py`**：
   - `valid_panes` 保留 `chat` 字段。
   - claude.exe 的默认选中：有 `chat` 为真的块就选它；没有就选面积最大的块。其他程序维持现状（index 0）。
   - 用户按旋钮 3 切过栏以后记住的 index：如果这次读到的块数和记住时不同，就回到上面的默认值（避免布局变了还指着旧位置）。
4. **`pc/hub_desktop.py`**：没有缓存时的兜底落点改成窗口正中（不要再落在右边缘）。`_pane_point` 对真实读到的块维持"右边往里 16 像素、上下居中"不变。
5. 测试（新建 `pc/test_hub_scroll_panes.py`，或并进已有的滚动测试）：
   - 两块（对话区 chat=True 在左、另一块在右）→ claude.exe 默认选对话区；
   - 没有 chat 标记 → 选面积最大的；
   - 记住的 index 在块数变化后回到默认；
   - 无缓存时落点 = 窗口正中；
   - PowerShell 侧的过滤不好单测的，至少在 `test_claude_uia.py` 里验证 `chat` 字段能透传。

## 不要做
- 不改滚动方向、速度、平滑参数；不改键位文件；不动动画。
- 不往 0xFF00 接口或 COM4 发东西；不写 `%APPDATA%\Claude` 和 `~/.claude` 下任何文件。
- 不在用户正在用的窗口上做真实滚动、点击测试（只允许只读的 UIA 查询）。

## 做完的标准
- 用只读 UIA 跑一次新的 `Get-ScrollPanes`（对当前 Claude 窗口），输出里不再有那块隐藏的浏览器页面，对话区带 `chat: true`。把这次输出贴出来。
- `pc/test_*.py` 全部通过（逐个用 `D:\conda\miniconda3\python.exe -X utf8` 跑；`test_verify_real_session.py` 偶发失败时单独重跑确认）。
- 列出改动文件；不要提交 git。
