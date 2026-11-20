"""Report stalled event loops without relying on the event loops themselves."""
import logging
import sys
import threading
import time
import traceback


log = logging.getLogger("agentdeck.hub.watchdog")


class Watchdog:
    """Each watched loop must beat itself, even when there are no input events."""

    def __init__(self, *, timeout=3., interval=.25, monotonic=time.monotonic):
        if timeout <= 0 or interval <= 0:
            raise ValueError("watchdog timeout and interval must be positive")
        self.timeout, self.interval, self.monotonic = timeout, interval, monotonic
        self._lock = threading.Lock()
        self._watched = {}
        self._stop = threading.Event()
        self._thread = None

    def watch(self, name, thread_id=None, wake=None):
        with self._lock:
            self._watched[name] = {"last": self.monotonic(), "stalled": False,
                                   "wake": wake,
                                   "thread_id": threading.get_ident() if thread_id is None else thread_id}

    def beat(self, name):
        recovered = None
        with self._lock:
            target = self._watched.get(name)
            if target is not None:
                now = self.monotonic()
                if target["stalled"]:
                    recovered = now - target["last"]
                target["last"], target["stalled"] = now, False
        if recovered is not None:
            log.info("%s 已恢复（卡顿 %.1f 秒）", name, recovered)

    def unwatch(self, name):
        with self._lock:
            self._watched.pop(name, None)

    @staticmethod
    def _stacks():
        names = {thread.ident: thread.name for thread in threading.enumerate()}
        frames = sys._current_frames()
        lines = ["所有线程调用栈：\n"]
        try:
            for ident, frame in sorted(frames.items()):
                lines.append("\nThread %s (id=%s):\n" % (names.get(ident, "unknown"), ident))
                lines.extend(traceback.format_stack(frame))
        finally:
            # Do not retain live frames and their local objects between checks.
            frames.clear()
        return "".join(lines)

    def check(self):
        stalled = []
        wakes = []
        with self._lock:
            now = self.monotonic()
            for name, target in self._watched.items():
                age = now - target["last"]
                if age > self.timeout:
                    wake = target["wake"]
                    if wake is not None:
                        wakes.append((name, wake))
                    if not target["stalled"]:
                        target["stalled"] = True
                        stalled.append((name, age, target["thread_id"], wake is not None))
        # Waking, stack formatting and logging must never hold the heartbeat lock.
        for name, wake in wakes:
            try:
                wake()
            except Exception as error:
                log.debug("%s wake failed: %s", name, error)
        if stalled:
            stacks = self._stacks()
            for name, age, thread_id, has_wake in stalled:
                log.warning("%s 卡顿 %.1f 秒（thread id=%s）%s\n%s", name, age, thread_id,
                            "；已发送唤醒" if has_wake else "", stacks)

    def _run(self):
        while not self._stop.wait(self.interval):
            self.check()

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="AgentDeck watchdog", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.)
