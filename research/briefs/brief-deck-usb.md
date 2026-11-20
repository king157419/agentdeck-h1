# 简报：deck USB 直读后端（把宏键盘从 Windows 手里拿过来自己读）

## 背景
- 低级钩子独占方案实测失败：钩子先于 Raw Input，吞键后 Windows 不再产生 WM_INPUT，无法按设备判断，宏键盘的字照样打进窗口。
- 新方案：用户会用 Zadig 把宏键盘（USB 4132:2107）**接口 0（键盘）** 的驱动换成 WinUSB。之后 Windows 不再把它当键盘，我们用 pyusb 直接读它的 HID 报文。其它接口不动。
- 已装：`pyusb`、`libusb-package`（`libusb_package.get_libusb1_backend()` 提供 backend）。

## 要做的
1. 新建 `pc/deck_usb.py`：
   - 用 libusb_package 的 backend 找 4132:2107，选接口 0 的 interrupt IN 端点。
   - 可选发 SET_PROTOCOL=boot（class request 0x0B，wValue=0）保证 8 字节报文；失败就按实际报文长度解析。兼容 NKRO 位图报文的话更好，不确定就只支持 boot 报文，并在日志里打印报文长度。
   - 循环读（超时 100 ms），把“修饰键字节 + 键码数组”的差分转成按下/抬起事件。
   - 键名格式：`hid:0x08`，带修饰键时写成 `ctrl+hid:0x1D`（修饰键用该设备自己的修饰位；左右不区分）。
   - 自动重复只触发一次；抬起不触发。
   - 设备拔出或报错时自动重连（每 2 秒），不崩溃。
   - 找不到 WinUSB 驱动（打不开 / NotImplementedError / Access denied）时，给出明确提示：“请先用 Zadig 把 4132:2107 接口0 换成 WinUSB”。
2. `deck.py`：
   - `run` 增加 `--backend usb|rawinput`，默认 `auto`：能用 USB 打开就用 usb，否则退回 rawinput 只观察并警告“宏键盘按键会漏到窗口”。
   - 低级钩子独占模式默认关闭（保留代码，加 `--exclusive` 才开），README 写明已知它无效的原因。
   - `learn` 也支持 usb 后端，打印 `hid:` 键名。
3. `deck_map.json` 换成 hid 键名，按用户实测的物理布局：
   - 按键：`hid:0x08`(E)=slot 1，`hid:0x05`(B)=slot 2，`ctrl+hid:0x1D`(Ctrl+Z)=slot 3，`hid:0x2C`(空格)=slot 4，`hid:0x0A`(G)=approve，`ctrl+hid:0x09`(Ctrl+F)=deny，`hid:0x0B`(H)=next_wait
   - 旋钮4（最右）：`hid:0x30`(])=cycle +1，`hid:0x2F`([)=cycle -1，`ctrl+hid:0x27`(按下 Ctrl+0)=next_wait
   - 旋钮1（最左）按下 `hid:0x0F`(L)=auto
   - 保留旧的 vk 映射在 `_rawinput_bindings` 里。
   - 说明里列出全部 4 个旋钮的出厂键：旋钮1 顺 S 逆 F 按 L；旋钮2 顺 R 逆 P 按 Q；旋钮3 顺 - 逆 = 按 V；旋钮4 顺 ] 逆 [ 按 Ctrl+0。
4. 离线测试 `pc/test_deck_usb.py`：报文差分、修饰键组合、自动重复、重连、映射解析、auto 后端选择。现有全部测试继续通过。
5. README 宏键盘一节：Zadig 步骤（Options→List All Devices，选 USB ID 4132 2107 **Interface 0**，目标 WinUSB，Replace Driver）、恢复原驱动方法（设备管理器里对该设备“卸载设备”并勾选删除驱动，再拔插）、run/learn 用法、映射表。
6. 改动前把要改的文件复制到 `_rollback/deck-v0-usb/`。

## 做完的标准
全部测试输出；`python pc/deck.py run --backend usb -v` 在当前（还没换驱动）环境下运行 3 秒，确认给出 Zadig 提示并正常退出；改动文件清单。
