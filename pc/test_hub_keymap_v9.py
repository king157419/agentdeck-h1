"""V9 controller regressions: fake clocks/effects only, no user windows or keys."""
from pathlib import Path
import tempfile
import unittest

import hub
from hub_layers import Layers, classify_layer


class Desktop:
    voice_active = False
    _window_switcher = None

    def __init__(self):
        self.current = (11, "claude.exe", "Claude")
        self.calls = []

    def foreground(self):
        return self.current

    def release_window_switch(self):
        return True

    def current_session_title(self, sessions):
        return None

    def show_session(self, session, sessions):
        self.calls.append(("show", session["session_id"]))
        return {"claude_sidebar": True, "switched": True}

    def context(self, session, sessions, layer, index):
        self.calls.append(("ctx", layer, index))
        return {"noop": "输入框不是空的"} if session.get("draft") else True

    def context_list(self, session, sessions, layer, direction):
        self.calls.append(("list", layer, direction))
        return True

    def next_pane(self, session, sessions):
        return {"panes": [{"rect": [0, 0, 100, 100], "name": "中 1"}], "selected": 0}

    def close(self):
        pass


class LayerTests(unittest.TestCase):
    def test_classification_process_and_browser_title(self):
        cases = [("claude.exe", "", "agent"), ("Codex.exe", "", "agent"),
                 ("WindowsTerminal.exe", "codex", "default"),
                 ("Weixin.exe", "", "chat"), ("WeChat.exe", "", "chat"),
                 ("Feishu.exe", "", "chat"), ("Lark.exe", "", "chat"),
                 ("chrome.exe", "docs", "browser"), ("msedge.exe", "YouTube", "video"),
                 ("firefox.exe", "哔哩哔哩", "video"), ("chrome.exe", "抖音", "video")]
        for exe, title, layer in cases:
            with self.subTest(exe=exe, title=title):
                self.assertEqual(classify_layer((11, exe, title)), layer)
        self.assertEqual(classify_layer((11, "chrome.exe", "x"), fullscreen=True), "video")
        self.assertEqual(classify_layer(None), "default")

    def test_delay_restarts_on_foreground_change_and_freezes(self):
        layers = Layers()
        agent, chat = (1, "claude.exe", ""), (2, "wechat.exe", "")
        self.assertFalse(layers.update(agent, 0))
        self.assertFalse(layers.update(agent, .299))
        self.assertTrue(layers.update(agent, .3))
        self.assertFalse(layers.update(chat, .31))
        self.assertFalse(layers.update(chat, 1, frozen=True))
        self.assertEqual(layers.current, "agent")
        self.assertTrue(layers.update(chat, 1.01))


class ControlTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.clock = 100.
        self.effects = Desktop()
        self.engine = hub.Hub(home=Path(folder.name), desktop=self.effects, lcd_enabled=False,
                              monotonic=lambda: self.clock, wall_time=lambda: self.clock)
        self.addCleanup(self.engine.close)

    def action(self, action):
        return self.engine.action({"action": action})

    def session(self, sid, state="idle"):
        self.engine.event("cc", {"hook_event_name": "SessionStart", "session_id": sid,
            "session_title": sid.title(), "agentdeck_window": {"hwnd": 11, "exe": "claude.exe"}})
        self.engine.sessions[("cc", sid)]["state"] = state
        self.clock += 1

    def test_layer_waits_and_card_freezes_it(self):
        self.engine.maintain()
        self.clock += .3
        self.engine.maintain()
        self.assertEqual(self.engine.state()["layer"], "agent")
        self.action("session next")
        self.effects.current = (2, "wechat.exe", "WeChat")
        self.engine.maintain()
        self.clock += .5
        self.engine.maintain()
        self.assertEqual(self.engine.state()["layer"], "agent")
        self.clock += 3
        self.engine.maintain()
        self.assertEqual(self.engine.state()["layer"], "chat")

    def test_rotation_orders_by_need_freezes_and_never_focuses(self):
        for sid, state in (("idle", "idle"), ("running", "tool"), ("done", "done"),
                           ("error", "error"), ("question", "wait")):
            self.session(sid, state)
        self.engine.sessions[("cc", "question")]["needs_answer"] = "AskUserQuestion"
        selected = self.engine.selected
        self.action("session next")
        card = self.engine.state()["session_card"]
        self.assertEqual(card["order"], [5, 4, 3, 2, 1])
        self.assertEqual(card["selected_slot"], 5)
        self.assertEqual(self.engine.selected, selected)
        self.assertFalse(self.effects.calls)
        self.engine.sessions[("cc", "idle")]["state"] = "error"
        self.assertEqual(self.engine.state()["session_card"]["order"], card["order"])
        self.action("session next")
        self.assertEqual(self.engine.state()["session_card"]["selected_slot"], 4)
        self.action("session select")
        self.assertEqual(self.effects.calls, [("show", "error")])
        self.assertFalse(self.engine.state()["session_card"]["open"])

    def test_idle_session_press_no_keys_and_waiting_press_shows(self):
        self.session("idle")
        self.assertEqual(self.action("session select")["noop"], "没有等你的会话")
        self.assertFalse(self.effects.calls)
        self.session("question", "wait")
        self.action("session select")
        self.assertEqual(self.effects.calls, [("show", "question")])

    def test_session_card_times_out_without_action(self):
        self.session("idle")
        self.action("session next")
        self.clock += 2.5
        self.engine.maintain()
        self.assertFalse(self.engine.state()["session_card"]["open"])
        self.assertFalse(self.effects.calls)

    def test_list_rotation_selects_only_then_press_executes(self):
        for layer in ("browser", "video", "default"):
            with self.subTest(layer=layer):
                self.effects.calls.clear()
                self.engine.controls.layers.current = layer
                self.action("ctx next")
                self.action("ctx next")
                self.assertFalse(self.effects.calls)
                self.action("ctx select")
                self.assertEqual(self.effects.calls, [("list", layer, "next")] * 2)

    def test_agent_template_card_and_chat_deferred(self):
        self.session("agent")
        self.engine.controls.layers.current = "agent"
        self.action("ctx next")
        self.assertFalse(self.effects.calls)
        self.action("ctx next")
        self.action("ctx select")
        self.assertEqual(self.effects.calls, [("ctx", "agent", 2)])
        self.effects.calls.clear()
        self.engine.controls.layers.current = "chat"
        self.assertEqual(self.action("ctx next")["noop"], "这一步还没做")
        self.assertFalse(self.effects.calls)

    def test_help_tap_hold_and_move(self):
        self.action("overlay_down")
        self.clock += .2
        self.action("overlay_up")
        self.assertFalse(self.engine.state()["overlay_visible"])
        self.action("overlay_down")
        self.clock += .4
        self.engine.maintain()
        self.assertTrue(self.engine.state()["overlay_help"])
        self.action("overlay move")
        self.action("overlay_up")
        state = self.engine.state()
        self.assertFalse(state["overlay_visible"])
        self.assertFalse(state["overlay_help"])
        self.assertEqual(state["overlay_move_requests"], 1)
        self.assertEqual(state["overlay_save_requests"], 2)

    def test_panes_metadata_uses_wall_expiry(self):
        self.action("pane next")
        self.assertEqual(self.engine.state()["panes"]["items"][0]["name"], "中 1")
        self.assertEqual(self.engine.state()["panes"]["until"], self.clock + 1.2)

    def test_feedback_categories_dedup_and_suppression(self):
        for action in ("scroll 1", "window next", "copy", "paste", "app wechat"):
            self.engine.note_action(action, {"status": "sent"})
            self.assertIsNone(self.engine.state()["last_input"])
        self.engine.note_action("send", {"status": "noop", "noop": "输入框是空的"})
        first = self.engine.state()["last_input"]
        self.assertEqual(first["kind"], "noop")
        self.engine.note_action("send", {"status": "noop", "noop": "输入框是空的"})
        self.assertEqual(self.engine.state()["last_input"]["seq"], first["seq"])
        self.clock += 3
        self.engine.note_action("send", {"status": "sent"})
        self.assertEqual(self.engine.state()["last_input"]["kind"], "success")
        self.engine.note_action("send", error=ValueError("failed"))
        self.assertEqual(self.engine.state()["last_input"]["kind"], "error")

    def test_layer_binding_precedes_global_and_release_stays_paired(self):
        self.engine.controls.layers.current = "chat"
        config = {"bindings": {"hid:0x0A": "ctx 1"}, "layers": {"chat": {"hid:0x0A": "ctx 2"}}}
        keys = hub.USBKeys(self.engine, config)
        keys({"usage": 0x0A, "keys": ["hid:0x0A"], "pressed": [0x0A], "down": True, "t": self.clock})
        self.assertEqual(self.effects.calls, [("ctx", "chat", 2)])
        self.engine.controls.layers.current = "agent"
        self.assertEqual(keys.lookup("hid:0x0A"), "ctx 1")

    def test_modifier_tap_dispatches_only_on_usb_release_and_chords_cancel(self):
        self.engine.controls.layers.current = "default"
        keys = hub.USBKeys(self.engine, {"bindings": {"alt": "ctx 4"}})
        for reader in ("Raw Input", "USB"):
            for down in (True, False):
                keys({"usage": 0xE2, "modifier": True, "down": down, "pressed": [],
                      "t": self.clock, "reader": reader})
                self.clock += .1
        self.assertEqual(self.effects.calls, [("ctx", "default", 4)])

    def test_physical_help_rotation_skips_detent_threshold(self):
        keys = hub.USBKeys(self.engine, {"bindings": {"hid:0x07": "overlay", "hid:0x09": "window next"}})
        keys({"usage": 7, "keys": ["hid:0x07"], "pressed": [7], "down": True, "t": self.clock})
        keys({"usage": 9, "keys": ["hid:0x09"], "pressed": [9], "down": True, "t": self.clock})
        keys({"usage": 7, "keys": [], "pressed": [], "down": False, "t": self.clock})
        self.assertEqual(self.engine.state()["overlay_move_requests"], 1)
        self.assertFalse(self.engine.state()["overlay_help"])
        self.assertFalse(self.effects.calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
