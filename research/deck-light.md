# CXT 宏键盘灯光：只读协议调研

日期：2026-11-18。对象：USB `4132:2107`，用户现有 20 键 + 4 旋钮设备。范围依据：[简报](brief-deck-light.md)。

## 结论

**本轮尚不能给这块设备提供已确认可用的灯光报文。** 这不等于硬件不能控制：旧 VIA-C 有明确的全局颜色、亮度、效果设置协议；新版 CXT Hub 官方教程还描述了逐键配色。但没有证据把其中任何协议和功能匹配到本机 `4132:2107 / 0xFF00:0x01`。

| 能力 | 对当前设备的结论 | 已有证据及边界 |
|---|---|---|
| 整板改色 | **未确认** | VIA-C 有全局 H/S 颜色、独立亮度及纯色效果；其 HID 筛选与实机不符，目标定义缺失 |
| 单键改色 | **未确认** | 新 Hub 教程明确描述逐键配色，但未给出本机支持信息及通信格式；旧 VIA-C 未找到任意物理单键 RGB 接口 |
| 切预设效果 | **未确认可用于本机** | 旧客户端有模式命令，模式编号依赖设备定义；不能断言本机“只能切预设” |
| 完全不能控制 | **没有证据支持此判断** | 当前缺口是匹配固件的协议和功能定义，并非已证明硬件不支持 |

本轮设备操作只有一次 `hid.enumerate(0x4132, 0x2107)`。**未打开 HID 设备、未向设备发送任何报文、未打开 COM4、未改驱动或 `pc/`、未执行下载的 JS、未安装依赖。** 下文全部报文均为静态记录或条件性提案，未发送。

## 1. 网页实际是什么，下载了什么

简报给出的 [新版网址](http://47.92.105.50/index.html) 本次返回 **CXT Hub 官网及桌面客户端下载页**，不是包含 WebHID 配置器的页面：

- 首页提供客户端下载和旧站入口：[`index.html:59`](cxt-web-driver/index.html:59)、[`index.html:64`](cxt-web-driver/index.html:64)。
- 下载页列出 Windows `.exe` 和 macOS `.dmg`，Windows 链接指向网盘：[`download.html:63`](cxt-web-driver/download.html:63)、[`download.html:74`](cxt-web-driver/download.html:74)、[`download.html:79`](cxt-web-driver/download.html:79)、[`download.html:110`](cxt-web-driver/download.html:110)。本轮没有下载、安装或运行客户端安装包。
- 首页唯一外部脚本是 `assets/app.js`：[`index.html:242`](cxt-web-driver/index.html:242)。该脚本共 199 行，静态内容为主题、锚点、复制按钮、二维码、资源过滤和标签页交互；没有 HID 通信代码。保存内容未经格式化或执行。
- 进一步下载首页直接链接的教程与下载等页面，以及其灯光章节。旧站 `http://47.92.107.3/` 是教程站，其 HTML 直接引用的 `runtime.js`、`app.js` 也已保存；这两个脚本不是本机设备协议的证据。

重要的新增线索：新版[进阶教程灯光章节](http://47.92.105.50/tutorial-advanced.html#lighting)描述按键分别配置颜色，并说明不同型号的可用灯效由固件决定，见本地 [`tutorial-advanced.html:160`](cxt-web-driver/tutorial-advanced.html:160)、[`:162`](cxt-web-driver/tutorial-advanced.html:162)、[`:172`](cxt-web-driver/tutorial-advanced.html:172)。**这是产品功能说明，不是已确认的 `4132:2107` 能力，更没有给出单键命令。**

| 要找的新版驱动信息 | 本轮结果 |
|---|---|
| `usagePage / usage` 过滤 | 已保存的 HTML/JS 中没有设备过滤实现，未知 |
| 报文长度、Report ID | 无设备通信实现，未知；不能用旧 VIA-C 的 32/33 字节代填 |
| 模式、颜色、亮度命令 | 页面有功能介绍，无命令字节 |
| 单键颜色命令 | 教程有功能描述，无地址映射、颜色编码或命令字节 |
| 保存至 flash / 临时 RAM 模式 | 教程说明配置存于键盘内部，未给出保存策略或 RAM-only 接口 |

下载结果在 [`cxt-web-driver/`](cxt-web-driver/)：10 个 HTML、3 个直接引用的外部 JS，另附以下证据。所有 14 处外部 script 引用均能对应本地文件。未递归下载旧站运行时可能加载的通用页面分块，也未把“文本检索无命中”扩大为“所有 CXT 软件都无 WebHID”。

- [`manifest.json`](cxt-web-driver/manifest.json)：来源 URL、最终 URL、记录时间、大小、SHA-256；保留一次教程页面 502 和随后成功重试的记录。
- [`static-audit.json`](cxt-web-driver/static-audit.json)：HTML script 引用核对及逐文件文本检索。`navigator.hid`、`requestDevice`、`sendReport`、`sendFeatureReport`、`receiveFeatureReport`、`usagePage`、`usage_page`、`WebHID` 在本次保存的 HTML/JS 中合计 0 命中。检索只解析文本，没有 JS 执行。
- [`hid-enumeration.json`](cxt-web-driver/hid-enumeration.json)：本轮实际枚举返回字段，path 的 bytes 转为文本保存。

## 2. 实机枚举：三个 HID 接口

时间：`2026-11-18T15:12:20.004997+00:00`。解释器：`D:\conda\miniconda3\python.exe`；hid 模块：`D:\conda\miniconda3\Lib\site-packages\hid.cp313-win_amd64.pyd`。实际调用仅为：

```python
import hid
items = hid.enumerate(0x4132, 0x2107)
```

| interface_number | usage page | usage | 对应集合 |
|---|---|---|---|
| 3 | `0xFF00` | `0x0001` | 厂商自定义 |
| 2 | `0x000C` | `0x0001` | Consumer Control / 多媒体 |
| 1 | `0x0001` | `0x0002` | 鼠标 |

原样路径（顺序同枚举结果）：

```text
\\?\HID#VID_4132&PID_2107&MI_03#a&1b1f30c3&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}
\\?\HID#VID_4132&PID_2107&MI_02#a&32e2bd08&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}
\\?\HID#VID_4132&PID_2107&MI_01#a&f0b7f46&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}
```

接口 0 本次未出现在 HID 枚举中，与简报所述已换为 WinUSB 相符；本轮没有另行查询或更换驱动。枚举不提供本次所需的 Report descriptor，因此本机 Report ID、有效报文长度仍未知。

旧 VIA-C 先用 VID/PID 定义表筛选，再要求 `usagePage=0xFF60, usage=0x61`，见下文 A:5168–5185；随附定义没有 `0x41322107`，既有 [VIA-C 协议报告](via-c-protocol.md)已记录这点。**不能因为同属 CXT 或都有灯光，就绕过筛选向 `FF00:01` 发旧协议。**

## 3. VIA-C 源码证据与传输包装

检查范围：`research/via-c-src/main.js`、`static/` 下全部 7 个 JS，以及引用的 `via-reader` 灯光枚举、预设和转换代码。下文采用三个固定文件简称，行号都是保存源码的原始行号：

- **A** = [`research/via-c-src/static/js/7f943605.js`](via-c-src/static/js/7f943605.js)。
- **T** = [`research/via-c-src/node_modules/via-reader/src/types.ts`](via-c-src/node_modules/via-reader/src/types.ts)。
- **P** = [`research/via-c-src/node_modules/via-reader/src/lighting-presets.ts`](via-c-src/node_modules/via-reader/src/lighting-presets.ts)。

以下只描述该客户端命名空间。**不是当前设备已经确认的报文格式，也不是标准 VIA 命令表。**

定义 `B` 为交给 node-hid `write` 的完整缓冲，`R` 为客户端处理的响应数组，索引从 0 开始：

```text
B[0]       = 00                 主机 API 使用的 Report ID 前缀
B[1]       = command
B[2...]    = arguments
未使用字节补 00，B 总长 33 字节；命令 payload 长 32 字节。
R 不含上述 Report ID 前缀；读取结果索引均按 R 计算。
```

证据：A:9224–9239。33 字节是 **node-hid 调用缓冲长度**，不要写成已证实本机 USB 在线上发送 33 字节；未编号报告的 API 前导 `00` 也不等于已读取本机描述符。请求按队列串行处理（A:9191–9216），响应要求以请求的 command/arguments 开头（A:9235–9237）。

### 3.1 主命令和颜色命令

表中列出 B 的起始字节，剩余补零至 33 字节。

| 用途 | B 起始字节 | 取值/意义 | 证据 |
|---|---|---|---|
| 读取属性 | `00 0D s` | 通常取 `R[2:2+n]`，默认 n=1 | A:9053–9055 |
| 设置属性 | `00 12 s values...` | API 自身不跟发保存 | A:9058–9060 |
| 读取背光模式 | `00 0D 0A` | `R[2]` 为模式 | A:9063–9066 |
| 设置背光模式 | `00 12 0A mode` | mode 来自设备定义 | A:9103–9105 |
| 读取背光亮度 | `00 0D 09` | `R[2]` 为亮度 | A:9069–9072 |
| 读取颜色 1 / 2 | `00 0D 0C` / `00 0D 0D` | `R[2]=H, R[3]=S` | A:9075–9081 |
| 设置颜色 1 / 2 | `00 12 0C H S` / `00 12 0D H S` | 两个颜色分量，不是 RGB 三分量 | A:9084–9086 |
| 读取自定义色槽 | `00 0D 17 i` | `R[3]=H, R[4]=S` | A:9089–9095 |
| 设置自定义色槽 | `00 12 17 i H S` | i 是效果色槽，未证实为实体 LED/键号 | A:9098–9100 |
| 显式保存灯光 | `00 11` | 无参数 | A:9108–9109 |

`0D` 既可能是主命令“读取”，也可能是颜色 2 的属性号；`11` 也可能是保存主命令或层指示位置属性。必须按字节位置解释，不能只搜索一个编号就决定用途。

### 3.2 所有灯光属性

除 `17` 的特殊索引格式外，均按 `00 0D s` 读、`00 12 s values...` 写。表中的数值范围来自 UI，不代表本机固件已接受这些范围。

| s | 含义 | 设置的 values | 证据 |
|---|---|---|---|
| `01` | split backspace LED 布局选项 | 1 字节 | T:3；A:4504 |
| `02` | split left shift LED 布局选项 | 1 字节 | T:4；A:4505 |
| `03` | split right shift LED 布局选项 | 1 字节 | T:5；A:4506 |
| `04` | 7U spacebar LED 布局选项 | 1 字节 | T:6；A:4502 |
| `05` | ISO enter LED 布局选项 | 1 字节 | T:7；A:4503 |
| `06` | HHKB blocker LED 禁用选项 | 1 字节 | T:8；A:4508 |
| `07` | USB suspend 时关灯 | 1 字节开关 | T:9；A:4509、1881–1882 |
| `08` | 自动关灯超时 | 1 字节，UI 0–255 分钟，0=Never | T:10；A:1883–1891 |
| `09` | 背光亮度 | `B`，0–255 | T:11；A:1794–1797 |
| `0A` | 背光效果 | `mode`，定义表效果数组索引 | T:12；A:1768–1778 |
| `0B` | 背光速度 | `speed`，0–3 | T:13；A:1801–1804 |
| `0C` / `0D` | 背光颜色 1 / 2 | `H S`，各 0–255 | T:14–15；A:9075–9086 |
| `0E` | Caps Lock 指示色 | `H S` | T:16；A:4493、1892–1895 |
| `0F` | Caps Lock 指示位置 | `row col` | T:17；A:4494、1894–1895 |
| `10` / `11` | Layer 1 指示色 / 位置 | `H S` / `row col` | T:18–19；A:4495、4498 |
| `12` / `13` | Layer 2 指示色 / 位置 | `H S` / `row col` | T:20–21；A:4496、4499 |
| `14` / `15` | Layer 3 指示色 / 位置 | `H S` / `row col` | T:22–23；A:4497、4500 |
| `17` | 自定义效果色槽 | `i H S`；读取也需要 i | T:24；A:9089–9100 |
| `80` | QMK RGBLIGHT 亮度 | `B`，0–255 | T:26；A:1806–1809 |
| `81` | QMK RGBLIGHT 效果 | `mode`，underglowEffects 数组索引 | T:27；A:1810–1812、1768–1778 |
| `82` | QMK RGBLIGHT / Matrix 速度 | `speed`，0–255 | T:28；A:1813–1816 |
| `83` | QMK RGBLIGHT 颜色 | `H S` | T:29；A:4491、1863–1868 |

颜色 picker 把色相 0–360 度和饱和度缩放为两个 0–255 字节（A:1418–1423）；亮度另设。不要把 `H S` 编成 `R G B`。指示位置的 UI 开关实际只写 `FE FE` / `FF FF`（A:1782–1787），没有证明对本机任意 row/col 均可用。

### 3.3 为什么不是逐键 RGB

`17 i H S` 的 i 来自效果要求的颜色数量：初始化按所有效果所需颜色数的最大值读取色槽（A:4530–4533）；当前效果需要多于两个颜色且有 customColors 时，UI 把 Color 1…N 对应到这些色槽（A:1831–1855）。**这条链路没有物理键位号或 LED 映射，不能把“色槽 0”解释为“第一个键”。** Caps/Layer 状态指示色也不能等价为任意会话对应键的独立渲染。

客户端确有纯色效果：WT RGB 的默认列表 `mode=01` 为 Solid Color 1（P:148–151），QMK RGBLIGHT 默认列表 `mode=01` 为 Solid Color（P:83–87）。不过设备定义能覆盖效果列表（[`transform.ts:95`](via-c-src/node_modules/via-reader/src/transform.ts:95)），所以不能直接给本机发 `mode=01` 并宣称会整板纯色。

## 4. 保存、flash 磨损与 RAM-only

| 观察 | 能得出的结论 |
|---|---|
| `setBacklightValue`、`setColor`、`setCustomColor`、`setRGBMode` 只发送 `12`，不内置 `11`（A:9058–9105） | 主机可省略显式保存命令 |
| 普通 UI 改参数后跟发 `saveLighting()`（A:4590–4596）；改色槽也保存（A:4598–4610） | 不能照搬 UI 的每次更新路径用于高频 agent 状态刷新 |
| `toggleLights()` 读取旧模式、切换闪灯后恢复，没有 `saveLighting()`（A:4082–4089） | 有主机侧临时调灯的实际代码路径，但未证明目标固件的存储行为 |
| 新教程说明灯效等配置存于键盘内部（[`tutorial.html:150`](cxt-web-driver/tutorial.html:150)）；旧教程描述 UI 调灯重启仍保留（[`lightsetting.html:9`](cxt-web-driver/legacy/lightsetting.html:9)） | 厂商描述了持久化的产品行为，没有说明原始 `12` 单独发送是否持久化 |

**目前不能保证“只改 RAM，不保存”。** `11` 是客户端命名的显式保存入口；缺少匹配固件源码，无法确认实际介质是否 flash/EEPROM、是否自动或延迟保存、擦写粒度、寿命或磨损均衡。旧教程说“无需保存”是 UI 无需手动点击，不代表客户端没有自动跟发 `11`。

如果每次更新都触发非易失写入，频繁刷新可能增加磨损；现有证据不能计算安全频率或寿命。未来集成应先证明设备支持临时控制，再只在状态变化时更新；不能把省略 `11` 当作已经解决磨损问题。

## 5. 危险命令清单：不要发

下表按 **32 字节 payload** 表示，省略 node-hid 的 Report ID 前导 `00` 及尾部补零。全部编号仅属于本份 VIA-C 协议。

| payload | 风险 | 证据 |
|---|---|---|
| `01` | **不要发**：跳 bootloader，打断正常运行 | A:9116–9117 |
| `04` | **不要发**：reset EEPROM，可能清除原配置/键位 | A:9112–9113 |
| `10 layer row col key_hi key_lo` | **不要发**：改写单键 | A:9120–9122 |
| `0C offset_hi offset_lo size data...` | **不要发**：批量改键 | A:9033–9039 |
| `05` | **不要发**：清空宏 | A:9168–9169 |
| `0F offset_hi offset_lo size data...` | **不要发**：写入宏数据 | A:9147–9164 |
| `02 selector values...` | **不要发**：通用键盘配置写入，不是灯光设置 | A:9048–9050 |
| `03 80 enabledModes` | **不要发**：修改旋钮自定义模式配置 | A:2888–2900 |
| `03 82 index behavior key_hi key_lo` | **不要发**：修改旋钮行为/键码，且 index 非已确认的物理旋钮号 | A:2901–2911 |
| `11` | **不要发**：显式保存灯光，本轮及临时试验均不需要 | A:9108–9109 |
| `12` 的布局、Caps/Layer 指示设置 | **不要发**：会改灯珠/指示配置，超出最小试验 | A:1782–1787、4493–4509 |

另外，原客户端的 `isCorrectProtocol()` 在厂商标识不符时竟然调用 `jumpToBootloader()`（A:8950–8956），层数和矩阵读写也有类似分支（A:8959–8969、8972 起、9017–9022）。**不要运行原应用的初始化/探测逻辑来做“只读查询”。**

对当前未知 `FF00:01` 协议，连本表之外的 `0D`“读取”也不能认作安全探针：在另一协议中同一字节可能有别的意义。本轮所有报文均禁止发送。没有证据证明上述操作一定导致永久损坏，但可能丢配置或进入引导模式；不能靠 reset 恢复一次试写。

## 6. 最小试验与恢复提案：本轮不执行

**当前不具备实机执行条件。** 下面是旧 VIA-C 协议得到匹配证据后的候选，不是已经适配 `4132:2107` 的命令。后续须先确认目标固件、接口、Report ID、长度及属性支持，再由用户批准实际发送；用户批准不能代替缺失的兼容性证据。

最小候选只改一个亮度属性，避免同时猜效果编号和颜色。若确认设备使用 WT 背光 selector `09`：

| 步骤 | 完整 33 字节 node-hid 缓冲表示 | 意义 |
|---|---|---|
| 先读取原值 | `00 0D 09` + `00 × 30` | 确认回显 `R[0:2]=0D 09`，保存 `b_old=R[2]`；无有效旧值则不写 |
| 单条试验写入 | `00 12 09 20` + `00 × 29` | 亮度设为 32；若原值已经是 32，则可提案改为 64，即把 `20` 换成 `40` |
| 恢复原值 | `00 12 09 b_old` + `00 × 29` | 精确恢复读取到的原亮度 |

依据：A:9053–9060、9069–9072、9224–9239。三者都不跟发 `00 11`；恢复后可在获批试验范围内重新读取核对。若读写失败，停止继续试探，不尝试其它命令号、reset 或 bootloader。当前效果若关闭或不使用此亮度域，试验可能没有可见变化，不能据此认定协议失效。若目标只支持 QMK RGBLIGHT，则应在得到证据后把整套 selector 改为 `80`，不能两套都试。

这只能叫“省略显式保存的最小单属性候选”，**不能承诺 RAM-only**。没有读取到原值之前，不存在可填写的真实恢复命令；断电也不是已经验证的恢复方案。

若将来要求整板纯色，至少需要确认所用效果列表和颜色域，并先保存模式、颜色及亮度，再分别修改及恢复；本轮没有足够证据给当前设备指定这些值。单键 AgentDeck 状态灯还缺物理键到 LED 的映射和真正的单键命令，不应使用 `17 i H S` 冒充实现。

## 7. 交付范围与验证

新增范围仅为本报告和 `research/cxt-web-driver/` 的网页快照、下载清单、静态检查及枚举证据。没有修改固件、`pc/`、驱动或现有 VIA-C 源码；没有触及 `wokwi/`、`backup/`、`_rollback/`。本次没有代码清理或重构。

核验了本报告的本地引用文件及行号范围、13 个下载快照的大小和 SHA-256、14 处外部 script 引用的本地文件完整性。VIA-C 命令与风险说明另经独立只读复核。未修改程序源码，无需新增 lint/typecheck 配置；本次静态检查针对资料完整性及协议证据。

使用指定解释器并带 `-X utf8 -B` 运行项目要求的三组离线回归（`-B` 避免生成字节码缓存），退出码均为 0。实际输出末行为：

```text
python pc/test_ui.py
UI: 7 groups passed

python pc/test_daemon.py
daemon offline tests: 10 groups passed

python pc/test_pc.py
PC and firmware loop: 4 groups passed
```

以上测试使用项目已有替身，没有打开真实设备。显示输出没有变化，未运行会重新生成预览图的 `pc/sim.py`。

剩余缺口：匹配本机的厂商协议/客户端静态通信实现、设备功能定义、单键 LED 映射，以及临时更新与持久化的固件证据。拿到这些证据前，保持不打开、不发送的边界。
