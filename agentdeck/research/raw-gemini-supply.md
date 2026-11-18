# AgentDeck v2 供应链精简调研报告（Gemini）

- **调研日期**：2026-11-17
- **目标形态（D1）**：3.2–3.5 寸长条 IPS 屏（6 等分状态区）+ 6 个矮轴机械键（RGB）+ 3 个大号机械键 + 2 个小键 + 金属滚轮编码器 + MEMS 麦克风 + ESP32-S3 + USB-C 有线（铝顶板 + 注塑底壳）
- **数据原则**：所有报价均附公开可查来源 URL；未检索到公开带链接报价的项均标注“未找到”。

---
## 1. 3.2–3.5 寸长条 IPS 屏（型号、驱动 IC、接口与单价）

> **选型关键提示（针对 ESP32-S3）**：ESP32-S3 原生支持 **SPI / QSPI / 8080 并口 / 16-bit RGB** 接口，**不支持 MIPI DSI**。采购长条屏时必须避开纯 MIPI 接口型号，优先选 **QSPI**（仅占 6 根引脚，留足 GPIO 给 11 键 + 滚轮 + 麦克风）或 **SPI + 16-bit RGB**。

| 规格分类 | 代表型号 | 分辨率 & 显示区 (AA) | 驱动 IC | 接口类型 | 渠道单价（每条附来源 URL） |
|---|---|---|---|---|---|
| **3.49 寸长条 IPS 屏**<br>*(首选：引脚最少，宽度适配紧凑 6 键)* | • 面板号：`H0349S001T001`<br>• 模组号：`TTH348BVT-02CG` (Tailor Pixels)<br>• 开发板同款：`ESP32-S3-Touch-LCD-3.49` | **172 × 640**<br>AA: `22.58 × 84.00 mm`<br>*(横置宽 84mm，6 等分每格宽 14mm)* | **AXS15231B**<br>*(显示 + 触控一体 SoC)* | **QSPI** (显示) + **I2C** (触控) | • **工业屏供应商样品价（裸屏/触控模组）**：**$6.90 – $11.50 / 片**（[Tailor Pixels 产品页](https://tailorpixels.com/product/3-48-touch-lcd-172x640-mipi-rgb-mcu-spi/)、[QSPI 屏目录](https://tailorpixels.com/input-interface-signal/qspi/)；规格参考 [Panelook H0349S001T001](https://m.panelook.com/H0349S001T001-V1-3-49-inch-172X640-bar-shaped-LCD-display-fully-laminated-touch-screen-full-interface-ready-detail_182256.html)）<br>• **淘宝现货（裸屏/替换屏及集成板）**：裸屏样品约 **¥40 – ¥80 / 片**，集成开发板约 **¥60 – ¥100**（[淘宝 3.49 寸 172×640 商品列表](https://www.taobao.com/list/item/bVdSRXB1czZQVW9jMGNyNFBOU2F0Zz09.htm)）<br>• **Waveshare 官方整板参考（含 ESP32-S3R8 + 屏 + 音频）**：**$29.99 – $31.99**（[Waveshare 产品页](https://www.waveshare.com/esp32-s3-touch-lcd-3.49.htm)）<br>• **1688 批发单价**：未找到公开固定标价单品页（需按起订量询盘）<br>• **AliExpress 裸屏单价**：未找到独立裸屏链接（仅见整套开发板）<br>• **LCSC / 立创商城**：未找到（不直接备货此款异形 LCM 玻璃模组） |
| **3.16 / 3.2 寸长条 IPS 屏** | • 面板号：`TL032FWV01-I1440A`<br>• 零售同款：Adafruit `#5828` | **320 × 820**<br>AA: `26.40 × 67.65 mm`<br>*(外形约 31.2 × 76.6 mm)* | **ST7701S** | **3/4-line SPI + 16/18-bit RGB** (40-Pin FPC) | • **1688 批发/拿样**：无触控版约 **¥45 – ¥55 / 片**，带电容触控 40-Pin IPS 版约 **¥65 / 片**（[1688 3寸/3.16寸 320×820 条形屏商品列表](https://tw.1688.com/item/-D2BABEA7C6C133B4E7.html?beginPage=27)）<br>• **海外零售对照（Adafruit 裸屏）**：**$15.00 – $18.00 / 片**（[Adafruit #5828](https://www.adafruit.com/product/5828)）<br>• **AliExpress 裸屏单价**：未找到 `320×820` 独立裸屏直售链接<br>• **LCSC / 立创商城**：未找到 |
| **3.4 寸高分长条 IPS 屏**<br>*(备选：宽度更接近标准 6 键)* | • 东升微 (EastRising)：`ER-TFT034-1` | **412 × 960**<br>*(长条形 Bar Type)* | **ST7701S** | **SPI + RGB** | • **BuyDisplay（东升微官方跨境店）**：**$10.90 – $13.00 / 片**（[BuyDisplay ER-TFT034-1](https://www.buydisplay.com/bar-type-3-4-inch-412x960-ips-tft-lcd-display-spi-rgb-interface)）<br>• **1688 / 淘宝 / LCSC**：未找到该型号公开直标链接 |
| **3.5 寸常规比例 IPS 屏**<br>*(低成本对照参考)* | • 通用 3.5" SPI IPS 模组 / `ER-TFT035IPS-6` | **320 × 480** | **ST7796S / ILI9488** | **4-wire SPI / MCU / RGB** | • **AliExpress 零售模组价**：**$8.00 – $12.00 / 片**（[AliExpress Item 1005008077523581](https://www.aliexpress.com/item/1005008077523581.html)）<br>• **LCSC**：未找到长条窄边切割款 |

---
## 2. 矮轴与普通机械轴单价（6 个 RGB 矮轴 + 3 大键 + 2 小键）

> **选型提示**：凯华 Choc V1 (`PG1350`) 为双扁脚猪鼻十字外轴心，不兼容常规 MX 键帽；凯华 Choc V2 (`PG1353`) 与佳达隆矮轴 2.0/3.0 (`KS-33`) 均为十字轴心，键帽生态更广，但三者 PCB 焊盘孔位互不兼容，开板前必须锁定一家。下方 3 大键 + 2 小键可用标准 MX 机械轴（支持 SMD RGB 反贴灯或导光柱）。

| 类别 | 品牌与型号 | 渠道与起订层级 | 单价（每条附来源 URL） |
|---|---|---|---|
| **矮轴机械轴** | **凯华 Kailh Choc V1 (`PG1350` / `CPG135001D01`)** | LCSC / JLCPCB 元件库 (`#C400229`) | • **1+ 颗**：**$1.1964 / 颗**；**10+ 颗**：**$0.9672 / 颗**（[JLCPCB 机械轴分类库](https://jlcpcb.com/parts/2nd/Switches/Mechanical_Keyboard_Shaft_2212)） |
| **矮轴机械轴** | **凯华 Kailh Choc V1 (`PG1350`)** | 跨境客制化零售 (Mechkeys / AliExpress 同级) | • **10 颗装**：**$6.00 – $7.00**（折合 **$0.60 – $0.70 / 颗**）（[Mechkeys PG1350](https://mechkeys.com/products/kailh-1350-low-profile-chocolate-keyboard-switch)）<br>• **1688 公开直标单品链接**：未找到固定挂牌链接（行业询盘价通常低于零售） |
| **矮轴机械轴** | **凯华 Kailh Choc V2 (`PG1353` 十字轴心)** | 凯华官方跨境店 | • **零售单价**：**$0.55 – $0.75 / 颗**（[Kailh 官方店 PG1353](https://kailhswitch.net/products/kailh-choc-v2-low-profile-switch-1353-chocolate-v2-mechanical-keyboard-switch-custom-diy-clicky-tactile-linear)、[官网规格书](https://www.kailhswitch.com/mechanical-keyboard-switches/key-switches/kailh-low-profile-switch-choc-v2.html)） |
| **矮轴机械轴** | **佳达隆 Gateron 矮轴 2.0/3.0 (`KS-33`)** | 淘宝零售 / AliExpress | • **淘宝常规款（红/茶/青等，10 颗装 ¥20–¥25）**：折合 **¥2.00 – ¥2.50 / 颗**（[淘宝 KS-33 矮轴列表](https://www.taobao.com/list/item/dXEwU1p4aEZKUEZSQ0JKV0d3blI3UT09.htm)）<br>• **淘宝静音矮轴款（10 颗装 ¥26–¥30）**：折合 **¥2.60 – ¥3.00 / 颗**（[淘宝店铺页](https://www.taobao.com/list/dianpu/203821044.htm)）<br>• **AliExpress 零售**：约 **$0.35 – $0.60 / 颗**（[AliExpress Gateron Low Profile 专区](https://aliexpress.ru/popular/gateron-low-profile-3-0)）<br>• **LCSC**：未找到 |
| **普通机械轴 (MX)** | **凯华标准 MX 轴 (`CPG151101D01`)** | JLCPCB PCBA 元件库 (`#C49234238`) | • **50+ 颗**：**$0.0856 / 颗**（约 ¥0.62）<br>• **150+ 颗**：**$0.0747 / 颗**<br>• **2,500+ 颗**：**$0.0598 / 颗**；**5,000+ 颗**：**$0.0565 / 颗**（约 ¥0.41）（[JLCPCB C49234238](https://jlcpcb.com/partdetail/HanElectricity-CPG151101D01/C49234238)） |
| **普通机械轴 (MX)** | **佳达隆 Gateron G Pro 系列** | 佳达隆官方海外店 | • **10 颗起售盒装**：约 **$5.00 – $9.00 / 10 颗**（折合 **$0.50 – $0.90 / 颗**）（[Gateron 官网 Switch Set](https://www.gateron.co/products/gateron-switch-set)）<br>• **1688 公开带链接阶梯价**：未找到精确单品直链 |
| *附：热插拔轴座* | **凯华 MX 热插拔轴座 (`CPG151101S11-16`)** | LCSC (`#C5156480`) | • **基础单价**：**$0.0664 / 个**起（大批量约 $0.025–$0.04）（[LCSC C5156480](https://www.lcsc.com/product-detail/mechanical-keyboard-shaft_kailh-cpg151101s11-16_C5156480.html)） |

---
## 3. 金属滚轮 / EC11 编码器单价

> **量产避坑提示**：客制化圈常见的松下滚筒式滚轮编码器 **`EVQWGD001` 已正式停产（EOL）**，仅剩高价拆机/尾货，**不可用于量产 BOM**。量产实现“右侧金属滚轮/旋钮”有两种成熟低成本结构：
> 1. **立式/卧式 EC11 旋转编码器 + CNC 阳极氧化铝合金滚花旋钮帽**（支持下按确认，寿命与手感最稳）；
> 2. **鼠标滚轮机械编码器（如凯华 CEN98 / TTC 金轮）+ CNC 铝合金滚轮轴 + 侧立微动**（需开注塑/金属轴承座支架）。

| 器件类型 | 品牌与型号 | 渠道与料号 | 单价（每条附来源 URL） |
|---|---|---|---|
| **EC11 旋转编码器（带按压开关）** | **ALPSALPINE `EC11E18244AU`**<br>*(18 脉冲 36 定位点，带开关)* | LCSC (`#C202365`) | • **1+ 颗**：**$2.25 / 颗**；**10+ 颗**：**$1.92 / 颗**<br>• **120+ 颗**：**$1.34 / 颗**；**960+ 颗**：**$1.20 / 颗**（[LCSC C202365](https://www.lcsc.com/product-detail/C202365.html)） |
| **EC11 旋转编码器（经济型原厂款）** | **ALPSALPINE `EC11L1525G01`** | 立创商城 (`#3453459`) | • **参考起步价**：约 **¥4.11 / 颗**起（[立创商城 3453459](https://item.szlcsc.com/3453459.html)） |
| **EC11 旋转编码器（常规带开关款）** | **ALPSALPINE `EC11E1834403` / `EC11E15244B2`** | 立创商城 (`#335993` / `#476834`) | • `EC11E1834403`：约 **¥7.08 / 颗**起（[立创商城 335993](https://item.szlcsc.com/335993.html)）<br>• `EC11E15244B2`：约 **¥8.21 / 颗**起（[立创商城 476834](https://item.szlcsc.com/476834.html)） |
| **配套金属旋钮帽 / 滚轮件** | **CNC 铝合金阳极氧化滚花旋钮（适配 EC11 6mm 轴）** | 1688 源头加工厂 | • **CNC 精雕阳极氧化款批发价**：约 **¥2.50 – ¥6.00 / 个**（普通车件大货低至 ¥0.80–¥2.00）（[1688 商品页 968613542192](https://m.1688.com/offer/968613542192.html)；成品键盘应用参考 [淘宝铝制旋钮键盘列表](https://www.taobao.com/list/product/%E9%93%9D%E5%88%B6%E6%9C%BA%E6%A2%B0%E9%94%AE%E7%9B%98%E5%B8%A6%E9%9F%B3%E9%87%8F.htm)） |
| **卧式滚筒拨轮编码器（已停产对照）** | **Panasonic `EVQWGD001`** *(已停产 EOL)* | 海外客制化店尾货 / LCSC | • **尾货零售价**：**$7.00 – $30.00 / 颗**且常断货（[Keebd 商品页](https://keebd.com/en-us/products/encoder-roller-with-push-switch)、[停产说明](https://ergomech.store/blog/ergomech-blog-1/the-roller-encoder-is-dead-long-live-the-roller-encoder-13)）<br>• **LCSC 现货**：未找到（已停产无库存） |

---
## 4. 主控（ESP32-S3-WROOM-1 N8R8）与 MEMS 麦克风单价

> **量产避坑提示**：创客项目常用的两款 TDK InvenSense 数字 I²S 麦克风 **`INMP441` 和 `ICS-43434` 均已进入停产（EOL / Discontinued）状态**！正规代理与立创/LCSC 原厂裸片库存枯竭或处于尾货清仓价，淘宝/AliExpress 低价模块多为拆机或翻新小板。EVT 原型验证可用 `ICS-43434` 现货或 `INMP441` 模块跑通链路，但 DVT/量产建议切换至在产国产/主流数字硅麦（如歌尔、瑞声、敏芯微新系列或楼氏在产型号）。

| 器件类别 | 具体型号 | 渠道与料号 | 单价（每条附来源 URL） |
|---|---|---|---|
| **主控模组** | **乐鑫 `ESP32-S3-WROOM-1-N8R8`**<br>*(8MB Flash + 8MB Octal PSRAM，PCB 板载天线)* | **立创商城** (`#3198299` / `#C2913201`) | • **国内参考单价**：约 **¥21.03 / 片**（随阶梯下调）（[立创商城 3198299](https://item.szlcsc.com/3198299.html)） |
| **主控模组** | **乐鑫 `ESP32-S3-WROOM-1-N8R8`** | **LCSC 国际站** (`#C2913201`) / **DigiKey** | • **LCSC 阶梯价**：**1+ 片 $5.09**；**10+ 片 $4.46**；**100+ 片 $3.70**；**1,000+ 片 $3.48 / 片**（规格书直链 [LCSC Datasheet](https://datasheet.lcsc.com/datasheet/pdf/24a44651a4767a6582addcdaa9cab2ca.pdf?productCode=C3013946)）<br>• **DigiKey 对照（同系 1U-N8R8）**：1+ 片 **$6.32 / 片**（[DigiKey 产品页](https://www.digikey.com/en/products/detail/espressif-systems/ESP32-S3-WROOM-1U-N8R8/16162638)） |
| **MEMS 麦克风** | **TDK InvenSense `ICS-43434`**<br>*(数字 I²S，已停产 EOL 尾货)* | **LCSC** (`#C5656610`) | • **1+ 颗**：**$4.29**；**10+ 颗**：**$3.71**；**100+ 颗**：**$3.02**；**1,000+ 颗**：**$2.82 / 颗**（库存余约 3,947 颗，标注停产）（[LCSC C5656610](https://www.lcsc.com/product-detail/C5656610.html)） |
| **MEMS 麦克风** | **TDK InvenSense `INMP441`**<br>*(数字 I²S，已停产 EOL)* | **LCSC / JLCPCB** (`#C5438445`) & 模块零售 | • **LCSC 裸片**：常规无现货，JLCPCB 外部调货参考价高达 **$25.00 / 颗**（[LCSC C5438445](https://www.lcsc.com/product-detail/C5438445.html)、[JLCPCB C5438445](https://jlcpcb.com/partdetail/TDKInvenSense-INMP441/C5438445)）<br>• **eBay / 跨境模块板参考**：散片模块约 **$1.00 – $2.50 / 块**（[eBay INMP441 模块搜索页](https://www.ebay.com/shop/inmp441?_nkw=inmp441)；AliExpress 精确直达单品链接：未找到） |
| *参考：国产 I²S 硅麦* | **敏芯微 `MSM261S4030H0R`** *(ESP32 开发板常用款)* | **立创商城 / JLCPCB** (`#3020642` / `#C2840615`) | • **立创历史参考价**：约 **¥7.65 / 颗**（当前亦标停售，建议选敏芯/歌尔新一代在产料号）（[立创商城 3020642](https://item.szlcsc.com/3020642.html)、[JLCPCB C2840615](https://jlcpcb.com/partdetail/MEMS-MSM261S4030H0R/C2840615)） |

---
## 5. 深圳可承接小键盘整机打样的 ODM / 方案商（5 家）

针对 D1 结构（**CNC 铝顶板 + 注塑底壳 + 长条 IPS 屏 + 矮轴/MX 混排 + 金属旋钮 + 自定义上位机通信**），以下 5 家深圳本土厂商覆盖了“整机 ODM 代工”与“带屏/旋钮键盘 PCBA 方案开发”两类核心资源：

| # | 公司 / 品牌名称 | 所在区域 | 核心能力匹配度 | 官方网站 / OEM 入口 |
|---|---|---|---|---|
| 1 | **深圳市赛米泰克科技有限公司（Semitek）** | 深圳 | 老牌客制化与小配列宏键盘 ODM/方案厂，长期出货 3/6/9/12 键旋钮宏键盘、异形配列机械键盘，具备从 PCB、结构手板到自定义上位机驱动的整机打样与中小批量交付能力。 | https://www.pc-100.com/about-us/ |
| 2 | **魔极客 / 艾酷科技（MonsGeek / Akko）** | 深圳 | 拥有独立面向全球客户的 OEM/ODM 事业部，极其擅长**“CNC 铝合金壳体 + 注塑底壳 + 旋钮 + 彩屏套件”**全链路开模、轴体/键帽配套与中小批量定制生产。 | https://www.monsgeek.cn/oem-service/ |
| 3 | **麦修科技（Mathew Technology）** | 深圳 | 专注客制化机械键盘套件、异形配列键盘、旋钮/小屏键盘及键帽轴体的源头 ODM/OEM 工厂，支持私模结构打样与小批量试产。 | http://www.mathewkb.com/oem-odm/ |
| 4 | **深圳市恒上电子有限公司（RECCAZR 雷咖泽）** | 深圳 | 深圳本土实力键盘制造工厂，承接各类小配列键盘、客制化热插拔/旋钮外设的 ODM/OEM 整机定制、模具注塑及组装测试。 | https://www.reccazr.com/news/512893 |
| 5 | **睿联微科技（深圳）有限公司** *(搭配方案商)*<br>*备选：深圳市三佛科技有限公司* | 深圳 | **键盘电子与带屏方案商**：睿联微专攻带 **LCD 彩屏/状态屏 + 独立 LED 驱动**的机械键盘 PCBA 方案；三佛科技专攻旋钮 + 宏扩展 + QMK/VIA 小键盘 PCBA 快速打样。适合配合深圳 CNC 手板/注塑厂做 EVT 联合开发。 | • 睿联微：https://www.witmod.com/productinfo/1281385.html<br>• 三佛科技：https://www.sanfo888.com/article/1665 |

---
## 6. 中国 CCC 认证是否适用于纯 USB 有线键盘（附官方与机构来源）

### 结论：**不适用（无需办理强制性 CCC 认证）**

独立销售、仅通过 **USB-C 5V 直流有线供电**、**无内置可充电锂电池**、**不附带 220V 交流电源适配器**的纯有线键盘（含带状态小屏与麦克风的桌面控制器形态），**不属于中国强制性产品认证（CCC）目录范围**，在国内生产和销售无需办理 CCC 证书。

### 法规与界定依据

1. **不在 09 类“信息技术设备”强制认证子目录内**：
   根据国家市场监督管理总局发布的《强制性产品认证目录描述与界定表（2023年修订）》（市场监管总局 2023 年第 36 号公告），第 09 类“信息技术设备”仅涵盖微型计算机（0901）、便携式计算机（0902）、与计算机连用的显示设备（0903）、打印设备（0904）、多用途打印复印机（0905）、扫描仪（0906）、计算机内置电源及电源适配器充电器（0907）、电脑游戏机（0908）、学习机（0911）、复印机（0912）、服务器（0913）以及锂离子电池和电池组/移动电源（0914/0915）。**独立售卖的计算机外围输入设备（键盘、鼠标、宏控制器）未被列入目录。**
   - 来源 1（《强制性产品认证目录描述与界定表（2023年修订）》目录汇编）：http://www.cqc-3c.com/about/3crenzhengmulu/
   - 来源 2（中国电子技术标准化研究院 CESI 强制性认证目录说明）：https://www.cesi.cn/cesi/page/marketservice.jsp?catalog=/004/004-005/004-005-001

2. **低于 >36V 供电电压强制适用门槛（安全特低电压 III 类小功率设备豁免）**：
   根据《强制性产品认证目录描述与界定表》总则说明第 1 条及《电子产品及安全附件强制性产品认证实施规则》（CNCA-C09-01）：除电信终端等特定类别外，电气电子产品 CCC 适用范围**仅限于可直接或间接连接到大于 36V（直流或交流有效值）供电电源的产品**；标称额定电压 ≤ 5V DC、消耗功率 < 15W 且无可充电电池的 USB 供电外设属于 III 类低压设备，不在 CCC 强制发证范围内。
   - 来源 3（中国网络安全审查认证和市场监管大数据中心 `isccc.gov.cn` 官方电子产品及安全附件实施规则 PDF）：https://www.isccc.gov.cn/wlaqrz/cprz/cccrz/ywlb_664/08dzcpjaqfjy080916l/ssgz_675/202512/P020251204588204135045.pdf
   - 来源 4（2023 年第 36 号公告总则“大于 36V 供电电源”界定说明）：http://atc-lab.com/cnNewsDetail/114
   - 来源 5（认监委电子产品实施规则附件关于低压小功率设备界定 PDF）：https://www.cccap.org.cn/upload/2021/07/27/40581d4e-77e9-4256-8e97-31bcb220fabf.pdf

### 国内上市合规实操补充（非 CCC 项）

- **电商平台质检报告**：虽免 CCC，但国内电商平台（京东/天猫等）及政企采购通常要求提供依据强制性国标 `GB 4943.1-2022`（安规）及 `GB/T 9254.1`（EMC）出具的第三方 **CMA/CNAS 质检报告**。
- **主控含射频模组的 SRRC 注意事项**：D1 方案选用的 `ESP32-S3-WROOM-1-N8R8` 模组硬件内置 2.4GHz Wi-Fi / BLE 射频电路（乐鑫该模组本身已具备模块级 **SRRC 无线电发射设备型号核准证**）。若整机宣传或启用任何无线/蓝牙能力，需按规定办理整机 SRRC 认证或合规引用认证模组；若纯有线形态彻底不用无线，量产亦可评估无射频 MCU（或软件彻底禁用射频并在铭牌/说明书仅声明有线 USB 设备）。
