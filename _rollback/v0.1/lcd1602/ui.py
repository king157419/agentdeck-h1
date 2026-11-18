# Agent 状态屏 v0.1：纯逻辑，不依赖硬件、系统时钟或 MicroPython 专有模块。
VERSION = "0.1"
STATES = ("idle", "think", "tool", "wait", "done", "error")
PRIO = {"wait": 6, "error": 5, "tool": 3, "think": 2, "done": 1, "idle": 0}
WORD = {"idle": b"READY", "think": b"THINK", "tool": b"TOOL",
        "wait": b"WAIT!", "done": b"DONE", "error": b"ERROR"}
AGENT = {"cc": b"Claude", "cx": b"Codex", "ds": b"DSK"}
MAXSESS = 8
NAME_LIMIT = 24
FOCUS_MS = 60000
REINIT_MS = 5 * 60 * 1000
TTL = {"idle": 15 * 60, "done": 15 * 60, "think": 3 * 3600,
       "tool": 3 * 3600, "wait": 12 * 3600, "error": 3600}

# 每张图为 10×16；第 5/6 列和第 8/9 行之间有字符格的物理间隙。
ART = {
    "cc": (
        # 小螃蟹：方块身体、两只深色眼睛、两侧伸出的钳子、四条腿
        "..........", "..........", "..######..", ".########.",
        ".########.", ".#.####.#.", ".#.####.#.", "##########",
        "##########", ".########.", ".########.", ".########.",
        ".#.#..#.#.", ".#.#..#.#.", ".#.#..#.#.", ".........."),
    "cx": (
        # 终端窗口：粗标题栏，里面是 > 和 _
        "..........", "##########", "##########", "#........#",
        "#.#......#", "#..#.....#", "#...#....#", "#....#...#",
        "#...#....#", "#..#.....#", "#.#..###.#", "#........#",
        "##########", "..........", "..........", ".........."),
    "ds": (
        # 鲸鱼：头朝右，头顶喷水，左边翘起的尾巴，右边一只深色眼睛
        "..........", ".....#.#..", "......#...", "......#...",
        "#.#.......", ".#..####..", ".#.######.", ".########.",
        ".######.##", ".#########", "..#######.", "...#####..",
        "..........", "..........", "..........", ".........."),
    "robot": (
        ".########.", "##########", "#..####..#", "#..####..#",
        "##########", "###....###", ".########.", "...####...",
        "..######..", ".########.", "#.######.#", "#.######.#",
        "..######..", "..##..##..", "..##..##..", ".###..###."),
    "sleep": (
        ".########.", "##########", "##########", "#..####..#",
        "##########", "###....###", ".########.", "...####...",
        "..######..", ".########.", "#.######.#", "#.######.#",
        "..######..", "..##..##..", "..##..##..", ".###..###."),
    "wait": (
        "..........", "...####...", "...####...", "...####...",
        "...####...", "...####...", "...####...", "...####...",
        "...####...", "....##....", "..........", "..........",
        "...####...", "...####...", "..........", ".........."),
    "done": (
        "..........", "..........", "........##", ".......###",
        ".......###", "......###.", "......###.", ".....###..",
        "##...###..", "###.###...", ".######...", "..####....",
        "...##.....", "..........", "..........", ".........."),
    "error": (
        "..........", "##......##", "###....###", ".###..###.",
        "..######..", "...####...", "...####...", "....##....",
        "...####...", "..######..", ".###..###.", "###....###",
        "##......##", "..........", "..........", ".........."),
}


def shift(bitmap, dx=0, dy=0):
    """平移点阵，超出边界的像素丢弃，空位补暗；四个方向共用此函数。"""
    return tuple("".join(bitmap[y - dy][x - dx]
                         if 0 <= y - dy < 16 and 0 <= x - dx < 10 else "."
                         for x in range(10)) for y in range(16))


def to_glyphs(bitmap):
    """依次返回左上、右上、左下、右下四个字符。"""
    return tuple(bytes(sum((1 << (4 - x)) if bitmap[y + row][x + col] == "#" else 0
                           for x in range(5)) for y in range(8))
                 for row, col in ((0, 0), (0, 5), (8, 0), (8, 5)))


# 开机一次性转换；动画期间只选择已有字节串。
FRAMES = {}
for _key, _art in ART.items():
    FRAMES[_key] = (to_glyphs(_art), to_glyphs(shift(_art, dy=-1)),
                    to_glyphs(shift(_art, dy=1)), to_glyphs(shift(_art, dx=-1)),
                    to_glyphs(shift(_art, dx=1)))

I_WAIT = (b"\x04\x0e\x0e\x0e\x04\x00\x04\x00",
          b"\x1f\x11\x15\x15\x11\x15\x1f\x00")
I_DONE = b"\x00\x01\x03\x16\x1c\x08\x00\x00"
I_ERR = b"\x00\x1b\x0e\x04\x0e\x1b\x00\x00"
I_SPIN = (b"\x00\x04\x04\x04\x04\x04\x00\x00",
          b"\x00\x10\x08\x04\x02\x01\x00\x00",
          b"\x00\x00\x00\x1f\x00\x00\x00\x00",
          b"\x00\x01\x02\x04\x08\x10\x00\x00")


def clean(text, limit=NAME_LIMIT):
    return bytes(47 if ord(c) == 92 else ord(c) if 32 <= ord(c) < 126 else 63
                 for c in text)[:limit]


def marquee(name, width, elapsed):
    """往返滚动：两端各停两秒，中间每四百毫秒一格。"""
    distance = len(name) - width
    if distance <= 0:
        return name
    # 第一格在暂停结束时移动，最后一格抵达后立即开始另一端的两秒暂停。
    travel = (distance - 1) * 400
    phase = elapsed % (4000 + 2 * travel)
    if phase < 2000:
        offset = 0
    elif phase < 2000 + travel:
        offset = min(distance, 1 + (phase - 2000) // 400)
    elif phase < 4000 + travel:
        offset = distance
    else:
        offset = max(0, distance - 1 - (phase - 4000 - travel) // 400)
    return name[offset:offset + width]


class UI:
    def __init__(self, lcd, led):
        self.lcd, self.led = lcd, led
        self.sess, self.order = {}, []
        self.focus_target, self.focus_at = None, 0
        self.sequence = 0
        self.rows = [b" " * 16, b" " * 16]
        self.glyphs = [None] * 8
        self.scroll_context, self.scroll_at = None, 0

    def invalidate(self):
        # 屏幕重新初始化后，CGRAM 和两行内容都必须恢复。
        self.glyphs = [None] * 8

    def glyph(self, idx, rows):
        if self.glyphs[idx] != rows:
            self.lcd.glyph(idx, rows)
            self.glyphs[idx] = rows

    def show(self, row, data):
        self.rows[row] = (bytes(data) + b" " * 16)[:16]
        self.lcd.show(row, self.rows[row])

    def drop(self, key):
        self.sess.pop(key, None)
        if key in self.order:
            self.order.remove(key)

    def handle(self, line, now):
        # 串口可能收到任意坏行；协议错误只回 err，不能打断主循环。
        try:
            return self._handle(line, now)
        except Exception:
            return "err bad command"

    def _handle(self, line, now):
        parts = line.strip().split()
        if not parts:
            return None
        cmd = parts[0].lower()
        if cmd == "set":
            if len(parts) < 3:
                return "err set: usage: set <key> <state> [name]"
            key, state = parts[1], parts[2].lower()
            if state not in PRIO:
                return "err set: bad state '%s' (%s)" % (state, "|".join(STATES))
            old = self.sess.get(key)
            if old is None:
                if len(self.order) >= MAXSESS:
                    candidates = [k for k in self.order if self.sess[k][1] in ("idle", "done")]
                    if not candidates:
                        return "err set: full (%d sessions)" % MAXSESS
                    self.drop(min(candidates, key=lambda k: self.sess[k][2]))
                self.order.append(key)
            name = clean(" ".join(parts[3:])) if len(parts) > 3 else (old[0] if old else clean(key))
            since = old[3] if old and old[1] == state else now
            self.sequence += 1
            self.sess[key] = [name, state, now, since, self.sequence]
            return "ok set %s %s" % (key, state)
        if cmd == "focus":
            if len(parts) != 2:
                return "err focus: usage: focus <key|cc|cx|ds|->"
            self.focus_target = None if parts[1] == "-" else parts[1]
            self.focus_at = now
            return "ok focus %s" % parts[1]
        if cmd == "end":
            if len(parts) != 2:
                return "err end: usage: end <key>"
            if parts[1] not in self.sess:
                return "err end: no such session '%s'" % parts[1]
            self.drop(parts[1])
            return "ok end %s" % parts[1]
        if cmd in ("clear", "list", "ping", "dump") and len(parts) != 1:
            return "err %s: unexpected arguments" % cmd
        if cmd == "clear":
            count = len(self.order)
            self.sess.clear()
            del self.order[:]
            return "ok clear %d" % count
        if cmd == "list":
            return "\n".join(["ok list n=%d" % len(self.order)] +
                             ["  %s %s %s" % (k, self.sess[k][1], self.sess[k][0].decode())
                              for k in self.order])
        if cmd == "ping":
            return "ok pong agent-lcd %s sessions=%d" % (VERSION, len(self.order))
        if cmd == "dump":
            h = lambda data: "".join("%02x" % c for c in data)
            return "ok dump %s %s %s" % (h(self.rows[0]), h(self.rows[1]),
                    " ".join(h(g) if g is not None else "-" for g in self.glyphs))
        return "err unknown command '%s' (set|end|clear|list|ping|dump|focus)" % cmd

    def expire(self, now):
        for key in list(self.order):
            if now - self.sess[key][2] > TTL[self.sess[key][1]] * 1000:
                self.drop(key)
        if self.focus_target is not None and now - self.focus_at >= FOCUS_MS:
            self.focus_target = None

    def rank(self, key, now):
        session = self.sess[key]
        return 4 if session[1] == "done" and now - session[3] < 5000 else PRIO[session[1]]

    def choose(self, now):
        self.expire(now)
        if self.focus_target is not None:
            if self.focus_target in AGENT:
                keys = [k for k in self.order if k[:2] == self.focus_target]
                return max(keys, key=lambda k: (self.sess[k][2], self.sess[k][4])) if keys else None
            return self.focus_target if self.focus_target in self.sess else None
        if not self.order:
            return None
        top = max(self.rank(k, now) for k in self.order)
        keys = [k for k in self.order if self.rank(k, now) == top]
        return keys[(now // 3000) % len(keys)]

    def ribbon(self, now):
        if len(self.order) < 2:
            return b""
        icons = {"idle": 46, "think": 7, "tool": 62 if (now // 200) % 2 else 126,
                 "wait": 4 if (now // 400) % 2 == 0 else 32, "done": 5, "error": 6}
        return bytes(icons[self.sess[k][1]] for k in self.order)

    def render(self, now):
        key = self.choose(now)
        self.glyph(4, I_WAIT[(now // 400) % 2])
        self.glyph(5, I_DONE)
        self.glyph(6, I_ERR)
        self.glyph(7, I_SPIN[(now // 250) % 4])
        focused = self.focus_target is not None
        prefix = key[:2] if key else self.focus_target[:2] if focused else "robot"
        mascot = prefix if prefix in AGENT else "robot"
        name, state, age = b"ready to work", "idle", 0
        if key is not None:
            name, state, updated, since, seq = self.sess[key]
            age = max(0, now - since)
        frame = FRAMES[mascot][0]
        word = WORD[state]
        suffix = b""
        if key is None and not focused:
            frame = FRAMES["sleep"][0]
            heading = b"Agent Monitor"
        else:
            if state == "idle":
                frame = FRAMES[mascot][1 if now % 5000 >= 4850 else 0]
            elif state == "think":
                frame = FRAMES[mascot][1 + (age // 600) % 2]
                suffix = b"\x07"
            elif state == "tool":
                frame = FRAMES[mascot][3 + (age // 200) % 2]
                suffix = b">" if (age // 200) % 2 == 0 else b"\x7e"
            elif state == "wait":
                if (age // 400) % 2 == 0:
                    frame = FRAMES["wait"][0]
                else:
                    word = b">YOU<"
            elif state == "done":
                if age < 3000:
                    frame = FRAMES["done"][0]
                else:
                    suffix = b"\x05"
            elif state == "error" and (age // 500) % 2 == 0:
                frame = FRAMES["error"][0]
            heading = AGENT.get(prefix, b"Agent") + b" " + word + suffix
        for idx in range(4):
            self.glyph(idx, frame[idx])
        self.show(0, b"\x00\x01 " + heading)
        tail = self.ribbon(now)
        if not tail and key is not None and state != "idle":
            seconds = age // 1000
            tail = ("%ds" % seconds if seconds < 60 else "%dm" % (seconds // 60)
                    if seconds < 3600 else "%dh" % (seconds // 3600)).encode()
        width = 13 - len(tail) - (1 if tail else 0)
        context = (key, name, width)
        if context != self.scroll_context:
            self.scroll_context, self.scroll_at = context, now
        text = marquee(name, width, now - self.scroll_at)
        self.show(1, b"\x02\x03 " + text + b" " * (13 - len(text) - len(tail)) + tail)
        alert = state in ("wait", "error") or any(self.sess[k][1] == "wait" for k in self.order)
        self.led((now // 400) % 2 if alert else 0)
