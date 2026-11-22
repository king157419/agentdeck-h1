"""Run the management panel with temporary settings and simulated sessions."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
import time

from hub import HubServer, load_json, load_token
from panel import Panel


class PreviewHub:
    monotonic = staticmethod(time.monotonic)
    wall_time = staticmethod(time.time)

    def __init__(self, home):
        self.home = home
        self.lock = Lock()
        self.prompts = load_json(Path(__file__).with_name("hub_prompts.json"))
        self.key_events = []
        self.key_seq = 0
        self.pending = {}
        self.hold_mode = "auto"
        self.selected_slot = 1
        now = self.wall_time()
        self.sessions = {
            ("cc", "preview-claude"): {
                "agent": "cc", "session_id": "preview-claude", "slot": 1,
                "title": "检查面板键位", "project": "AgentDeck 预览",
                "state": "idle", "last_updated": now,
            },
            ("cx", "preview-codex"): {
                "agent": "cx", "session_id": "preview-codex", "slot": 2,
                "title": "运行示例测试", "project": "AgentDeck 预览",
                "state": "tool", "last_updated": now - 20,
            },
        }
        self.controls = self

    def state(self):
        with self.lock:
            return {
                "sessions": list(self.sessions.values()),
                "selected_slot": self.selected_slot,
                "layer": "agent",
                "deck_connected": False,
                "hold_mode": self.hold_mode,
                "hold_active": self.hold_mode == "always",
            }

    def action(self, payload, source):
        with self.lock:
            self.hold_mode = payload["action"].split()[1]

    def _show_session(self, identity):
        with self.lock:
            self.selected_slot = self.sessions[identity]["slot"]
        return {"status": "ok"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="loopback port (default: choose a free port)")
    args = parser.parse_args(argv)

    with TemporaryDirectory(prefix="agentdeck-panel-preview-") as home:
        hub = PreviewHub(Path(home))
        panel = Panel(hub)
        with HubServer(hub, load_token(hub.home), port=args.port, panel=panel) as server:
            print(panel.login_url(panel.new_login_code(), server.server_port), flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
