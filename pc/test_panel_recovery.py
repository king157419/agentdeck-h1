"""Panel recovery uses fake windows, browser APIs, DOM, fetch and timers only."""
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import panel_launch


class Windows:
    def __init__(self, items, events):
        self.items = items
        self.events = events
        self.user = SimpleNamespace(PostMessageW=self.Post(self.events))

    class Post:
        def __init__(self, events):
            self.events = events

        def __call__(self, hwnd, message, wparam, lparam):
            self.events.append(("post", hwnd, message, wparam, lparam))
            return True

    def windows(self):
        return list(self.items)

    def read(self, hwnd):
        return next((item for item in self.items if item[0] == hwnd), (hwnd, "", ""))

    def activate(self, hwnd):
        self.events.append(("activate", hwnd))
        return True


class LaunchRecoveryTests(unittest.TestCase):
    def launch(self, items, has_session, edge=True):
        events = []
        windows = Windows(items, events)

        def new_code():
            events.append(("code",))
            return "CODE"

        panel = SimpleNamespace(auth=SimpleNamespace(has_session=lambda: has_session),
                                new_login_code=new_code,
                                login_url=lambda code, port: "http://127.0.0.1:%d/panel#code=%s" % (port, code))
        with patch.object(panel_launch, "find_edge", return_value="msedge.exe" if edge else None):
            result = panel_launch.open_panel(panel, 47800, windows=windows,
                                            popen=lambda cmd: events.append(("open", cmd)),
                                            browser_open=lambda url: events.append(("browser", url)))
        return result, events

    def test_expired_panel_is_closed_before_new_login_and_edge_window(self):
        result, events = self.launch([(7, r"C:\Edge\msedge.exe", "AgentDeck")], False)
        self.assertEqual(result, "edge")
        self.assertEqual(events[0], ("post", 7, 0x0010, 0, 0))
        self.assertEqual(events[1], ("code",))
        self.assertEqual(events[2][0], "open")
        self.assertIn("--app=http://127.0.0.1:47800/panel#code=CODE", events[2][1])

    def test_valid_panel_only_activates(self):
        result, events = self.launch([(7, r"C:\Edge\MSEDGE.EXE", "AgentDeck")], True)
        self.assertEqual((result, events), ("activated", [("activate", 7)]))

    def test_browser_fallback_also_closes_old_window_first(self):
        result, events = self.launch([(7, "msedge.exe", "AgentDeck")], False, edge=False)
        self.assertEqual(result, "browser")
        self.assertEqual([event[0] for event in events], ["post", "code", "browser"])

    def test_other_executables_and_nonexact_titles_are_never_closed_or_activated(self):
        items = [(1, "notepad.exe", "AgentDeck"), (2, "chrome.exe", "AgentDeck"),
                 (3, "msedge.exe", "AgentDeck - Microsoft Edge"), (4, "msedge.exe", " AgentDeck ")]
        for has_session in (False, True):
            with self.subTest(has_session=has_session):
                result, events = self.launch(items, has_session)
                self.assertEqual(result, "edge")
                self.assertEqual([event[0] for event in events], ["code", "open"])

    def test_close_rechecks_handle_executable_and_exact_title(self):
        for current in ((7, "notepad.exe", "AgentDeck"), (7, "msedge.exe", "other"),
                        (7, "msedge.exe", " AgentDeck "), (8, "msedge.exe", "AgentDeck")):
            with self.subTest(current=current):
                events = []
                windows = Windows([], events)
                windows.read = lambda hwnd: current
                self.assertFalse(panel_launch.close_window(windows, 7))
                self.assertEqual(events, [])


@unittest.skipUnless(shutil.which("node"), "Node is needed to run panel.js with DOM and timer fakes")
class PageRecoveryTests(unittest.TestCase):
    def test_401_retries_every_three_seconds_then_resumes_normal_polling(self):
        script = r'''
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
class Element {
  constructor() {
    this.nodeType = 1; this.children = []; this.hidden = true; this.dataset = {};
    this.style = {setProperty() {}};
    this.classList = {toggle() {}, add() {}, remove() {}};
  }
  setAttribute() {}
  addEventListener() {}
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  querySelectorAll() { return []; }
  contains() { return false; }
}
const state = {
  device: {connected: false}, hold: {mode: "always"}, sessions: [], layer: "agent",
  layer_names: {agent: "Agent", chat: "聊天", browser: "浏览器", video: "视频", default: "默认"},
  layout: {rows: [], knobs: []}, bindings: {agent: {}, default: {}},
  keys: {events: [], last_seq: 0}, can_edit: true
};
async function scenario(hash, statuses) {
  const elements = new Map(), timers = new Map(), calls = [];
  let nextId = 0;
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const context = {
    document: {hidden: false, activeElement: null, getElementById: get,
      createElement: () => new Element(), createTextNode: text => ({nodeType: 3, text}),
      querySelectorAll: () => [], addEventListener() {}},
    location: {hash, pathname: "/panel", search: ""}, history: {replaceState() {}},
    setTimeout(callback, delay) { const id = ++nextId; timers.set(id, {callback, delay}); return id; },
    clearTimeout(id) { timers.delete(id); },
    async fetch(path, options) {
      calls.push({path, options});
      const status = statuses.shift();
      assert.ok(status, "unexpected fetch");
      return {status, ok: status === 200, async json() { return status === 200 ? state : {error: "login required"}; }};
    }
  };
  vm.runInNewContext(source, context);
  const flush = () => new Promise(resolve => setImmediate(resolve));
  await flush();
  assert.strictEqual(get("gate").hidden, false);
  assert.match(get("gate-text").textContent, /过期/);
  async function retry(expectedDelay) {
    assert.strictEqual(timers.size, 1, "only one poll may be scheduled");
    const [id, timer] = timers.entries().next().value;
    assert.strictEqual(timer.delay, expectedDelay);
    timers.delete(id);
    await timer.callback();
    await flush();
  }
  await retry(3000);
  assert.strictEqual(get("gate").hidden, false);
  await retry(3000);
  assert.strictEqual(get("gate").hidden, true);
  assert.strictEqual(timers.size, 1);
  assert.strictEqual([...timers.values()][0].delay, 600);
  assert.strictEqual(calls.length, 3);
  assert.strictEqual(calls[1].path, "/panel/api/state");
  assert.strictEqual(calls[2].options.credentials, "same-origin");
}
(async () => {
  await scenario("", [401, 401, 200]);
  await scenario("#code=expired", [401, 401, 200]);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run([shutil.which("node"), "-e", script,
                                 str(Path(__file__).with_name("ui") / "panel.js")],
                                capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
