// AgentDeck 天使轮 BP 生成脚本：node build_bp.js
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const ROOT = path.resolve(__dirname, "..");
const IMG = (n) => path.join(ROOT, "concept", n);
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
pres.title = "AgentDeck 天使轮融资";
pres.author = "AgentDeck";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

pres.defineSlideMaster({
  title: "TITLE",
  background: { color: HEX.bg },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 1.2, w: 4.6, h: 1.6,
      fontSize: 36, bold: true, color: C.text1, valign: "bottom", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.6, y: 2.95, w: 4.6, h: 1.4,
      fontSize: 16, color: C.text2, valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: HEX.bg },
  margin: [0.5, 0.5, 0.45, 0.5],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.3, w: 9.0, h: 0.7,
      fontSize: 26, bold: true, color: C.text1, valign: "middle", margin: 0 }, text: "" } },
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
function source(s, t) { text(s, t, { x: 0.5, y: 5.2, w: 8.5, h: 0.3, fontSize: 9, color: C.text2 }); }

// 1 封面
{
  const s = add("开场", "TITLE");
  s.addImage({ path: IMG("hero.png"), x: 5.0, y: 0, w: 5.0, h: 5.625, sizing: { type: "cover", w: 5.0, h: 5.625 }, objectName: "hero" });
  s.addText("一个人，指挥十个 AI", { placeholder: "title" });
  s.addText([
    { text: "AgentDeck：跨所有 agent 的实体遥控器", options: { breakLine: true } },
    { text: "天使轮融资 · 2026 年 11 月", options: { color: C.accent1 } },
  ], { placeholder: "body" });
  s.addNotes("开场一句话：Codex Micro 证明了开发者愿意为 agent 遥控器买单，但它只服务 Codex。我们做的是跨所有 agent、国内能用、更便宜的那一个。");
}

// 2 问题
{
  const s = add("问题与验证");
  title(s, "瓶颈不再是模型，而是人");
  const stats = [
    ["59%", "开发者已在用 coding agent", "Stack Overflow 2026-04 Pulse", C.accent3],
    ["1/3", "agent 用户同时开多个 agent", "同上，n=1,100", C.accent1],
    ["97%", "权限提示被直接批准，多数没细看", "Anthropic auto mode 博文", C.accent4],
  ];
  stats.forEach(([n, l, src, col], i) => {
    const x = 0.5 + i * 3.05;
    card(s, x, 1.25, 2.85, 2.2, "stat" + i);
    text(s, n, { x: x + 0.25, y: 1.4, w: 2.4, h: 0.95, fontSize: 48, bold: true, color: col });
    text(s, l, { x: x + 0.25, y: 2.4, w: 2.4, h: 0.6, fontSize: 14 });
    text(s, src, { x: x + 0.25, y: 3.0, w: 2.4, h: 0.3, fontSize: 10, color: C.text2 });
  });
  text(s, [
    { text: "“The bottleneck increasingly isn't Claude's speed — it's the human noticing that Claude is waiting.”", options: { italic: true, breakLine: true } },
    { text: "— anthropics/claude-code issue #36885", options: { fontSize: 11, color: C.text2 } },
  ], { x: 0.5, y: 3.75, w: 9.0, h: 1.0, fontSize: 15 });
  source(s, "来源：stackoverflow.blog 2026-05-27；anthropic.com/research/claude-code-auto-mode；thenewstack.io/claude-code-auto-mode");
}

// 3 需求已被验证
{
  const s = add("问题与验证");
  title(s, "大厂已经替我们验证了需求");
  const rows = [
    ["OpenAI × Work Louder", "Codex Micro，$230，12 小时售罄，eBay 炒到 $450–1,850", C.accent2],
    ["Anthropic", "官方开源 claude-desktop-buddy（BLE 实体批准键），2.7k stars", C.accent1],
    ["Logitech", "2026-10 发布面向开发者的 MX Keypad（9 个屏幕键）", C.accent3],
    ["Ulanzi × 腾讯", "国内 Vibe Key ¥269–299，6 键 + 旋钮 + 麦克风", C.accent4],
  ];
  rows.forEach(([who, what, col], i) => {
    const y = 1.25 + i * 0.9;
    dot(s, 0.5, y + 0.12, col, String(i + 1), "row" + i);
    text(s, who, { x: 1.15, y, w: 2.4, h: 0.65, fontSize: 16, bold: true, valign: "middle" });
    text(s, what, { x: 3.6, y, w: 5.9, h: 0.65, fontSize: 14, color: C.text2, valign: "middle" });
  });
  source(s, "来源：fortune.com 2026-07-27；github.com/anthropics/claude-desktop-buddy；YouTube MX Keypad 2026-10-15；InfoQ Vibe Key 评测");
}

// 4 机会
{
  const s = add("问题与验证");
  title(s, "但每一家都只服务自己的 agent");
  const cols = [
    ["Codex Micro", "只管 Codex", "闭源 · 无麦克风 · $230", false],
    ["Claude Buddy", "只管 Claude 桌面版", "开发者模式 · 2 个键", false],
    ["Vibe Key", "绑定腾讯生态", "无逐会话状态屏", false],
    ["AgentDeck", "Claude · Codex · Cursor · Gemini · Trae · Qwen · Kimi · CodeBuddy", "一台设备管全部", true],
  ];
  cols.forEach(([n, a, b, ours], i) => {
    const x = 0.5 + i * 2.28;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.3, w: 2.1, h: 3.2, rectRadius: 0.08,
      fill: { color: ours ? C.accent1 : C.background2 }, line: { color: ours ? C.accent1 : C.background2 }, objectName: "col" + i });
    const fg = ours ? C.background1 : C.text1;
    text(s, n, { x: x + 0.2, y: 1.5, w: 1.7, h: 0.5, fontSize: 18, bold: true, color: fg });
    text(s, a, { x: x + 0.2, y: 2.15, w: 1.7, h: 1.3, fontSize: 14, color: fg });
    text(s, b, { x: x + 0.2, y: 3.55, w: 1.7, h: 0.8, fontSize: 12, color: ours ? C.background1 : C.text2 });
  });
  text(s, "开发者同时用好几家 agent，没有人做中立的那一层。", { x: 0.5, y: 4.7, w: 9.0, h: 0.4, fontSize: 15, bold: true, color: C.accent1 });
}

// 5 产品
{
  const s = add("产品");
  title(s, "跨所有 agent 的 Codex Micro");
  s.addImage({ path: IMG("desk-setup.png"), x: 0.5, y: 1.2, w: 5.2, h: 2.93, objectName: "desk" });
  const feats = [
    ["6 个会话键", "键上小屏显示谁在跑、谁在等你，一按跳到那个窗口", C.accent1],
    ["✓ / ✗", "直接回答 agent 的批准请求，不往窗口里打字", C.accent2],
    ["按住说话", "语音指令发进当前选中的会话", C.accent3],
    ["截图 · Ctrl · 滚轮", "截图发给 agent；常用指令模板；滚轮翻会话", C.accent5],
  ];
  feats.forEach(([h, d, col], i) => {
    const y = 1.2 + i * 0.75;
    s.addShape(pres.shapes.OVAL, { x: 6.0, y: y + 0.08, w: 0.22, h: 0.22, fill: { color: col }, line: { color: col }, objectName: "f" + i });
    text(s, h, { x: 6.35, y, w: 3.15, h: 0.3, fontSize: 14, bold: true });
    text(s, d, { x: 6.35, y: y + 0.3, w: 3.15, h: 0.42, fontSize: 11, color: C.text2 });
  });
  text(s, "产品渲染图（概念阶段）", { x: 0.5, y: 4.2, w: 5.2, h: 0.3, fontSize: 10, color: C.text2 });
}

// 6 技术：怎么做到
{
  const s = add("产品");
  title(s, "按键直接回答 agent，而不是模拟键盘");
  const steps = [
    ["agent 请求权限", "Claude Code / Codex 的 PermissionRequest 钩子", C.accent3],
    ["本地中枢", "按风险分级，键屏显示真实命令", C.accent1],
    ["你按 ✓ / ✗", "高风险命令要按两次才放行", C.accent2],
    ["agent 继续", "超时或离线自动退回终端原生提示", C.accent5],
  ];
  steps.forEach(([h, d, col], i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 1.35, 2.05, 2.2, "step" + i);
    dot(s, x + 0.2, 1.55, col, String(i + 1), "sd" + i);
    text(s, h, { x: x + 0.2, y: 2.1, w: 1.7, h: 0.4, fontSize: 15, bold: true });
    text(s, d, { x: x + 0.2, y: 2.55, w: 1.7, h: 0.9, fontSize: 12, color: C.text2 });
    if (i < 3) s.addText("›", { isTextBox: true, x: x + 2.05, y: 2.2, w: 0.25, h: 0.4, fontSize: 22, color: C.text2, align: "center", margin: 0 });
  });
  text(s, [
    { text: "不会批错窗口：", options: { bold: true, color: C.accent1 } },
    { text: "请求带 ID，按键只回答屏幕上显示的那一条。", options: { breakLine: true } },
    { text: "失败也安全：", options: { bold: true, color: C.accent1 } },
    { text: "中枢不在、超时或出错时，agent 自动回到自己的确认流程。" },
  ], { x: 0.5, y: 3.85, w: 9.0, h: 0.9, fontSize: 14 });
}

// 7 进展
{
  const s = add("产品");
  title(s, "原型已经跑通核心链路");
  const items = [
    ["已完成", [
      "宏键盘按键与 Windows 隔离（WinUSB 直读），不会误打字",
      "实体状态屏：ESP32 + LCD 显示多个 agent 的状态",
      "Hub v1：本地中枢 + 钩子转发 + 一键安装器，离线测试 51 项通过",
      "真实进程端到端：批准 / 拒绝 / 高风险双按 / 离线回退全部验证",
    ], C.accent2],
    ["下一步", [
      "在真实 Claude Code、Codex 会话中常驻试用",
      "接入 Qwen Code、CodeBuddy 的批准钩子",
      "整屏 + 透明键帽方案打样，拿 3 家工厂报价",
    ], C.accent1],
  ];
  items.forEach(([h, list, col], i) => {
    const x = 0.5 + i * 4.6;
    card(s, x, 1.25, 4.4, 3.6, "prog" + i);
    text(s, h, { x: x + 0.25, y: 1.4, w: 3.9, h: 0.4, fontSize: 18, bold: true, color: col });
    s.addText(list.map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < list.length - 1 } })),
      { isTextBox: true, x: x + 0.25, y: 1.9, w: 3.9, h: 2.8, fontSize: 13, color: C.text1, valign: "top", paraSpaceAfter: 6, margin: 0 });
  });
}

// 8 市场
{
  const s = add("市场与竞争");
  title(s, "市场规模（我们的估算）");
  const tiers = [
    ["TAM", "$9.6 亿", "全球职业开发者 × 用 agent 比例 × 均价", 1.0],
    ["SAM", "$3.2 亿", "同时跑多个 agent 的人", 0.62],
    ["SOM", "$160–470 万", "3 年可拿下：1.4–4.1 万台", 0.3],
  ];
  tiers.forEach(([k, v, d, f], i) => {
    const y = 1.25 + i * 1.05;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.5, y, w: 5.2 * f, h: 0.85, rectRadius: 0.06,
      fill: { color: [C.accent3, C.accent1, C.accent2][i] }, line: { color: [C.accent3, C.accent1, C.accent2][i] }, objectName: "tier" + i });
    text(s, k, { x: 0.65, y: y + 0.08, w: 1.2, h: 0.7, fontSize: 18, bold: true, color: C.background1, valign: "middle" });
    text(s, v, { x: 5.9, y, w: 1.8, h: 0.45, fontSize: 20, bold: true });
    text(s, d, { x: 5.9, y: y + 0.45, w: 3.6, h: 0.4, fontSize: 11, color: C.text2 });
  });
  card(s, 0.5, 4.45, 9.0, 0.65, "cn");
  text(s, "中国单独计算：TAM 约 ¥18 亿，SAM 约 ¥3.6 亿；Codex Micro 未在国内正式销售，国产 agent 没有跨厂商硬件配套。",
    { x: 0.7, y: 4.5, w: 8.6, h: 0.55, fontSize: 12, valign: "middle" });
  source(s, "【估算】口径与算式见 01-市场调研.md；开发者数来自 JetBrains、Stack Overflow 2025–2026");
}

// 9 竞争格局
{
  const s = add("市场与竞争");
  title(s, "我们站在没人占的那一格");
  const X0 = 1.2, Y0 = 1.2, W = 5.6, H = 3.7;
  s.addShape(pres.shapes.LINE, { x: X0, y: Y0 + H / 2, w: W, h: 0, line: { color: HEX.grid, width: 1.5 }, objectName: "ax" });
  s.addShape(pres.shapes.LINE, { x: X0 + W / 2, y: Y0, w: 0, h: H, line: { color: HEX.grid, width: 1.5 }, objectName: "ay" });
  text(s, "绑定单一厂商", { x: X0, y: Y0 + H + 0.05, w: 2, h: 0.3, fontSize: 11, color: C.text2 });
  text(s, "跨所有 agent", { x: X0 + W - 2, y: Y0 + H + 0.05, w: 2, h: 0.3, fontSize: 11, color: C.text2, align: "right" });
  text(s, "逐会话状态", { x: 0.3, y: Y0, w: 0.85, h: 0.6, fontSize: 11, color: C.text2 });
  text(s, "无状态 / 单屏", { x: 0.3, y: Y0 + H - 0.6, w: 0.85, h: 0.6, fontSize: 11, color: C.text2 });
  const pts = [
    ["Codex Micro", 0.2, 0.28, C.accent5], ["Claude Buddy", 0.12, 0.62, C.accent5], ["Vibe Key", 0.3, 0.8, C.accent5],
    ["Keychron F4", 0.6, 0.85, C.accent5], ["VibeKeys", 0.7, 0.62, C.accent5], ["Stream Deck+插件", 0.55, 0.38, C.accent5],
    ["AgentDeck", 0.85, 0.15, C.accent1],
  ];
  pts.forEach(([n, fx, fy, col], i) => {
    const x = X0 + fx * W, y = Y0 + fy * H;
    s.addShape(pres.shapes.OVAL, { x: x - 0.09, y: y - 0.09, w: 0.18, h: 0.18, fill: { color: col }, line: { color: col }, objectName: "p" + i });
    text(s, n, { x: x + 0.12, y: y - 0.15, w: 1.6, h: 0.3, fontSize: 11, bold: col === C.accent1, color: col === C.accent1 ? C.accent1 : C.text1 });
  });
  text(s, [
    { text: "结构性空缺", options: { bold: true, color: C.accent1, breakLine: true } },
    { text: "跨厂商 + 逐会话状态 + 通过钩子安全审批，三者同时具备的产品目前没有。", options: { breakLine: true } },
    { text: "Stream Deck 插件能拼出一部分，但要自己装插件、配钩子，一家一个。", options: { color: C.text2 } },
  ], { x: 7.1, y: 1.4, w: 2.4, h: 3.4, fontSize: 13, paraSpaceAfter: 8 });
}

// 10 商业模式
{
  const s = add("商业模式");
  title(s, "硬件卖钱，软件留人");
  const skus = [
    ["Lite", "¥299 / $59", "无屏键 + RGB 状态灯", C.accent5],
    ["Standard", "¥699 / $129", "整屏透明键帽 · 滚轮 · 麦克风", C.accent1],
    ["Pro", "¥999 / $199", "铝壳 · 蓝牙 · 状态灯环", C.accent3],
  ];
  skus.forEach(([n, p, d, col], i) => {
    const x = 0.5 + i * 2.05;
    card(s, x, 1.25, 1.9, 2.4, "sku" + i);
    text(s, n, { x: x + 0.2, y: 1.4, w: 1.5, h: 0.4, fontSize: 16, bold: true, color: col });
    text(s, p, { x: x + 0.2, y: 1.85, w: 1.6, h: 0.45, fontSize: 15, bold: true });
    text(s, d, { x: x + 0.2, y: 2.4, w: 1.55, h: 1.1, fontSize: 11, color: C.text2 });
  });
  s.addImage({ path: IMG("topdown.png"), x: 6.75, y: 1.25, w: 2.75, h: 1.55, objectName: "top" });
  text(s, "对标 Codex Micro $230：主力款约为其一半价格，并支持全部 agent。", { x: 6.75, y: 2.9, w: 2.75, h: 0.8, fontSize: 11, color: C.text2 });
  const sw = [
    ["免费软件", "驱动任何键盘 / Stream Deck，拉用户"],
    ["Team 订阅 ¥30/人/月", "审批策略、审计日志、团队模板"],
    ["OEM 授权", "把适配层授权给其他硬件厂商"],
  ];
  sw.forEach(([h, d], i) => {
    const x = 0.5 + i * 3.05;
    text(s, h, { x, y: 3.95, w: 2.9, h: 0.35, fontSize: 14, bold: true, color: C.accent2 });
    text(s, d, { x, y: 4.3, w: 2.9, h: 0.5, fontSize: 12, color: C.text2 });
  });
}

// 11 壁垒
{
  const s = add("商业模式");
  title(s, "壁垒不在硬件，在适配层");
  const m = [
    ["多厂商适配层", "每家 agent 的钩子、状态识别、会话定位都不同，且每月在变。国产 CodeBuddy、Qwen Code、Kimi 已有类似钩子。", C.accent1],
    ["安全审批策略", "跨厂商统一的风险分级、双按确认和审计日志，团队版的核心。", C.accent2],
    ["工作流沉淀", "模板、按键布局、团队策略存在我们的软件里，换设备成本高。", C.accent3],
    ["国内生态位置", "做国产 agent 厂商的官方硬件伙伴；海外大厂不会做支持竞争对手的设备。", C.accent4],
  ];
  m.forEach(([h, d, col], i) => {
    const x = 0.5 + (i % 2) * 4.6, y = 1.25 + Math.floor(i / 2) * 1.85;
    card(s, x, y, 4.4, 1.65, "moat" + i);
    dot(s, x + 0.2, y + 0.2, col, String(i + 1), "md" + i);
    text(s, h, { x: x + 0.8, y: y + 0.22, w: 3.4, h: 0.4, fontSize: 16, bold: true });
    text(s, d, { x: x + 0.2, y: y + 0.75, w: 4.0, h: 0.85, fontSize: 12, color: C.text2 });
  });
}

// 12 路线图
{
  const s = add("计划与融资");
  title(s, "18 个月路线图");
  const ms = [
    ["2027 Q1", "4 家 agent 批准钩子实测可用"],
    ["2027 Q2", "3 家工厂报价，BOM ≤ ¥300"],
    ["2027 Q3", "软件周活 2,000，等候名单 8,000"],
    ["2027 Q4", "众筹 ≥ ¥80 万（底线 ¥30 万）"],
    ["2028 Q1", "交付 1,150 台，不良率 < 2%"],
    ["2028 Q2", "零售上线，8 周留存 ≥ 60%"],
  ];
  s.addShape(pres.shapes.LINE, { x: 0.7, y: 2.35, w: 8.6, h: 0, line: { color: HEX.grid, width: 2 }, objectName: "tl" });
  ms.forEach(([q, d], i) => {
    const x = 0.5 + i * 1.5;
    s.addShape(pres.shapes.OVAL, { x: x + 0.12, y: 2.23, w: 0.24, h: 0.24, fill: { color: i < 2 ? C.accent2 : C.accent1 }, line: { color: i < 2 ? C.accent2 : C.accent1 }, objectName: "m" + i });
    text(s, q, { x, y: 1.6, w: 1.4, h: 0.4, fontSize: 14, bold: true });
    text(s, d, { x, y: 2.65, w: 1.38, h: 1.1, fontSize: 12, color: C.text2 });
  });
  card(s, 0.5, 4.0, 9.0, 0.85, "rule");
  text(s, "每个里程碑回答一个风险：技术能不能做、毛利够不够、有没有人要、愿不愿付钱、能不能量产、用户留不留。",
    { x: 0.7, y: 4.05, w: 8.6, h: 0.75, fontSize: 13, valign: "middle" });
}

// 13 财务
{
  const s = add("计划与融资");
  title(s, "财务预测（基准情景，保守）");
  s.addChart(pres.charts.BAR, [{ name: "收入（万元）", labels: ["2027", "2028", "2029"], values: [0, 374, 856] }], {
    x: 0.5, y: 1.2, w: 5.4, h: 3.6, barDir: "col", chartColors: [HEX.amber],
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: HEX.text, dataLabelFontSize: 12, dataLabelFontFace: "+mn-lt",
    showTitle: true, title: "收入（万元）", titleColor: HEX.text, titleFontSize: 13, titleFontFace: "+mn-lt",
    catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
    valGridLine: { color: HEX.grid, size: 0.5 }, catGridLine: { style: "none" }, showLegend: false,
  });
  const kv = [
    ["13,350 台", "2029 年销量"], ["37%", "2029 年毛利率"], ["3.5 万台/年", "盈亏平衡点"],
  ];
  kv.forEach(([v, k], i) => {
    const y = 1.25 + i * 1.15;
    card(s, 6.2, y, 3.3, 1.0, "kv" + i);
    text(s, v, { x: 6.4, y: y + 0.08, w: 2.9, h: 0.5, fontSize: 22, bold: true, color: C.accent1 });
    text(s, k, { x: 6.4, y: y + 0.58, w: 2.9, h: 0.35, fontSize: 12, color: C.text2 });
  });
  source(s, "【假设】成本未拿到工厂报价；软件收入按保守口径，2029 年仅 ¥55 万。详见 08-商业模式与财务.md");
}

// 14 融资
{
  const s = add("计划与融资");
  title(s, "本轮：天使轮 ¥600 万");
  text(s, [
    { text: "¥600 万", options: { fontSize: 44, bold: true, color: C.accent1, breakLine: true } },
    { text: "投后估值 ¥3,000 万 · 出让约 20%", options: { fontSize: 16, breakLine: true } },
    { text: "可分两期：¥300 万先到，众筹达 ¥30 万后到第二笔", options: { fontSize: 12, color: C.text2 } },
  ], { x: 0.5, y: 1.3, w: 4.2, h: 2.2 });
  s.addChart(pres.charts.DOUGHNUT, [{ name: "资金用途", labels: ["团队", "品牌与获客", "行政法务云", "研发打样", "模具认证", "库存", "安全垫"], values: [45, 12, 7, 10, 5, 5, 21] }], {
    x: 4.9, y: 1.1, w: 4.6, h: 3.8, holeSize: 55,
    chartColors: [HEX.amber, HEX.blue, "6B7280", HEX.green, HEX.red, "C9CED6", "3A424D"],
    showPercent: true, showValue: false, showLegend: true, legendPos: "r", legendColor: HEX.text, legendFontSize: 11, legendFontFace: "+mn-lt",
    dataLabelColor: "111418", dataLabelFontSize: 10, dataLabelFontFace: "+mn-lt",
    showTitle: true, title: "资金用途（%）", titleColor: HEX.text, titleFontSize: 13, titleFontFace: "+mn-lt",
  });
  text(s, "资金撑到 2028 Q2，届时用真实销量、留存和渠道数据启动 Pre-A（¥1,500–2,000 万）。",
    { x: 0.5, y: 3.7, w: 4.2, h: 1.0, fontSize: 13, color: C.text2 });
}

// 15 风险
{
  const s = add("计划与融资");
  title(s, "我们主动回答的三个风险");
  const r = [
    ["大厂自己做？", "OpenAI、Anthropic 只会做支持自己的设备；中立跨厂商和国内市场是它们不会去的位置。"],
    ["agent 越来越自主，审批会消失？", "主卖点是“谁在等我、一键过去、不打字就指挥”。63% 的开发者很少让 agent 无人看管地跑。"],
    ["CtrlVibe 众筹只筹到约 1 万美元？", "先用免费软件积累周活和等候名单，达到门槛才开模具和众筹。"],
  ];
  r.forEach(([q, a], i) => {
    const y = 1.25 + i * 1.2;
    card(s, 0.5, y, 9.0, 1.05, "risk" + i);
    text(s, q, { x: 0.7, y: y + 0.1, w: 3.0, h: 0.85, fontSize: 15, bold: true, color: C.accent1, valign: "middle" });
    text(s, a, { x: 3.8, y: y + 0.1, w: 5.5, h: 0.85, fontSize: 13, valign: "middle" });
  });
}

// 16 团队与结尾
{
  const s = add("结尾", "TITLE");
  s.addImage({ path: IMG("ring.png"), x: 5.0, y: 0, w: 5.0, h: 5.625, sizing: { type: "cover", w: 5.0, h: 5.625 }, objectName: "ring" });
  s.addText("让每个开发者都能带一支 AI 团队", { placeholder: "title" });
  s.addText([
    { text: "团队：硬件 + 软件 + 产品，已独立做出可运行原型", options: { breakLine: true } },
    { text: "本轮在招：嵌入式、桌面端、工业设计", options: { color: C.accent1 } },
  ], { placeholder: "body" });
  s.addNotes("团队成员姓名、背景和联系方式由创始人补充后再发给投资人。");
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
