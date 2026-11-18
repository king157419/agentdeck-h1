"""Review regressions with temporary state and pre-macOS differential checks."""
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import hub


class VoiceDesktop:
    def __init__(self, fail_down=False):
        self.voice_active = False
        self.fail_down = fail_down
        self.calls = []
        self.on_stop = None

    def voice_down(self, session, sessions, *, on_stop=None):
        self.calls.append(("down", session["key"]))
        if self.fail_down:
            return False
        self.voice_active = True
        self.session = session
        self.on_stop = on_stop
        return True

    def voice_up(self):
        self.calls.append(("up",))
        self.voice_active = False
        if self.on_stop:
            callback, self.on_stop = self.on_stop, None
            callback(dict(session=self.session, reason="released", restores=0, closed=True))
        return False

    def close(self):
        return None


class MacVoiceRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def engine(self, module=hub, desktop=None):
        engine = module.Hub(home=self.temp.name, desktop=desktop or VoiceDesktop(),
                            sender=lambda *args, **kwargs: None,
                            hold_path=Path(self.temp.name) / "hold",
                            focus_guard=lambda **kwargs: nullcontext(),
                            monotonic=lambda: 100, wall_time=lambda: 100,
                            prompts={})
        self.addCleanup(engine.close)
        engine.event("cc", dict(hook_event_name="SessionStart", session_id="review",
                                cwd="/work/project"))
        return engine

    def test_failed_macos_voice_down_preserves_confirmation_and_redraws_cleared_target(self):
        for action in ("voice", "voice_down"):
            with self.subTest(action=action):
                engine = self.engine(desktop=VoiceDesktop(fail_down=True))
                request = hub.Pending("request", engine.selected, "Bash", "sudo test",
                                      "high", 100, 200, armed_at=100)
                engine.pending[request.id] = request
                engine.displayed_request_id = request.id
                rendered_targets = []
                with patch.object(hub.sys, "platform", "darwin"), patch.object(
                        engine, "_show", side_effect=lambda: rendered_targets.append(engine.voice_target)):
                    result = engine.action({"action": action})
                self.assertEqual(result, {"action": action, "status": "unavailable"})
                self.assertFalse(engine.desktop.voice_active)
                self.assertIsNone(engine.voice_target)
                self.assertEqual(rendered_targets[-1], None)
                self.assertEqual(request.armed_at, 100)
                self.assertEqual([call[0] for call in engine.desktop.calls], ["down"])

    def test_false_voice_up_is_unavailable_only_on_macos(self):
        for platform, expected in (("darwin", "unavailable"), ("win32", "sent")):
            with self.subTest(platform=platform):
                engine = self.engine()
                with patch.object(hub.sys, "platform", platform):
                    self.assertEqual(engine.action({"action": "voice_up"})["status"], expected)

    def test_windows_voice_flow_matches_pre_mac_bytes(self):
        path = Path(__file__).resolve().parents[1] / "_rollback/hub-pre-mac/hub.py"
        spec = importlib.util.spec_from_file_location("_pre_mac_voice_hub", path)
        legacy = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {spec.name: legacy}):
            spec.loader.exec_module(legacy)
        for actions in (("voice_up",), ("voice_down", "voice_up", "voice_up"), ("voice",)):
            for fail_down in (False, True):
                with self.subTest(actions=actions, fail_down=fail_down):
                    observations = []
                    for module in (legacy, hub):
                        engine = self.engine(module, VoiceDesktop(fail_down=fail_down))
                        lines = []
                        engine.sender = lambda batch, **kwargs: lines.extend(batch)
                        with patch.object(hub.sys, "platform", "win32"):
                            results = [engine.action({"action": action}) for action in actions]
                        observations.append(json.dumps([results, engine.desktop.calls, lines,
                                                        engine.voice_target], ensure_ascii=False).encode("utf-8"))
                    self.assertEqual(observations[1], observations[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
