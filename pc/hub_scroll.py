"""Pane selection and wheel momentum; pure state can be tested with a fake clock."""
import logging
import math
import ntpath
import threading
import time

log = logging.getLogger("agentdeck.hub.scroll")


def valid_panes(items, fallback):
    panes = []
    for item in items if isinstance(items, list) else []:
        rect = item.get("rect") if isinstance(item, dict) else None
        if (isinstance(rect, (list, tuple)) and len(rect) == 4
                and all(type(value) in (int, float) and math.isfinite(value) for value in rect)
                and rect[2] > rect[0] and rect[3] > rect[1]):
            panes.append({"rect": tuple(int(value) for value in rect)})
    panes = sorted(panes[:4], key=lambda pane: pane["rect"][0]) or [{"rect": tuple(fallback)}]
    for index, pane in enumerate(panes):
        position = "中" if len(panes) == 1 or index == len(panes) // 2 else "左" if index < len(panes) // 2 else "右"
        pane["name"] = "%s %s" % (position, index + 1)
    return panes


class PaneSelection:
    def __init__(self, reader, rectangle, *, monotonic=time.monotonic):
        self.reader, self.rectangle, self.monotonic = reader, rectangle, monotonic
        self.cache, self.indices, self.requested = {}, {}, {}
        self._reading = set()
        self._lock = threading.RLock()
        self._closed = False

    def snapshot(self, window, *, advance=False, refresh=False):
        hwnd, process, _ = window
        process = ntpath.basename(process or "").casefold()
        with self._lock:
            panes = self.cache.get(hwnd)
            if panes is None:
                panes = valid_panes([], self.rectangle(hwnd))
            index = min(self.indices.get(process, len(panes) // 2 if process == "claude.exe" else 0), len(panes) - 1)
            if advance:
                index = (index + 1) % len(panes)
                if hwnd in self.cache:
                    self.indices[process] = index
            now = self.monotonic()
            if (refresh and not self._closed and hwnd not in self._reading
                    and now >= self.requested.get(hwnd, float("-inf")) + .5):
                self.requested[hwnd] = now
                self._reading.add(hwnd)
                threading.Thread(target=self._read, args=(window,), name="AgentDeck panes", daemon=True).start()
            return {"panes": [dict(pane, rect=list(pane["rect"])) for pane in panes],
                    "selected": index, "until": now + 1.2}

    def _read(self, window):
        try:
            result = self.reader(window[0])
            panes = valid_panes(result.get("panes") if isinstance(result, dict) else None,
                                self.rectangle(window[0]))
            with self._lock:
                if not self._closed:
                    self.cache[window[0]] = panes
        except Exception:
            # UIA is optional; the synchronous fallback remains usable.
            pass
        finally:
            with self._lock:
                self._reading.discard(window[0])

    def close(self):
        with self._lock:
            self._closed = True


class SmoothScroll:
    INTERVAL = 1 / 120
    DECAY = .120

    def __init__(self, emit, foreground, *, monotonic=time.monotonic, automatic=True):
        self.emit, self.foreground, self.monotonic = emit, foreground, monotonic
        self.automatic = automatic
        self.velocity, self.remainder = 0.0, 0.0
        self.last_tick = self.last_pulse = None
        self.window = self.point = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._round_active = False
        self._delta_total = self._emit_count = 0

    def _finish_round(self, reason):
        if self._round_active:
            # Native smooth_wheel_events negates logical deltas for Windows mouseData.
            log.info("scroll finished reason=%s logical_delta_total=%+d wheel_total=%+d count=%d",
                     reason, self._delta_total, -self._delta_total, self._emit_count)
            self._round_active = False
            self._delta_total = self._emit_count = 0

    def pulse(self, notches, window, point):
        now = self.monotonic()
        with self._lock:
            if self._stop.is_set():
                return False
            if self.window is not None and self.window[0] != window[0]:
                self._finish_round("window_changed")
                self.velocity = self.remainder = 0.0
                self.last_pulse = self.last_tick = None
            if self.last_pulse is not None and now - self.last_pulse >= .5:
                self._finish_round("idle_reset")
                self.velocity = self.remainder = 0.0
                self.last_tick = now
            self.window, self.point = window, point
            gap = None if self.last_pulse is None else now - self.last_pulse
            multiplier = 1 if gap is None or gap >= .2 else min(6, max(1, .12 / max(gap, .020)))
            if self.velocity * notches < 0:
                self._finish_round("reversed")
                self.velocity = self.remainder = 0.0
            self._round_active = True
            self.velocity += notches * 120 / self.DECAY * multiplier
            self.velocity = max(-3600, min(3600, self.velocity))
            self.last_pulse = now
            if self.last_tick is None:
                self.last_tick = now
            if self.automatic and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._run, name="AgentDeck smooth wheel", daemon=True)
                self._thread.start()
        return True

    def tick(self):
        with self._lock:
            now = self.monotonic()
            if self.window is None or self.last_tick is None:
                return None
            if self.foreground()[0] != self.window[0] or self._stop.is_set():
                self._finish_round("stopped" if self._stop.is_set() else "foreground_changed")
                self.velocity = self.remainder = 0.0
                return None
            dt = max(0, now - self.last_tick)
            self.last_tick = now
            decay = math.exp(-dt / self.DECAY)
            self.remainder += self.velocity * self.DECAY * (1 - decay)
            self.velocity *= decay
            if abs(self.remainder) < 10:
                return None
            delta = int(math.copysign(min(30, int(abs(self.remainder))), self.remainder))
            self.remainder -= delta
            if not self.emit(self.window, self.point, delta):
                self._finish_round("emit_failed")
                self.velocity = self.remainder = 0.0
                return None
            self._delta_total += delta
            self._emit_count += 1
            return delta

    def _run(self):
        while not self._stop.wait(self.INTERVAL):
            try:
                self.tick()
            except Exception:
                with self._lock:
                    self._finish_round("error")
                    self.velocity = self.remainder = 0.0
            with self._lock:
                if abs(self.velocity) < 1:
                    self._finish_round("decayed")
                    self.velocity = self.remainder = 0.0
                    return
        with self._lock:
            self._finish_round("stopped")

    def close(self):
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=.25)
        with self._lock:
            self._finish_round("closed")
