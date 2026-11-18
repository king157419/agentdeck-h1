# 桌面小画 · Wokwi 仿真（经典 ESP32 + ILI9341）

把 `sim/index.html` 里的「星图」「小窗」两种画面移植成真实固件。
可在 wokwi.com 网页版跑，也可**本地用 PlatformIO 编译 + VS Code 的 Wokwi 插件仿真**。
Wokwi 只有 ILI9341 240×320，所以只在左上 240×240 作画，其余涂黑。

## 文件

| 文件 | 作用 |
|---|---|
| `src/main.cpp` | **本地编译以此为准**（内容 = sketch.ino，Arduino.h 已 include） |
| `sketch.ino` | 网页版 Wokwi 用的原稿，保留不删。改固件请改 `src/main.cpp`，要贴回网页版时再同步 |
| `platformio.ini` | PlatformIO 配置（espressif32@8.0.0、库版本已锁定、`core_dir` 在 D 盘） |
| `wokwi.toml` | 告诉 Wokwi 插件固件位置：`.pio/build/esp32dev/firmware.bin` / `.elf` |
| `diagram.json` | 接线图（网页版与本地共用，原样） |
| `libraries.txt` | 仅网页版用 |
| `build.ps1` | 一条命令用 venv 里的 pio 编译 |
| `.vscode/extensions.json` | 推荐安装 Wokwi 插件 |

工具链位置：`D:\desk\hardware\.pio-venv`（Python venv，内含 platformio）、
`D:\desk\hardware\.platformio`（ESP32 平台/工具链/库，大目录，已放 D 盘）。

## 本地用法

1. **编译**：在本目录运行 `.\build.ps1`（或 `D:\desk\hardware\.pio-venv\Scripts\pio.exe run`）。
   产物：`.pio\build\esp32dev\firmware.bin` 和 `firmware.elf`。改了代码必须重新编译，Wokwi 不负责编译。
2. **首次：申请 Wokwi 许可证**（需要登录 Wokwi 账号，免费账号即可）：
   VS Code 里用 `文件 > 打开文件夹` 打开本目录 → 按 `F1` → 运行 **`Wokwi: Request a new License`** →
   浏览器里登录/注册 → 点获取许可证按钮 → 回 VS Code 确认。只需做一次。
3. **启动仿真**：按 `F1` → **`Wokwi: Start Simulator`**。重新编译后 Wokwi 会自动重载固件。
   （没有 Pro 套餐时插件需要联网；离线使用需 Pro，见 docs.wokwi.com/vscode/offline-mode。）
4. 上电默认进入自动演示。

## 串口命令（仿真器里的串口监视器输入，回车发送）

上电默认画面是多会话的「小楼」(house)，并开着 4 个会话的自动演示。每行一条命令，不分大小写；
成功回显以 `ok` 开头，出错以 `err` 开头并说明原因。这套命令也是以后电脑端程序给设备发状态用的协议。

- `new [name]`：新会话。回显 `ok new sid=N name=X win=K`（排队时 `win=queue`）。名字 1–15 个字符，限 `a-z 0-9 - _ .`
- `set <sid> <idle|think|tool|wait|done|error>`：改某个会话的状态
- `end <sid>`：结束会话，它那扇窗变成无人的暗窗
- `clear`：清空暗窗
- `list`：列出当前会话（布局、排队数、暗窗数、各会话状态和窗号）
- `sel <sid>`：选中会话（星图 / 小窗画面和按钮 1 跟随它）
- `demo on` / `demo off`（`auto on|off` 同义）：多会话自动演示开关
- `idle` / `think` / `tool` / `wait` / `done` / `error`：旧命令，改"选中会话"的状态
- `scene 0..2`（或 `scene stars` / `scene window` / `scene house`）：切画面。0 = 星图，1 = 小窗，2 = 小楼
- `help`：命令一览
- 除 `sel`、`list`、`clear`、`scene` 外，手动命令都会关掉自动演示。
- 每 5 秒串口会打印一行 `[stat] 帧率、每帧刷新像素数、会话数、每帧图元峰值`。

小楼的窗数：1 个会话 = 一扇大窗，2–4 个 = 2×2，5–9 个 = 3×3，超过 9 个排队并在角落显示 `+N`。

## 按钮

仿真窗口里点按钮，或按键盘：`1` = STATE（把选中会话切到下一个状态，并关闭自动演示），`2` = SCENE（循环切画面）。
（快捷键来自 diagram.json 里的 `key` 属性。）

## 接线表

| ILI9341 | ESP32 (DevKit C v4) | 说明 |
|---|---|---|
| VCC | 3V3 | |
| GND | GND.1 | |
| CS | GPIO 5 | VSPI CS |
| RST | GPIO 4 | Wokwi 里此脚不参与仿真，真屏要接 |
| D/C | GPIO 2 | |
| MOSI | GPIO 23 | VSPI MOSI |
| SCK | GPIO 18 | VSPI SCK |
| LED | 3V3 | 背光（仿真里无效） |
| MISO | GPIO 19 | 可不接 |
| 按钮 STATE | GPIO 32 ↔ GND | 仿真专用，内部上拉 |
| 按钮 SCENE | GPIO 33 ↔ GND | 仿真专用 |

## 网页版 Wokwi（可选）

打开 <https://wokwi.com/projects/new/esp32>，贴入 `sketch.ino`、`diagram.json`，
Library Manager 添加 `Adafruit GFX Library`、`Adafruit ILI9341`，点运行。

## 渲染思路（为什么仿真里不卡）

切画面/状态时整幅刷一次；之后 `dirty()` 只上报会动的小元素（矩形 + 外观签名），与上一帧对比，
只重画变了的矩形：在内存小缓冲里把 `draw()` 画一遍（自动裁剪），再一次 SPI 写出。
动画按 `millis()/50` 取时间，掉帧时动画速度不变，只是帧更稀。
加新画面（盆栽 / 潮汐）：照星图写一组 `init/enter/update/draw/dirty`，加进 `SCENES[]`。
`draw()` 必须是纯函数；`dirty()` 要覆盖所有会变的元素。

## 换成真 240×240 屏（ST7789）要改的地方

1. `src/main.cpp` 顶部「显示器配置」块：`#define DISPLAY_ST7789 1`（用 `tft.init(240, 240, SPI_MODE3)`）。
2. `platformio.ini` 的 `lib_deps`：把 `Adafruit ILI9341` 换成 `adafruit/Adafruit ST7735 and ST7789 Library`（先 `pio pkg show` 查版本并锁定）。
3. 按实际接线改 `TFT_CS_PIN / TFT_DC_PIN / TFT_RST_PIN`。
4. 真产品没有按键：删掉 `BTN_*` 两个引脚和 `pollButtons()`，状态改由主机发来的串口行驱动（`handleLine()` 已是这个接口）。`SCR_W / SCR_H` 保持 240。
5. 真机烧录：接上板子后 `pio run -t upload`（Wokwi 仿真不需要）。
