# AgentDeck v2 固件草稿 — Waveshare ESP32-S3-Touch-LCD-3.49

> **状态声明：【待实测】**  
> 本目录为 AgentDeck v2 长条屏方案的原型固件草稿（Arduino 框架 + PlatformIO + LVGL v8），基于微雪官方 Wiki、原理图引脚配置与官方示例源码编写，**尚未在物理开发板上电实测**。所有涉及真机硬件时序、屏幕方向、触摸坐标与电源锁存的条目均标有 **【待实测】**。

---

## 1. 官方资料与参考链接

- **微雪官方 Wiki（英文）**：<https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-3.49>
- **微雪官方 Wiki（中文）**：<https://www.waveshare.net/wiki/ESP32-S3-Touch-LCD-3.49>
- **官方示例代码仓库（V2 / PCB 丝印 `Rev1.1`，2026-06 起出货的主力版本）**：  
  <https://github.com/waveshareteam/ESP32-S3-Touch-LCD-3.49-V2>
- **官方示例代码仓库（V1，早期停产版本）**：  
  <https://github.com/waveshareteam/ESP32-S3-Touch-LCD-3.49>
- **推荐图形库版本**：
  - **LVGL**：官方仓库示例同时提供 `LVGL v8`（离线包内为 `8.4.0`）与 `LVGL v9` 两套互斥工程（`09_LVGL_V8_Test` / `10_LVGL_V9_Test`）。本工程固定依赖 **`lvgl/lvgl @ ^8.3.11`**（与官方 `09_LVGL_V8_Test` API 完全一致）：<https://github.com/lvgl/lvgl>
  - **底层 QSPI 驱动参考**：本工程直接调用 ESP-IDF 标准 `driver/spi_master.h` 实现微雪官方 `esp_lcd_axs15231b.c` 的 QSPI 帧传输协议（零第三方显示库版本冲突）；若需 `Arduino_GFX` 方案可参考 <https://github.com/moononournation/Arduino_GFX>（需 `v1.6.2+` 并配合 `Arduino_Canvas` 软件旋转）。

---

## 2. 硬件规格与引脚定义（V2 vs V1）

### 2.1 核心参数
- **主控**：ESP32-S3R8（双核 Xtensa LX7 @ 240 MHz，内置 **8 MB Octal PSRAM (`opi`)**，外置 **16 MB QIO Flash**）
- **显示屏**：3.49 寸 IPS 长条屏，物理扫描分辨率 **172 × 640**（竖屏），驱动与触控二合一 IC **AXS15231B**（显示走 QSPI，电容触摸走独立 I2C `0x3B`）
- **IO 扩展**：**TCA9554**（系统 I2C `0x20`），管理电源锁存 `SYS_EN` 及 V2 版本的屏幕复位/背光使能

### 2.2 引脚映射表（源自官方 `user_config.h` / `button_bsp.c`）

> **硬件版本注意**：微雪自 2026 年 6 月起出货均为 **V2（PCB 丝印 `Rev1.1`）**，V1 已停产。V2 与 V1 交换了 `LCD_TE`/`LCD_RST` 和 `LCD_BL`/`EXIO_INT`，混用固件会导致黑屏。`platformio.ini` 默认编译 V2 环境 `waveshare_esp32s3_lcd349_v2`；若手头是早期 V1 板，请切换至 `waveshare_esp32s3_lcd349_v1`。

| 功能信号 | V2 (`Rev1.1`，默认) | V1（早期停产版） | 备注 |
|---|---|---|---|
| `LCD_CS` (QSPI 片选) | `GPIO 9` | `GPIO 9` | `SPI3_HOST`，40 MHz，SPI Mode 3 |
| `LCD_PCLK` (QSPI 时钟) | `GPIO 10` | `GPIO 10` | — |
| `LCD_D0`..`LCD_D3` | `GPIO 11, 12, 13, 14` | `GPIO 11, 12, 13, 14` | 4-line QIO 像素传输 |
| `LCD_RST` (屏幕复位) | **TCA9554 `EXIO5`** | `GPIO 21` | 低有效复位脉冲 |
| `LCD_TE` (撕裂同步) | `GPIO 21` | 未引出 | — |
| `LCD_BL` (背光 PWM) | `GPIO 42` + **TCA9554 `EXIO1`** | `GPIO 8` | V2 需同时拉高 `EXIO1 (BL_EN)` |
| `EXIO_INT` | `GPIO 8` | — | TCA9554 中断输入 |
| 系统 I2C (`Wire`) | `SDA = GPIO 47`, `SCL = GPIO 48` | `SDA = GPIO 47`, `SCL = GPIO 48` | 挂载 TCA9554 (`0x20`)、RTC (`0x51`)、IMU (`0x6B`) |
| 触摸 I2C (`Wire1`) | `SDA = GPIO 17`, `SCL = GPIO 18` | `SDA = GPIO 17`, `SCL = GPIO 18` | 独立总线，挂载 AXS15231B Touch (`0x3B`) |
| `SYS_EN` (电池锁存) | **TCA9554 `EXIO6`** | TCA9554 `EXIO6` | **必须保持高电平**，否则电池供电会掉电关机 |
| 板载按键 `BOOT` | `GPIO 0`（低有效） | `GPIO 0`（低有效） | 本固件映射为 `KEY APPROVE` (`✓`) |
| 板载按键 `PWR` | `GPIO 16`（低有效） | `GPIO 16`（低有效） | 短按映射为 `KEY DENY` (`✗`)；长按会断开硬件电源锁存 |
| 原生 USB CDC | `GPIO 19 (D-)`, `GPIO 20 (D+)` | `GPIO 19 (D-)`, `GPIO 20 (D+)` | `-DARDUINO_USB_MODE=1 -DARDUINO_USB_CDC_ON_BOOT=1` |

### 2.3 AXS15231B QSPI 初始化与横屏刷新要点
1. **QSPI 指令封装**：写寄存器使用单线指令头 `0x02` + 24 位地址 `(cmd << 8)`；写像素使用 `0x32` 指令头（单线发指令/地址，4 线 `SPI_TRANS_MODE_QIO` 发 RGB565 数据），开启 `LV_COLOR_16_SWAP = 1`。
2. **全帧连续流式刷新**：AXS15231B 在 QSPI 模式下忽略 `RASET (0x2B)` 局部行窗口，必须设置 `disp_drv.full_refresh = 1`，首块发送 `0x2C (RAMWR)`，后续 9 个 DMA 分块（每块 `172 × 64 × 2 = 22,016 B`）发送 `0x3C (RAMWRC)`。
3. **软件 90° 横置旋转**：AXS15231B QSPI 不支持通过 `MADCTL` 的 `MV` 位直接做硬件 90° 横屏旋转。固件遵循微雪官方 `lvgl_port.c` 方案，在 8 MB OPI PSRAM 中分配 `640 × 172` 绘制缓冲与 `172 × 640` 旋转缓冲，在 `flush_cb` 中完成转置后经内部 SRAM DMA 分块推屏。

---

## 3. 界面布局（640 × 172 横置）

```text
+---------------- 640 px ----------------+
|  #1  12s |  #2   4s |  #3   1m |  #4   8s |  #5      |  #6   2s |  ┐
| +------+ | +------+ | +------+ | +------+ | +------+ | +------+ |  | 136 px
| | RUN  | | | ASK  | | | DONE | | | ERR  | | | IDLE | | | GATE | |  | 6 等分区
| +------+ | +------+ | +------+ | +------+ | +------+ | +------+ |  | (每格 ~106px)
| cc-a1b2  | cx-9f04  |  cursor  |  gemini  | qwen-cli | cc-prod  |  ┘
+-----------------------------------------------------------------+
| [ HIGH #6 ]  HOLD! press again within 1.5s | git push --force   |  ← 36 px 底部提示行
+-----------------------------------------------------------------+
```

- **6 等分槽位卡片（`y = 0..135`）**：
  - 每区显示槽位号 `#1`..`#6`、状态持续时间（设备本地按 `millis()` 计时）、状态色块、Agent 名称（最多 **8 个 ASCII 字符**，超出自动截断）。
  - **6 种状态色块**：
    - `RUN`：绿色 `#22C55E`（兼容别名 `THINK`、`TOOL`）
    - `ASK`：琥珀色 `#F59E0B`（兼容别名 `WAIT`、`INPUT`）
    - `DONE`：蓝色 `#3B82F6`
    - `ERR`：红色 `#EF4444`（兼容别名 `ERROR`）
    - `IDLE`：灰色 `#4B5563`（未分配槽位为暗灰 `#1E293B` 并显示 `--`）
    - `GATE`：**红色闪烁**（设备端本地以 250 ms 半周期在亮红 `#EF4444` 与暗红 `#3B0A0A` 间切换，无需主机轮询推帧）
- **底部提示与审批栏（`y = 136..171`）**：
  - `low`：琥珀色徽标 `LOW #n` + 待批命令摘要
  - `high`：**整栏深红底 + 亮红徽标 `HIGH #n`** + 待批命令摘要（若收到 `HINT` / `APPROVAL_HINT` 则同屏前置显示，如二次确认提示）
  - `critical`：**高危红栏 + `CRIT #n` + 固定前置文案 `LOCKED: use terminal`**（如 `LOCKED: use terminal | rm -rf ...`）
  - 无待批请求时显示 `HINT` 文本；若曾收到 `HEARTBEAT` 且超过 3 秒中断，则变红显示 `OFFLINE` 告警。

---

## 4. USB CDC 串口行协议

参考 [`../../agentdeck/07-技术方案.md`](../../agentdeck/07-技术方案.md) 第 10 节（`SLOT_SET` / `APPROVAL_SHOW` / `APPROVAL_CLEAR` / `APPROVAL_HINT` / `HEARTBEAT` / `KEY`）。量产版走 64 B 厂商自定义 HID（`0xFF61`），本原型阶段走 ESP32-S3 原生 **USB CDC 串口文本行协议**（波特率无关，`\n` 或 `\r\n` 结尾，单行上限 512 字节，大小写不敏感）。

### 4.1 主机 → 设备命令

| 命令（含兼容别名） | 参数说明 | 设备回复示例 |
|---|---|---|
| `PING [seq]` | 连通性探测 | `PONG`（带参时回 `PONG <seq>`） |
| `HELLO`（或 `VERSION`） | 查询协议与固件能力信息 | `OK HELLO proto=2 fw=0.2.0-draft board=esp32-s3-touch-lcd-3.49 res=640x172 slots=6` |
| `SLOT <1..6> <state> [name]`<br/>别名：`SLOT_SET ...` | 设置槽位状态与名称；`state` 取 `RUN\|ASK\|DONE\|ERR\|IDLE\|GATE`；`name` 最多保留 8 字符（`-` 表示清空/保持） | `OK SLOT 1 RUN cc-a1b2` |
| `SLOT_CLEAR <1..6>` | 清空指定槽位并回到未分配 `IDLE` | `OK SLOT_CLEAR 1` |
| `APPROVAL <0..6> <tier> <nonce> <cmd...>`<br/>别名：`APPROVAL_SHOW ...` | 显示待批请求；`slot` 为 `0..6`（`0` 表示不绑定槽位），`tier` 取 `low\|high\|critical`（兼容 `l0..l3`），`nonce` 为单次令牌，`<cmd...>` 为命令摘要（最长 96 字符，超出自动 `...`）<br/>亦支持简写：`APPROVAL <tier> <cmd...>` | `OK APPROVAL 6 high n2002` |
| `APPROVAL_CLEAR [nonce] [reason]`<br/>或 `APPROVAL CLEAR` | 清除当前审批条；若传入非 `-`/`*` 的 `nonce` 且与屏上不一致，返回 `ERR NONCE_MISMATCH` | `OK APPROVAL_CLEAR` |
| `HINT <text...>`<br/>或 `APPROVAL_HINT <nonce> <text...>` | 在底部提示行显示短提示（如 `HOLD! press again`）；`HINT -` 或 `HINT CLEAR` 清空提示 | `OK HINT` / `OK HINT_CLEAR` |
| `SELECT <0..6>`（或 `FOCUS`） | 高亮选中槽位边框（`0` 或 `-` 取消选中） | `OK SELECT 2` |
| `HEARTBEAT [seq]`（别名 `HB`） | 主机心跳；启用后若连续 > 3000 ms 未收到心跳，底部提示中枢离线 | `OK HB 1` |
| `BRIGHTNESS <0..255>` | 调整屏幕背光 PWM 占空比 | `OK BRIGHTNESS 220` |
| `CLEAR` | 清空全部 6 个槽位、待批请求与提示行 | `OK CLEAR` |
| `STATE`（别名 `LIST`） | 单行导出当前 6 槽与审批状态（便于无屏调试） | `OK STATE s1=cc-a1b2:RUN ... appr=none:-` |

### 4.2 设备 → 主机异步事件（触摸与按键）【待实测】

遵循 `07-技术方案.md` §6.3 的 **fail-closed 硬约束**：固件内部**不存在任何本地自动放行逻辑**，触摸与物理按键仅上报边沿事件及按下瞬间屏上显示的 `nonce`，由主机 `hub` 校验决策：

```text
KEY SLOT <1..6> DOWN nonce=<shown_nonce> ms=<device_ms>[ offline=1]
KEY SLOT <1..6> UP   nonce=<shown_nonce> ms=<device_ms>[ offline=1]
KEY APPROVE DOWN     nonce=<shown_nonce> ms=<device_ms>[ offline=1]
KEY APPROVE UP       nonce=<shown_nonce> ms=<device_ms>[ offline=1]
KEY DENY DOWN        nonce=<shown_nonce> ms=<device_ms>[ offline=1]
KEY DENY UP          nonce=<shown_nonce> ms=<device_ms>[ offline=1]
```

- 点击上方 6 等分区域（`y < 136`）：本地高亮对应槽位，并回发 `KEY SLOT <1..6> DOWN/UP`。
- 底部审批栏（`y >= 136`）不映射触摸批准，防止误触放行。
- 板载 `BOOT` 键（`GPIO 0`）映射为 `KEY APPROVE`，`PWR` 键（`GPIO 16`）短按映射为 `KEY DENY`。若需关闭触摸上报，可在 `platformio.ini` 将 `-DENABLE_TOUCH_KEYS=1` 改为 `0`。

---

## 5. 编译、烧录与演示步骤

### 5.1 目录结构

```text
firmware/strip349/
├── platformio.ini          # PlatformIO 配置（含 V2 默认环境与 V1 兼容环境、固定库版本）
├── include/
│   ├── board_config.h      # Waveshare 3.49 V1/V2 引脚、QSPI、双 I2C、TCA9554 常量
│   ├── deck_protocol.h     # 纯 C++11 协议解析、状态机与触摸分区映射（支持主机侧单测）
│   └── lv_conf.h           # LVGL v8.3 配置文件（RGB565 byte-swap + 自定义 tick）
├── src/
│   └── main.cpp            # 固件主程序（TCA9554 + AXS15231B QSPI + LVGL 横屏 UI + CDC 串口）
├── tools/
│   └── send_demo.py        # 主机侧 pyserial 演示与 KEY 事件监听脚本
└── README.md
```

### 5.2 使用 PlatformIO 编译与烧录【待实测】

1. 安装 PlatformIO Core（`pip install platformio` 或使用 VS Code PlatformIO 插件）。
2. 用 USB-C 数据线连接开发板（ESP32-S3 原生 USB 口，无需 CH340 驱动）。
3. 在当前目录编译并上传：
   ```powershell
   # V2 硬件（PCB 丝印 Rev1.1，默认）
   pio run -e waveshare_esp32s3_lcd349_v2
   pio run -e waveshare_esp32s3_lcd349_v2 -t upload

   # 若为早期停产版 V1 硬件
   pio run -e waveshare_esp32s3_lcd349_v1 -t upload
   ```
4. **手动进入下载模式（若首次烧录未自动复位）**：按住板载 **`BOOT`** 键不放，短按一下 **`PWR`/复位**（或重新插拔 USB），待系统识别出 `USB JTAG/serial debug unit` 端口后松开 `BOOT` 再次执行上传。

### 5.3 运行主机侧演示脚本

```powershell
# 离线干跑预览（不打开任何串口，立即可跑）
python tools/send_demo.py --dry-run

# 连接真机自动识别 Espressif USB CDC (VID 0x303A)，或手动指定端口并持续监听触摸 KEY 事件【待实测】
python tools/send_demo.py --port COM7 --listen
```

---

## 6. 本机编译验证说明

在本机环境执行 `pio --version` 检查结果如下：

```text
pio : The term 'pio' is not recognized as the name of a cmdlet, function, script file, or operable program.
```

**说明**：本机当前**未安装 PlatformIO (`pio`)**，因此无法在本机拉取 `espressif32` 工具链生成 `.bin` 固件镜像。为尽可能保证代码可编译性与协议正确性，已在本机通过以下两项离线验证：

1. **C++11 严格语法与单测验证**：使用本机 `MinGW64 g++ (4.9.2)` 在 `-std=gnu++11 -Wall -Wextra -Werror`（对齐 PlatformIO `espressif32@^6.9.0` 默认 C++11 标准，含 `Arduino.h` 的 `LOW`/`HIGH` 宏冲突检查）下：
   - 编译并运行 `include/deck_protocol.h` + `include/board_config.h` 主机侧断言测试（覆盖 `PING`/`PONG`、8 字符截断、6 槽全状态、`APPROVAL` 三档风险、`nonce` 校验、心跳超时、640×172 六等分坐标命中），全部通过；
   - 对 `src/main.cpp` 分别在 `BOARD_HW_VERSION=2`（开启触摸 + OTP 初始化）与 `BOARD_HW_VERSION=1`（关闭触摸 + 完整寄存器初始化表）两套宏组合下执行 `-fsyntax-only -Wall -Wextra -Werror` 语法与类型检查，零警告通过。
2. **演示脚本验证**：使用 `D:\conda\miniconda3\python.exe`（`pyserial 3.5`）运行 `python tools/send_demo.py --dry-run` 通过。

---

## 7. 已知未验证项清单（全部【待实测】）

拿到微雪 ESP32-S3-Touch-LCD-3.49 实物后，请按以下顺序逐项上板核对：

1. **硬件版本确认（V1 vs V2 `Rev1.1`）【待实测】**：上电前先核对外壳 QC 标签或 PCB 丝印是否为 `Rev1.1`（V2）。若屏幕背光不亮，优先检查 `BOARD_HW_VERSION` 是否与实物一致。
2. **AXS15231B OTP 与寄存器初始化表【待实测】**：默认采用微雪官方 `09_LVGL_V8_Test` 的精简 OTP 初始化序列（`0x11` + `0x29`）。若个别批次面板未烧录出厂 OTP 导致花屏/偏色/不亮，将 `platformio.ini` 中的 `-DAXS15231B_USE_VENDOR_INIT_TABLE=0` 改为 `1`（已内置官方 `esp_lcd_axs15231b.c` 完整 Gamma/时序寄存器表）。
3. **横置方向（左起 1→6）与色彩字节序【待实测】**：
   - 若红蓝反色或花屏，核对 `include/lv_conf.h` 中 `LV_COLOR_16_SWAP`（当前为 `1`）及 `MADCTL (0x36)` 的 RGB/BGR 位；
   - 若横屏画面上下颠倒（取决于 USB-C 口朝左还是朝右摆放），将 `lvgl_flush_cb` 中转置公式 `src[LCD_UI_W * (LCD_UI_H - 1 - px) + py]` 改为 `src[LCD_UI_W * px + (LCD_UI_W - 1 - py)]` 即可翻转 180°。
4. **电容触摸坐标轴方向【待实测】**：`poll_touch_slots()` 采用官方 11 字节读取帧 `{0xB5, 0xAB, 0xA5, 0x5A, ...}`，默认 `TOUCH_INVERT_X=1`、`TOUCH_INVERT_Y=1`。实测点击 `#1` 格若上报 `KEY SLOT 6`，在 `platformio.ini` 添加 `-DTOUCH_INVERT_X=0` 即可修正。
5. **TCA9554 电池供电锁存（`EXIO6 SYS_EN`）【待实测】**：代码已按先写输出寄存器锁住 `EXIO6=1` 再配方向寄存器的防掉电顺序编写；接锂电池脱离 USB 运行时需实测开机保持与 `PWR` 长按关机行为。
6. **中文字体与后续 USB HID 演进**：当前草稿使用内置 Montserrat 拉丁字库（非 ASCII 字符安全替换为 `?`）；后续按 `07-技术方案.md` §10 切到 TinyUSB 复合设备（`ARDUINO_USB_MODE=0` + Vendor HID `0xFF61`）并烧录 GB2312 子集字库。
