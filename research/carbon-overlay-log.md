### 一、改动文件清单

1. [`pc/hub_overlay.py`](file:///D:/desk/hardware/h1/pc/hub_overlay.py)
   - 检查并补全浮窗逻辑：关浮窗改为只隐藏（`withdraw`）、新请求到达自动重新出现（`deiconify`）；默认收拢为细条（显示“N 个会话 / M 个待批”），待批请求到达时展开、处理完收回；支持鼠标任意拖动并将坐标持久化到 `~/.agentdeck/overlay.json`；提供“半透明”切换开关（默认透明度 0.85，可切换 1.0 并持久化）。
2. [`pc/hub.py`](file:///D:/desk/hardware/h1/pc/hub.py)
   - 检查并补全动作分发：在 `action()` 允许的合法指令集中加入 `next_wait`；实现循环遍历跳到下一个处于 `wait` 或 `locked` 状态的会话，无等待会话时安全返回 `{"action": "next_wait", "status": "no_waiting_session", "slot": None}`。
3. [`pc/hub_keys.json`](file:///D:/desk/hardware/h1/pc/hub_keys.json)
   - 在顶层 `bindings` 与 `v2_emulation.bindings` 中配置 6 个空闲键的出厂 HID usage 映射：
     - M (`hid:0x10`) → `prompt continue`
     - Ctrl+T (`ctrl+hid:0x17`) → `prompt tests`
     - Ctrl+D (`ctrl+hid:0x07`) → `prompt summary`
     - U (`hid:0x18`) → `prompt commit`
     - X (`hid:0x1B`) → `cycle +1`
     - Tab (`hid:0x2B`) → `next_wait`
   - Ctrl+C (`ctrl+hid:0x06`) 与 Ctrl+V (`ctrl+hid:0x19`) 依要求留空未绑定，避免与系统快捷键混淆；保留旧的兼容映射（`hid:0x14`、`hid:0x19`、`ctrl+hid:0x27`）。
4. [`pc/hub_keys.md`](file:///D:/desk/hardware/h1/pc/hub_keys.md)
   - 更新宏键盘说明文档，新增实测确认的完整 **4 列 × 5 排 宏键盘出厂键位表**，并标注各按键出厂码、对应动作及 4 颗旋钮的完整映射说明。
5. [`pc/hub_README.md`](file:///D:/desk/hardware/h1/pc/hub_README.md)
   - 更新文档中关于浮窗特性的说明（细条折叠、关闭只隐藏不退 hub、新待批自动唤醒、位置拖动持久化、半透明开关）及 USB 模式下的 4×5 宏键盘实测键位表。
6. [`pc/test_hub_overlay.py`](file:///D:/desk/hardware/h1/pc/test_hub_overlay.py)
   - 增加对要求 1、2、3 的离线单元测试，全部使用 Mock/FakeWindow，无需真实 GUI 或硬件环境。

---

### 二、每条要求具体实现方式

#### 1. 关浮窗不再关 hub
- **点关闭只隐藏浮窗**：
  - 在 [`pc/hub_overlay.py`](file:///D:/desk/hardware/h1/pc/hub_overlay.py#L400) 中，窗口的关闭协议绑定 `self.root.protocol("WM_DELETE_WINDOW", self.hide)`，右上角“×”按钮同样调用 `self.hide()`，不再触发 `self.stop()` 或退出主循环。
  - `hide()` 方法设置 `self.hidden = True`，将当前活跃的请求 ID 记录进 `self._dismissed_requests`，调用 `self.root.withdraw()` 隐藏窗口，若 overlay 是当前的渲染源，则上报 `record_rendered(None, None)` 避免盲批。
- **新待批请求自动重新唤醒**：
  - 在 `_poll()` 轮询时，比对当前活跃请求集合与已忽略集合 `reappear = self.hidden and bool(active_ids - self._dismissed_requests)`。当有新的请求 ID 到达时，自动触发 `self.show()`，调用 `self.root.deiconify()` 并应用透明度，无缝重新显示。
- **真正的退出通道**：
  - Hub 进程不随浮窗关闭而终止，仅通过外部执行 [`stop_agentdeck.bat`](file:///D:/desk/hardware/h1/stop_agentdeck.bat) 强行停止进程，或在终端按下 `Ctrl+C` 触发 `KeyboardInterrupt` 退出。

#### 2. 浮窗不挡视野
- **细条收拢与自动展开**：
  - 在 `display_model()` 中增加 `session_count`、`pending_count`、`summary_text`（格式形如 `"N 个会话 / M 个待批"`）以及 `expanded = bool(pending_count or detail is not None)` 标识。
  - 在 `_render()` 中，当 `expanded` 为 `False` 时调用 `self.body.grid_remove()`，只保留包含状态标签、半透明开关和关闭按钮的头部细条；当有待批或锁定请求时恢复 `self.body.grid()`。
  - 在 `_poll()` 检测到高度变化（展开或收起）时，通过 `_anchor_bottom` 计算新坐标并调用 `geometry()`，保持窗口底边固定，展开向上延伸、收起向下回归。
- **鼠标拖动与位置记忆**：
  - 为浮窗的 `frame`、`header`、`status_label` 绑定鼠标左键拖拽事件（`<ButtonPress-1>`、`<B1-Motion>`、`<ButtonRelease-1>`）。
  - 拖拽过程更新实时坐标 `self._pos = (x, y)` 与 `self._anchor_bottom`；在松开鼠标且发生位移时触发 `self._save_prefs()`，原子写入 `~/.agentdeck/overlay.json`。
  - 启动时通过 `_load_prefs()` 读取坐标，并根据当前屏幕尺寸限制在可见范围内（`min/max` 约束），沿用上次放置位置。
- **半透明开关**：
  - 设定 `TRANSLUCENT_ALPHA = 0.85`，默认属性 `self.translucent = True`。
  - 标题栏放置 `alpha_button`（“半透明”），点击触发 `toggle_translucent()`，在 0.85 与 1.0 之间切换，通过 `root.attributes("-alpha", ...)` 生效，并同步保存至 `overlay.json`。

#### 3. 空闲键配指令
- **键位映射与保留策略**：
  - 在 [`pc/hub_keys.json`](file:///D:/desk/hardware/h1/pc/hub_keys.json) 的 `bindings` 和 `v2_emulation.bindings` 中配置实测空闲键：
    - `hid:0x10` → `prompt continue`
    - `ctrl+hid:0x17` → `prompt tests`
    - `ctrl+hid:0x07` → `prompt summary`
    - `hid:0x18` → `prompt commit`
    - `hid:0x1B` → `cycle +1`
    - `hid:0x2B` → `next_wait`
  - `ctrl+hid:0x06`（Ctrl+C）与 `ctrl+hid:0x19`（Ctrl+V）依要求留空不配置；原有的 `hid:0x14`、`hid:0x19`、`ctrl+hid:0x27` 完整保留。
- **`next_wait` 指令实现**：
  - 在 [`pc/hub.py`](file:///D:/desk/hardware/h1/pc/hub.py#L570) 的合法指令检查中加入 `next_wait`。
  - 执行时按照会话槽位顺序，从当前选中的会话向后循环查找第一个处于 `wait` 或 `locked` 状态的会话进行选中与窗口聚焦；若无任何等待会话，安全返回 `{"action": "next_wait", "status": "no_waiting_session", "slot": None}`。
- **文档更新**：
  - [`pc/hub_keys.md`](file:///D:/desk/hardware/h1/pc/hub_keys.md) 与 [`pc/hub_README.md`](file:///D:/desk/hardware/h1/pc/hub_README.md) 中整理输出完整的 4×5 实测键位矩阵表格及旋钮动作说明。

---

### 三、新加的测试用例

在 [`pc/test_hub_overlay.py`](file:///D:/desk/hardware/h1/pc/test_hub_overlay.py) 中新增了 3 个测试类、共 10 个独立测试方法：

1. **`OverlayVisibilityAndReappearTests`**（覆盖要求 1）：
   - `test_hide_withdraws_root_without_stopping_hub`：测试关闭/隐藏只调用 `withdraw`，不触发 `stopped` 事件，不退出 hub。
   - `test_hide_clears_rendered_request_if_overlay_was_source`：测试隐藏后清空 overlay 维度的渲染标记，防止隐蔽审批。
   - `test_hidden_overlay_reappears_on_new_request`：测试对已关闭的旧请求保持隐藏，当新的待批请求到达时自动触发 `show()` 展开。

2. **`OverlayViewAndPrefsTests`**（覆盖要求 2）：
   - `test_display_model_summary_and_expanded_flag`：测试不同会话状态下 `summary_text`（“N 个会话 / M 个待批”）及 `expanded` 折叠标记的正确生成。
   - `test_render_collapses_body_when_not_expanded`：测试无待批请求时 `body.grid_remove()` 收回细条，有待批请求时 `body.grid()` 展开并更新样式。
   - `test_prefs_save_and_load_position_and_translucency`：测试拖动位置和透明度状态向 `overlay.json` 的持久化写入与跨实例加载。
   - `test_toggle_translucent_flips_alpha_and_saves_state`：测试半透明开关在 0.85 和 1.0 之间翻转，调用 `-alpha` 属性并同步持久化。
   - `test_drag_motion_updates_position_and_saves_on_release`：测试鼠标拖拽位移计算、底边锚定更新以及松开鼠标时的配置保存。

3. **`KeyBindingsAndNextWaitTests`**（覆盖要求 3）：
   - `test_hub_keys_bindings_contain_all_idle_keys`：测试 `hub_keys.json` 中 M、Ctrl+T、Ctrl+D、U、X、Tab 六颗键的映射正确，Ctrl+C/V 未占用，旧键码保留。
   - `test_next_wait_action_cycles_waiting_sessions_and_reports_no_wait`：测试 `next_wait` 指令在等待中的会话间环状跳转、切换焦点，以及在无等待会话时的状态返回。

---

### 四、不确定的地方

1. **浮窗顶边靠顶时的展开行为**：
   - 目前浮窗按照原项目的底边锚定逻辑（`anchor - height`），展开时向上长高以避免超出任务栏。若用户将细条拖拽至屏幕极顶部（例如 `y < 100`），展开时由于可用上方空间不足，会被 `max(0, anchor - height)` 限制在屏幕顶端（`y = 0`），待批处理完毕收回后会回到用户拖动的原始坐标。
2. **`next_wait` 单个等待会话时的反馈**：
   - 当系统中仅有 1 个会话处于 `wait` 状态且该会话已被选中时，按下 Tab（`next_wait`）会再次选中该会话并触发一次聚焦确认。若需在这种情况下不重复触发窗口激活，可进一步增加是否已在该会话上的判断（当前实现与现有 `slot` 指令的重选逻辑保持一致）。
