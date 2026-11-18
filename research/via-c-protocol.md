# VIA-C 协议调查：当前宏键盘尚不满足写入条件

调查日期：2026-11-17。仅只读检查 `D:\VIA-C\resources\app.asar`，未运行 VIA-C、未连接 HID、未发送任何 HID 报文、未修改 `D:\VIA-C`。

## 结论与写入门槛

**不能把这份 VIA-C 源码中的命令用于当前 `VID_4132&PID_2107`、usage page `0xFF00` / usage `0x01` 的设备。** 已找到完整的 CXT/VIA 类协议，但该应用实际筛选的是 `0xFF60/0x61`，其随附键盘定义也没有目标 VID/PID。当前设备矩阵尺寸、普通按键位置、四个旋钮的地址和方向均无法从这份软件确认。

因此应停在 `backup` / `show` 的只读检查阶段并明确报错；不得发送键位写入命令、猜测矩阵、猜测旋钮地址，或用“试写后恢复”的办法探协议。现有 `pc/deck_probe.py` 拒绝打开未知 `0xFF00` 接口的行为仍然适用。没有完整、可验证的备份时，也不能把元数据文件冒充键位备份。

## 提取方法与来源

- `research/extract_via_asar.py` 使用 Python 标准库读取 ASAR 的 little-endian Pickle 头，数据区为 `8 + header_size`；安装目录只以 `rb` 打开。
- 已提取 8215 个有效文件到 [`via-c-src/`](via-c-src/)，包括随附的 unpacked 文件。头部另有 18 个明显越界的伪条目（十个随机名称、`license/production/development/staging/secrets` 及三个 `test/*.js`），未尝试分配或读取这些越界长度。
- [`via-c-src/package.json`](via-c-src/package.json:2)：应用名 `via-c`，版本 `0.3.5`，作者 CXT Studio；依赖包含 `node-hid` `^2.1.1` 和 `via-reader` `1.0.0`。
- [`via-c-src/index.html`](via-c-src/index.html:1)：实际加载 `b3cb9540.js`、`19d43329.js`、`7f943605.js`。后者有可读换行，本文行号直接对应提取后的原始文件，未经格式化。

## HID 接口与传输格式

设备枚举入口位于 [`7f943605.js:5168`](via-c-src/static/js/7f943605.js:5168)。它先要求设备的 VID/PID 出现在定义表，再要求：

```javascript
return [97].includes(e) && [65376].includes(t);
```

即 usage `0x61`、usagePage `0xFF60`，原句在 [`7f943605.js:5181`](via-c-src/static/js/7f943605.js:5181)。目标设备的 `0xFF00/0x01` 不符合该筛选条件。对 `main.js` 和 `static/` 下全部七个 JS 文件的检索只找到这一个 `usagePage` 筛选入口；十进制 `65280` 只在旋钮键码的高字节掩码中出现，并非接口筛选（[`7f943605.js:2909`](via-c-src/static/js/7f943605.js:2909)）。媒体文件内类似 `FF60` 的字符只是音频 Base64 数据。

- 按已匹配设备的 path 使用 `new HID(path)` 打开：[`7f943605.js:8877`](via-c-src/static/js/7f943605.js:8877)。
- `_hidCommand` 构造 `[0, command, ...arguments]` 后补零到 **33 字节**：首字节是 HID report ID `0`，有效 payload 32 字节（[`7f943605.js:9225`](via-c-src/static/js/7f943605.js:9225)）。
- 源码先刷新句柄，再 `write`，然后异步 `read`，读到的数据不含 report ID；返回前要求其前缀逐字节匹配请求的 command 和 arguments（[`7f943605.js:9230`](via-c-src/static/js/7f943605.js:9230)、[`7f943605.js:9237`](via-c-src/static/js/7f943605.js:9237)）。
- 所有报文由队列串行处理；不得并发请求后随意配对响应（[`7f943605.js:9201`](via-c-src/static/js/7f943605.js:9201)）。
- 16 位整数、offset、keycode 都是 **大端**；`x([hi,lo]) = hi<<8|lo`，`S(value) = [value>>8,value&255]`（[`7f943605.js:8857`](via-c-src/static/js/7f943605.js:8857)）。

## 找到的命令（仅已匹配的 CXT/VIA 设备）

以下是软件中的确切编号，**不能替换成标准 VIA 的编号**，也不表示目标 `0xFF00/0x01` 固件支持它们。

| 用途 | command 与参数（不含 report ID） | 返回格式 | 源码 |
|---|---|---|---|
| 协议版本 | `0x0B` | `[0x0B, version_hi, version_lo, ...]` | [`8911`](via-c-src/static/js/7f943605.js:8911) |
| 厂商标识 C | `0x20` | `[0x20, hi, lo, ...]`，应用要求值为 `3` | [`8920`](via-c-src/static/js/7f943605.js:8920)、[`8951`](via-c-src/static/js/7f943605.js:8951) |
| 厂商标识 X | `0x21` | BE16，应用读取矩阵前要求为 `8` | [`8929`](via-c-src/static/js/7f943605.js:8929)、[`8971`](via-c-src/static/js/7f943605.js:8971) |
| 厂商标识 T | `0x22` | BE16，应用整体写矩阵前要求为 `4` | [`8938`](via-c-src/static/js/7f943605.js:8938)、[`9017`](via-c-src/static/js/7f943605.js:9017) |
| 层数 | `0x09` | `[0x09, layer_count, ...]`；协议 `7` 固定四层，`>=8` 才查询 | [`8964`](via-c-src/static/js/7f943605.js:8964) |
| 单键读取 | `0x0A, layer, row, col` | `[0x0A, layer, row, col, key_hi, key_lo, ...]` | [`8945`](via-c-src/static/js/7f943605.js:8945) |
| 连续键位读取 | `0x07, offset_hi, offset_lo, size` | 响应第 `4` 字节起为 `size` 字节，`size<=28` | [`8980`](via-c-src/static/js/7f943605.js:8980) |
| 单键写入 | `0x10, layer, row, col, key_hi, key_lo` | 回显同一前缀，代码读取响应 `[4:6]` 的 keycode | [`9120`](via-c-src/static/js/7f943605.js:9120) |
| 连续键位写入 | `0x0C, offset_hi, offset_lo, size, ...data` | 前缀回显；每块至多 28 字节 | [`9033`](via-c-src/static/js/7f943605.js:9033) |
| 保存灯光 | `0x11` | 普通回显 | [`9108`](via-c-src/static/js/7f943605.js:9108) |
| 宏数量（不是层数） | `0x13` | `[0x13, macro_count, ...]` | [`9125`](via-c-src/static/js/7f943605.js:9125) |

矩阵 buffer 顺序是 layer → row → col；每项两个字节，offset 为 `layer * rows * cols * 2 + key_index * 2`。实现见 [`7f943605.js:8985`](via-c-src/static/js/7f943605.js:8985)。矩阵行列来自键盘定义，不是上述命令的返回值。

**不要照搬源码的失败处理。** `isCorrectProtocol` / `getLayerCount` / `readRawMatrix` / `writeRawMatrix` 在厂商标识不符时会调用 `jumpToBootloader()`（`0x01`），这是破坏当前运行状态的行为，调查工具必须直接报错。`resetEEPROM()` 是 `0x04`，同样不属于本任务应执行的命令（[`7f943605.js:9112`](via-c-src/static/js/7f943605.js:9112)）。

### 是否需要保存

普通键位 UI 路径只调用 `setKey` 然后更新内存状态，没有额外保存调用（[`7f943605.js:4613`](via-c-src/static/js/7f943605.js:4613)、[`7f943605.js:4622`](via-c-src/static/js/7f943605.js:4622)）。`saveLighting()` 只在灯光变更路径调用（[`7f943605.js:4596`](via-c-src/static/js/7f943605.js:4596)、[`7f943605.js:4610`](via-c-src/static/js/7f943605.js:4610)）。因此，源码不支持“写键后发 `0x11` 保存键位”的推断；仅凭此处也无法证明目标设备的持久化行为。

## 旋钮：找到的是自定义模式表，不能认作四个旋钮的键位表

源码存在 `RotaryEncoder` 自定义功能页：

- `ra=128`、`ia=129`、`la=130`、`ca=131`（[`7f943605.js:2600`](via-c-src/static/js/7f943605.js:2600)）。
- `_a(api, index)` 用 `[0x02, 0x82, index]` 读回三个 BE16，依次取响应 bytes `3..8`（[`7f943605.js:2619`](via-c-src/static/js/7f943605.js:2619)）。
- UI 列标题为 `CW` / `CCW` / `Press`（[`7f943605.js:2978`](via-c-src/static/js/7f943605.js:2978)）。
- 写一个行为为 `[0x03,0x82,index,behavior,key_hi,key_lo]`（[`7f943605.js:2901`](via-c-src/static/js/7f943605.js:2901)）。
- UI 提取 `index=0,1,2` 三组，枚举名为 `ENC_MODE_CUSTOM0/1/2`（[`7f943605.js:2631`](via-c-src/static/js/7f943605.js:2631)、[`7f943605.js:2880`](via-c-src/static/js/7f943605.js:2880)）。这没有 layer 参数，也没有四个物理旋钮到矩阵的映射证据。

没有找到可归属于 `4132:2107` 的 encoder get/set 命令。不能把“custom mode index 0”解释成“第一个物理旋钮”，不能假定方向、layer、旋钮按下位置或普通键的位置。

## 设备定义和矩阵缺失

[`7f943605.js:5101`](via-c-src/static/js/7f943605.js:5101) 定义远程数据来源为 `https://tan54.oss-cn-beijing.aliyuncs.com/KBData.v3.json`；先读 electron-store 的 `remoteData`，无缓存时载入 fallback bundle `7ead46c5.js`（[`7f943605.js:5129`](via-c-src/static/js/7f943605.js:5129)）。本次没有发起网络请求。

设备键是 `vendorId * 65536 + productId`（[`7f943605.js:5164`](via-c-src/static/js/7f943605.js:5164)），目标值为 `1093804295` / `0x41322107`。默认 bundle [`7ead46c5.js:20`](via-c-src/static/js/7ead46c5.js:20) 仅有以下 11 个型号，**没有目标值**：CXT 60 Matrix、GH63 RGB、GH64、64 Split、MINILA、3x3 E2、20E2、3x4 Micro、12E3 New、2X6 E3、12E4。名称近似或键数近似不足以当作目标矩阵定义。

electron-store 默认文件为 `app.getPath('userData')/config.json`：[`node_modules/electron-store/index.js:16`](via-c-src/node_modules/electron-store/index.js:16)、[`54`](via-c-src/node_modules/electron-store/index.js:54)、[`66`](via-c-src/node_modules/electron-store/index.js:66)。当前 `APPDATA` 为 `C:\Users\king\AppData\Roaming`，只读检查 `via-c`、`VIA-C`、`via_c`、`VIAC`、`VIA C`、`VIA` 的 `config.json` 均不存在，目录中亦无 `*via*` / `*VIA*` / `*CXT*` 应用目录，未找到可弥补缺失的本地缓存。

## F13–F24 的确切键码

以下值直接来自 [`7f943605.js:5327`](via-c-src/static/js/7f943605.js:5327) 至第 5338 行；它们是键盘存储的 HID/QMK keycode，**不是 Windows VK**。

| 键 | 键码 | Windows VK（现有 deck_map） |
|---|---|---|
| F13 | `0x0068` | `0x7C` |
| F14 | `0x0069` | `0x7D` |
| F15 | `0x006A` | `0x7E` |
| F16 | `0x006B` | `0x7F` |
| F17 | `0x006C` | `0x80` |
| F18 | `0x006D` | `0x81` |
| F19 | `0x006E` | `0x82` |
| F20 | `0x006F` | `0x83` |
| F21 | `0x0070` | `0x84` |
| F22 | `0x0071` | `0x85` |
| F23 | `0x0072` | 未默认绑定 |
| F24 | `0x0073` | 未默认绑定 |

用户要求的目标值已明确：前八个普通按键应依次为 `0068,0069,006A,006B,006C,006D,0070,0071`，首个旋钮 CW=`006E`、CCW=`006F`。**这些值明确不等于位置明确。** 未确认矩阵及旋钮位置前不执行写入；后续需要正确固件/软件的目标定义、明确的读写和旋钮协议，并先完成全部层的完整备份。
