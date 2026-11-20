# Daily fixes 实现与验证结果

日期：2026-11-20。依据：`research/briefs/brief-daily-fixes.md`。

完成状态：六项要求均已实现；48 个 `pc/test_*.py` 分别在独立进程运行，最终全部退出 0。未打包 exe、未 git commit。

## 逐项改动

1. **所有旋钮的软件段落**
   - `hub_keyboard.KnobDetents` 独立保存四个旋钮的方向、最后一格时间和累计脉冲。
   - 与上一格反向且不足 120 ms 的脉冲丢弃；被丢弃的脉冲不更新时间。边界 120 ms 可以执行。
   - `config.json` 的 `knob_divider` 接入实际 `USBKeys` 路径，默认每个旋钮 1 个脉冲一格；如 `{"1": 2}`。方向改变时重新累计，非法配置拒绝启动。
   - 仅裸旋转 HID 码经过过滤；按下和 Ctrl+F 等组合键保持原行为。共用的 `hid:0x13` 按旋钮规则处理。
2. **Alt+Tab**
   - 每次切换的首格，无论方向均发送 Alt+Tab；Alt 保持期间，后续顺转 Tab、逆转 Shift+Tab。
   - 默认停转 1200 ms 后释放 Alt；`window_switch_release_ms` 从配置传到桌面对象及 `WindowSwitcher`。
   - 保留发送失败、部分发送、退出时释放按键的保护。
3. **旋钮 2 选会话**
   - `cycle` 只修改选择和显示，不调用窗口激活或 Claude 侧栏切换；按下执行原有 `show` 路径。
   - UI Automation 由后台线程在每次转动开始时读取一次；首格直接返回。只有用户尚未转第二格、没有执行其他动作且仍在本次转动期间，回读结果才能将选择移到当前 Claude 会话。
   - 转动停止不足 5 秒时，旋钮和浮窗共用冻结顺序；期间新会话追加后也固定位置，后续事件不会使它重排。过期后恢复最近事件排序。
   - 退出时关闭桌面对象并有界等待读取线程；关闭状态和惰性资源创建共用锁，防止退出后创建 UIA 或整个桌面对象。
4. **无操作可做的反馈**
   - 空批准/拒绝显示“现在没有要批准的请求”；导航因 agent 未提问被拦时显示“只有 agent 提问时才能用”。
   - USB 与热键共用 `Hub.note_action`，短提示复用浮窗标题行，不新增反馈行；提示出现和消失时保留窗口大小、位置，也不反复隐藏/重显。
5. **浮窗**
   - 默认隐藏；待批请求持续显示；完成、错误和普通按键反馈显示 3 秒；旋钮选会话停转 2 秒后隐藏。旋钮反馈不会额外延长到 3 秒。
   - `overlay toggle` 切换常驻/自动隐藏；`overlay corner` 按右下、右上、左上、左下循环。默认在右下，因此首次切换到右上。位置和角落锚定状态持久化；上方角落重启后遇到内容高度变化仍固定上边，拖动解除角落固定。
   - 回复预览去掉 Markdown 标记并保留代码块正文、链接文字。
   - 宽度不超过主屏的 22%，最多显示 4 个会话，选中项始终在可见范围。
6. **说明书和 PDF**
   - 同步按键表、旋钮设置、切换会话、导航反馈、浮窗说明及配置示例。
   - 将 Markdown 复制到临时目录，按指定的 `report.py ... --css ... --out ...` 命令生成 PDF。
   - 实际输出：`页数=15，最常见字号=11.2pt（74% 字符）`，退出 0。
   - 已渲染并检查全部 15 页，无可见裁切或重叠。浮窗修改前后截图已检查：保持原样式，测试画面的高度由 467 缩为 377 像素，会话从 6 行缩为 4 行，Markdown 转为纯文本。视觉检查记录在 `.omx/state/daily-fixes/ralph-progress.json`。

## 修改文件

实现文件：

- `pc/hub.py`
- `pc/hub_keyboard.py`
- `pc/hub_window_switch.py`
- `pc/hub_desktop.py`
- `pc/hub_hotkey.py`
- `pc/hub_overlay.py`

新增测试：

- `pc/test_hub_daily_fixes.py`：12 个集成回归测试，涵盖不激活窗口、异步不阻塞、迟到结果失效、冻结及新增会话排序、关闭竞争、短提示、热键元数据、滤波接入和配置传递。
- `pc/test_hub_overlay_daily.py`：13 个回归测试，涵盖默认隐藏、待批持续、3 秒/2 秒计时、常驻、角落持久化、重启高度变化、短提示几何、尺寸和 Markdown。

更新现有测试：

- `pc/test_hub_keyboard.py`
- `pc/test_hub_window_switch.py`
- `pc/test_hub_overlay.py`
- `pc/test_session_titles_uia.py`
- `pc/test_hub_fixes.py`
- `pc/test_hub_keypad.py`
- `pc/test_hub_app_switch.py`
- `pc/test_hub_tk_wake.py`
- `pc/test_hub_ui_live.py`
- `pc/test_agentdeck_app.py`

说明书：`agentdeck/使用说明书.md`、`agentdeck/使用说明书.pdf`。

验证附件：本报告、`daily-fixes-tests.txt`、`daily-fixes-retest.txt`、`daily-fixes-final-checks.txt`、`daily-fixes-retest-summary.json`、最终汇总 `daily-fixes-test-summary.json`、`daily-fixes-overlay-before.png`、`daily-fixes-overlay-after.png`。

## 验证结果

解释器为 `D:/conda/miniconda3/python.exe`。每个测试文件单独运行；子进程的 `HOME`、`USERPROFILE`、`APPDATA`、`LOCALAPPDATA` 均指向临时目录。

- 最终 **48/48 个测试文件退出 0**；`test_focus_lock.py` 首次通过，无需重试。
- 集成过程中修正了默认可见、紧邻反向脉冲的旧断言及测试替身时钟；首轮 4 个失败文件已逐文件复跑通过。异步读取的旧断言也已同步更新。初始失败输出仍保存在原始日志，最终状态见汇总 JSON。
- 原有 soak 测试的真实 USB、Raw Input 和驱动探测改用替身，继续验证协调逻辑和运行期不启动子进程，避免访问真实键盘及注册表。
- 18 个修改/新增 Python 文件通过 AST 解析、编译和 `tabnanny` 缩进检查；`git -c core.whitespace=cr-at-eol diff --check` 无输出，退出 0。
- 仓库未配置独立 lint/typecheck 命令，环境无 ruff、pyflakes、pyright 或 mypy；未为本任务安装依赖，不把编译检查称为完整类型检查。
- 规格审查和标准/生命周期审查提出的冻结尾部排序、热键反馈元数据、角落重启锚定、退出后惰性创建问题均已修复，并经复核通过。

项目规定的命令真实输出：

```text
python pc/test_ui.py
test_layout_states: PASS
test_marquee: PASS
test_focus: PASS
test_compatibility: PASS
test_priority_rotation: PASS
test_bad_commands_glyphs: PASS
test_dance: PASS
UI: 7 groups passed

python pc/test_daemon.py
test_mapping: PASS
test_focus: PASS
test_hold_rechecked_before_focus_send: PASS
test_focus_mutex_serializes_delayed_daemon_send_and_manual_hold: PASS
test_focus_mutex_rechecks_hold_after_waiting_for_manual_owner: PASS
test_focus_mutex_timeout_skips_send_and_retries_next_tick: PASS
test_state_machine: PASS
test_log_tick: PASS
test_main_schedule_and_lock: PASS
test_process_snapshot: PASS
daemon offline tests: 10 groups passed

python pc/test_pc.py
test_names_hooks: PASS
test_ensure_daemon: PASS
test_demo: PASS
test_firmware_loop: PASS
PC and firmware loop: 4 groups passed

python pc/sim.py
Rendered 42 scenarios -> D:\desk\hardware\h1\lcd1602\preview-sim.png
```

以上四条命令均退出 0。模拟器重新生成的图片内容未产生 Git 差异。

## 简化与剩余验证范围

选择状态集中在 `_select_session`，USB/热键反馈共用 `note_action`，避免两个入口再次产生不同的浮窗计时或短提示行为；未引入新依赖或新默认键位。

实机旋钮手感、真实 Claude UI Automation 时延、Windows 窗口切换权限和多显示器/DPI 实际表现仍需人工使用验证。本次使用替身、真实 Tk 构建及受控截图验证，没有打开 COM4、上传固件、修改真实用户配置、注册表或计划任务，也没有访问键盘 0xFF00 接口。
