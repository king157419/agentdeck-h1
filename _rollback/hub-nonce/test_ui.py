"""离线纯断言测试：不导入硬件模块、不访问串口或用户配置。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lcd1602"))
from ui import UI, ART, FRAMES, DANCE, DANCE_FRAMES, TTL, clean, shift, to_glyphs, marquee


class FakeLCD:
    def __init__(self):
        self.rows = [b" " * 16, b" " * 16]
        self.glyphs = [None] * 8
        self.writes = []

    def show(self, row, data):
        assert len(data) == 16
        self.rows[row] = bytes(data)

    def glyph(self, idx, rows):
        assert 0 <= idx < 8 and len(rows) == 8 and max(rows) < 32
        self.glyphs[idx] = bytes(rows)
        self.writes.append((idx, bytes(rows)))


def make_ui():
    lcd, lights = FakeLCD(), []
    return UI(lcd, lights.append), lcd, lights


def test_layout_states():
    for tool, label in (("cc", b"Claude"), ("cx", b"Codex"), ("ds", b"DSK"), ("zz", b"Agent")):
        for state, word in (("idle", b"READY"), ("think", b"THINK\x07"),
                            ("tool", b"TOOL>"), ("wait", b"WAIT!"),
                            ("done", b"DONE"), ("error", b"ERROR")):
            ui, lcd, lights = make_ui()
            assert ui.handle("set %s-a %s app" % (tool, state), 0).startswith("ok set ")
            ui.render(0)
            assert lcd.rows[0] == (b"\x00\x01 " + label + b" " + word).ljust(16)
            assert lcd.rows[1].startswith(b"\x02\x03 app")
            assert lcd.rows[1].endswith(b"0s" if state != "idle" else b"  ")
            ui.render(400 if state == "wait" else 500 if state == "error" else 3000)
            if state == "wait":
                assert b">YOU<" in lcd.rows[0] and tuple(lcd.glyphs[:4]) == FRAMES.get(tool, FRAMES["robot"])[0]
            if state == "done":
                assert b"DONE\x05" in lcd.rows[0]
            if state == "error":
                assert tuple(lcd.glyphs[:4]) == FRAMES.get(tool, FRAMES["robot"])[0]
    ui, lcd, _ = make_ui()
    ui.render(0)
    assert lcd.rows == [b"\x00\x01 Agent Monitor", b"\x02\x03 ready to work"]
    assert tuple(lcd.glyphs[:4]) == FRAMES["sleep"][0]
    for now, word in ((12000, b"12s"), (300000, b"5m"), (7200000, b"2h")):
        ui.handle("set cc-a think app", 0)
        ui.render(now)
        assert lcd.rows[1].endswith(word)


def test_marquee():
    name = b"abcdefghijklmnopqrstuvwx"
    assert len(clean(name.decode() + "ignored")) == 24
    assert clean("a\\b\x00") == b"a/b?"
    assert marquee(name, 10, 0) == name[:10]
    assert marquee(name, 10, 1999) == name[:10]
    assert marquee(name, 10, 2000) == name[1:11]
    assert marquee(name, 10, 2400) == name[2:12]
    assert marquee(name, 10, 7200) == name[-10:]
    assert marquee(name, 10, 9199) == name[-10:]
    assert marquee(name, 10, 9200) == name[13:23]
    assert marquee(name, 10, 14400) == name[:10]
    assert marquee(b"abcdef", 5, 1999) == b"abcde"
    assert marquee(b"abcdef", 5, 2000) == b"bcdef"
    assert marquee(b"abcdef", 5, 3999) == b"bcdef"
    assert marquee(b"abcdef", 5, 4000) == b"abcde"
    ui, lcd, _ = make_ui()
    ui.handle("set cc-a idle " + name.decode(), 0)
    ui.render(0)
    ui.render(2400)
    assert lcd.rows[1][3:] == name[2:15]


def test_focus():
    ui, lcd, lights = make_ui()
    ui.handle("set cc-w wait urgent", 0)
    ui.handle("set cx-a think app", 0)
    assert ui.choose(0) == "cc-w"
    assert ui.handle("focus cx-a", 100) == "ok focus cx-a"
    assert ui.choose(200) == "cx-a"
    ui.render(400)
    assert b"Codex THINK" in lcd.rows[0] and lights[-1] == 1
    assert lcd.rows[1][-2:] == b" \x07"
    ui.render(800)
    assert lcd.rows[1][-2:] == b"\x04\x07" and lights[-1] == 0
    ui.handle("focus cx-a", 20100)
    assert ui.choose(80099) == "cx-a"
    assert ui.choose(80100) == "cc-w"
    ui.handle("focus cx", 81000)
    ui.handle("set cx-b idle second", 81000)
    assert ui.choose(81000) == "cx-b"
    ui.handle("set cx-a tool app", 81000)
    assert ui.choose(81000) == "cx-a"
    ui.handle("focus ds", 82000)
    ui.render(82000)
    assert lcd.rows[0].startswith(b"\x00\x01 DSK READY")
    assert tuple(lcd.glyphs[:4]) == DANCE_FRAMES["ds"][(82000 // 450) % 4]
    assert ui.handle("focus -", 83000) == "ok focus -"
    assert ui.choose(83000) == "cc-w"
    ui.handle("focus cx-missing", 84000)
    ui.render(84000)
    assert b"Codex READY" in lcd.rows[0]
    ui.handle("clear", 85000)
    ui.handle("focus ds", 85000)
    ui.render(85000)
    assert lcd.rows[1] == b"\x02\x03 ready to work"


def test_compatibility():
    ui, _, _ = make_ui()
    assert ui.handle("set cc-a idle project", 0) == "ok set cc-a idle"
    assert ui.handle("set cc-a idle", 100) == "ok set cc-a idle"
    assert ui.sess["cc-a"][3] == 0
    ui.handle("set cx-b wait web", 100)
    assert ui.handle("list", 100) == "ok list n=2\n  cc-a idle project\n  cx-b wait web"
    assert ui.handle("clear", 100) == "ok clear 2"
    for i in range(8):
        ui.handle("set cc-%d idle p" % i, i)
    ui.handle("set cc-0 idle", 9)
    assert ui.handle("set cx-new think p", 10) == "ok set cx-new think"
    assert "cc-1" not in ui.sess and len(ui.order) == 8
    ui.handle("clear", 10)
    for i in range(8):
        ui.handle("set cc-%d think p" % i, 10)
    assert ui.handle("set cx-full think p", 10) == "err set: full (8 sessions)"
    for state, ttl in TTL.items():
        ui.handle("clear", 100)
        ui.handle("set cc-exp %s p" % state, 100)
        ui.expire(100 + ttl * 1000)
        assert "cc-exp" in ui.sess
        ui.expire(101 + ttl * 1000)
        assert not ui.sess


def test_priority_rotation():
    ui, _, _ = make_ui()
    for i, state in enumerate(("idle", "done", "think", "tool", "error", "wait")):
        ui.handle("set cc-%d %s p" % (i, state), 0)
    assert ui.choose(100) == "cc-5"
    ui.drop("cc-5")
    assert ui.choose(100) == "cc-4"
    ui.drop("cc-4")
    assert ui.choose(4999) == "cc-1"
    assert ui.choose(5000) == "cc-3"
    ui.handle("clear", 0)
    ui.handle("set cc-a think a", 0)
    ui.handle("set cx-b think b", 0)
    assert ui.choose(0) == "cc-a" and ui.choose(3000) == "cx-b"
    assert ui.choose(6000) == "cc-a"


def test_bad_commands_glyphs():
    ui, lcd, _ = make_ui()
    for line in (None, 3, b"\xff", "set", "set cc-a bogus", "end", "end missing",
                 "focus", "focus cc extra", "wat", "clear extra"):
        assert ui.handle(line, 0).startswith("err")
    assert ui.handle(" \t\n", 0) is None
    assert ui.handle("ping", 0) == "ok pong agent-lcd 0.2 sessions=0"
    ui.render(0)
    first = len(lcd.writes)
    ui.render(0)
    assert len(lcd.writes) == first
    ui.glyph(0, bytes(bytearray(lcd.glyphs[0])))
    assert len(lcd.writes) == first
    ui.invalidate()
    ui.render(0)
    assert len(lcd.writes) == first + 8
    reply = ui.handle("dump", 0).split()
    assert len(reply) == 12 and len(reply[2]) == 32 and len(reply[3]) == 32
    for key, art in ART.items():
        assert len(art) == 16 and all(len(row) == 10 and set(row) <= set("#.") for row in art)
        assert len(to_glyphs(art)) == 4
        assert shift(art, dy=-1)[-1] == "." * 10
        assert shift(art, dy=1)[0] == "." * 10
        assert all(row[0] == "." for row in shift(art, dx=1))
        assert all(row[-1] == "." for row in shift(art, dx=-1))
    for state, boundary in (("think", 600), ("tool", 200), ("wait", 400), ("error", 500), ("done", 3000)):
        ui, lcd, _ = make_ui()
        ui.handle("set cc-a %s app" % state, 0)
        ui.render(0)
        before = tuple(lcd.glyphs[:4])
        ui.render(boundary)
        assert tuple(lcd.glyphs[:4]) != before


def test_dance():
    for tool in ("cc", "cx", "ds"):
        assert len(DANCE[tool]) == 4
        for art in DANCE[tool]:
            assert len(art) == 16 and all(len(row) == 10 and set(row) <= set("#.") for row in art)
        assert tuple(DANCE_FRAMES[tool]) == tuple(to_glyphs(a) for a in DANCE[tool])
    assert len(DANCE_FRAMES["robot"]) == 4
    for tool in ("cc", "cx", "ds", "zz"):
        for setup in (["set %s-a idle app" % tool], ["focus %s" % tool]):
            if tool == "zz" and setup[0].startswith("focus"):
                continue
            ui, lcd, _ = make_ui()
            for line in setup:
                assert ui.handle(line, 0).startswith("ok ")
            shots = []
            for now in (0, 450, 900, 1350, 1800):
                ui.render(now)
                shots.append(tuple(lcd.glyphs[:4]))
            for i in range(4):
                assert shots[i] != shots[(i + 1) % 4], (tool, setup, i)
            assert shots[4] == shots[0]
            frames = DANCE_FRAMES.get(tool, DANCE_FRAMES["robot"])
            assert shots[:4] == list(frames)
    for tool in ("cc", "cx", "ds"):
        for i in range(4):
            a, b = DANCE[tool][i], DANCE[tool][(i + 1) % 4]
            assert sum(x != y for ra, rb in zip(a, b) for x, y in zip(ra, rb)) >= 8, (tool, i)


def main():
    tests = [test_layout_states, test_marquee, test_focus, test_compatibility,
             test_priority_rotation, test_bad_commands_glyphs, test_dance]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("UI: %d groups passed" % len(tests))


if __name__ == "__main__":
    main()
