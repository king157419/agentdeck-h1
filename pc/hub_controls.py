"""V9 cards and contextual controls, independent of Tk and native keyboard APIs."""
import sys
import threading

from hub_layers import Layers
from claude_sessions import read_catalog
from session_titles import session_label


class Controls:
    def __init__(self, hub, session_reader=None):
        self.hub = hub
        self.layers = Layers()
        self.layer_changed_at = float("-inf")
        self.session_card = {"open": False, "order": [], "selected_slot": None}
        self.list_card = {"open": False, "items": [], "selected": 0}
        self.overlay_visible = True
        self.overlay_help = False
        self.help_down_at = None
        self.help_moved = False
        self.move_requests = 0
        self.save_requests = 0
        self.panes = None
        self.card_generation = 0
        self.origin_reader = None
        self.wait_cursor = None
        self.session_reader = read_catalog if session_reader is None else session_reader
        self.claude_sessions = []
        self.hidden_claude_session_ids = set()
        self.catalog_reader = None
        self.catalog_refresh_at = float("-inf")

    def refresh_sessions(self, force=False):
        """Publish a background file snapshot; never read Claude files under the Hub lock."""
        hub = self.hub
        with hub.lock:
            if (hub.closed or self.catalog_reader is not None and self.catalog_reader.is_alive()
                    or not force and hub.monotonic() < self.catalog_refresh_at):
                return
            self.catalog_refresh_at = hub.monotonic() + 10

            def read():
                try:
                    result = self.session_reader()
                    # Keep list-only injected readers compatible with older callers.
                    sessions, hidden_ids = result if isinstance(result, tuple) else (result, set())
                    sessions = [dict(s) for s in sessions]
                    hidden_ids = set(hidden_ids)
                except Exception:
                    sessions, hidden_ids = [], set()
                with hub.lock:
                    if not hub.closed:
                        self.claude_sessions = sessions
                        self.hidden_claude_session_ids = hidden_ids

            self.catalog_reader = threading.Thread(target=read, name="AgentDeck Claude sessions", daemon=True)
            self.catalog_reader.start()

    def _hidden_claude_session(self, session):
        return (session.get("agent") == "cc"
                and session.get("session_id") in self.hidden_claude_session_ids)

    def _card_sessions(self):
        hub = self.hub
        entries, seen = [], set()
        for source in self.claude_sessions:
            cli_id = source.get("cli_session_id")
            if cli_id in self.hidden_claude_session_ids:
                continue
            identity = ("cc", cli_id)
            marker = identity if cli_id else ("claude", source["session_id"])
            if marker in seen:
                continue
            seen.add(marker)
            known = hub.sessions.get(identity) if cli_id else None
            entry = dict(known) if known is not None else {
                "agent": "cc", "session_id": source["session_id"],
                "slot": "claude:" + source["session_id"], "state": "idle", "_catalog_only": True}
            entry.update(title=source["title"], cwd=source["cwd"], cli_session_id=cli_id,
                         claude_session_id=source["session_id"],
                         last_updated=max(source["last_activity"] / 1000, entry.get("last_updated", 0)))
            entries.append(entry)
        for identity, session in hub.sessions.items():
            if (session.get("agent") in ("cc", "cx") and identity not in seen
                    and not self._hidden_claude_session(session)):
                entries.append(dict(session))
        return sorted(entries, key=lambda s: -s.get("last_updated", 0))[:12]

    def _card_entries(self):
        entries = []
        for source in self.session_card.get("entries", []):
            entry = dict(source)
            identity = (("cc", source["cli_session_id"]) if source.get("cli_session_id") else
                        (source["agent"], source["session_id"]) if not source.get("_catalog_only") else None)
            current = self.hub.sessions.get(identity)
            if current is not None:
                entry.update(current)
                entry.update(slot=source["slot"], _catalog_only=False)
                if source.get("claude_session_id"):
                    entry.update(title=source.get("title"), cwd=source.get("cwd"))
            elif source.get("claude_session_id"):
                entry.update(state="idle", native_wait=False, needs_answer=False,
                             wait_kind=None, _catalog_only=True)
            entries.append(entry)
        return entries

    def snapshot(self):
        return {"layer": self.layers.current, "layer_changed_at": self.layer_changed_at,
                "session_card": {**self.session_card, "entries": self._card_entries()},
                "list_card": dict(self.list_card),
                "overlay_visible": self.overlay_visible, "overlay_help": self.overlay_help,
                "overlay_move_requests": self.move_requests,
                "overlay_save_requests": self.save_requests, "panes": self.panes}

    def _switching(self):
        desktop = self.hub.desktop
        switcher = getattr(desktop, "_window_switcher", None) if desktop is not None else None
        return getattr(switcher, "active", False) is True

    def maintain(self):
        hub = self.hub
        if hub.desktop_enabled:
            self.refresh_sessions()
        now = hub.monotonic()
        desktop = hub.desktop
        foreground = getattr(desktop, "foreground", None) if desktop is not None else None
        window = foreground() if callable(foreground) else None
        fullscreen = False
        if isinstance(window, (tuple, list)) and len(window) >= 3:
            check = getattr(desktop, "is_fullscreen", None)
            fullscreen = check(window) is True if callable(check) else False
        with hub.lock:
            for card in (self.session_card, self.list_card):
                if card["open"] and now >= card.get("deadline", float("inf")):
                    card["open"] = False
                    self.card_generation += 1
            if self.help_down_at is not None and now - self.help_down_at >= .4:
                self.overlay_help = True
            frozen = self._switching() or self.session_card["open"] or self.list_card["open"]
            if window is not None and self.layers.update(window, now, frozen=frozen, fullscreen=fullscreen):
                self.layer_changed_at = hub.wall_time()

    def _sessions(self):
        hub = self.hub
        pending = {p.session for p in hub.pending.values()} | {p.session for p in hub.locked.values()}
        def rank(identity):
            item = hub.sessions[identity]
            group = (0 if identity in pending or item.get("native_wait") else
                     1 if item.get("needs_answer") or item.get("state") == "wait" else
                     2 if item.get("state") == "error" else
                     3 if item.get("state") == "done" and not item.get("read") else
                     4 if item.get("state") in ("tool", "think") else 5)
            return group, -item.get("last_updated", 0), item["slot"]
        return sorted(hub.sessions, key=rank)

    def _session(self):
        """Use the foreground conversation for input guards, not a card highlight."""
        hub = self.hub
        selected = hub.sessions.get(hub.selected)
        foreground = getattr(hub.desktop, "foreground", None)
        window = foreground() if callable(foreground) else None
        if isinstance(window, (tuple, list)) and len(window) >= 3:
            candidates = [s for s in hub.sessions.values() if s.get("hwnd") == window[0]]
            if candidates and selected not in candidates:
                selected = max(candidates, key=lambda s: s.get("last_updated", 0))
            elif not candidates:
                selected = None
        result = dict(selected or {})
        identity = (result.get("agent"), result.get("session_id"))
        result["_permission_pending"] = (any(p.session == identity for p in hub.pending.values())
                                         or any(p.session == identity for p in hub.locked.values())
                                         or result.get("native_wait") is True
                                         or result.get("wait_kind") == "permission_prompt")
        return result

    def _desktop(self, method, *args, **kwargs):
        hub = self.hub
        desktop = hub._desktop()
        session = self._session()
        sessions = [dict(s) for s in hub.sessions.values()]
        function = getattr(desktop, method, None)
        if not callable(function):
            return {"noop": "这一步还没做"}
        result = function(session, sessions, *args, **kwargs)
        if isinstance(result, dict) and "noop" in result:
            return {"status": "noop", **result}
        if result is False:
            if sys.platform == "darwin":
                return {"status": "unavailable"}
            return {"status": "error", "message": "操作未完成"}
        return {"status": "sent", **(result if isinstance(result, dict) else {})}

    def _origin(self, generation):
        hub = self.hub
        candidates = self._card_entries()
        def read():
            try:
                desktop = hub._desktop()
                method = getattr(desktop, "current_session_title", None)
                title = method(candidates) if callable(method) else None
                with hub.lock:
                    if hub.closed or generation != self.card_generation or not self.session_card["open"]:
                        return
                    matches = [s for s in candidates if s.get("title") == title]
                    match = max(matches, key=lambda s: (
                        (s["agent"], s.get("cli_session_id") or s["session_id"]) == hub.selected,
                        s.get("last_updated", 0)), default=None)
                    if match and match["slot"] in self.session_card["order"]:
                        self.session_card["selected_slot"] = match["slot"]
            except Exception:
                pass  # first item remains a usable fallback
        self.origin_reader = threading.Thread(target=read, name="AgentDeck card origin", daemon=True)
        self.origin_reader.start()

    def _show_session(self, identity, session_override=None):
        hub = self.hub
        with hub.lock:
            if identity not in hub.sessions:
                return {"status": "noop", "noop": "这个会话已结束"}
            hub._select_session(identity)
            selected = dict(hub.sessions[identity])
            selected.update(session_override or {})
            self.session_card["opening_slot"] = (self.session_card["selected_slot"]
                                                 if self.session_card["open"] else selected["slot"])
            self.session_card["deadline"] = hub.monotonic() + 5
            effect = hub._focus_effect("show", identity, {"status": "selected"},
                                       session_override=session_override)
        result = effect()
        with hub.lock:
            self.session_card.pop("opening_slot", None)
            self.session_card["open"] = False
            self.card_generation += 1
            if identity in hub.sessions and result.get("switched") is not False and result.get("window") == "focused":
                hub.sessions[identity]["read"] = True
        if result.get("switched") is False or result.get("window") != "focused":
            return {"status": "error", "message": "打开会话失败：" + session_label(selected, 18)}
        return {"status": "sent", "message": "已打开：" + session_label(selected, 18)}

    def _show_claude_session(self, selected):
        hub = self.hub
        with hub.lock:
            sessions = [dict(s) for s in hub.sessions.values()]
            self.session_card["opening_slot"] = selected["slot"]
            self.session_card["deadline"] = hub.monotonic() + 5
        try:
            result = hub._desktop().show_claude_session(selected, sessions)
            opened = isinstance(result, dict) and result.get("switched") is True
        except Exception:
            opened = False
        finally:
            with hub.lock:
                self.session_card.pop("opening_slot", None)
                self.session_card["open"] = False
                self.card_generation += 1
        return {"status": "sent" if opened else "error",
                "message": ("已打开：" if opened else "打开会话失败：") + session_label(selected, 18)}

    def action(self, command, argument, received_at):
        hub = self.hub
        if command in ("overlay_down", "overlay_up"):
            with hub.lock:
                if command == "overlay_down":
                    self.help_down_at, self.help_moved = received_at, False
                else:
                    if self.help_down_at is not None:
                        if received_at - self.help_down_at < .4 and not self.help_moved:
                            self.overlay_visible = not self.overlay_visible
                        self.save_requests += 1
                    self.help_down_at, self.overlay_help = None, False
            return {"status": "ignored"}
        if command == "overlay" and argument == "move":
            with hub.lock:
                self.move_requests += 1
                self.help_moved, self.overlay_help = True, True
            return {"status": "ignored"}
        if command == "session":
            with hub.lock:
                if argument in ("next", "prev"):
                    self.card_generation += 1
                    first = not self.session_card["open"]
                    if first:
                        entries = self._card_sessions()
                        order = [s["slot"] for s in entries]
                        self.session_card.update(open=True, order=order, entries=entries,
                                                 generation=self.session_card.get("generation", 0) + 1,
                                                 selected_slot=order[0] if order else None)
                        self.refresh_sessions(force=True)
                    else:
                        order = self.session_card["order"]
                        slot = self.session_card["selected_slot"]
                        index = order.index(slot) if slot in order else 0
                        if order:
                            self.session_card["selected_slot"] = order[max(0, min(len(order) - 1, index + (1 if argument == "next" else -1)))]
                    self.session_card["deadline"] = hub.monotonic() + 8
                    if first:
                        self._origin(self.card_generation)
                    return {"status": "ignored"}
                if self.session_card["open"]:
                    slot = self.session_card["selected_slot"]
                    entry = next((s for s in self._card_entries() if s["slot"] == slot), None)
                    identity = ((entry["agent"], entry["session_id"])
                                if entry and not entry.get("_catalog_only") else None)
                    self.session_card["open"] = False
                    self.card_generation += 1
                else:
                    entry = None
                    waiting = [i for i in self._sessions()
                               if hub.sessions[i].get("state") in ("wait", "locked", "error")
                               and not self._hidden_claude_session(hub.sessions[i])]
                    index = waiting.index(self.wait_cursor) + 1 if self.wait_cursor in waiting else 0
                    identity = waiting[index % len(waiting)] if waiting else None
                    self.wait_cursor = identity
            if entry and entry.get("_catalog_only"):
                return self._show_claude_session(entry)
            if identity is None:
                return {"status": "noop", "noop": "没有等你的会话"}
            if entry and entry.get("claude_session_id"):
                return self._show_session(identity, session_override={"title": entry["title"], "cwd": entry["cwd"]})
            return self._show_session(identity)
        if command == "ctx":
            layer = self.layers.current
            if argument == "select":
                with hub.lock:
                    card_open = self.list_card["open"]
                if not card_open:
                    return self._desktop("context_list", layer, "enter")
            if argument in ("next", "prev", "select") and layer == "agent":
                with hub.lock:
                    session = self._session()
                    asking = bool(session.get("needs_answer"))
                    options = session.get("question_options", []) if asking else ["继续", "跑测试", "总结"]
                    if not options:
                        return {"status": "noop", "noop": "没有可选的项目"}
                    if argument != "select":
                        first = not self.list_card["open"]
                        index = 0 if first else self.list_card["selected"] + (1 if argument == "next" else -1)
                        self.list_card.update(open=True, items=list(options), selected=max(0, min(len(options) - 1, index)),
                                              generation=self.list_card.get("generation", 0) + int(first),
                                              title="回答选项" if asking else "提示模板", deadline=hub.monotonic() + 8)
                        return {"status": "ignored"}
                    if not self.list_card["open"]:
                        return {"status": "noop", "noop": "先转旋钮选择项目"}
                    index = self.list_card["selected"] + 1
                    self.list_card["open"] = False
                return self._desktop("context", layer, index)
            if argument in ("next", "prev", "select"):
                if layer == "chat":
                    return {"status": "noop", "noop": "这一步还没做"}
                if argument != "select":
                    with hub.lock:
                        first = not self.list_card["open"]
                        index = 3 if first else self.list_card["selected"]
                        index = max(0, min(6, index + (1 if argument == "next" else -1)))
                        unit = {"browser": "标签页", "video": "5 秒", "default": "行"}[layer]
                        labels = [("向前 " if i < 3 else "向后 ") + str(abs(i - 3)) + " " + unit
                                  if i != 3 else "不移动" for i in range(7)]
                        self.list_card.update(open=True, items=labels, selected=index, title="列表",
                                              generation=self.list_card.get("generation", 0) + int(first),
                                              deadline=hub.monotonic() + 8)
                    return {"status": "ignored"}
                with hub.lock:
                    if not self.list_card["open"]:
                        delta = None
                    else:
                        delta = self.list_card["selected"] - 3
                        self.list_card["open"] = False
                if delta is None:
                    return self._desktop("context_list", layer, "enter")
                if delta == 0:
                    return {"status": "ignored"}
                result = None
                for _ in range(abs(delta)):
                    result = self._desktop("context_list", layer, "next" if delta > 0 else "prev")
                    if result.get("status") != "sent":
                        break
                return result
            return self._desktop("context", layer, int(argument))
        if command == "pane":
            result = self._desktop("next_pane")
            if "panes" in result:
                self.panes = {"items": result["panes"], "selected": result.get("selected", 0),
                              "until": hub.wall_time() + 1.2}
            return {**result, "status": "ignored"}
        if command in ("copy", "paste", "clear"):
            return self._desktop(command)
        if command in ("send", "interrupt"):
            if command == "interrupt" and self._switching():
                desktop = hub._desktop()
                desktop._window_switcher.cancel()
                return {"status": "ignored"}
            return self._desktop(command, layer=self.layers.current)
        if command == "app":
            return self._desktop("app", argument)
        if command == "window":
            return self._desktop("window", argument)
        raise ValueError("unknown contextual action")
