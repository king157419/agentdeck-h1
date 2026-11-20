# 简报：截图键在 Claude 桌面版里粘贴图片本身

现状（`pc/hub_desktop.py` 的 `DesktopEffects.screenshot`）：截全屏 → 存 PNG 到 `~/.agentdeck/shots/` → 把**文件路径**粘贴到所选会话窗口的输入框（不回车）。
用户的会话在 Claude 桌面版里，粘贴路径没用，用户要的是一张图片附件。

## 要做的
1. 目标窗口（`_focus` 返回的那个）所属进程是 Claude 桌面版（claude.exe）或 Codex 桌面版（进程名里含 codex、且是 GUI 窗口而非终端）时：
   - 图片仍然存到 shots 目录（留档）；
   - 把图片放进剪贴板：CF_DIB（由 PIL 图像生成 BITMAPINFOHEADER + 像素，32 位或 24 位都行），同时放注册格式 "PNG"（PNG 字节），这样 Chromium/Electron 能当图片粘贴；
   - 调到前台后发 Ctrl+V，不回车；
   - 剪贴板处理和现有的 `_paste` 保持一致的风格（打开/清空/设置/关闭，失败要关闭剪贴板；如果 `_paste` 会恢复用户原来的剪贴板，这里也同样在粘贴后恢复，注意等粘贴完成再恢复）。
2. 其他窗口（终端、VS Code 等）保持原来的行为：粘贴路径。
3. 反馈文字：图片方式"截图已贴进输入框"，路径方式保持原样。
4. Raw Input 读键时仍然拒绝（不变）。
5. 测试：用假的剪贴板/按键对象覆盖两条路径（claude.exe → 设置了 CF_DIB 和 PNG 两种格式并发 Ctrl+V、没发回车；终端 → 粘贴路径），以及剪贴板打开失败时不留下打开状态。
6. 更新 `agentdeck/使用说明书.md` 里截图键的说明（第 3 排第 1 颗和旋钮 1 按下是同一个信号 L，所以两者都是截图；在 Claude/Codex 桌面版里贴图片，在终端里贴路径），PDF 按上次命令重新生成：复制 md 到临时目录，`D:/conda/miniconda3/python.exe -X utf8 D:/desk/claudex/_reports/tools/report.py <copy>.md --css agentdeck/使用说明书.css --out agentdeck/使用说明书.pdf`。

## 做完的标准
每个 `pc/test_*.py` 单独跑都退出 0。不打包 exe，不 git commit，不碰真实的 ~/.claude、~/.codex、计划任务、注册表、键盘 0xFF00 接口。
