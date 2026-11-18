# CARBON-本次修改说明

## 一、改了哪些文件、为什么改

按模拟投资人审阅（`review\投资人审阅-gemini.md`）与一致性复查意见，围绕**前 18 个月只做唯一主力款（国内 ¥499 / 海外 $99，早鸟 ¥399 / $79；上方 3.2–3.5 寸长条屏 + 6 颗矮轴灯键 + 3 颗大机械键 + 金属滚轮 + 板载麦克风，USB-C 有线注塑壳）+ 两层软件订阅（个人 Pro ¥19/月、企业 Team ¥39–59/人/月，彻底砍掉优篮子 OEM 授权幻想）+ 天使轮 ¥500 万分两期自造血模型**，把全套文档、财务表和路演 PPT 彻底拉齐，消除了之前文档改了一半但 PPT 正文跳过、爆炸图说明过期、测试数与认证事实前后打架等问题：

1. **`deck\build_bp.js` 与 `deck\apply_polish.py`（重点重写并重新生成 PPTX / PDF）**
   - **修掉 PPT 残留硬伤**：
     - 第 6 页删掉残留的 v1 旧词“键屏”，改为“长条屏 / 置顶浮窗显示真实命令”，补上 `PreToolUse` 高危闸门双钩子，并如实注明设备端随机数校验（`shown_nonce`）待手板实现；
     - 第 9 页补齐中国 3 年 SOM 金额（¥165–494 万）与全球+中国合计（1.8–5.4 万台、约 ¥1,200–3,550 万，汇率 7.1）；
     - 第 10 页升级竞争象限纵轴为“钩子直答 + 高危把关 + 板载语音”，把实际走通用映射的优篮子 Vibe Key（AU05）从“锁死单一厂商”左半区挪回右半区，并补入装有免费同名插件的优篮子 D200；
     - 第 11 页如实写清免费软件当前通过“F13–F24 热键 + 置顶浮窗”兼容存量键盘，Stream Deck / D200 按键屏原生插件下一步开发；
     - 第 12 页如实区分各家钩子能力（Kimi 只能通知不能阻断，Qwen / CodeBuddy 待实测）；
     - 第 13 页把个人 Pro 上线时间从错误的 `2028-03` 修正为与财务表一致的 `2028-01`（随众筹交付同步上线），不开模转纯软件留存现金统一为“约 ¥150–160 万、订金测试仅投 ¥6.4 万”；
     - 第 14 页收入柱状图精确对齐财务模型 CSV（`0.0 / 346.0 / 697.3 / 1005.0` 万元）；
     - 第 15 页修正资金用途圆环图标题与图例（6 项合计正好 **¥500.0 万 / 100%**，占比 **36% + 10% + 4% + 10% + 9% + 31% = 100%**，彻底消除早期 105% 与单位错标问题），首期用途补入“达标后开模（¥12 万）”，二期条件统一为“周活 ≥ 2,000 且众筹 ≥ ¥50 万（或全球付费订金海外 $1 + 国内 ¥9.9 合计 ≥ 1,500 人）”；
     - 第 16 页主动回应里补上“云端异步 Agent 迁移（扩展 Cursor Cloud Agent 与 GitHub PR/CI 槽位）”。
   - **同步生成产物**：更新了 `deck\AgentDeck-天使轮BP.pptx`、`deck\bp.pptx`、`deck\AgentDeck-天使轮BP.pdf`、`deck\bp.pdf`、逐页预览图 `deck\slide-01.jpg`–`slide-17.jpg`、`deck\sheet5.jpg`，并用 UTF-8 编码重新导出了无乱码的 `review\BP文字版.md`。

2. **`01-市场调研.md`、`02-竞品分析.md`、`03-差异化.md`、`04-技术壁垒.md`**
   - 标题统一加上 `AgentDeck（暂名）`。
   - `01`：修正第八节里程碑表述，明确 2027-08 开模（¥12 万）使用的是第一期资金（前提是全球 $1 / ¥9.9 付费订金累计 ≥ 1,500 人），第二期 ¥250 万用于认证、量产备货与运营，与 `08` 完全一致。
   - `02`、`03`：统一免费软件当前兼容方式（热键+浮窗先行，按键屏原生插件待开发）、优篮子 AU05（¥269–299，部分渠道至 ¥319）与 D200（电商 ¥298–598，官方日常约 ¥500 左右）价格口径；按最新名字排查结果更新候选名风险（`Baton` 与海外同类编排器 `getbaton.dev` 及 App Store 应用撞名建议淘汰，新增低冲突首推候选“驭阵 / ReinPad”等，正式商标检索均标【待核实】；把已退役的 `USPTO TESS` 更正为新版 `USPTO Trademark Search`）。
   - `04`：把中枢离线单元测试数量从旧的 252 项更新为实跑通过的 **264 项**（含新增虚拟 v2 设备窗口测试），统一付费订金双轨口径。

3. **`05-PRD-简版.md`、`06-PRD-详细版.md`、`07-技术方案.md`**
   - `05`、`06`、`07` 标题统一加上 `AgentDeck（暂名）`，单测数统一更新为 **264 项 + 回放自检 12/12**，补充虚拟 v2 设备窗口与微雪 3.49 寸固件草稿现状。
   - `06`：把人类手动盲批比例从模糊的 `93%～97%` 统一为 Anthropic 官方报告核实的 **97%**；修正 `exploded-v2b.png` 图注（新图已修好 11 键/11 轴/11 焊位与注塑壳对齐，删掉“焊盘数对不上待重画”的过期旧话）；补入纯 USB 5V 有线无电池外设免国内强制 CCC 的法规核实结论（整机 SRRC 认定仍标【待核实】）。
   - `07`：修正顶部 `exploded-v2b.png` 与第 15 节的过期爆炸图说明；第 11.2 节补齐 9 颗 RGB 灯（含说话键背光）；第 12 节在不改动任何 BOM 金额（裸物料 ¥295/¥191、含预留 ¥339/¥220、到手成本 ¥387/¥253）的前提下补入供应链公开核实数据（3.49 寸 `AXS15231B` QSPI 屏样品价、避开已停产的 `EVQWGD001` 滚轮与 `INMP441`/`ICS-43434` 麦克风、有线无电池免强制 CCC）；修掉第 14 节残留的“`test_hub.py` 按简报编写中”旧话。

4. **`08-商业模式与财务.md` 与 `08-财务模型.csv`**
   - 重跑 `research\08-model.py` 校验 `08-财务模型.csv` 全部 16 个季度数据与正文分毫不差；更新扉页与 BOM/认证说明以衔接 `raw-gemini-supply.md` 公开器件核查结论（同时严守“尚无代工厂正式书面报价”的诚实口径）；统一优篮子 D200 价格描述与全球付费订金（海外 $1 + 国内 ¥9.9）口径；为单台账补充整数四舍五入说明。

5. **`00-目录.md`（及配套同步 `09-融资前验证计划.md`、`research\strategy-core.md`、`gtm\` 一页纸与私信）**
   - `00-目录.md` 补齐 17 页 PPTX、PDF 版、纯文本导出及供应链核查报告入口，同步 264 项单测、虚拟 v2 设备窗口、3.49 寸固件草稿及未完成项清单；顺手把 `09`、`strategy-core`（罗技发布时间 2026-09）和 `gtm` 一页纸里的单测数同步到 264 项，保证整个项目目录零冲突。
   - 安全排查：扫描全项目未发现真实泄露的密钥或密码（文档中仅含 `$AGENTDECK_TOKEN` 等示例变量名）。

---

## 二、怎么验证的（测试命令与原样输出最后几行）

### 1. 财务模型复算、BP 重新生成、OOXML 结构校验、PDF 转换与回放自检

运行命令：
```powershell
$env:NODE_PATH = "D:\desk\hardware\h1\agentdeck\deck\node_modules"
$env:PPTX_SKILL = "D:\desk\hardware\h1\agentdeck\deck\_sk"
$env:PYTHONIOENCODING = "utf-8"
Set-Location "D:\desk\hardware\h1\agentdeck"
& "D:\conda\miniconda3\python.exe" "research\08-model.py" | Select-Object -Last 6
Set-Location "D:\desk\hardware\h1\agentdeck\deck"
node build_bp.js
& "D:\conda\miniconda3\python.exe" apply_polish.py
& "D:\conda\miniconda3\python.exe" _sk\scripts\office\validate.py "AgentDeck-天使轮BP.pptx"
Copy-Item "AgentDeck-天使轮BP.pptx" "bp.pptx" -Force
& "C:\Program Files\LibreOffice\program\soffice.com" "--headless" "--convert-to" "pdf" "--outdir" "D:\desk\hardware\h1\agentdeck\deck" "D:\desk\hardware\h1\agentdeck\deck\bp.pptx"
Copy-Item "bp.pdf" "AgentDeck-天使轮BP.pdf" -Force
& "D:\conda\miniconda3\python.exe" "D:\desk\hardware\h1\research\selftest_hub_replay.py" | Select-Object -Last 4
```

结果最后几行（原样粘贴）：
```text
wrote D:\desk\hardware\h1\agentdeck\08-财务模型.csv
wrote D:\desk\hardware\h1\agentdeck\deck\AgentDeck-天使轮BP.pptx
(1, 'notes', 107)
(2, 'notes', 101)
(17, 'notes', 95)
pages parsed: 17 slides: 17
All validations PASSED!
Could not find platform independent libraries <prefix>
convert D:\desk\hardware\h1\agentdeck\deck\bp.pptx as a Impress document -> D:\desk\hardware\h1\agentdeck\deck\bp.pdf using filter : impress_pdf_Export
Overwriting: D:\desk\hardware\h1\agentdeck\deck\bp.pdf
PASS | Decisions persisted in the temporary audit chain
PASS | Temporary Hub startup and cleanup
12 PASS / 0 FAIL
Physical Ctrl+session chords remain pending user confirmation; see pc/hub_keys.md.
```

### 2. 中枢全量单元测试（核实测试总数）

运行命令：
```powershell
& "D:\conda\miniconda3\python.exe" -m unittest discover -s "D:\desk\hardware\h1\pc" -p "test_hub*.py" -q
```

结果最后几行（原样粘贴）：
```text
2026-11-17 20:31:04,632 agentdeck.hub INFO Hub listening on 127.0.0.1:12345 (usb,hotkey)
2026-11-17 20:31:04,660 agentdeck.hub INFO Hub listening on 127.0.0.1:12345 (usb,hotkey)
----------------------------------------------------------------------
Ran 264 tests in 8.988s

OK
```

此外已将生成的 PDF 逐页转成图片（`deck\slide-01.jpg`–`slide-17.jpg` 及 `deck\sheet5.jpg`）逐页肉眼检查排版，确认 17 页均无文字溢出、无遮挡、无乱码。

---

## 三、还剩什么没做（需创始人或后续真机推进）

1. **创始人拍板事项**：最终定下新品牌名并委托代理机构做中美第 9/42 类正式商标检索（文档中已标【待核实】）；在 BP 第 17 页和一页纸里填入真实的创始人姓名、履历、分工与联系方式。
2. **需要真机账号 / 外部询价才能消掉的【待实测】与【待核实】**：
   - 创始人在本机登录 `claude` CLI、在 Codex 里输入 `/hooks` 手动信任钩子，跑通真实会话与真实 Auto Mode 下的 `PreToolUse` 高危闸门实测；
   - 实测国产 Qwen Code、CodeBuddy、Kimi、Trae（及 Antigravity CLI、Cursor 云端接口）的真实钩子边界并录屏；
   - 采购微雪 3.49 寸开发板搭出首台彩屏真机手板，实现设备端 `shown_nonce` 随机数校验，并补齐 macOS 版中枢及 Stream Deck / 优篮子 D200 按键屏原生插件；
   - 找 2–3 家深圳代工厂拿正式书面 BOM 报价（验证 1 万台裸 BOM ≤ ¥176），并由认证实验室书面确认关断射频后的有线 FCC / CE / SRRC 送测口径；
   - 将落地页接入真实收表与支付服务，招募 30–50 名重度多开开发者跑出真实 D14 留存率。
