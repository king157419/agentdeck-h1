// 桌面小画 · H1 · Wokwi 仿真固件 (经典 ESP32 + ILI9341)
// 画面逻辑移植自 sim/index.html：只用 矩形 / 点 / 线 / 圆，RGB565，目标 20 帧/秒。
//
// 渲染方式（为了让仿真器里的 SPI 不被整屏刷新拖死）：
//   1. 切换画面 / 状态时：整幅 240x240 刷一次（分条带）。
//   2. 平时：scene.dirty() 只上报"会动的小元素"(矩形 + 签名)，
//      与上一帧对比，只有变了的元素才重画；重画 = 在内存小缓冲里把整个
//      scene.draw() 画一遍（自动裁剪到该矩形），再一次性 SPI 写出该矩形。
//   所以 draw() 必须是"纯函数"：同样的 (state, sf, tf) 画出同样的图。
//
// 「小楼」(house) 是多会话画面，走自己的渲染路径（逻辑画布 120x120 + 底图 + 脏小块），见下方 house 一节。
//
// 加新画面（盆栽 / 潮汐）：照 "星图" 写一组 init/enter/update/draw/dirty，
// 然后把它加进 SCENES[] 即可。

#include <Arduino.h>
#include <SPI.h>
#include <Adafruit_GFX.h>

// ---------- 类型（必须放在所有函数之前：Arduino 会自动生成函数原型） ----------
enum St : uint8_t { IDLE, THINK, TOOL, WAIT, DONE, ERR, NST };
static const char* const ST_NAME[NST] = {"idle", "think", "tool", "wait", "done", "error"};

struct Scene {
  const char* name;
  void (*init)();
  void (*enter)(St prev, St next);
  void (*update)(St st, int sf, int tf);   // 每帧一次：推进动画状态
  void (*draw)(St st, int sf, int tf);     // 纯函数：画整幅 240x240
  void (*dirty)(St st, int sf, int tf);    // 上报当前所有"会动的元素"
};

struct El { int16_t x, y, w, h; int32_t key; };
struct Per { int px, bob, arm; bool show; };
// ---- 小楼 / 会话用的类型 ----
struct Sess { uint16_t sid; char name[16]; St st; int32_t tf0; uint8_t combo; int8_t slot; };   // tf0 = 进入当前状态的帧号
struct Rc { int8_t x, y, w, h; };
struct WRect { int x, y, w, h, s, cx, G, ty, base, ly; };
struct WKey { int16_t kind; uint16_t glass; int16_t px, pose, legs, bob, dir, dots, conf, mark, chair, combo, base; };   // 窗内容签名：变了才重画
struct Prm { WKey key; uint16_t floor; int16_t dark; };
struct LaneStep { uint8_t st; uint8_t sec; };
struct Lane { const char* name; const LaneStep* steps; uint8_t n; uint8_t i; uint32_t t0; int sid; };

// ========================================================================
//  显示器配置 —— 换屏只改这一块（README 里有说明）
// ========================================================================
#define DISPLAY_ST7789 0          // 0 = ILI9341 (Wokwi)；1 = ST7789 240x240 真屏
#define SCR_W 240                 // 作画区域宽（画面代码全部按 240 写）
#define SCR_H 240                 // 作画区域高
#define TFT_CS_PIN  5
#define TFT_DC_PIN  2
#define TFT_RST_PIN 4
// 仿真专用输入（真产品没有按键）
#define BTN_STATE_PIN 32
#define BTN_SCENE_PIN 33

#if DISPLAY_ST7789
  #include <Adafruit_ST7789.h>
  Adafruit_ST7789 tft(TFT_CS_PIN, TFT_DC_PIN, TFT_RST_PIN);
  static void displayInit() {
    tft.init(240, 240, SPI_MODE3);   // 240x240 方屏
    tft.setRotation(0);
    tft.fillScreen(0);
  }
#else
  #include <Adafruit_ILI9341.h>
  Adafruit_ILI9341 tft(TFT_CS_PIN, TFT_DC_PIN, TFT_RST_PIN);
  static void displayInit() {
    tft.begin(40000000);             // ILI9341 240x320，只用左上 240x240
    tft.setRotation(0);
    tft.fillScreen(0);               // 其余区域涂黑
  }
#endif
// ========================================================================

// ---------- 颜色：0xRRGGBB -> RGB565（编译期） ----------
constexpr uint16_t C(uint32_t h) {
  return (uint16_t)((((h >> 16) & 0xF8) << 8) | (((h >> 8) & 0xFC) << 3) | ((h & 0xFF) >> 3));
}

// ---------- 小缓冲 + 绘图原语（带裁剪，对应网页版 R/P/line/disc/ring） ----------
#define MAXPIX (SCR_W * 40)
static uint16_t buf[MAXPIX];
static int ox, oy, rw, rh;               // 当前缓冲对应的屏幕矩形

static inline int rd(float x) { return (int)floorf(x + 0.5f); }
static inline int iabs(int a) { return a < 0 ? -a : a; }

static void R(int x, int y, int w, int h, uint16_t c) {
  int x0 = x > ox ? x : ox, y0 = y > oy ? y : oy;
  int x1 = x + w < ox + rw ? x + w : ox + rw;
  int y1 = y + h < oy + rh ? y + h : oy + rh;
  if (x0 >= x1 || y0 >= y1) return;
  for (int yy = y0; yy < y1; yy++) {
    uint16_t* p = buf + (yy - oy) * rw + (x0 - ox);
    for (int xx = x0; xx < x1; xx++) *p++ = c;
  }
}
static inline void P(int x, int y, uint16_t c) { R(x, y, 1, 1, c); }

static void line(int x0, int y0, int x1, int y1, uint16_t c, int t = 1) {
  int dx = iabs(x1 - x0), dy = -iabs(y1 - y0);
  int sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
  int e = dx + dy;
  for (;;) {
    R(x0, y0, t, t, c);
    if (x0 == x1 && y0 == y1) break;
    int e2 = 2 * e;
    if (e2 >= dy) { e += dy; x0 += sx; }
    if (e2 <= dx) { e += dx; y0 += sy; }
  }
}
static void disc(int cx, int cy, int r, uint16_t c) {
  if (r <= 0) { P(cx, cy, c); return; }
  for (int dy = -r; dy <= r; dy++) {
    int dx = rd(sqrtf(r * r + r * 0.8f - dy * dy));
    R(cx - dx, cy + dy, 2 * dx + 1, 1, c);
  }
}
static void ring(int cx, int cy, int r, uint16_t c) {
  for (int dy = -r; dy <= r; dy++) {
    int xo = rd(sqrtf(r * r + r * 0.8f - dy * dy));
    int ri = r - 1;
    if (iabs(dy) >= ri) { R(cx - xo, cy + dy, 2 * xo + 1, 1, c); continue; }
    int xi = rd(sqrtf(ri * ri + ri * 0.8f - dy * dy));
    int w = xo - xi; if (w < 1) w = 1;
    R(cx - xo, cy + dy, w, 1, c); R(cx + xo - w + 1, cy + dy, w, 1, c);
  }
}
static float hs(int32_t n) {            // 与网页版相同的整数哈希
  uint32_t v = (uint32_t)n;
  v = (v ^ 61u) ^ (v >> 16);
  v = v + (v << 3);
  v = v ^ (v >> 4);
  v = v * 0x27d4eb2du;
  v = v ^ (v >> 15);
  return (float)((double)v / 4294967296.0);
}

// ---------- 脏元素登记 ----------
#define MAXEL 112
static El curEl[MAXEL], prevEl[MAXEL];
static int nCur = 0, nPrev = 0;
static void emit(int x, int y, int w, int h, int32_t key) {
  if (nCur >= MAXEL) return;
  curEl[nCur++] = {(int16_t)x, (int16_t)y, (int16_t)w, (int16_t)h, key};
}

// ---------- 共用叠加 ----------
static void bang(int x, int y, uint16_t c) { R(x, y, 3, 9, c); R(x, y + 11, 3, 3, c); }
static void beaconDraw(int tf) {          // 等你确认：琥珀色呼吸边框
  int p = tf % 20; if (p >= 12) return;
  uint16_t c = p < 6 ? C(0xffc030) : C(0xc08012);
  R(0, 0, 240, 3, c); R(0, 237, 240, 3, c); R(0, 3, 3, 234, c); R(237, 3, 3, 234, c);
}
static void beaconEmit(int tf) {
  int p = tf % 20, k = p < 6 ? 1 : (p < 12 ? 2 : 0);
  emit(0, 0, 240, 3, k); emit(0, 237, 240, 3, k); emit(0, 3, 3, 234, k); emit(237, 3, 3, 234, k);
}
static void errMarkDraw(int tf) { if ((tf % 12) < 8) bang(20, 18, C(0xf05060)); }
static void errMarkEmit(int tf) { emit(20, 18, 3, 14, (tf % 12) < 8); }

// ========================================================================
//  画面：星图
// ========================================================================
#define NPATH 14
static const int16_t PATH[NPATH][2] = {
  {40,170},{62,138},{50,100},{84,84},{104,52},{136,66},{160,40},
  {186,70},{176,108},{200,138},{184,174},{150,156},{112,184},{78,204}};
static const uint16_t SKYC[3] = {C(0x2c3760), C(0x56669a), C(0x9fb0e0)};
#define NSTAR 36
static uint8_t s_x[NSTAR], s_y[NSTAR], s_base[NSTAR];
static int s_n = 0, s_births[NPATH], s_lastBirth = -100;

static void stars_init() {
  for (int i = 0; i < NSTAR; i++) {
    s_x[i] = 8 + (int)floorf(hs(i * 3 + 1) * 224);
    s_y[i] = 8 + (int)floorf(hs(i * 3 + 2) * 224);
    s_base[i] = hs(i * 3 + 3) < 0.3f ? 1 : 0;
  }
  s_n = 0;
}
static void stars_enter(St p, St n) {
  if (n == THINK && p == IDLE) s_n = 0;
  if (n == TOOL) { if (s_n >= NPATH) s_n = 0; s_lastBirth = -100; }
}
static void stars_update(St st, int sf, int tf) {
  if (st == TOOL && s_n < NPATH && sf - s_lastBirth >= 18) {
    s_births[s_n++] = tf; s_lastBirth = sf;
  }
}
static int stars_lv(int i, St st, int sf, int tf) {
  int lv = s_base[i];
  if (st == THINK && i % 2 == 0) { int tw = ((tf >> 2) + i * 5) % 8; lv = tw < 2 ? 2 : (tw < 5 ? 1 : 0); }
  else if (st == TOOL && i % 4 == 0) { int tw = ((tf >> 2) + i * 5) % 8; lv = tw < 2 ? 2 : lv; }
  else if (st == WAIT) lv = 0;
  else if (st == IDLE && i % 12 == 0) { lv = (((tf >> 4) + i) % 4 == 0) ? 2 : lv; }
  else if (st == DONE && sf < 40) { lv = (hs(i + (tf >> 2) * 37) > 0.6f) ? 2 : lv; }
  return lv;
}
static int stars_jit(St st, int sf, int tf) { return (st == ERR && sf < 40) ? (((tf >> 1) & 1) ? 1 : -1) : 0; }

static void stars_draw(St st, int sf, int tf) {
  R(0, 0, 240, 240, C(0x070b1a));
  int jit = stars_jit(st, sf, tf);
  for (int i = 0; i < NSTAR; i++) {
    int lv = stars_lv(i, st, sf, tf);
    int xx = s_x[i] + jit, yy = s_y[i] - jit;
    P(xx, yy, SKYC[lv]);
    if (lv == 2) { uint16_t a = C(0x56669a); P(xx - 1, yy, a); P(xx + 1, yy, a); P(xx, yy - 1, a); P(xx, yy + 1, a); }
  }
  bool bad = st == ERR;
  for (int i = 1; i < s_n; i++) {
    const int16_t* a = PATH[i - 1]; const int16_t* b = PATH[i];
    float p = (tf - s_births[i]) / 10.0f; if (p > 1) p = 1;
    line(a[0], a[1], (int)(a[0] + (b[0] - a[0]) * p), (int)(a[1] + (b[1] - a[1]) * p),
         (bad && i == s_n - 1) ? C(0x8a2a3a) : C(0x3f5aa0), 1);
  }
  for (int i = 0; i < s_n; i++) {
    int x = PATH[i][0], y = PATH[i][1], age = tf - s_births[i];
    bool last = bad && i == s_n - 1;
    bool red = last && ((tf >> 2) & 1);
    uint16_t cm = last ? C(0xe0484c) : C(0xf6efd2), ca = last ? C(0xa83040) : C(0xb8b2d8);
    if (age < 10) ring(x, y, age + 2, C(0x6f86c8));
    int arm = age < 8 ? 5 : (age < 16 ? 4 : 3);
    R(x - arm, y, 2 * arm + 1, 1, ca); R(x, y - arm, 1, 2 * arm + 1, ca);
    R(x - 1, y - 1, 3, 3, red ? C(0xff9aa0) : cm);
  }
  if (st == DONE && sf < 40) {            // 流星
    int hx = 236 - 6 * sf, hy = 8 + 4 * sf;
    for (int j = 0; j < 10; j++) {
      uint16_t c = j < 2 ? C(0xffffff) : (j < 5 ? C(0xb8c8f0) : C(0x5a6aa0));
      int x = hx + j * 3, y = hy - j * 2;
      if (j < 3) { P(x, y, c); P(x + 1, y, c); P(x, y + 1, c); P(x + 1, y + 1, c); } else P(x, y, c);
    }
  }
  if (st == WAIT) {                       // 等你确认：脉动亮星
    int p = tf % 20, r = rd(2 + (p < 10 ? p : 20 - p) * 0.7f);
    if (r >= 5) ring(120, 120, r * 2 + 4, C(0xc08012));
    R(120 - (r * 2 + 3), 120, 2 * (r * 2 + 3) + 1, 1, C(0xffd870));
    R(120, 120 - (r * 2 + 3), 1, 2 * (r * 2 + 3) + 1, C(0xffd870));
    disc(120, 120, r, C(0xfff0b0));
    beaconDraw(tf);
  }
  if (bad) {
    if (s_n == 0) disc(120, 120, 2, ((tf >> 2) & 1) ? C(0xff9aa0) : C(0xe0484c));
    errMarkDraw(tf);
  }
}
static void stars_dirty(St st, int sf, int tf) {
  int jit = stars_jit(st, sf, tf);
  for (int i = 0; i < NSTAR; i++)
    emit(s_x[i] - 2, s_y[i] - 2, 5, 5, stars_lv(i, st, sf, tf) * 3 + jit + 1);
  bool bad = st == ERR;
  for (int i = 1; i < s_n; i++) {
    const int16_t* a = PATH[i - 1]; const int16_t* b = PATH[i];
    int p10 = tf - s_births[i]; if (p10 > 10) p10 = 10; if (p10 < 0) p10 = 0;
    int x0 = a[0] < b[0] ? a[0] : b[0], y0 = a[1] < b[1] ? a[1] : b[1];
    emit(x0 - 1, y0 - 1, iabs(a[0] - b[0]) + 3, iabs(a[1] - b[1]) + 3, 100 + p10 * 2 + (bad && i == s_n - 1));
  }
  for (int i = 0; i < s_n; i++) {
    int age = tf - s_births[i];
    bool last = bad && i == s_n - 1, red = last && ((tf >> 2) & 1);
    int stage = age < 10 ? age : (age < 16 ? 10 : 11);
    int32_t key = 1000 + stage * 4 + red * 2 + last;
    if (age < 10) emit(PATH[i][0] - 12, PATH[i][1] - 12, 25, 25, key);
    else emit(PATH[i][0] - 5, PATH[i][1] - 5, 11, 11, key);
  }
  if (st == DONE && sf < 40) { int hx = 236 - 6 * sf, hy = 8 + 4 * sf; emit(hx - 1, hy - 19, 32, 22, 5000 + sf); }
  if (st == WAIT) {
    int p = tf % 20, r = rd(2 + (p < 10 ? p : 20 - p) * 0.7f);
    emit(96, 96, 49, 49, 6000 + r);
    beaconEmit(tf);
  }
  if (bad) {
    if (s_n == 0) emit(118, 118, 5, 5, 7000 + ((tf >> 2) & 1));
    errMarkEmit(tf);
  }
}

// ========================================================================
//  画面：小窗
// ========================================================================
static int w_moon = 0;
static uint8_t w_sx[8], w_sy[8], w_px[5], w_py[5];
static void win_init() {
  for (int i = 0; i < 8; i++) { w_sx[i] = 10 + (int)floorf(hs(i * 2 + 50) * 220); w_sy[i] = 6 + (int)floorf(hs(i * 2 + 51) * 44); }
  for (int j = 0; j < 5; j++) { w_px[j] = 170 + (int)floorf(hs(j + 70) * 60); w_py[j] = 8 + (int)floorf(hs(j + 80) * 40); }
  w_moon = 0;
}
static void win_enter(St p, St n) { if (n == THINK || n == TOOL || n == WAIT || n == ERR) w_moon = 0; }
static void win_update(St st, int sf, int tf) { if (st == DONE) w_moon = 1; }
static int win_lamp(St st, int sf, int tf) {
  if (st == THINK || st == TOOL || st == WAIT) return 2;
  if (st == ERR) return hs(tf >> 1) > 0.5f ? 2 : 0;
  if (st == DONE) return sf < 18 ? 2 : 0;
  return w_moon ? 0 : 1;
}
static Per win_person(St st, int sf, int tf, int lamp) {
  Per q = {120, 0, 0, false};
  q.show = (st == THINK || st == TOOL || st == WAIT || st == ERR) && lamp > 0;
  if (st == THINK) q.px = 120 + rd(sinf(tf * 0.05f) * 28);
  else if (st == TOOL) { q.px = 120 + rd(sinf(tf * 0.13f) * 32); q.bob = (tf % 6 < 3) ? 0 : 1; }
  else if (st == WAIT) { q.px = 120; q.arm = (tf % 12 < 6) ? 2 : 1; }
  else if (st == ERR) q.px = 100 + (((tf >> 1) & 1) ? 1 : 0);
  return q;
}
static int win_moonY(St st, int sf) {
  float p = st == DONE ? (sf / 25.0f > 1 ? 1 : sf / 25.0f) : 1;
  return 30 + rd((1 - p) * 40);
}
static void win_draw(St st, int sf, int tf) {
  int lamp = win_lamp(st, sf, tf);
  const uint16_t skyc = C(0x141a33);
  R(0, 0, 240, 240, skyc);
  for (int i = 0; i < 8; i++) P(w_sx[i], w_sy[i], w_moon ? C(0x6a78b0) : C(0x3a4470));
  if (w_moon) {
    int my = win_moonY(st, sf);
    disc(196, my, 10, C(0xf2eac0)); disc(201, my - 3, 9, skyc);
    if (st == DONE && sf < 60) {
      for (int j = 0; j < 5; j++) {
        if (((sf + j * 7) % 14) >= 7) continue;
        int x = w_px[j], y = w_py[j];
        P(x, y, C(0xfff0b0)); P(x - 1, y, C(0xb8c8f0)); P(x + 1, y, C(0xb8c8f0)); P(x, y - 1, C(0xb8c8f0)); P(x, y + 1, C(0xb8c8f0));
      }
    }
  }
  R(0, 60, 240, 6, C(0x3a2c40)); R(0, 66, 240, 174, C(0x2a2230));
  for (int r = 0; r < 12; r++) {
    int y = 66 + r * 14 + 13; R(0, y, 240, 1, C(0x221b28));
    for (int x = (r % 2) * 20; x < 240; x += 40) R(x, y - 13, 1, 13, C(0x221b28));
  }
  const uint16_t rc[3] = {C(0x182036), C(0x6a5236), C(0xe9b955)};
  const uint16_t fc[3] = {C(0x121a2c), C(0x52402a), C(0xc79a3a)};
  const uint16_t cur[3] = {C(0x2a1a28), C(0x5a2e38), C(0xa04a5a)};
  const uint16_t bulb[3] = {C(0x2a3250), C(0x8a7040), C(0xfff3b0)};
  R(64, 78, 112, 112, C(0x7a5a3c));
  R(70, 84, 100, 100, rc[lamp]); R(70, 160, 100, 24, fc[lamp]);
  uint16_t sil = lamp == 2 ? C(0x2a1e2a) : (lamp == 1 ? C(0x3a2c24) : C(0x0d1222));
  Per q = win_person(st, sf, tf, lamp);
  if (q.show) {
    int px = q.px, fy = 172 - q.bob, ph = (tf >> 2) & 1;
    R(px - 6, fy - 24, 12, 16, sil);
    if (st == WAIT || st == ERR) { R(px - 5, fy - 8, 4, 8, sil); R(px + 1, fy - 8, 4, 8, sil); }
    else { R(px - 5, fy - 8, 4, ph ? 8 : 6, sil); R(px + 1, fy - 8, 4, ph ? 6 : 8, sil); }
    disc(px, fy - 31, 6, sil);
    if (q.arm) { line(px + 5, fy - 22, px + 13, q.arm == 2 ? fy - 37 : fy - 29, sil, 3); disc(px + 14, q.arm == 2 ? fy - 38 : fy - 30, 2, sil); }
    else R(px + 6, fy - 22, 3, 12, sil);
    if (st == WAIT && (tf % 16) < 11) bang(px - 1, fy - 62, C(0xffb020));
    if (st == THINK) for (int j = 0; j < 3; j++) if (((tf >> 3) % 4) > j) disc(px + 10 + j * 7, fy - 48 - j * 3, 2, sil);
  }
  R(70, 84, 10, 52, cur[lamp]); R(160, 84, 10, 52, cur[lamp]);
  R(119, 84, 2, 16, C(0x5a4a3a)); R(112, 100, 16, 3, C(0x6a4a30)); R(108, 103, 24, 2, C(0x6a4a30)); disc(120, 108, 2, bulb[lamp]);
  R(58, 190, 124, 7, C(0x8a6a48)); R(58, 197, 124, 2, C(0x5a4430));
  if (st == ERR) errMarkDraw(tf);
  if (st == WAIT) beaconDraw(tf);
}
static void win_dirty(St st, int sf, int tf) {
  int lamp = win_lamp(st, sf, tf);
  emit(58, 78, 124, 122, 100 + lamp);                       // 窗 + 窗台（灯光变化时整窗重画）
  Per q = win_person(st, sf, tf, lamp);
  if (q.show) {
    int fy = 172 - q.bob, ph = (tf >> 2) & 1;
    int bangOn = (st == WAIT && (tf % 16) < 11), dots = st == THINK ? (int)((tf >> 3) % 4) : 0;
    int32_t key = ((((((q.px * 2 + q.bob) * 4 + q.arm) * 2 + ph) * 2 + bangOn) * 4 + dots) * 3 + lamp);
    emit(q.px - 8, fy - 66, 38, 70, 1000 + key);
    // 人影把前一帧的位置也带进脏区：由 prev/cur 对比自动处理
  }
  if (w_moon) {
    emit(185, win_moonY(st, sf) - 12, 27, 24, 2000 + win_moonY(st, sf));
    if (st == DONE && sf < 60)
      for (int j = 0; j < 5; j++) emit(w_px[j] - 1, w_py[j] - 1, 3, 3, 3000 + j * 2 + (((sf + j * 7) % 14) < 7));
  }
  if (st == ERR) errMarkEmit(tf);
  if (st == WAIT) beaconEmit(tf);
}

// ========================================================================
//  全局运行状态（星图 / 小窗 显示"选中会话"的状态）
// ========================================================================
static St state = IDLE;
static int sceneI = 0;
static uint32_t t0 = 0;
static int tfNow = 0, stateTf0 = 0, lastTf = -1;
static bool needFull = true;
static uint32_t pxTotal = 0;
#define SCN_STARS 0
#define SCN_WINDOW 1
#define SCN_HOUSE 2

static int nowTf() { return (int)((millis() - t0) / 50); }
static void applySel(St p, bool callEnter);   // 定义在渲染器之后

// ========================================================================
//  会话模块：最多 9 扇窗 + 排队。不碰屏幕，只管"谁住哪扇窗、什么状态"
//  对应网页版 sessions / slotSid / slotVac / addSession / endSession ...
// ========================================================================
#define MAXSESS 24                       // 在线会话上限（9 扇窗 + 最多 15 个排队）
#define NWIN 9
static Sess sess[MAXSESS];
static int nSess = 0;
static int slotSid[NWIN];                // 窗里住的会话号，-1 = 空
static bool slotVac[NWIN];               // 空窗是否是"暗窗"（会话结束留下的）
static uint16_t nextSid = 1;
static int selSid = -1, comboPtr = 0;

static Sess* S_(int sid) { for (int i = 0; i < nSess; i++) if (sess[i].sid == sid) return &sess[i]; return nullptr; }
static Sess* curSel() { return selSid < 0 ? nullptr : S_(selSid); }
static St selState() { Sess* s = curSel(); return s ? s->st : IDLE; }
static void giveSlot(Sess& s) {
  for (int i = 0; i < NWIN; i++) if (slotSid[i] < 0) { slotSid[i] = s.sid; slotVac[i] = false; s.slot = i; return; }
}
static void sessReset() {
  nSess = 0; selSid = -1; comboPtr = 0;
  for (int i = 0; i < NWIN; i++) { slotSid[i] = -1; slotVac[i] = false; }
}
static void selectSess(int sid) {
  St p = selState(); selSid = sid; St n = selState();
  applySel(p, p != n);
}
static const char* const AUTONAME[] = {"h1-fw","webapp","notes","api","blog","infra","ml-lab","docs","cli","shop","bot","site","game","wiki"};
static bool nameInUse(const char* n) { for (int i = 0; i < nSess; i++) if (!strcmp(sess[i].name, n)) return true; return false; }
static int addSession(const char* name, St st) {      // 返回会话号；满了返回 -1
  if (nSess >= MAXSESS) return -1;
  Sess& s = sess[nSess];
  memset(&s, 0, sizeof(s));
  if (name && *name) { strncpy(s.name, name, 15); s.name[15] = 0; }
  else {
    bool ok = false;
    for (unsigned i = 0; i < sizeof(AUTONAME) / sizeof(AUTONAME[0]) && !ok; i++)
      if (!nameInUse(AUTONAME[i])) { strcpy(s.name, AUTONAME[i]); ok = true; }
    if (!ok) snprintf(s.name, sizeof(s.name), "s%u", (unsigned)nextSid);
  }
  int c = comboPtr;                                     // 窗帘组合：优先挑没人用的
  for (int k = 0; k < 12; k++) { int cc = (comboPtr + k) % 12; bool used = false;
    for (int i = 0; i < nSess; i++) if (sess[i].combo == cc) used = true;
    if (!used) { c = cc; break; } }
  comboPtr = (c + 1) % 12;
  s.sid = nextSid++; s.st = st; s.tf0 = nowTf(); s.combo = c; s.slot = -1;
  nSess++;
  giveSlot(s);
  int sid = s.sid;
  if (selSid < 0) selectSess(sid);
  return sid;
}
static bool endSession(int sid) {
  int idx = -1; for (int i = 0; i < nSess; i++) if (sess[i].sid == sid) idx = i;
  if (idx < 0) return false;
  Sess s = sess[idx];
  for (int i = idx; i < nSess - 1; i++) sess[i] = sess[i + 1];
  nSess--;
  if (s.slot >= 0) {
    slotSid[s.slot] = -1; slotVac[s.slot] = true;
    for (int i = 0; i < nSess; i++) if (sess[i].slot < 0) { giveSlot(sess[i]); break; }   // 排队的第一个住进来
  }
  if (selSid == sid) { selSid = nSess ? sess[0].sid : -1; applySel(s.st, true); }
  return true;
}
static bool setSessionState(int sid, St st) {
  Sess* s = S_(sid); if (!s) return false;
  St p = s->st; s->st = st; s->tf0 = nowTf();
  if (sid == selSid) applySel(p, true);
  return true;
}
static void clearVacant() { for (int i = 0; i < NWIN; i++) slotVac[i] = false; }
static int countVacant() { int n = 0; for (int i = 0; i < NWIN; i++) if (slotVac[i]) n++; return n; }

// ========================================================================
//  画面：小楼（多会话）—— 移植自 sim/index.html 的 Town
//  逻辑画布 120x120，1 画素 = 2x2 屏幕像素。
//  bgImg  = 背景底图（只在布局变化时重画）
//  curImg = 当前画面（每帧只改变了的部分）；改过的 4x4 画素小块记入脏表，帧末合并成矩形、放大 2 倍一次写屏
//  houseOps = 网页版同口径的"图元数"，每帧预算 150
// ========================================================================
#define LW 120
#define TILE 4
#define TN (LW / TILE)
#define BUDGET 150
static uint16_t bgImg[LW * LW];
static uint16_t curImg[LW * LW];
static uint16_t* tgt = curImg;
static bool dirtyT[TN * TN];
static bool anyDirty = false;
static int houseOps = 0, houseOpsPeak = 0;
static bool trk = false;
static bool clOn = false;
static int clx, cly, clw, clh;

constexpr uint16_t P_SKY = C(0x121630), P_WALL_L = C(0x3e4766), P_MOON = C(0xf2e6b8), P_WALL = C(0x2e3550), P_WALL_D = C(0x232840),
  P_ROOF = C(0x4a2f3e), P_ROOF_L = C(0x6e4250), P_WOOD = C(0x8c6446), P_WARM = C(0xf4c06a), P_WARM_D = C(0xa86a32),
  P_GLASS = C(0x141a2e), P_SIL = C(0x3a2430), P_AMBER = C(0xffa828), P_RED = C(0xe0485a), P_GREEN = C(0x5c9a58),
  P_BLUE = C(0x5c6cb8), P_TEAL = C(0x3c8a86);
static const uint16_t HUES[4] = {P_ROOF_L, P_TEAL, P_BLUE, P_MOON};
static const uint16_t CONF[4] = {P_BLUE, P_TEAL, P_RED, P_GREEN};

static void markDirty(int x0, int y0, int x1, int y1) {          // 逻辑矩形 [x0,x1) x [y0,y1)，已裁剪
  for (int ty = y0 / TILE; ty <= (y1 - 1) / TILE; ty++)
    for (int tx = x0 / TILE; tx <= (x1 - 1) / TILE; tx++) dirtyT[ty * TN + tx] = true;
  anyDirty = true;
}
static void Q(int x, int y, int w, int h, uint16_t c) {            // 对应网页版 Q：逻辑坐标、可被裁剪框裁剪、算 1 个图元
  if (clOn) {
    int x2 = x + w < clx + clw ? x + w : clx + clw, y2 = y + h < cly + clh ? y + h : cly + clh;
    x = x > clx ? x : clx; y = y > cly ? y : cly; w = x2 - x; h = y2 - y;
  }
  if (w <= 0 || h <= 0) return;
  houseOps++;
  int x0 = x < 0 ? 0 : x, y0 = y < 0 ? 0 : y, x1 = x + w > LW ? LW : x + w, y1 = y + h > LW ? LW : y + h;
  if (x0 >= x1 || y0 >= y1) return;
  for (int yy = y0; yy < y1; yy++) { uint16_t* p = tgt + yy * LW + x0; for (int xx = x0; xx < x1; xx++) *p++ = c; }
  if (tgt == curImg && !trk) markDirty(x0, y0, x1, y1);
}
static void B(int x, int y, int w, int h) {                        // 从底图恢复一块（算 1 个图元）
  if (w <= 0 || h <= 0) return;
  houseOps++;
  int x0 = x < 0 ? 0 : x, y0 = y < 0 ? 0 : y, x1 = x + w > LW ? LW : x + w, y1 = y + h > LW ? LW : y + h;
  if (x0 >= x1 || y0 >= y1) return;
  for (int yy = y0; yy < y1; yy++) memcpy(curImg + yy * LW + x0, bgImg + yy * LW + x0, (x1 - x0) * 2);
  markDirty(x0, y0, x1, y1);
}
static inline int rdd(double x) { return (int)floor(x + 0.5); }
static void discQ(int cx, int cy, int r, uint16_t c) {
  for (int dy = -r; dy <= r; dy++) { int dx = rdd(sqrt((double)(r * r) + r * 0.8 - dy * dy)); Q(cx - dx, cy + dy, 2 * dx + 1, 1, c); }
}
static double hsd(int32_t n) {
  uint32_t v = (uint32_t)n;
  v = (v ^ 61u) ^ (v >> 16); v = v + (v << 3); v = v ^ (v >> 4); v = v * 0x27d4eb2du; v = v ^ (v >> 15);
  return (double)v / 4294967296.0;
}

// 3x5 像素字体
struct Glyph { char c; const char* b; };
static const Glyph FONT[] = {
  {'A',"010101111101101"},{'B',"110101110101110"},{'C',"011100100100011"},{'D',"110101101101110"},{'E',"111100110100111"},
  {'F',"111100110100100"},{'G',"011100101101011"},{'H',"101101111101101"},{'I',"111010010010111"},{'J',"001001001101010"},
  {'K',"101101110101101"},{'L',"100100100100111"},{'M',"101111111101101"},{'N',"110101101101101"},{'O',"010101101101010"},
  {'P',"110101110100100"},{'Q',"010101101110011"},{'R',"110101110101101"},{'S',"011100010001110"},{'T',"111010010010010"},
  {'U',"101101101101111"},{'V',"101101101101010"},{'W',"101101111111101"},{'X',"101101010101101"},{'Y',"101101010010010"},
  {'Z',"111001010100111"},{'0',"111101101101111"},{'1',"010110010010111"},{'2',"110001010100111"},{'3',"110001010001110"},
  {'4',"101101111001001"},{'5',"111100110001110"},{'6',"011100111101111"},{'7',"111001010010010"},{'8',"111101111101111"},
  {'9',"111101111001110"},{'-',"000000111000000"},{'_',"000000000000111"},{'+',"000010111010000"},{'.',"000000000000010"}};
static int textW(const char* s) { return (int)strlen(s) * 4 - 1; }
static void text(int x, int y, const char* s, uint16_t c) {
  for (int k = 0; s[k]; k++) {
    const char* b = nullptr;
    for (unsigned g = 0; g < sizeof(FONT) / sizeof(FONT[0]); g++) if (FONT[g].c == s[k]) b = FONT[g].b;
    if (!b) continue;                                   // 空格或字库外字符：留白
    for (int r = 0; r < 5; r++) {
      int run = -1;
      for (int q = 0; q <= 3; q++) {
        bool on = q < 3 && b[r * 3 + q] == '1';
        if (on && run < 0) run = q;
        if (!on && run >= 0) { Q(x + k * 4 + run, y + r, q - run, 1, c); run = -1; }
      }
    }
  }
}

// 人影（以 (px, 脚底) 为原点的单位矩形；dir<0 时左右镜像）。pose: 1 think 2 carry 3 waveA 4 waveB 5 cheer 6 err
#define NA(a) ((uint8_t)(sizeof(a) / sizeof(a[0])))
static const Rc S_BODY[] = {{-1,-14,2,1},{-2,-13,4,2},{-1,-11,2,1},{-2,-10,4,1},{-3,-9,6,5}};
static const Rc S_BODYE[] = {{-1,-13,2,1},{-2,-12,4,2},{-1,-10,2,1},{-3,-9,6,5}};
static const Rc S_LEG0[] = {{-2,-4,2,4},{0,-4,2,4}}, S_LEG1[] = {{-3,-4,2,4},{1,-4,2,4}};
static const Rc S_A0[] = {{-4,-9,1,4},{3,-9,1,4}};
static const Rc S_A1[] = {{-4,-9,1,4},{3,-10,1,2},{2,-11,1,1}};
static const Rc S_A2[] = {{-4,-9,1,4},{3,-8,1,1}};
static const Rc S_A3[] = {{-4,-9,1,4},{3,-10,1,1},{4,-11,1,1},{5,-12,1,1},{6,-14,2,2}};
static const Rc S_A4[] = {{-4,-9,1,4},{3,-10,3,1},{6,-11,2,2}};
static const Rc S_A5[] = {{-4,-14,1,5},{-5,-16,2,2},{3,-14,1,5},{3,-16,2,2}};
static const Rc S_A6[] = {{-4,-9,1,4},{3,-11,1,3},{2,-12,1,1}};
static const Rc S_BOX[] = {{4,-10,3,3}};
static const Rc B_BODY[] = {{-2,-22,4,1},{-3,-21,6,5},{-2,-16,4,1},{-1,-15,2,1},{-4,-14,8,1},{-5,-13,10,6},{-4,-7,8,1}};
static const Rc B_BODYE[] = {{-2,-21,4,1},{-3,-20,6,5},{-2,-15,4,1},{-4,-14,8,1},{-5,-13,10,6},{-4,-7,8,1}};
static const Rc B_LEG0[] = {{-4,-6,3,6},{1,-6,3,6}}, B_LEG1[] = {{-5,-6,3,6},{2,-6,3,5}};
static const Rc B_A0[] = {{-6,-13,1,7},{5,-13,1,7}};
static const Rc B_A1[] = {{-6,-13,1,7},{5,-13,1,3},{3,-17,2,2}};
static const Rc B_A2[] = {{-6,-13,1,7},{5,-13,1,2}};
static const Rc B_A3[] = {{-6,-13,1,7},{5,-21,1,8},{5,-23,2,2}};
static const Rc B_A4[] = {{-6,-13,1,7},{6,-15,1,2},{7,-17,1,2},{8,-19,1,2},{9,-21,2,2}};
static const Rc B_A5[] = {{-6,-21,1,8},{-7,-23,2,2},{5,-21,1,8},{5,-23,2,2}};
static const Rc B_A6[] = {{-6,-13,1,7},{5,-14,1,2},{6,-18,1,4},{4,-20,2,2}};
static const Rc B_BOX[] = {{5,-12,5,4}};
struct Sp { const Rc *body, *bodyE, *leg[2], *arm[7], *box; uint8_t nb, nbE, nleg[2], narm[7], nbox; int8_t dot[4]; int half; };
static const Sp SMALL = {S_BODY, S_BODYE, {S_LEG0, S_LEG1}, {S_A0,S_A1,S_A2,S_A3,S_A4,S_A5,S_A6}, S_BOX,
  NA(S_BODY), NA(S_BODYE), {NA(S_LEG0), NA(S_LEG1)}, {NA(S_A0),NA(S_A1),NA(S_A2),NA(S_A3),NA(S_A4),NA(S_A5),NA(S_A6)}, NA(S_BOX), {4,2,-13,1}, 5};
static const Sp BIGS = {B_BODY, B_BODYE, {B_LEG0, B_LEG1}, {B_A0,B_A1,B_A2,B_A3,B_A4,B_A5,B_A6}, B_BOX,
  NA(B_BODY), NA(B_BODYE), {NA(B_LEG0), NA(B_LEG1)}, {NA(B_A0),NA(B_A1),NA(B_A2),NA(B_A3),NA(B_A4),NA(B_A5),NA(B_A6)}, NA(B_BOX), {6,3,-19,2}, 9};
// arm[] 下标 = pose 号（0 不用）
static void sprite(const Rc* l, int n, int px, int base, int s, int dir, uint16_t c) {
  for (int i = 0; i < n; i++) { int x = dir < 0 ? -l[i].x - l[i].w : l[i].x; Q(px + x * s, base + l[i].y * s, l[i].w * s, l[i].h * s, c); }
}

static WRect wrect(int G, int i) {
  int cx, y, w, h, s;
  if (G == 1) { cx = 56; y = 42; w = 44; h = 38; s = 2; }
  else if (G == 2) { cx = (i & 1) ? 77 : 35; y = (i >> 1) ? 73 : 39; w = 26; h = 22; s = 1; }
  else { static const int CX[3] = {29,56,83}, CY[3] = {36,59,82}; cx = CX[i % 3]; y = CY[i / 3]; w = 19; h = 13; s = 1; }
  WRect r; r.x = cx - (w >> 1); r.y = y; r.w = w; r.h = h; r.s = s; r.cx = cx; r.G = G;
  r.ty = G == 1 ? y + 6 : (G == 2 ? y + 3 : y + 2);
  r.base = G == 3 ? y + h + 4 : y + h - 2;
  r.ly = y + h + (G == 3 ? 3 : 4);
  return r;
}
static void townLayout(int& G, int& over) {
  int hi = -1; for (int i = 0; i < NWIN; i++) if (slotSid[i] >= 0 || slotVac[i]) hi = i;
  int need = hi + 1 > 1 ? hi + 1 : 1;
  G = need <= 1 ? 1 : (need <= 4 ? 2 : 3);
  over = 0; for (int i = 0; i < nSess; i++) if (sess[i].slot < 0) over++;
}

// ---- 小楼状态 ----
static int townSig = -1;
static bool townForce = true;
static WKey wkeys[NWIN]; static bool wkeyOk[NWIN];
static uint8_t fkeys[NWIN];
static int bkey = 0, skey = -1, lkey = 0;
static bool lrectOk = false; static int lrx, lry, lrw, lrh;

static void renderBg(int G, int over) {
  tgt = bgImg;
  Q(0, 0, 120, 120, P_SKY);
  static const int8_t STARS[10][2] = {{6,22},{38,4},{60,13},{67,3},{94,6},{104,28},{114,42},{7,46},{30,16},{113,60}};
  for (int i = 0; i < 10; i++) Q(STARS[i][0], STARS[i][1], 1, 1, P_WALL_L);
  static const int8_t STARS2[2][2] = {{48,7},{100,15}};
  for (int i = 0; i < 2; i++) { int x = STARS2[i][0], y = STARS2[i][1]; Q(x - 1, y, 3, 1, P_WALL_L); Q(x, y - 1, 1, 3, P_WALL_L); Q(x, y, 1, 1, P_MOON); }
  discQ(20, 11, 6, P_MOON); discQ(23, 9, 5, P_SKY);                                 // 新月
  Q(76, 14, 5, 12, P_WALL_L); Q(76, 17, 5, 1, P_WALL); Q(76, 20, 5, 1, P_WALL); Q(75, 13, 7, 2, P_WALL_D);   // 烟囱
  for (int i = 0; i < 5; i++) { Q(11 + 3 * i, 30 - 2 * i, 90 - 6 * i, 2, P_ROOF); Q(11 + 3 * i, 30 - 2 * i, 1, 2, P_ROOF_L); }   // 阶梯屋顶
  Q(23, 22, 66, 1, P_ROOF_L); Q(10, 32, 92, 1, P_ROOF_L); Q(11, 33, 90, 1, P_ROOF);
  Q(14, 34, 84, 70, P_WALL); Q(14, 34, 84, 1, P_WALL_D);
  Q(14, 35, 1, 69, P_WALL_L); Q(97, 35, 1, 69, P_WALL_D);
  static const int8_t BRK[6][2] = {{16,44},{87,52},{18,77},{84,90},{44,101},{60,36}};
  for (int i = 0; i < 6; i++) { int x = BRK[i][0], y = BRK[i][1]; Q(x, y, 4, 1, P_WALL_L); Q(x + 5, y, 3, 1, P_WALL_L); Q(x + 2, y + 2, 4, 1, P_WALL_L); }
  Q(14, 104, 84, 2, P_WALL_D);
  Q(0, 106, 120, 14, P_WALL_D); Q(0, 106, 120, 1, P_WALL);                          // 人行道
  static const int8_t PV[5] = {8,30,52,74,96};
  for (int i = 0; i < 5; i++) Q(PV[i], 108, 1, 3, P_GLASS);
  Q(101, 106, 17, 1, P_WALL_L); Q(103, 107, 13, 1, P_WALL); Q(105, 108, 9, 1, P_WALL);   // 路灯光斑
  Q(109, 71, 1, 35, P_SIL); Q(108, 104, 3, 2, P_SIL); Q(109, 67, 1, 1, P_SIL); Q(107, 68, 5, 1, P_SIL); Q(108, 69, 3, 2, P_WARM);
  if (G == 1) { Q(80, 91, 10, 13, P_WOOD); Q(81, 92, 8, 12, P_ROOF); Q(82, 93, 6, 2, P_WARM_D); Q(87, 99, 1, 1, P_WARM); Q(78, 104, 14, 1, P_WALL_L); }
  for (int i = 0; i < G * G; i++) {
    WRect r = wrect(G, i);
    if (G < 3) Q(r.x - 2, r.y - 3, r.w + 4, 1, P_WALL_L);                           // 窗楣
    Q(r.x - 1, r.y - 1, r.w + 2, r.h + 2, P_WOOD); Q(r.x, r.y, r.w, r.h, P_GLASS);
    Q(r.x - 2, r.y + r.h + 1, r.w + 4, G == 3 ? 1 : 2, P_WOOD); Q(r.x - 1, r.y + r.h + (G == 3 ? 2 : 3), r.w + 2, 1, P_WALL_D);   // 窗台 + 影
  }
  if (over > 0) { char t[16]; snprintf(t, sizeof(t), "+%d", over % 100); text(115 - textW(t), 4, t, P_MOON); }
  tgt = curImg;
  B(0, 0, 120, 120);
}

// 窗内容参数（动画全由 帧号 tf + 窗号 i + 会话的 sf 决定，没有随机数）
static Prm params(const Sess* S, const WRect& r, int i, int tf) {
  Prm p; memset(&p, 0, sizeof(p));
  if (!S) { p.key.kind = 0; p.key.glass = P_GLASS; p.dark = 1; return p; }
  St st = S->st; int sf = tf - S->tf0; if (sf < 0) sf = 0;
  int t = tf + i * 5, tq = t >> 1, rng = (r.w >> 1) - (r.G == 1 ? BIGS.half : SMALL.half);
  p.key.kind = 1; p.key.glass = P_WARM; p.floor = P_WARM_D; p.key.pose = 0; p.key.px = r.cx; p.key.legs = 0; p.key.bob = 0; p.key.dir = 1;
  p.key.dots = 0; p.key.conf = -1; p.key.mark = 0; p.key.chair = 0; p.key.combo = S->combo; p.dark = 0; p.key.base = r.base;
  if (st == IDLE) { p.key.glass = P_WARM_D; p.floor = P_WOOD; p.key.chair = 1; }
  else if (st == THINK) {
    double a = tq * 0.045 + i * 1.7; p.key.pose = 1; p.key.px = r.cx + rdd(sin(a) * rng); p.key.dir = cos(a) >= 0 ? 1 : -1;
    p.key.legs = p.key.px & 1; p.key.dots = (t >> 3) % 4;
  } else if (st == TOOL) {
    int Pd = 2 * rng > 2 ? 2 * rng : 2, q = tq % Pd;
    p.key.px = r.cx - rng + (q < rng ? q : Pd - q); p.key.dir = q < rng ? 1 : -1; p.key.legs = (tq >> 1) & 1; p.key.bob = p.key.legs; p.key.pose = 2;
  } else if (st == WAIT) { p.key.pose = ((t >> 3) & 1) ? 3 : 4; p.key.base = r.base + (r.G == 1 ? 2 : 1); }
  else if (st == DONE) {
    if (sf < 36) { int q = (sf + i) >> 2; p.key.pose = 5; p.key.bob = q & 1; p.key.conf = q; }
    else if (sf < 48) { p.key.glass = P_WARM_D; p.floor = P_WOOD; }
    else { p.key.glass = P_GLASS; p.dark = 1; }
  } else if (st == ERR) {
    int c = t % 40; if ((c >= 10 && c < 12) || (c >= 26 && c < 29)) { p.key.glass = P_GLASS; p.dark = 1; }
    p.key.pose = 6; p.key.px = r.cx - (rng >> 1); p.key.mark = 1;
  }
  return p;
}

static void curtains(const WRect& r, int combo, bool lit) {
  uint16_t hue = HUES[combo & 3]; int sty = (combo >> 2) % 3, x = r.x, y = r.y, w = r.w, h = r.h;
  if (sty == 0) {
    int cw = r.G == 1 ? 7 : (r.G == 2 ? 4 : 3), ch = rdd(h * 0.62), lw = cw - 2 > 1 ? cw - 2 : 1;
    if (lit) { Q(x, y, cw, ch, hue); Q(x, y + ch, lw, h - ch, hue); Q(x + w - cw, y, cw, ch, hue); Q(x + w - lw, y + ch, lw, h - ch, hue); }
    else { Q(x + cw - 1, y, 1, ch, hue); Q(x + w - cw, y, 1, ch, hue); }
  } else if (sty == 1) {
    int vh = r.ty - y + (r.G == 1 ? 4 : (r.G == 2 ? 2 : 1)), st = r.G == 1 ? 6 : 4, sw = r.G == 1 ? 3 : 2;
    if (lit) { Q(x, y, w, vh, hue); for (int xx = x + 1; xx + sw <= x + w; xx += st) Q(xx, y + vh, sw, 1, hue); }
    else Q(x, y + vh - 1, w, 1, hue);
  } else {
    int cy = y + rdd(h * 0.76), hw = w >> 1;
    if (lit) { Q(x, cy, hw, h - (cy - y), hue); Q(x + hw + 1, cy, w - hw - 1, h - (cy - y), hue); Q(x, cy - 1, w, 1, P_WOOD); }
    else Q(x, cy, w, 1, hue);
  }
}

static void drawWin(const WRect& r, const Prm& p, int sid) {
  int s = r.s;
  clOn = true; clx = r.x; cly = r.y; clw = r.w; clh = r.h;
  Q(r.x, r.y, r.w, r.h, p.key.glass);
  if (!p.dark && r.G < 3) { int fh = r.G == 1 ? 6 : 3; Q(r.x, r.y + r.h - fh, r.w, fh, p.floor); }
  if (p.key.chair) { static const Rc CH[3] = {{0,-8,1,8},{0,-4,4,1},{3,-3,1,3}}; sprite(CH, 3, r.cx - (r.w >> 2), r.base, s, 1, P_SIL); }
  if (r.G == 1 && !p.dark && p.key.kind == 1) {                                      // 大窗：吊灯
    int lx = r.cx + 9; Q(lx, r.ty + 1, 1, 4, P_SIL); Q(lx - 3, r.ty + 5, 7, 2, P_WOOD); Q(lx - 1, r.ty + 7, 3, 1, P_MOON);
  }
  if (p.key.pose) {
    const Sp& SP = r.G == 1 ? BIGS : SMALL; int pose = p.key.pose, px = p.key.px, dir = p.key.dir, base = p.key.base - p.key.bob;
    if (pose == 6) sprite(SP.bodyE, SP.nbE, px, base, 1, dir, P_SIL); else sprite(SP.body, SP.nb, px, base, 1, dir, P_SIL);
    sprite(SP.leg[p.key.legs], SP.nleg[p.key.legs], px, base, 1, dir, P_SIL);
    sprite(SP.arm[pose], SP.narm[pose], px, base, 1, dir, P_SIL);
    if (pose == 2) sprite(SP.box, SP.nbox, px, base, 1, dir, P_WOOD);
    int d0 = SP.dot[0], dd = SP.dot[1], dy = SP.dot[2], dz = SP.dot[3];
    for (int j = 0; j < p.key.dots && j < 3; j++) Q(px + (d0 + j * dd) * dir - (dir < 0 ? dz : 0), base + dy, dz, dz, P_SIL);
  }
  if (p.key.kind == 1) curtains(r, p.key.combo, !p.dark);
  Q(r.x, r.ty, r.w, 1, P_WOOD);
  if (r.G == 1) { Q(r.x + 14, r.y, 1, r.ty - r.y, P_WOOD); Q(r.x + 29, r.y, 1, r.ty - r.y, P_WOOD); }
  if (p.key.conf >= 0) {
    for (int j = 0; j < 7; j++) {
      int cx = r.x + 1 + (int)floor(hsd(j * 7 + sid * 13) * (r.w - 2));
      int cy = r.y + ((p.key.conf * (2 + (j & 1)) + (int)floor(hsd(j * 3 + sid) * r.h)) % r.h);
      Q(cx, cy, s, s, CONF[j & 3]);
    }
  }
  if (p.key.mark) { Q(r.x + r.w - 2 - s, r.ty + 2 * s, s, 3 * s, P_RED); Q(r.x + r.w - 2 - s, r.ty + 6 * s, s, s, P_RED); }
  if (p.dark) { for (int j = 0; j < (r.G == 1 ? 3 : 2); j++) Q(r.x + 2 + j * s, r.ty + 2 + (2 - j) * s, s, s, P_WALL_L); }
  if (p.key.kind == 1) {
    int x0 = r.x + r.w - 2 - 3 * s, y0 = r.y + r.h - 2 * s;
    Q(x0, y0, 3 * s, 2 * s, P_WALL_L); Q(x0, y0 - 2 * s, s, s, P_GREEN); Q(x0 + s, y0 - 3 * s, s, 3 * s, P_GREEN); Q(x0 + 2 * s, y0 - 2 * s, s, s, P_GREEN);
  }
  clOn = false;
}

// 窗重画前先留一份快照，画完逐小块比较，只有真的变了的小块才进脏表（避免整窗重推）
static uint16_t snap[48 * 42];
static void trackBegin(const WRect& r) {
  trk = true;
  for (int y = 0; y < r.h; y++) memcpy(snap + y * r.w, curImg + (r.y + y) * LW + r.x, r.w * 2);
}
static void trackEnd(const WRect& r) {
  trk = false;
  for (int y = 0; y < r.h; y++) {
    const uint16_t* a = snap + y * r.w; const uint16_t* b = curImg + (r.y + y) * LW + r.x;
    for (int x = 0; x < r.w; x++) if (a[x] != b[x]) dirtyT[((r.y + y) / TILE) * TN + (r.x + x) / TILE] = true, anyDirty = true;
  }
}

static void houseDraw(int tf) {
  houseOps = 0;
  int G, over; townLayout(G, over);
  int sig = G * 100 + over;
  if (sig != townSig || townForce) {
    townSig = sig; townForce = false; renderBg(G, over);
    for (int i = 0; i < NWIN; i++) { wkeyOk[i] = false; fkeys[i] = 0; }
    bkey = 0; skey = -1; lkey = 0; lrectOk = false;
  }
  bool busy = false; int nw = 0; const Sess* wS[NWIN]; WRect wR[NWIN];
  for (int i = 0; i < G * G; i++) {
    const Sess* S = slotSid[i] < 0 ? nullptr : S_(slotSid[i]);
    if (S && S->st == TOOL) busy = true;
    if (S && S->st == WAIT) { wS[nw] = S; wR[nw] = wrect(G, i); nw++; }
  }
  // 烟囱：有会话在跑工具时冒几粒烟
  int sk = busy ? (tf >> 2) + 1 : 0;
  if (sk != skey) {
    skey = sk; Q(73, 2, 16, 11, P_SKY);
    if (busy) for (int k = 0; k < 3; k++) {
      int a = ((tf >> 2) + k * 5) % 15, y = 11 - (a * 9 / 14), x = 77 + (a >> 2) + (k == 1 ? 1 : 0), z = a < 5 ? 2 : 1;
      if (y + z <= 13) Q(x, y, z, z, a < 5 ? P_WALL_L : P_WALL);
    }
  }
  // 等待标签：多个同时在等时，每 2.5 秒轮换
  bool anyWait = false; for (int i = 0; i < nSess; i++) if (sess[i].st == WAIT) anyWait = true;
  int lk = 0; const Sess* ls = nullptr; WRect lr;
  if (nw) { int k = (tf / 50) % nw; ls = wS[k]; lr = wR[k]; lk = ls->sid * 100 + G * 10 + (ls->slot + 1); }
  if (lk != lkey && houseOps + 48 <= BUDGET) {
    lkey = lk;
    if (lrectOk) { B(lrx, lry, lrw, lrh); lrectOk = false; }
    if (lk) {
      char t[8]; int n = 0; while (n < 6 && ls->name[n]) { t[n] = toupper((unsigned char)ls->name[n]); n++; } t[n] = 0;
      int tw = textW(t), lx = lr.cx - (tw >> 1);
      lrx = lx - 2; lry = lr.ly - 1; lrw = tw + 4; lrh = 7; lrectOk = true;
      Q(lrx, lry, lrw, lrh, P_GLASS); text(lx, lr.ly, t, P_AMBER);
    }
  }
  // 琥珀边框：常亮，0.8 秒一档明暗交替
  int bk = anyWait ? (((tf >> 4) & 1) ? 2 : 1) : 0;
  if (bk != bkey) {
    bkey = bk;
    if (bk) { uint16_t c = bk == 1 ? P_AMBER : P_WARM_D; Q(0, 0, 120, 2, c); Q(0, 118, 120, 2, c); Q(0, 2, 2, 116, c); Q(118, 2, 2, 116, c); }
    else { B(0, 0, 120, 2); B(0, 118, 120, 2); B(0, 2, 2, 116); B(118, 2, 2, 116); }
  }
  // 窗：只重画内容变了的；按轮转顺序，每帧预算 150 图元，超了的留到下一帧
  int n = G * G, WCOST = G == 1 ? 45 : 32;
  for (int k = 0; k < n; k++) {
    int i = (k + tf) % n; const Sess* S = slotSid[i] < 0 ? nullptr : S_(slotSid[i]); WRect r = wrect(G, i);
    uint8_t fk = S ? (S->st == WAIT ? 'a' : 'w') : 'v';
    if (fk != fkeys[i] && houseOps + 4 <= BUDGET) {
      fkeys[i] = fk; uint16_t c = fk == 'a' ? P_AMBER : (fk == 'w' ? P_WOOD : P_WALL_D);
      Q(r.x - 1, r.y - 1, r.w + 2, 1, c); Q(r.x - 1, r.y + r.h, r.w + 2, 1, c); Q(r.x - 1, r.y, 1, r.h, c); Q(r.x + r.w, r.y, 1, r.h, c);
    }
    Prm p = params(S, r, i, tf);
    if ((!wkeyOk[i] || memcmp(&p.key, &wkeys[i], sizeof(WKey))) && houseOps + WCOST <= BUDGET) {
      wkeys[i] = p.key; wkeyOk[i] = true;
      trackBegin(r); drawWin(r, p, S ? S->sid : 0); trackEnd(r);
    }
  }
  if (houseOps > houseOpsPeak) houseOpsPeak = houseOps;
}

// 把脏小块合并成矩形，放大 2 倍，一个矩形一次写屏
static void pushLogical(int x, int y, int w, int h) {
  int lr = MAXPIX / (4 * w); if (lr < 1) lr = 1;
  for (int yy = y; yy < y + h; yy += lr) {
    int n = (yy + lr > y + h) ? (y + h - yy) : lr;
    for (int r = 0; r < n; r++) {
      const uint16_t* src = curImg + (yy + r) * LW + x;
      uint16_t* d0 = buf + (r * 2) * (2 * w);
      for (int i = 0; i < w; i++) { d0[2 * i] = src[i]; d0[2 * i + 1] = src[i]; }
      memcpy(d0 + 2 * w, d0, 2 * w * 2);
    }
    tft.startWrite();
    tft.setAddrWindow(2 * x, 2 * yy, 2 * w, 2 * n);
    tft.writePixels(buf, (uint32_t)(4 * w * n));
    tft.endWrite();
    pxTotal += (uint32_t)(4 * w * n);
  }
}
static void housePush() {
  if (!anyDirty) return;
  anyDirty = false;
  for (int ty = 0; ty < TN; ty++)
    for (int tx = 0; tx < TN; tx++) {
      if (!dirtyT[ty * TN + tx]) continue;
      int w = 1; while (tx + w < TN && dirtyT[ty * TN + tx + w]) w++;
      int h = 1;
      for (;;) {
        if (ty + h >= TN) break;
        bool all = true; for (int k = 0; k < w; k++) if (!dirtyT[(ty + h) * TN + tx + k]) { all = false; break; }
        if (!all) break;
        h++;
      }
      for (int yy = 0; yy < h; yy++) for (int k = 0; k < w; k++) dirtyT[(ty + yy) * TN + tx + k] = false;
      pushLogical(tx * TILE, ty * TILE, w * TILE, h * TILE);
    }
}
static void houseFrame(int tf) { houseDraw(tf); housePush(); }
static void house_init() {}
static void house_enter(St, St) {}
static void house_update(St, int, int) {}

// ========================================================================
//  画面表（以后加"盆栽""潮汐"：写好一组函数，加到这里）
//  house 走自己的渲染路径（houseFrame），draw/dirty 为空
// ========================================================================
static const Scene SCENES[] = {
  {"stars",  stars_init, stars_enter, stars_update, stars_draw, stars_dirty},
  {"window", win_init,   win_enter,   win_update,   win_draw,   win_dirty},
  {"house",  house_init, house_enter, house_update, nullptr,    nullptr},
};
#define NSCENES (int)(sizeof(SCENES) / sizeof(SCENES[0]))

// ========================================================================
//  渲染器（星图 / 小窗：脏矩形 + 小缓冲；小楼：见上）
// ========================================================================
static void blit(int x, int y, int w, int h) {
  tft.startWrite();
  tft.setAddrWindow(x, y, w, h);
  tft.writePixels(buf, (uint32_t)w * h);
  tft.endWrite();
  pxTotal += (uint32_t)w * h;
}
static void paintRect(int x, int y, int w, int h) {
  if (x < 0) { w += x; x = 0; }
  if (y < 0) { h += y; y = 0; }
  if (x + w > SCR_W) w = SCR_W - x;
  if (y + h > SCR_H) h = SCR_H - y;
  if (w <= 0 || h <= 0) return;
  int rows = MAXPIX / w;
  for (int yy = y; yy < y + h; yy += rows) {
    ox = x; oy = yy; rw = w; rh = (yy + rows > y + h) ? (y + h - yy) : rows;
    SCENES[sceneI].draw(state, tfNow - stateTf0, tfNow);
    blit(ox, oy, rw, rh);
  }
}
static bool sameRect(const El& a, const El& b) { return a.x == b.x && a.y == b.y && a.w == b.w && a.h == b.h; }

static void renderFrame() {
  if (sceneI == SCN_HOUSE) {
    if (needFull) { needFull = false; townForce = true; }
    houseFrame(tfNow);
    return;
  }
  int sf = tfNow - stateTf0;
  const Scene& sc = SCENES[sceneI];
  sc.update(state, sf, tfNow);
  nCur = 0; sc.dirty(state, sf, tfNow);
  if (needFull) {
    needFull = false;
    paintRect(0, 0, SCR_W, SCR_H);
  } else {
    // 签名没变的元素跳过；新增/变化的画 cur 矩形，消失/变化的画 prev 矩形
    static bool curHit[MAXEL];
    for (int i = 0; i < nCur; i++) {
      bool found = false;
      for (int j = 0; j < nPrev && !found; j++)
        if (sameRect(curEl[i], prevEl[j]) && curEl[i].key == prevEl[j].key) found = true;
      curHit[i] = found;
    }
    for (int j = 0; j < nPrev; j++) {          // prev 里没匹配到的：旧位置要擦
      bool found = false, dup = false;
      for (int i = 0; i < nCur && !found; i++)
        if (sameRect(curEl[i], prevEl[j]) && curEl[i].key == prevEl[j].key) found = true;
      if (found) continue;
      for (int i = 0; i < nCur && !dup; i++) if (!curHit[i] && sameRect(curEl[i], prevEl[j])) dup = true;
      if (!dup) paintRect(prevEl[j].x, prevEl[j].y, prevEl[j].w, prevEl[j].h);
    }
    for (int i = 0; i < nCur; i++)
      if (!curHit[i]) paintRect(curEl[i].x, curEl[i].y, curEl[i].w, curEl[i].h);
  }
  memcpy(prevEl, curEl, sizeof(El) * nCur); nPrev = nCur;
}

// 选中会话（或其状态）变了：星图/小窗跟着变；小楼不需要整屏重画
static void applySel(St p, bool callEnter) {
  tfNow = nowTf();
  St n = selState(); Sess* s = curSel();
  state = n; stateTf0 = s ? s->tf0 : tfNow;
  if (callEnter) for (int i = 0; i < NSCENES; i++) SCENES[i].enter(p, n);
  if (sceneI != SCN_HOUSE) needFull = true;
}
static void setScene(int i) {
  sceneI = ((i % NSCENES) + NSCENES) % NSCENES;
  tfNow = nowTf();
  needFull = true;
  Serial.printf("scene -> %d (%s)\n", sceneI, SCENES[sceneI].name);
}

// ========================================================================
//  多会话自动演示：4 条"车道"，每条 60 秒一圈（照搬网页版 LANES）
//  16–22 秒 h1-fw 与 webapp 同时在等；notes 在 28 秒结束（暗窗），44 秒起新的 notes 住进同一扇窗
// ========================================================================
#define ENDS 255
static const LaneStep L_H1[] = {{THINK,3},{TOOL,7},{THINK,3},{WAIT,9},{TOOL,6},{DONE,4},{IDLE,6},{THINK,4},{TOOL,8},{DONE,4},{IDLE,6}};
static const LaneStep L_WEB[] = {{TOOL,5},{THINK,6},{TOOL,5},{WAIT,8},{THINK,4},{TOOL,6},{ERR,4},{THINK,4},{TOOL,6},{DONE,4},{IDLE,8}};
static const LaneStep L_NOTES[] = {{IDLE,4},{THINK,5},{TOOL,9},{DONE,5},{IDLE,5},{ENDS,16},{THINK,4},{TOOL,6},{WAIT,6}};
static const LaneStep L_API[] = {{IDLE,8},{THINK,4},{TOOL,4},{ERR,5},{THINK,4},{TOOL,10},{WAIT,5},{TOOL,5},{DONE,4},{IDLE,11}};
static Lane lanes[4] = {
  {"h1-fw", L_H1, NA(L_H1), 0, 0, -1}, {"webapp", L_WEB, NA(L_WEB), 0, 0, -1},
  {"notes", L_NOTES, NA(L_NOTES), 0, 0, -1}, {"api", L_API, NA(L_API), 0, 0, -1}};
static bool demoOn = false;

static void applyLane(Lane& L) {
  uint8_t st = L.steps[L.i].st;
  if (st == ENDS) { if (L.sid >= 0) { endSession(L.sid); L.sid = -1; } }
  else if (L.sid < 0 || !S_(L.sid)) L.sid = addSession(L.name, (St)st);
  else setSessionState(L.sid, (St)st);
}
static void startDemo() {
  sessReset();
  demoOn = true;
  uint32_t now = millis();
  for (int k = 0; k < 4; k++) { lanes[k].i = 0; lanes[k].t0 = now; lanes[k].sid = -1; }
  tfNow = nowTf();
  for (int k = 0; k < 4; k++) applyLane(lanes[k]);
  selectSess(lanes[0].sid);
  Serial.println("ok demo on");
}
static void demoTick() {
  if (!demoOn) return;
  uint32_t now = millis();
  for (int k = 0; k < 4; k++) {
    Lane& L = lanes[k];
    while (now - L.t0 >= (uint32_t)L.steps[L.i].sec * 1000UL) {
      L.t0 += (uint32_t)L.steps[L.i].sec * 1000UL;
      L.i = (L.i + 1) % L.n;
      applyLane(L);
    }
  }
}
// 手动改会话（串口 new/set/end 或按钮）时自动关演示，免得演示剧本跟你打架
static void manual() { if (demoOn) { demoOn = false; Serial.println("note: demo off (manual change)"); } }

// ========================================================================
//  串口命令（一行一条，大小写不敏感，回显以 ok / err 开头）
// ========================================================================
static const char* winText(const Sess& s, char* b, size_t n) {
  if (s.slot < 0) snprintf(b, n, "queue"); else snprintf(b, n, "%d", s.slot + 1);
  return b;
}
static bool parseState(const String& a, St& out) {
  for (int i = 0; i < NST; i++) if (a == ST_NAME[i]) { out = (St)i; return true; }
  if (a == "err") { out = ERR; return true; }
  return false;
}
static bool parseSid(const String& a, int& out) {
  if (!a.length() || a.length() > 5) return false;
  for (unsigned i = 0; i < a.length(); i++) if (!isDigit(a[i])) return false;
  out = a.toInt(); return true;
}
static bool validName(const String& a) {
  if (!a.length() || a.length() > 15) return false;
  for (unsigned i = 0; i < a.length(); i++) { char c = a[i]; if (!(isAlphaNumeric(c) || c == '-' || c == '_' || c == '.')) return false; }
  return true;
}
static String nextTok(String& rest) {
  rest.trim();
  int sp = rest.indexOf(' ');
  String t = sp < 0 ? rest : rest.substring(0, sp);
  rest = sp < 0 ? String("") : rest.substring(sp + 1);
  rest.trim();
  return t;
}
static void printHelp() {
  Serial.println("commands (one per line, case-insensitive):");
  Serial.println("  new [name]          new session -> 'ok new sid=N name=X win=K|queue'");
  Serial.println("  set <sid> <state>   state = idle|think|tool|wait|done|error");
  Serial.println("  end <sid>           end session (its window goes dark)");
  Serial.println("  clear               clear dark windows");
  Serial.println("  list                list sessions");
  Serial.println("  sel <sid>           select session (stars/window scenes + button 1 follow it)");
  Serial.println("  demo on|off         multi-session auto demo");
  Serial.println("  scene 0..2|stars|window|house");
  Serial.println("  idle|think|tool|wait|done|error   set state of the selected session");
}
static void handleLine(String s) {
  s.trim(); s.toLowerCase();
  if (!s.length()) return;
  String rest = s; String cmd = nextTok(rest);
  St st;
  if (parseState(cmd, st)) {                                   // 兼容旧命令：改选中会话的状态
    if (rest.length()) { Serial.printf("err %s: unexpected argument '%s'\n", cmd.c_str(), rest.c_str()); return; }
    manual();
    if (!curSel()) { int sid = addSession("main", st); if (sid < 0) { Serial.println("err full"); return; } }
    else setSessionState(selSid, st);
    Serial.printf("ok state sid=%d state=%s\n", selSid, ST_NAME[st]);
    return;
  }
  if (cmd == "new") {
    String nm = nextTok(rest);
    if (rest.length()) { Serial.println("err new: usage: new [name]"); return; }
    if (nm.length() && !validName(nm)) { Serial.println("err new: bad name (1-15 chars of a-z 0-9 - _ .)"); return; }
    manual();
    int sid = addSession(nm.length() ? nm.c_str() : nullptr, IDLE);
    if (sid < 0) { Serial.printf("err new: full (%d sessions)\n", MAXSESS); return; }
    Sess* x = S_(sid); char b[8];
    Serial.printf("ok new sid=%d name=%s win=%s\n", sid, x->name, winText(*x, b, sizeof(b)));
    return;
  }
  if (cmd == "set") {
    String a = nextTok(rest), b = nextTok(rest); int sid;
    if (!a.length() || !b.length() || rest.length()) { Serial.println("err set: usage: set <sid> <idle|think|tool|wait|done|error>"); return; }
    if (!parseSid(a, sid)) { Serial.printf("err set: bad session id '%s'\n", a.c_str()); return; }
    if (!parseState(b, st)) { Serial.printf("err set: bad state '%s' (idle|think|tool|wait|done|error)\n", b.c_str()); return; }
    if (!S_(sid)) { Serial.printf("err set: no such session %d\n", sid); return; }
    manual(); setSessionState(sid, st);
    Serial.printf("ok set sid=%d state=%s\n", sid, ST_NAME[st]);
    return;
  }
  if (cmd == "end" || cmd == "sel") {
    String a = nextTok(rest); int sid;
    if (!a.length() || rest.length()) { Serial.printf("err %s: usage: %s <sid>\n", cmd.c_str(), cmd.c_str()); return; }
    if (!parseSid(a, sid)) { Serial.printf("err %s: bad session id '%s'\n", cmd.c_str(), a.c_str()); return; }
    if (!S_(sid)) { Serial.printf("err %s: no such session %d\n", cmd.c_str(), sid); return; }
    if (cmd == "end") { manual(); endSession(sid); Serial.printf("ok end sid=%d\n", sid); }
    else { selectSess(sid); Serial.printf("ok sel sid=%d\n", sid); }
    return;
  }
  if (cmd == "clear") {
    if (rest.length()) { Serial.println("err clear: takes no argument"); return; }
    int n = countVacant(); clearVacant(); Serial.printf("ok clear dark=%d\n", n); return;
  }
  if (cmd == "list") {
    if (rest.length()) { Serial.println("err list: takes no argument"); return; }
    int G, over; townLayout(G, over);
    Serial.printf("ok list n=%d layout=%s queued=%d dark=%d demo=%s sel=%d\n", nSess, G == 1 ? "1" : (G == 2 ? "2x2" : "3x3"), over, countVacant(), demoOn ? "on" : "off", selSid);
    for (int i = 0; i < nSess; i++) {
      char b[8];
      Serial.printf("  sid=%d name=%s state=%s win=%s%s\n", sess[i].sid, sess[i].name, ST_NAME[sess[i].st], winText(sess[i], b, sizeof(b)), sess[i].sid == selSid ? " *" : "");
    }
    return;
  }
  if (cmd == "demo" || cmd == "auto") {
    String a = nextTok(rest);
    if (rest.length() || (a != "on" && a != "off")) { Serial.printf("err %s: usage: %s on|off\n", cmd.c_str(), cmd.c_str()); return; }
    if (a == "on") startDemo(); else { demoOn = false; Serial.println("ok demo off"); }
    return;
  }
  if (cmd == "scene") {
    String a = nextTok(rest);
    if (rest.length()) { Serial.println("err scene: usage: scene 0..2|stars|window|house"); return; }
    for (int i = 0; i < NSCENES; i++) if (a == SCENES[i].name) { setScene(i); return; }
    if (a.length() == 1 && isDigit(a[0]) && a.toInt() < NSCENES) { setScene(a.toInt()); return; }
    Serial.println("err scene: usage: scene 0..2|stars|window|house"); return;
  }
  if (cmd == "help" || cmd == "?") { printHelp(); return; }
  Serial.printf("err unknown command '%s' (try: help)\n", cmd.c_str());
}
static void pollSerial() {
  static String line;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') { handleLine(line); line = ""; }
    else if (line.length() < 60) line += c;
  }
}

// ---------- 仿真用按钮 ----------
// 按钮 1：给"当前选中会话"切到下一个状态（没有会话就先建一个 main）；按钮 2：切画面
static void pollButtons() {
  static uint32_t lastPress = 0;
  static bool prevS = HIGH, prevC = HIGH;
  bool s = digitalRead(BTN_STATE_PIN), c = digitalRead(BTN_SCENE_PIN);
  uint32_t now = millis();
  if (now - lastPress > 200) {
    if (prevS == HIGH && s == LOW) {
      lastPress = now; manual();
      if (!curSel()) addSession("main", IDLE);
      Sess* x = curSel();
      if (x) { St nx = (St)((x->st + 1) % NST); setSessionState(x->sid, nx); Serial.printf("button1: sid=%d state=%s\n", x->sid, ST_NAME[nx]); }
    }
    if (prevC == HIGH && c == LOW) { lastPress = now; setScene(sceneI + 1); }
  }
  prevS = s; prevC = c;
}

void setup() {
  Serial.begin(115200);
  pinMode(BTN_STATE_PIN, INPUT_PULLUP);
  pinMode(BTN_SCENE_PIN, INPUT_PULLUP);
  displayInit();
  for (int i = 0; i < NSCENES; i++) SCENES[i].init();
  t0 = millis();
  sessReset();
  Serial.println("desk-h1 sim ready. type 'help' for commands");
  setScene(SCN_HOUSE);
  startDemo();
}

void loop() {
  pollSerial();
  pollButtons();
  demoTick();
  int tf = (int)((millis() - t0) / 50);          // 20 帧/秒的时间基准
  if (tf == lastTf && !needFull) return;
  lastTf = tf; tfNow = tf;
  renderFrame();
  // 帧率统计（每 5 秒一行串口输出）
  static uint32_t statT = 0, frames = 0;
  frames++;
  uint32_t now = millis();
  if (now - statT >= 5000) {
    if (statT) Serial.printf("[stat] %.1f fps, %lu px/frame, sessions=%d, ops-peak=%d, scene=%s state=%s\n",
                             frames * 1000.0f / (now - statT), (unsigned long)(pxTotal / (frames ? frames : 1)),
                             nSess, houseOpsPeak, SCENES[sceneI].name, ST_NAME[state]);
    statT = now; frames = 0; pxTotal = 0; houseOpsPeak = 0;
  }
}
