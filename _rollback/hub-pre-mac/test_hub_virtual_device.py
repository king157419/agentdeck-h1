"""Offline checks for the virtual device draw model; no display or hub needed."""
import unittest

import hub_virtual_device as vd


def state(sessions=(), request=None, selected=None):
    out = {"sessions": list(sessions), "pending": [], "locked": [], "selected_slot": selected,
           "displayed_request_id": None}
    if request is not None:
        out["pending"] = [request]
        out["displayed_request_id"] = request["id"]
    return out


def session(slot, st="think", name="proj"):
    return {"slot": slot, "agent": "cc", "session_id": "s%d" % slot, "name": name, "state": st}


def req(session_id="s1", **kw):
    base = {"id": "r1", "agent": "cc", "session_id": session_id, "summary": "ls -la",
            "risk": "low", "status": "pending", "gate": False}
    base.update(kw)
    return base


class ZoneTests(unittest.TestCase):
    def test_colors_by_state(self):
        sessions = [session(i + 1, s) for i, s in enumerate(
            ["think", "wait", "done", "error", "idle"])]
        zones = vd.zone_models(state(sessions))
        self.assertEqual([z["color"] for z in zones[:5]],
                         ["#2BC864", "#F5A524", "#3B82F6", "#E5484D", vd.COLORS["IDLE"]])
        self.assertEqual(zones[5]["label"], "IDLE")
        self.assertFalse(zones[5]["occupied"])

    def test_name_truncated_to_8(self):
        zones = vd.zone_models(state([session(1, name="verylongprojectname")]))
        self.assertEqual(zones[0]["name"], "verylong")

    def test_gate_blinks_at_2hz(self):
        st = state([session(1, "wait", "a")], req(gate=True, risk="high"))
        on = vd.zone_models(st, 0.0)[0]
        off = vd.zone_models(st, 0.26)[0]
        again = vd.zone_models(st, 0.51)[0]
        self.assertEqual((on["label"], on["color"]), ("GATE", "#E5484D"))
        self.assertEqual((off["label"], off["color"]), ("GATE", vd.DARK))
        self.assertEqual(again["color"], "#E5484D")

    def test_locked_zone_and_line(self):
        st = state([session(1, "wait")], req(risk="critical", status="locked"))
        self.assertEqual(vd.zone_models(st)[0]["label"], "LOCKED")
        self.assertEqual(vd.request_line(st), ("LOCKED: use terminal", vd.COLORS["LOCKED"]))

    def test_request_line_truncates_and_colors(self):
        st = state([session(1, "wait")], req(summary="x" * 100, risk="high"))
        text, color = vd.request_line(st)
        self.assertEqual(color, "#E5484D")
        self.assertTrue(text.endswith("[HIGH]"))
        self.assertLessEqual(len(text.split(" [")[0]), 60)
        low = vd.request_line(state([session(1)], req()))
        self.assertEqual(low, ("ls -la [LOW]", "#F5A524"))
        gated = vd.request_line(state([session(1)], req(gate=True, risk="high")))
        self.assertTrue(gated[0].startswith("GATE "))
        self.assertEqual(vd.request_line(state())[0], "")


class ActionTests(unittest.TestCase):
    def act(self, control, ctrl=False, **kw):
        return vd.control_action(control, ctrl, **kw)

    def test_plain_keys(self):
        self.assertEqual(self.act("slot 3"), ({"action": "slot 3"}, False))
        self.assertEqual(self.act("approve", request_id="r1")[0],
                         {"action": "approve", "request_id": "r1"})
        self.assertEqual(self.act("deny")[0], {"action": "deny"})
        self.assertEqual(self.act("camera")[0], {"action": "screenshot"})

    def test_ctrl_toggle_and_consumption(self):
        self.assertEqual(self.act("ctrl"), (None, True))
        self.assertEqual(self.act("ctrl", True), (None, False))
        self.assertEqual(self.act("deny", True), ({"action": "interrupt"}, False))
        for slot, name in vd.CTRL_PROMPTS.items():
            self.assertEqual(self.act("slot %d" % slot, True),
                             ({"action": "prompt " + name}, False))
        self.assertEqual(self.act("slot 4", True)[0], {"action": "prompt commit"})

    def test_mic_hold(self):
        self.assertEqual(self.act("mic", phase="down")[0], {"action": "voice_down"})
        self.assertEqual(self.act("mic", phase="up")[0], {"action": "voice_up"})
        self.assertIsNone(self.act("approve", phase="up")[0])

    def test_wheel_to_cycle(self):
        self.assertEqual(vd.wheel_action(120), {"action": "cycle -1"})
        self.assertEqual(vd.wheel_action(-120), {"action": "cycle +1"})
        self.assertIsNone(vd.wheel_action(0))
        self.assertEqual(self.act("wheel_up")[0], {"action": "cycle -1"})
        self.assertEqual(self.act("wheel_down")[0], {"action": "cycle +1"})
        self.assertEqual(self.act("wheel_down", True)[1], True)


class SceneTests(unittest.TestCase):
    def test_hit_test_matches_layout(self):
        for name, (x, y, w, h) in vd.layout().items():
            self.assertEqual(vd.hit_test(x + w / 2, y + h / 2), name)
        self.assertIsNone(vd.hit_test(5, 400))

    def test_scene_glow_press_and_ctrl(self):
        st = state([session(2, "wait")])
        ops = vd.build_scene(st, {"ctrl": True, "pressed": {"slot 2": 1.0}}, 0.5)
        glow = [o for o in ops if o["tag"] == "glow"]
        self.assertEqual(len(glow), 6)
        self.assertEqual(glow[1]["fill"], "#F5A524")
        keys = {o["tag"]: o for o in ops if o["op"] == "rrect" and o["tag"].startswith("slot")}
        self.assertEqual(keys["slot 2"]["fill"], "#14171C")
        self.assertEqual(keys["slot 1"]["fill"], "#252A33")
        ctrl = [o for o in ops if o["tag"] == "ctrl" and o["op"] == "rrect"][0]
        self.assertEqual(ctrl["fill"], "#F5A524")
        later = vd.build_scene(st, {"pressed": {"slot 2": 1.0}}, 1.2)
        self.assertEqual({o["tag"]: o for o in later if o["op"] == "rrect"}["slot 2"]["fill"], "#252A33")

    def test_scene_is_pure(self):
        st = state([session(1)], req())
        self.assertEqual(vd.build_scene(st, None, 0.1), vd.build_scene(st, None, 0.1))


if __name__ == "__main__":
    unittest.main()
