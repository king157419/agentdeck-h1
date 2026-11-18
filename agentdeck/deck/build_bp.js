// AgentDeck（暂名）天使轮 BP 生成脚本：node build_bp.js
const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");
const SKILL_DIR = process.env.PPTX_SKILL || path.join(__dirname, "_sk");
const { applyTheme } = require(path.join(SKILL_DIR, "scripts", "apply_theme.js"));

const ROOT = path.resolve(__dirname, "..");
// Prefer the v2 (strip screen + mechanical keys) renders when they exist.
const IMG = (n, v2) => {
  const p2 = v2 && path.join(ROOT, "concept", "v2", v2);
  return p2 && fs.existsSync(p2) ? p2 : path.join(ROOT, "concept", n);
};
const OUT = path.join(__dirname, "AgentDeck-天使轮BP.pptx");

const THEME = {
  name: "AgentDeck Dark",
  headFontFace: "Microsoft YaHei",
  bodyFontFace: "Microsoft YaHei",
  colors: {
    dk1: "F2F4F7", lt1: "111418", dk2: "9AA3AE", lt2: "1C2128",
    accent1: "F5A524", accent2: "2BC864", accent3: "3B82F6",
    accent4: "E5484D", accent5: "C9CED6", accent6: "6B7280",
    hlink: "3B82F6", folHlink: "9AA3AE",
  },
};
// Hex copies for hex-only options.
const HEX = { bg: "111418", card: "1C2128", text: "F2F4F7", muted: "9AA3AE",
  amber: "F5A524", green: "2BC864", blue: "3B82F6", red: "E5484D", grid: "2A313A" };

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625 in
pres.title = "AgentDeck（暂名）天使轮融资商业计划书";
pres.author = "AgentDeck";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

pres.defineSlideMaster({
  title: "TITLE",
  background: { color: HEX.bg },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.55, y: 0.9, w: 4.25, h: 1.8,
      fontSize: 34, bold: true, color: C.text1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.55, y: 2.85, w: 4.25, h: 2.1,
      fontSize: 15, color: C.text2, valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: HEX.bg },
  margin: [0.5, 0.5, 0.45, 0.5],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.3, w: 9.0, h: 0.7,
      fontSize: 25, bold: true, color: C.text1, valign: "middle", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: 9.2, y: 5.25, w: 0.4, h: 0.25, fontSize: 9, color: C.text2 },
});

let section = null;
function add(sectionTitle, master = "CONTENT") {
  if (sectionTitle !== section) { pres.addSection({ title: sectionTitle }); section = sectionTitle; }
  return pres.addSlide({ masterName: master, sectionTitle });
}
function title(s, t) { s.addText(t, { placeholder: "title" }); }
function text(s, t, o) { s.addText(t, Object.assign({ isTextBox: true, margin: 0, color: C.text1, fontSize: 14, valign: "top" }, o)); }
function card(s, x, y, w, h, name) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08,
    fill: { color: C.background2 }, line: { color: C.background2 }, objectName: name });
}
function dot(s, x, y, color, label, name) {
  s.addShape(pres.shapes.OVAL, { x, y, w: 0.42, h: 0.42, fill: { color }, line: { color }, objectName: name });
  if (label) s.addText(label, { isTextBox: true, x, y, w: 0.42, h: 0.42, align: "center", valign: "middle",
    fontSize: 13, bold: true, color: C.background1, margin: 0 });
}
function source(s, t) { text(s, t, { x: 0.5, y: 5.2, w: 8.6, h: 0.3, fontSize: 9, color: C.text2 }); }

// 1 封面
{
  const s = add("开场", "TITLE");
  s.addImage({ path: IMG("hero.png", "hero-v2.png"), x: 5.0, y: 0, w: 5.0, h: 5.625, sizing: { type: "cover", w: 5.0, h: 5.625 }, objectName: "hero" });
  text(s, "概念渲染图，非实物（量产 BOM 按注塑壳计）", { x: 5.15, y: 5.3, w: 4.5, h: 0.25, fontSize: 9, color: C.text2 });
  s.addText([{ text: "一个人，", options: { breakLine: true } }, { text: "指挥十个 AI" }], { placeholder: "title" });
  s.addText([
    { text: "跨所有 agent 的 Codex Micro，", options: { breakLine: true } },
    { text: "外加高危操作的物理二次确认", options: { breakLine: true } },
    { text: "单款主力机 ¥499 / $99（早鸟 ¥399 / $79）", options: { fontSize: 12.5, color: C.text1, breakLine: true } },
    { text: "AgentDeck（暂名，商标【待核实】）· 天使轮 · 2026.11", options: { color: C.accent1, fontSize: 11.5 } },
  ], { placeholder: "body" });
  s.addNotes("各位好，我们在做 AgentDeck（暂名，路演前将完成改名与商标核查）。OpenAI 两百三十美元的控制器十二小时卖光，但只管自家。我们做九十九美元、四百九十九元跨海内外生态的物理调度台，把高危命令的最后确认放到实体按键上。");
}

// 2 问题
{
  const s = add("问题与验证");
  title(s, "瓶颈不再是模型，而是人的注意力");
  const stats = [
    ["59%", "开发者已在用 coding agent", "Stack Overflow 2026-04 Pulse", C.accent3],
    ["33%", "agent 用户同时开多个 agent 并行", "同上，n=1,100", C.accent1],
    ["86.4%", "危险操作被人工审查漏放（97% 提示盲批，仅拦 13.6%）", "Anthropic auto mode 研究，n=1,053", C.accent4],
  ];
  stats.forEach(([n, l, src, col], i) => {
    const x = 0.5 + i * 3.05;
    card(s, x, 1.25, 2.85, 2.2, "stat" + i);
    text(s, n, { x: x + 0.22, y: 1.38, w: 2.45, h: 0.9, fontSize: 44, bold: true, color: col });
    text(s, l, { x: x + 0.22, y: 2.32, w: 2.45, h: 0.65, fontSize: 13 });
    text(s, src, { x: x + 0.22, y: 3.02, w: 2.45, h: 0.3, fontSize: 9.5, color: C.text2 });
  });
  text(s, [
    { text: "Claude Code 年化收入破 $25 亿（官方）· Cursor 破 $40 亿（创投报道）——多开并行已成主流刚需", options: { bold: true, fontSize: 13, color: C.accent1, breakLine: true } },
    { text: "“The bottleneck increasingly isn't Claude's speed — it's the human noticing that Claude is waiting.” — anthropics/claude-code #36885", options: { italic: true, fontSize: 12.5, color: C.text2 } },
  ], { x: 0.5, y: 3.75, w: 9.0, h: 1.15, paraSpaceAfter: 6 });
  source(s, "来源：stackoverflow.blog 2026-05-27；anthropic.com/research/claude-code-auto-mode；Anthropic Series G 公告；Dealroom");
  s.addNotes("今天接近六成开发者已在用编程智能体，其中三分之一同时开好几个。痛点不在模型慢，而在人顾不过来：既不知道谁卡住了在等你，又在频繁弹窗里盲批了百分之九十七的请求，漏掉百分之八十六点四的危险操作。人成了新的系统瓶颈。");
}

// 3 需求已被验证
{
  const s = add("问题与验证");
  title(s, "四家大厂五个月内验证了这门生意");
  const rows = [
    ["OpenAI × Work Louder", "2026-07 · Codex Micro，$230，约 12 小时售罄（实测无内置麦克风、无屏幕、仅支持 Codex）", C.accent2],
    ["Anthropic", "2026-05 · 官方开源 claude-desktop-buddy（BLE 批准键，约 2.7k stars，仅支持 Claude 桌面端）", C.accent1],
    ["Logitech", "2026-09 · MX Keypad，$99.99，9 键 LCD 硅胶薄膜键，原生宣传支持 Copilot / Claude Code / Codex", C.accent3],
    ["Ulanzi 优篮子", "2026-09 · AU05 Vibe Key ¥269–299（带麦无屏，通用映射）；D200 商店已免费上架同名插件 AgentDeck", C.accent4],
  ];
  rows.forEach(([who, what, col], i) => {
    const y = 1.2 + i * 0.88;
    dot(s, 0.5, y + 0.1, col, String(i + 1), "row" + i);
    text(s, who, { x: 1.12, y, w: 2.35, h: 0.62, fontSize: 15, bold: true, valign: "middle" });
    text(s, what, { x: 3.55, y, w: 5.95, h: 0.62, fontSize: 13, color: C.text2, valign: "middle" });
  });
  text(s, "结论：需求已被巨头真金白银证道；罗技 $99.99 与优篮子 ¥269–598 划定了海内外定价锚点。", { x: 0.5, y: 4.76, w: 9.0, h: 0.32, fontSize: 13, bold: true, color: C.accent1 });
  source(s, "来源：Fortune 2026-07-27；PCMag/CNET 实测；github.com/anthropics/claude-desktop-buddy；9to5Mac 2026-09-08；ulanzi.com AU05 / D200");
  s.addNotes("这门生意不需要我们教育市场。今年五到九月，OpenAI 的控制器十二小时售罄，Anthropic 官方开源蓝牙审批键拿下两千七百星，罗技刚发九十九块九毛九的屏幕键盘，优篮子也上了语音键和同名插件。大厂已验证需求，也定了百美元价格锚。");
}

// 4 机会
{
  const s = add("问题与验证");
  title(s, "百美元内没人兼顾跨生态与物理把关");
  const cols = [
    ["Codex Micro", "只管 OpenAI Codex", "无内置麦克风 · 无屏 · $230", false],
    ["Claude Buddy", "支持 Claude 桌面端（含内部 Claude Code / Cowork）", "锁死 Anthropic 生态 · 仅 2 键", false],
    ["MX Keypad", "9 屏键，支持 Copilot / Claude Code / Codex（开放 SDK）", "硅胶薄膜键 · 无麦 · 不管国产与高危闸门 · $99.99", false],
    ["AgentDeck（暂名）", "中枢已实现 Claude Code / Codex 钩子（真会话【待实测】）；国产与云端在路线图", "长条屏 + 机械键 + 板载麦 + 高危二次确认 · $99 / ¥499", true],
  ];
  cols.forEach(([n, a, b, ours], i) => {
    const x = 0.5 + i * 2.28;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.25, w: 2.12, h: 3.3, rectRadius: 0.08,
      fill: { color: ours ? C.accent1 : C.background2 }, line: { color: ours ? C.accent1 : C.background2 }, objectName: "col" + i });
    const fg = ours ? C.background1 : C.text1;
    text(s, n, { x: x + 0.15, y: 1.42, w: 1.82, h: 0.42, fontSize: 14.5, bold: true, color: fg });
    text(s, a, { x: x + 0.15, y: 1.98, w: 1.82, h: 1.35, fontSize: 12.5, color: fg });
    text(s, b, { x: x + 0.15, y: 3.42, w: 1.82, h: 0.98, fontSize: 11, color: ours ? C.background1 : C.text2 });
  });
  text(s, "另：VibeKeys ($99) 虽接钩子推状态但无分格屏与高危闸门；百美元内尚无单品兼顾跨生态、防串窗直答与高危物理确权。", { x: 0.5, y: 4.72, w: 9.0, h: 0.42, fontSize: 13, bold: true, color: C.accent1 });
  s.addNotes("但百美元内还没有全能款：OpenAI 和 Anthropic 只管自家，罗技用薄膜键、没麦克风也不拦高危命令。我们中枢已写好 Claude 和 Codex 钩子代码，下一步跑通真实会话，并扩展云端任务和国产工具，把跨生态、语音和高危确认合一。");
}

// 5 产品
{
  const s = add("产品");
  title(s, "$99单品：长条屏配机械键与对讲麦");
  s.addImage({ path: IMG("desk-setup.png", "desk-v2.png"), x: 0.5, y: 1.2, w: 5.0, h: 2.85, sizing: { type: "cover", w: 5.0, h: 2.85 }, objectName: "desk" });
  const feats = [
    ["3.2–3.5\" 长条屏 + 6 矮轴灯键", "6 等分对齐显示谁在跑、谁在等，一按切窗口；P1 接入云端异步任务槽", C.accent1],
    ["✓ / ✗ 机械大键", "走官方钩子直答批准请求，不往窗口盲打字，高危命令强制二次确认", C.accent2],
    ["按住说话（板载 MEMS 麦）", "样机配板载麦；中枢已实现说话期间焦点守护（真机听写【待实测】）", C.accent3],
    ["截图 · Ctrl · 金属滚轮", "截图发当前会话；Ctrl 发常用指令模板；右侧金属滚轮翻会话", C.accent5],
  ];
  feats.forEach(([h, d, col], i) => {
    const y = 1.2 + i * 0.82;
    s.addShape(pres.shapes.OVAL, { x: 5.75, y: y + 0.08, w: 0.22, h: 0.22, fill: { color: col }, line: { color: col }, objectName: "f" + i });
    text(s, h, { x: 6.1, y, w: 3.4, h: 0.3, fontSize: 13.5, bold: true });
    text(s, d, { x: 6.1, y: y + 0.3, w: 3.4, h: 0.46, fontSize: 11, color: C.text2 });
  });
  text(s, "概念渲染图，非实物（v1 量产按注塑壳计，USB-C 有线不开蓝牙；已选微雪 $30 同款 3.49\" 开发板搭手板）", { x: 0.5, y: 4.18, w: 5.1, h: 0.55, fontSize: 9.5, color: C.text2 });
  s.addNotes("硬件前十八个月死守这一款：上方三点五寸长条屏六等分对齐六颗机械会话键，下方是批准、拒绝和按住说话三颗大键，只走有线省掉无线认证。画面目前是概念渲染图；我们已选好微雪三十美元同规格开发板，下一步搭出彩屏真机手板并测试板载麦克风。");
}

// 6 技术：怎么做到
{
  const s = add("产品");
  title(s, "走官方钩子直答，绝不往窗口盲打字");
  const steps = [
    ["双钩子拦截", "PermissionRequest 直答 + PreToolUse 高危闸门（v1.4 已实现）", C.accent3],
    ["本地中枢", "解析原始命令做三档分级，长条屏 / 置顶浮窗显示真实命令", C.accent1],
    ["物理按 ✓ / ✗", "低危单击放行；高危按两次才放行；curl|sh 极危锁死禁放", C.accent2],
    ["回退与审计", "中枢离线低危照常放行、高危拦截或退回原生提示；哈希链审计", C.accent5],
  ];
  steps.forEach(([h, d, col], i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 1.3, 2.05, 2.25, "step" + i);
    dot(s, x + 0.2, 1.48, col, String(i + 1), "sd" + i);
    text(s, h, { x: x + 0.2, y: 2.02, w: 1.7, h: 0.38, fontSize: 14, bold: true });
    text(s, d, { x: x + 0.2, y: 2.45, w: 1.7, h: 0.98, fontSize: 11.5, color: C.text2 });
    if (i < 3) s.addText("›", { isTextBox: true, x: x + 2.05, y: 2.15, w: 0.25, h: 0.4, fontSize: 22, color: C.text2, align: "center", margin: 0 });
  });
  text(s, [
    { text: "不会批错窗口：", options: { bold: true, color: C.accent1 } },
    { text: "请求带唯一 ID 绑定队首会话（设备端 shown_nonce 随机数校验已设计、待手板实现）。", options: { breakLine: true } },
    { text: "只加不减也安全：", options: { bold: true, color: C.accent1 } },
    { text: "高危闸门确认后交回 agent 原生规则继续判断，不覆盖 deny；故障一律安全回退。" },
  ], { x: 0.5, y: 3.82, w: 9.0, h: 1.0, fontSize: 13, paraSpaceAfter: 4 });
  s.addNotes("普通宏键盘靠往当前窗口盲敲回车，焦点一偏就批错库。我们走官方钩子协议直回结果，已在本地中枢与转发进程验证：低危单击过，高危强推按两次，极危管道脚本直接锁死，中枢掉线只拦高危不锁日常操作。下一步补齐设备端随机数校验和真实会话联调。");
}

// 7 进展
{
  const s = add("产品");
  title(s, "中枢链路已跑通，8周补齐真机验证");
  const items = [
    ["已完成（真机 / 进程实测）", [
      "宏键盘按键与 Windows 隔离（WinUSB 直读），不误打字（组合键回放 10/10）",
      "早期验证屏：ESP32 + 1602 字符屏跑通状态机；另有虚拟 v2 设备窗口与 3.49\" 固件草稿",
      "中枢 v1.4：钩子直答、三档风险、PreToolUse 高危闸门、哈希链审计、热键与置顶浮窗",
      "离线测试：中枢 264 项单测 + 12 项回放自检全通；转发进程与 F19/F20 热键实测通过（真会话【待实测】）",
    ], C.accent2],
    ["下一步：交割前 8 周验证硬门槛（D7）", [
      "Win + macOS 真实 Claude Code / Codex 会话 5 天 0 错批、p95 < 300ms",
      "Qwen Code、CodeBuddy、Kimi、Trae 钩子实测录屏（≥ 2 家直答；Kimi 仅通知）",
      "30–50 名重度用户用现有设备试用：目标 D14 留存 ≥ 40%、日均 ≥ 20 次按键",
      "2–3 家深圳工厂书面报价（1 万台裸 BOM ≤ ¥176）；$1 / ¥9.9 订金 ≥ 300 人（CAC ≤ ¥60）",
    ], C.accent1],
  ];
  items.forEach(([h, list, col], i) => {
    const x = 0.5 + i * 4.6;
    card(s, x, 1.25, 4.4, 3.7, "prog" + i);
    text(s, h, { x: x + 0.22, y: 1.38, w: 3.96, h: 0.4, fontSize: 16, bold: true, color: col });
    s.addText(list.map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < list.length - 1 } })),
      { isTextBox: true, x: x + 0.22, y: 1.86, w: 3.96, h: 2.95, fontSize: 12, color: C.text1, valign: "top", paraSpaceAfter: 6, margin: 0 });
  });
  s.addNotes("看真实进度：键盘 WinUSB 隔离、字符屏、中枢二百六十四项单测和十二项回放全通，热键与高危闸门也跑通进程实测。下一步八周完成五项验证：双端真会话零错批、国产钩子实测、三十人两周留存、深圳工厂报价及早鸟订金测试。");
}

// 8 真实截图
{
  const s = add("产品");
  title(s, "真实运行截图：四档风控实测跑通");
  s.addImage({ path: path.join(ROOT, "concept", "overlay-demo-真实截图.png"), x: 0.5, y: 1.2, w: 3.1, h: 3.24, objectName: "shot" });
  text(s, "中枢置顶浮窗（真实截图，非渲染）：6 个会话状态 + 待处理高危闸门", { x: 0.5, y: 4.5, w: 3.4, h: 0.5, fontSize: 10, color: C.text2 });
  const rows = [
    ["pytest -q", "低风险", "按一下 ✓（F19）→ 批准放行", C.accent2],
    ["git push --force origin main", "高风险", "按一下提示再按一次，两下才放行", C.accent1],
    ["curl … | sh", "极危", "设备上锁死禁放，立即退回终端原生确认", C.accent4],
    ["kubectl delete deploy api", "高危闸门", "PreToolUse 拦截拒绝（进程实测已通，真 auto mode 会话【待实测】）", C.accent3],
  ];
  rows.forEach(([cmd, tier, res, col], i) => {
    const y = 1.22 + i * 0.85;
    card(s, 4.15, y, 5.35, 0.74, "r" + i);
    s.addShape(pres.shapes.OVAL, { x: 4.32, y: y + 0.27, w: 0.2, h: 0.2, fill: { color: col }, line: { color: col }, objectName: "rd" + i });
    text(s, cmd, { x: 4.62, y: y + 0.08, w: 3.4, h: 0.28, fontSize: 12, bold: true });
    text(s, tier + "：" + res, { x: 4.62, y: y + 0.38, w: 4.78, h: 0.3, fontSize: 10.5, color: C.text2 });
  });
  text(s, "用真实系统热键（F19 / F20）驱动真实中枢与转发进程（演示模式喂入事件）；真实 Claude / Codex 会话联调是下一步。", { x: 4.15, y: 4.68, w: 5.35, h: 0.45, fontSize: 10.5, color: C.text2 });
  s.addNotes("这是 Windows 真机跑通的浮窗截图，用真实系统热键驱动：跑测试单击放行；强推双按放行；远程脚本锁死回退；删生产部署由高危闸门拦截拒绝。进程链路已全部验证；下一步接入真实 Claude、Codex 及自动模式会话。");
}

// 9 市场
{
  const s = add("市场与竞争");
  title(s, "市场测算：硬件保造血，软件拓上限");
  const tiers = [
    ["TAM", "$8.7 亿", "全球 2,200 万职业开发者 × 40% 用 agent × $99", 1.0],
    ["SAM", "$2.9 亿", "同时跑多个 agent 的 33% 开发者（约 290 万人）", 0.6],
    ["SOM", "$144–431 万", "全球 3 年硬件：1.45–4.36 万台（约 ¥1,022–3,060 万）", 0.3],
  ];
  tiers.forEach(([k, v, d, f], i) => {
    const y = 1.2 + i * 0.98;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.5, y, w: 5.0 * f, h: 0.82, rectRadius: 0.06,
      fill: { color: [C.accent3, C.accent1, C.accent2][i] }, line: { color: [C.accent3, C.accent1, C.accent2][i] }, objectName: "tier" + i });
    text(s, k, { x: 0.65, y: y + 0.06, w: 1.2, h: 0.7, fontSize: 17, bold: true, color: C.background1, valign: "middle" });
    text(s, v, { x: 5.7, y, w: 2.0, h: 0.42, fontSize: 19, bold: true });
    text(s, d, { x: 5.7, y: y + 0.42, w: 3.8, h: 0.38, fontSize: 11, color: C.text2 });
  });
  card(s, 0.5, 4.18, 9.0, 0.9, "cn");
  text(s, [
    { text: "中国独立测算（940 万广义口径）：TAM 约 ¥16.4 亿，SAM 约 ¥3.3 亿，3 年 SOM 0.33–0.99 万台（¥165–494 万）；", options: { breakLine: true } },
    { text: "全球 + 中国 3 年硬件 SOM 合计约 1.8–5.4 万台、¥1,200–3,550 万（1 USD = 7.1 CNY，软件另计）", options: { bold: true, color: C.accent1 } },
    { text: " —— 硬件自造血卡位桌面，跨端软件与企业网关拓上限。", options: { color: C.text2 } },
  ], { x: 0.68, y: 4.24, w: 8.65, h: 0.78, fontSize: 11.5, valign: "middle" });
  source(s, "【估算】最敏感假设为多 agent 占比 33%（n=1,100）；口径见 01-市场调研.md；人口来自 JetBrains 2026、工信部 2024-12");
  s.addNotes("市场我们按窄口径克制估算：全球加中国三年硬件可得市场约一点八到五点四万台，约一千二百到三千五百五十万元。硬件不是天花板，而是帮团队自造血、卡位重度用户桌面的抓手；下一步靠跨端软件与企业权限网关打开上限。");
}

// 10 竞争格局
{
  const s = add("市场与竞争");
  title(s, "直面罗技$99：赢在语音与高危把关");
  const X0 = 1.35, Y0 = 1.2, W = 5.35, H = 3.65;
  s.addShape(pres.shapes.LINE, { x: X0, y: Y0 + H / 2, w: W, h: 0, line: { color: HEX.grid, width: 1.5 }, objectName: "ax" });
  s.addShape(pres.shapes.LINE, { x: X0 + W / 2, y: Y0, w: 0, h: H, line: { color: HEX.grid, width: 1.5 }, objectName: "ay" });
  text(s, "锁死单一厂商", { x: X0, y: Y0 + H + 0.06, w: 2.0, h: 0.3, fontSize: 10.5, color: C.text2 });
  text(s, "跨多家 agent", { x: X0 + W - 2.0, y: Y0 + H + 0.06, w: 2.0, h: 0.3, fontSize: 10.5, color: C.text2, align: "right" });
  text(s, "钩子直答 +\n高危把关 +\n板载语音", { x: 0.28, y: Y0, w: 1.0, h: 0.85, fontSize: 10, color: C.text2 });
  text(s, "仅看状态 /\n快捷键映射", { x: 0.28, y: Y0 + H - 0.65, w: 1.0, h: 0.65, fontSize: 10, color: C.text2 });
  const pts = [
    ["Codex Micro", 0.18, 0.56, C.accent5],
    ["Claude Buddy", 0.12, 0.36, C.accent5],
    ["Keychron F4", 0.55, 0.86, C.accent5],
    ["Vibe Key (AU05)", 0.56, 0.72, C.accent5],
    ["Ulanzi D200+插件", 0.66, 0.56, C.accent5],
    ["MX Keypad", 0.58, 0.44, C.accent5],
    ["VibeKeys Max", 0.72, 0.34, C.accent5],
    ["AgentDeck（暂名）", 0.76, 0.12, C.accent1],
  ];
  pts.forEach(([n, fx, fy, col], i) => {
    const x = X0 + fx * W, y = Y0 + fy * H;
    s.addShape(pres.shapes.OVAL, { x: x - 0.08, y: y - 0.08, w: 0.16, h: 0.16, fill: { color: col }, line: { color: col }, objectName: "p" + i });
    text(s, n, { x: x + 0.11, y: y - 0.14, w: 1.45, h: 0.28, fontSize: 10.5, bold: col === C.accent1, color: col === C.accent1 ? C.accent1 : C.text1 });
  });
  text(s, [
    { text: "正面对标罗技与优篮子", options: { bold: true, color: C.accent1, breakLine: true } },
    { text: "MX Keypad（$99.99）与 D200（¥298–598，含免费同名插件）均为硅胶薄膜键、无板载麦、无高危闸门；AU05（¥269–299）带麦但无屏幕。", options: { breakLine: true } },
    { text: "我们定 $99 / ¥499（早鸟 $79 / ¥399），一次集齐 6 等分屏、机械大键、板载麦与高危二次确认。", options: { color: C.text2 } },
  ], { x: 6.95, y: 1.3, w: 2.55, h: 3.6, fontSize: 12, paraSpaceAfter: 8 });
  s.addNotes("海外最直接的对手是九十九块九毛九的罗技屏幕键盘，国内是优篮子两百六十九起的语音键和带免费插件的屏幕控台。我们定价九十九美元和四百九十九元正面对标，靠机械大键、高危双按锁死抢差异化；下一步补齐板载麦克风、国产工具和云端槽位。");
}

// 11 商业模式
{
  const s = add("商业模式");
  title(s, "免费软件拉新，单款硬件加两层订阅");
  card(s, 0.5, 1.2, 3.1, 2.45, "sku");
  text(s, "前 18 个月唯一硬件 SKU", { x: 0.68, y: 1.32, w: 2.75, h: 0.32, fontSize: 13, color: C.text2 });
  text(s, "¥499 / $99", { x: 0.68, y: 1.68, w: 2.75, h: 0.55, fontSize: 28, bold: true, color: C.accent1 });
  text(s, "众筹早鸟 ¥399 / $79", { x: 0.68, y: 2.28, w: 2.75, h: 0.28, fontSize: 12 });
  text(s, "砍掉 Lite、推迟 Pro；卡在罗技 $99.99 内，约为 Codex Micro $230 的 43%（删去优篮子 OEM 假设）", { x: 0.68, y: 2.62, w: 2.75, h: 0.9, fontSize: 10.5, color: C.text2 });
  s.addImage({ path: IMG("topdown.png", "topdown-v2.png"), x: 3.8, y: 1.2, w: 5.7, h: 2.35, sizing: { type: "contain", w: 5.7, h: 2.35 }, objectName: "top" });
  text(s, "概念渲染图，非实物（量产按注塑壳计）", { x: 3.8, y: 3.58, w: 4.2, h: 0.22, fontSize: 9, color: C.text2 });
  const sw = [
    ["免费软件（获客漏斗）", "现支持 F13–F24 热键 + 置顶浮窗接入存量键盘；Stream Deck / D200 按键屏原生插件下一步开发"],
    ["个人 Pro ¥19/月 · $3.99", "懂代码仓库符号的语音纠错、手机只读看板、云端 agent 状态桥接（2028-01 随交付上线）"],
    ["Team ¥39–59/人/月", "飞书/企微/钉钉/Okta SSO、合规仪表盘、私有化部署、MCP 工具白名单（2028-Q3 试点）"],
  ];
  sw.forEach(([h, d], i) => {
    const x = 0.5 + i * 3.05;
    text(s, h, { x, y: 3.9, w: 2.9, h: 0.32, fontSize: 13.5, bold: true, color: C.accent2 });
    text(s, d, { x, y: 4.24, w: 2.9, h: 0.72, fontSize: 11, color: C.text2 });
  });
  source(s, "【估算】硬件接近 1 万台/年采购规模盈利（1k 档亏损）；订阅毛利率估 >80%，详见 08-商业模式与财务.md");
  s.addNotes("商业模式分三层：免费软件现已支持热键加浮窗免驱接入存量键盘，下一步补第三方按键屏插件拉新；单款硬件卖四百九十九元、海外九十九美元；下一步再开十九元个人版代码语音与云桥接，以及企业合规版。硬件毛利待下一步深圳工厂报价确认。");
}

// 12 壁垒
{
  const s = add("商业模式");
  title(s, "硬件6个月可抄，壁垒在适配与风控");
  const m = [
    ["多厂商持续适配层", "每家 agent 钩子与云端接口每月变动，按能力分级适配（Claude/Codex 直答，Qwen/CodeBuddy【待实测】，Kimi 仅通知不阻断）。", C.accent1],
    ["高危操作的物理二次确认", "已实现：三档风险分级、双按确认、哈希链审计，及 auto mode 下也生效的 PreToolUse 闸门（进程实测已通，真实会话【待实测】）。", C.accent2],
    ["工作流与团队策略沉淀（待建）", "常用模板、按键布局、团队策略与审计沉淀在软件和企业部署端；今天为零，随用户量与 Team 版积累。", C.accent3],
    ["中立与国产合作位置", "海外大厂不做支持竞争对手的设备；国内争取非排他联合推广与官方推荐硬件背书（不假设排他）。", C.accent4],
  ];
  m.forEach(([h, d, col], i) => {
    const x = 0.5 + (i % 2) * 4.6, y = 1.25 + Math.floor(i / 2) * 1.85;
    card(s, x, y, 4.4, 1.65, "moat" + i);
    dot(s, x + 0.2, y + 0.2, col, String(i + 1), "md" + i);
    text(s, h, { x: x + 0.78, y: y + 0.22, w: 3.45, h: 0.4, fontSize: 15.5, bold: true });
    text(s, d, { x: x + 0.2, y: y + 0.72, w: 4.0, h: 0.85, fontSize: 11.5, color: C.text2 });
  });
  s.addNotes("我们坦承硬件外壳六个月就能被抄，壁垒绝不在模具。目前已做出跨工具三档风控、高危闸门和哈希链审计；下一步要深挖三道护城河：一是每月跟着各家接口改版持续维护的适配层，二是按用户量沉淀的工作流模板，三是与国产智能体厂商共建生态。");
}

// 13 路线图
{
  const s = add("计划与融资");
  title(s, "订金满1500才开模，每步先验再花");
  const ms = [
    ["2027-01", "验证达标，首期 ¥250 万到账，软件公测"],
    ["2027-07", "付费订金 ≥ 1,500（$1/¥9.9）→ 8 月开模"],
    ["2027-09", "众筹上线；周活 ≥ 2,000，二期 ¥250 万到账"],
    ["2028-01", "交付众筹 1,500 台；个人 Pro 同步上线"],
    ["2028-03", "天猫 / 京东 / 独立站零售；Q3 Team 试点"],
    ["2029-Q4", "首季经营利润转正；30-05 持续转正"],
  ];
  s.addShape(pres.shapes.LINE, { x: 0.7, y: 2.32, w: 8.6, h: 0, line: { color: HEX.grid, width: 2 }, objectName: "tl" });
  ms.forEach(([q, d], i) => {
    const x = 0.5 + i * 1.5;
    s.addShape(pres.shapes.OVAL, { x: x + 0.12, y: 2.2, w: 0.24, h: 0.24, fill: { color: i < 2 ? C.accent2 : C.accent1 }, line: { color: i < 2 ? C.accent2 : C.accent1 }, objectName: "m" + i });
    text(s, q, { x, y: 1.58, w: 1.4, h: 0.4, fontSize: 13.5, bold: true });
    text(s, d, { x, y: 2.6, w: 1.4, h: 1.15, fontSize: 11.5, color: C.text2 });
  });
  card(s, 0.5, 4.0, 9.0, 0.88, "rule");
  text(s, "止损铁律：2027-07 全球付费订金（海外 $1 + 国内 ¥9.9）不到 1,500 人就不开模、不众筹，第二期不到账，公司带着约 ¥150–160 万转为纯软件，订金测试仅投 ¥6.4 万。",
    { x: 0.7, y: 4.06, w: 8.6, h: 0.76, fontSize: 12.5, valign: "middle" });
  s.addNotes("硬件创业最怕盲目压货，我们下一步严格按里程碑花钱：明年初首期款到账先公测免费软件；七月攒够一千五百个付费早鸟订金才花十二万开模；九月软件周活过两千且众筹达标才触发二期款。万一订金不达标就停开模转纯软件，留住约一百五十到一百六十万现金。");
}

// 14 财务
{
  const s = add("计划与融资");
  title(s, "财务预测：一轮钱活到盈亏平衡");
  s.addChart(pres.charts.BAR, [{ name: "收入（万元）", labels: ["2027", "2028", "2029", "2030"], values: [0, 346.0, 697.3, 1005.0] }], {
    x: 0.5, y: 1.18, w: 5.4, h: 3.62, barDir: "col", chartColors: [HEX.amber],
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: HEX.text, dataLabelFontSize: 11.5, dataLabelFontFace: "+mn-lt", dataLabelFormatCode: "0.0",
    showTitle: true, title: "年度收入（万元｜软件：28年14.6 · 29年61.7 · 30年144.3）", titleColor: HEX.text, titleFontSize: 10.5, titleFontFace: "+mn-lt",
    catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
    valGridLine: { color: HEX.grid, size: 0.5 }, catGridLine: { style: "none" }, showLegend: false,
  });
  const kv = [
    ["18,500 台", "2027–2029 三年销量（累计收入 ¥1,043.3 万）"],
    ["2029 Q4", "旺季首季转正（+¥9.6万），2030-05 持续盈利"],
    ["¥35.5 万", "现金最低点（2029-10），不依赖 Pre-A"],
  ];
  kv.forEach(([v, k], i) => {
    const y = 1.22 + i * 1.15;
    card(s, 6.15, y, 3.35, 1.0, "kv" + i);
    text(s, v, { x: 6.35, y: y + 0.08, w: 3.0, h: 0.48, fontSize: 21, bold: true, color: C.accent1 });
    text(s, k, { x: 6.35, y: y + 0.56, w: 3.0, h: 0.36, fontSize: 11, color: C.text2 });
  });
  source(s, "【假设】BOM 尚无工厂书面报价（1 万台产品毛利率估国内 38% / 海外 52%，合格线裸 BOM ≤ ¥176）；2030 为延伸年；3 创始人低薪 ¥1.2 万/月是前提。见 08");
  s.addNotes("财务模型的核心是一轮钱活到盈亏平衡，不赌下一轮。按模型估算，三年卖一万八千五百台，二九年四季度首季转正，三零年五月起月度持续盈利，现金低点剩三十五点五万。前提是创始人锁死一万二低薪；下一步拿深圳工厂报价核实成本。");
}

// 15 融资
{
  const s = add("计划与融资");
  title(s, "天使轮融500万，按里程碑分两期");
  text(s, [
    { text: "¥500 万", options: { fontSize: 42, bold: true, color: C.accent1, breakLine: true } },
    { text: "投后估值 ¥2,500 万 · 出让 20%（推荐方案 B）", options: { fontSize: 15, bold: true, breakLine: true } },
    { text: "第一期 ¥250 万：签约即到账，用于验证、DVT、订金测试及达标后开模（¥12 万）", options: { fontSize: 11.5, color: C.text2, breakLine: true } },
    { text: "第二期 ¥250 万：软件周活 ≥ 2,000 且众筹锁定 ≥ ¥50 万（或全球付费订金 $1 / ¥9.9 合计 ≥ 1,500 人）", options: { fontSize: 11.5, color: C.text2 } },
  ], { x: 0.5, y: 1.25, w: 4.25, h: 2.65, paraSpaceAfter: 6 });
  s.addChart(pres.charts.DOUGHNUT, [{
    name: "资金用途（万元）",
    labels: ["团队 180.9万", "研发打样 50.6万", "模具认证 18.0万", "品牌订金众筹 48.4万", "行政法务商标 45.6万", "带入2029现金 156.5万"],
    values: [180.9, 50.6, 18.0, 48.4, 45.6, 156.5],
  }], {
    x: 4.85, y: 1.1, w: 4.65, h: 3.85, holeSize: 55,
    chartColors: [HEX.amber, HEX.green, HEX.red, HEX.blue, "6B7280", "3A424D"],
    showPercent: true, showValue: false, showLegend: true, legendPos: "r", legendColor: HEX.text, legendFontSize: 10, legendFontFace: "+mn-lt",
    dataLabelColor: "111418", dataLabelFontSize: 9.5, dataLabelFontFace: "+mn-lt",
    showTitle: true, title: "资金用途（合计 ¥500.0 万 / 100%）", titleColor: HEX.text, titleFontSize: 12, titleFontFace: "+mn-lt",
  });
  text(s, "基准情景不需要 Pre-A，加速扩张时再融。（备选方案 A 供加速器/种子轮：当前直接融 ¥200–350 万 / 投后 ¥1,200–1,800 万，配缩减计划，见 08 §7.1）",
    { x: 0.5, y: 4.05, w: 4.25, h: 0.9, fontSize: 11, color: C.text2 });
  s.addNotes("本轮融五百万元，投后两千五百万出让百分之二十，分两期各两百五十万。首期签约到账，下一步用于验证、样机、订金测试及达标后开模；二期锁死在软件周活满两千且众筹满五十万或订金满一千五百人后交割，把盲目开模风险关进笼子。");
}

// 16 风险
{
  const s = add("计划与融资");
  title(s, "主动拆解大厂、自动模式与冷启动");
  const r = [
    ["罗技 $99.99、大厂与免费插件？", "OpenAI、Anthropic 只做自家；罗技与 D200（含免费同名插件）系薄膜键、无板载麦、无高危闸门。我们定 $99 / ¥499 做机械键+板载麦+安全闸门，免费软件兼容对手引流，并改名规避冲突。"],
    ["auto mode 与云端迁移？", "日常命令交给 auto mode；不可逆操作由 PreToolUse 高危闸门再确认（已实现，真会话【待实测】）。6 个槽位下一步扩展接入 Cursor Cloud Agent 与 GitHub PR/CI 阻塞。"],
    ["CtrlVibe 在 Kickstarter 仅 59 人？", "它败在无屏幕且零蓄水冷启动（PledgeBox 仅是履约工具）。我们先攒免费软件周活 ≥ 2,000 与全球付费订金 ≥ 1,500 人（$1 / ¥9.9），达标才开模上众筹。"],
  ];
  r.forEach(([q, a], i) => {
    const y = 1.22 + i * 1.22;
    card(s, 0.5, y, 9.0, 1.08, "risk" + i);
    text(s, q, { x: 0.68, y: y + 0.08, w: 2.95, h: 0.92, fontSize: 14, bold: true, color: C.accent1, valign: "middle" });
    text(s, a, { x: 3.72, y: y + 0.08, w: 5.6, h: 0.92, fontSize: 12, valign: "middle" });
  });
  s.addNotes("主动回应三个顾虑：第一，巨头只管自家，我们做跨生态中立层；第二，自动模式普及后，我们已做出高危闸门专拦不可逆命令，下一步实测真会话并接云端任务；第三，同行众筹败在冷启动，我们下一步先攒两千周活和一千五百订金再开模。");
}

// 17 团队与结尾
{
  const s = add("结尾", "TITLE");
  s.addImage({ path: IMG("desk-setup.png", "desk-v2.png"), x: 5.0, y: 0, w: 5.0, h: 5.625, sizing: { type: "cover", w: 5.0, h: 5.625 }, objectName: "end" });
  text(s, "概念渲染图，非实物", { x: 5.15, y: 5.3, w: 3, h: 0.25, fontSize: 9, color: C.text2 });
  s.addText([{ text: "每个开发者，", options: { breakLine: true } }, { text: "都带一支 AI 团队" }], { placeholder: "title" });
  s.addText([
    { text: "创始团队已独立跑通底层隔离与双钩子风控中枢", options: { breakLine: true } },
    { text: "众筹成功前精简 4–5 人 · 首招深圳量产经验结构 / 供应链工程师", options: { fontSize: 13.5, color: C.accent1, breakLine: true } },
    { text: "【创始人履历、分工与联系方式待补充】", options: { fontSize: 12, color: C.text2 } },
  ], { placeholder: "body" });
  s.addNotes("最后是团队：创始团队亲手跑通了底层 USB 隔离、焦点仲裁与双钩子风控中枢。我们坦承目前零量产履历，下一步首期到账第一件事，就是全职招入深圳资深结构与供应链工程师。团队成员实名背景与联系方式由创始人补充后外发。谢谢！");
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
