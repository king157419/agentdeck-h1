# 简报：deck 独占模式——不改键盘，直接吃掉宏键盘的按键

## 背景
- 改键走不通：VIA-C 0.3.5 只认 0xFF60，这把键盘是 0xFF00（厂商新驱动），协议未知，**不要再碰 0xFF00，也不要写键盘**。
- 宏键盘（VID_4132&PID_2107）出厂发 Photoshop 快捷键（字母、Ctrl+Z 等），这些按键现在会传到前台窗口。
- 已有 `pc/deck.py` / `deck_input.py` 用 Raw Input 按设备识别按键，但不能吞键。

## 要做的
1. **独占（吞键）**：在 `deck run` 里加 WH_KEYBOARD_LL 低级键盘钩子，和 Raw Input 放在同一线程。
   - 做法：参考 LuaMacros / HIDMacros 的成熟做法。在钩子回调里用 PeekMessage(PM_REMOVE) 取同一 vkey、同一按下/抬起方向、来自宏键盘设备句柄的 WM_INPUT，最多等 50 ms。
   - 确认来自宏键盘才返回 1 吞掉；否则一律 CallNextHookEx 放行。宏键盘按键先到、钩子后到的顺序也要处理：用一个最近事件队列按 vkey、方向、时间匹配，有效期 100 ms。
   - 绝不能吞主键盘（Ace 68 等）的键。拿不准时放行。
   - 注入的事件（LLKHF_INJECTED）一律放行，包括我们自己 SendInput 发的 Enter/Esc。
   - 钩子回调要快，不做 IO，动作放到队列里，由另一个线程执行。
   - 加开关：`deck run --no-exclusive` 退回只观察、不吞键。
2. **组合键绑定**：按设备跟踪 Ctrl/Shift/Alt/Win 的按下状态（只看宏键盘自己的修饰键）。
   - 绑定键支持 `ctrl+vk:0x5A`、`alt+vk:0x4C` 这类写法。先匹配带修饰键的，再匹配裸 vk。
   - 单独按下修饰键本身不触发动作，除非显式绑定了 `vk:0x12` 等。
   - 动作只在按下时触发，抬起不触发；按住自动重复的按键只触发一次。
3. **默认映射改成出厂键码**，F13–F22 那套保留在文件里作备选。按用户实测顺序：
   - `vk:0x45`（E）= slot 1，`vk:0x42`（B）= slot 2，`ctrl+vk:0x5A`（Ctrl+Z）= slot 3，`vk:0x20`（空格）= slot 4
   - `vk:0x47`（G）= approve，`ctrl+vk:0x46`（Ctrl+F）= deny
   - `vk:0x48`（H）= next_wait，`vk:0x4C`（L）= auto
   - `vk:0xDD`（]）= cycle +1，`vk:0xDB`（[）= cycle -1
   - 其余宏键盘按键：独占模式下吞掉，不做任何动作，日志里记一行 `unbound`。
4. **测试**：离线测试覆盖以下几点，现有全部测试继续通过：
   - 钩子判定：宏键盘吞、主键盘放行、注入放行、超时放行、先 raw 后 hook 和先 hook 后 raw 两种顺序
   - 修饰键组合
   - 自动重复只触发一次
   - `--no-exclusive`
5. **真机冒烟**：后台启动 `deck run -v` 10 秒。期间用 SendInput 发几下普通字母，确认被放行（日志无吞键记录），然后正常退出。贴出日志。不要让它常驻。
6. README 宏键盘一节更新：独占模式说明、默认映射表（物理键用出厂功能描述）、怎么关、已知限制。

## 做完的标准
- 全部测试输出、冒烟日志、改动文件清单。改动前把要改的文件复制到 `_rollback/deck-v0-exclusive/`。
