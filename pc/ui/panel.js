"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  const LAYER_ORDER = ["agent", "chat", "browser", "video", "default"];
  const FLASH_MS = 600;
  const LIVE_HINT = "按下实体键时，图上对应的键会亮";
  let S = null;                 // latest state from the hub
  let selLayer = null;          // layer shown in the picture (never changes the real layer)
  let layerPicked = false;
  let selId = null;             // selected key ("r2c1") or knob ("k4")
  let lastSeq = null;
  let timer = null;
  let polling = false;
  let liveTimer = null;
  let savedNote = null;
  const sig = {};

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v == null) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  async function api(path, body) {
    const options = { credentials: "same-origin", cache: "no-store" };
    if (body !== undefined) {
      options.method = "POST";
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options);
    let data = {};
    try { data = await response.json(); } catch (e) { /* empty body */ }
    if (response.status === 401) { showGate(data.error); throw new Error("login"); }
    if (!response.ok) throw new Error(data.error || ("请求失败 " + response.status));
    return data;
  }

  function showGate(text) {
    $("gate-text").textContent = text && text !== "login required"
      ? text + "。请从托盘菜单点“管理面板”重新打开。"
      : "请从托盘菜单点“管理面板”重新打开。";
    $("gate").hidden = false;
  }

  // ---- helpers -------------------------------------------------------------
  function ago(seconds) {
    if (seconds < 20) return "刚刚";
    if (seconds < 3600) return Math.max(1, Math.round(seconds / 60)) + " 分钟";
    if (seconds < 86400) return Math.round(seconds / 3600) + " 小时";
    return Math.round(seconds / 86400) + " 天";
  }
  const DOT = { idle: "var(--idle)", think: "var(--run)", tool: "var(--run)", wait: "var(--wait)",
                locked: "var(--wait)", error: "var(--err)", done: "var(--done)" };
  function controls() {
    const out = [];
    for (const row of S.layout.rows) out.push(...row);
    for (const knob of S.layout.knobs) out.push(...knob.controls);
    return out;
  }
  function info(control) { return (S.bindings[selLayer] || {})[control.code] || { label: "空", action: null }; }
  function positionOf(action) {
    for (const row of S.layout.rows) for (const c of row) {
      const b = S.bindings.default[c.code];
      if (b && b.action === action) return c.row + "·" + c.col;
    }
    return null;
  }

  // ---- top bar ---------------------------------------------------------------
  function renderBar() {
    const d = S.device;
    const on = d.connected;
    $("device-dot").style.setProperty("background", on ? "var(--done)" : "var(--idle)");
    $("device-text").textContent = !on ? "宏键盘未连接"
      : d.reader === "usb" ? "宏键盘已连接 · USB 直读" : "宏键盘已连接 · 兼容读键（按键会漏进窗口）";
    for (const button of document.querySelectorAll("#hold button"))
      button.classList.toggle("on", button.dataset.mode === S.hold.mode);
  }

  // ---- sessions --------------------------------------------------------------
  function renderSessions() {
    const approve = positionOf("approve"), deny = positionOf("deny");
    const shape = JSON.stringify([S.sessions.map((s) => Object.assign({}, s, { ago: 0 })), approve, deny]);
    const box = $("sessions");
    if (sig.sessions !== shape) {
      sig.sessions = shape;
      box.replaceChildren();
      if (!S.sessions.length) box.append(h("div", { class: "empty-note", text: "还没有 agent 会话" }));
      for (const s of S.sessions) box.append(sessionRow(s, approve, deny));
    }
    for (const el of box.querySelectorAll("[data-ago]")) {
      const s = S.sessions.find((x) => x.agent + "/" + x.session_id === el.dataset.key);
      if (s) el.textContent = ago(s.ago);
    }
  }

  function sessionRow(s, approve, deny) {
    const key = s.agent + "/" + s.session_id;
    const meta = [s.agent_name, s.project, s.locked ? "请在终端确认" : s.needs_answer ? "在等你回答" : s.state_text]
      .filter(Boolean).join(" · ");
    const title = h("div", { class: "t" }, s.title, s.open ? h("span", { class: "badge", text: "Claude 里正打开" }) : null);
    const row = h("div", { class: "row" + (s.selected ? " sel" : ""), role: "button", tabindex: "0",
      title: "点一下，跳到这个会话" },
      h("span", { class: "dot", style: false }),
      h("div", {}, title, h("div", { class: "m", text: meta })),
      h("div", { class: "ago", "data-ago": true, "data-key": key, text: ago(s.ago) }));
    row.firstChild.style.setProperty("background", DOT[s.state] || "var(--idle)");
    const open = () => api("/panel/api/open", { agent: s.agent, session_id: s.session_id })
      .then((st) => { S = st; render(); }).catch((e) => note(e.message, true));
    row.addEventListener("click", open);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    if (s.request) {
      const r = s.request;
      const decide = (decision) => (event) => {
        event.stopPropagation();
        api("/panel/api/decision", { decision, request_id: r.id, nonce: r.nonce })
          .then((st) => { S = st; render(); note(resultText(st.result, decision), false); })
          .catch((e) => note(e.message, true));
      };
      row.append(h("div", { class: "ask" + (r.risk === "high" || r.risk === "critical" ? " risk" : ""),
        onclick: (e) => e.stopPropagation() },
        h("div", { class: "tool", text: r.tool || "工具" }),
        h("code", { text: r.command || "（没有命令内容）" }),
        h("div", { class: "actions" },
          h("button", { class: "btn go", type: "button", text: r.armed ? "再点一次批准" : "批准", onclick: decide("approve") }),
          h("button", { class: "btn no", type: "button", text: "拒绝", onclick: decide("deny") }),
          approve ? h("span", { class: "keys" }, h("span", { class: "kc", text: approve }), "批准 ",
            h("span", { class: "kc", text: deny || "" }), "拒绝") : null)));
    }
    return row;
  }

  function resultText(status, decision) {
    if (status === "confirm") return "高危请求：再点一次批准才放行";
    if (status === "allowed") return "已批准";
    if (status === "denied") return "已拒绝";
    return decision === "approve" ? "批准没有生效（" + status + "）" : "已处理";
  }

  // ---- layers + keyboard -----------------------------------------------------
  function renderLayers() {
    const shape = JSON.stringify([selLayer, S.layer]);
    if (sig.layers === shape) return;
    sig.layers = shape;
    const box = $("layers");
    box.replaceChildren(...LAYER_ORDER.map((name) => h("button", {
      type: "button", class: "layer" + (name === selLayer ? " on" : ""), role: "tab",
      "aria-selected": name === selLayer ? "true" : "false",
      title: name === S.layer ? "现在前台应用对应的层" : "只看这一层的键位，不改变真实的层",
      onclick: () => { selLayer = name; layerPicked = true; render(); } },
      S.layer_names[name], name === S.layer ? h("span", { class: "now" }) : null)));
  }

  function selected() {
    if (!selId) return null;
    const knob = S.layout.knobs.find((k) => k.id === selId);
    if (knob) return { knob, controls: knob.controls };
    const cell = controls().find((c) => c.id === selId);
    return cell ? { cell, controls: [cell] } : null;
  }

  function renderKeyboard() {
    const shape = JSON.stringify([selLayer, S.bindings[selLayer], S.layout, selId]);
    if (sig.keys === shape) return;
    sig.keys = shape;
    const grid = $("grid"), knobs = $("knobs");
    grid.replaceChildren();
    knobs.replaceChildren();
    for (const knob of S.layout.knobs) {
      const labels = knob.controls.map((c) => info(c).label);
      const el = h("button", { type: "button", class: "knob" + (selId === knob.id ? " on" : ""), "data-codes":
        knob.controls.map((c) => c.code).join(" "), title: "旋钮 " + knob.number + "：" + knob.name,
        onclick: () => { selId = knob.id; savedNote = null; render(); } },
        h("span", {}, h("span", { class: "kn", text: knob.name }), knob.number === 4 ? labels[2] : "旋钮 " + knob.number));
      knobs.append(el);
    }
    for (const row of S.layout.rows) for (const c of row) {
      const i = info(c);
      const blank = c.id === "r5c4" || i.action == null || i.action === "none";
      const el = h("button", { type: "button", "data-codes": c.code, title: c.position + "（物理键 " + c.name + "）" +
          (c.id === "r5c4" ? "，和旋钮 2 逆时针是同一个信号" : ""),
        class: "cap" + (blank ? " empty" : "") + (c.kind === "fixed" ? " fixed" : "") +
          (i.user && c.kind !== "fixed" ? " edited" : "") + (selId === c.id ? " on" : ""),
        onclick: () => { selId = c.id; savedNote = null; render(); } }, blank ? "空" : i.label);
      grid.append(el);
    }
  }

  // ---- detail ------------------------------------------------------------
  const LOCK = () => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", "16"); svg.setAttribute("height", "16"); svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "1.5");
    const body = document.createElementNS(svg.namespaceURI, "rect");
    for (const [k, v] of [["x", "3"], ["y", "7"], ["width", "10"], ["height", "7"], ["rx", "1.5"]]) body.setAttribute(k, v);
    const arc = document.createElementNS(svg.namespaceURI, "path");
    arc.setAttribute("d", "M5 7V5a3 3 0 0 1 6 0v2");
    svg.append(body, arc);
    return svg;
  };

  function renderDetail() {
    const box = $("detail");
    const sel = selected();
    const shape = JSON.stringify([selId, selLayer, sel && sel.controls.map((c) => [c.id, S.bindings[selLayer][c.code]]),
      S.can_edit, savedNote]);
    if (sig.detail === shape) return;
    if (box.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
    sig.detail = shape;
    box.replaceChildren();
    if (!sel) {
      box.append(h("h3", { text: "键位" }),
        h("div", { class: "hint", text: "点一颗键，在这里看它做什么、改成别的。带蓝点的键是你改过的；有锁的键在任何应用里都不变。" }));
      return;
    }
    const layerName = S.layer_names[selLayer];
    if (sel.knob) {
      box.append(h("h3", { text: "旋钮 " + sel.knob.number + " · " + sel.knob.name }),
        h("div", { class: "where", text: "左起第 " + sel.knob.number + " 个旋钮" + (sel.knob.number === 4 ? " · 当前查看：" + layerName + "层" : "") }));
      for (const c of sel.controls) {
        box.append(h("div", { class: "sub-h", text: c.direction }), controlBlock(c));
      }
    } else {
      const c = sel.cell;
      box.append(h("h3", { text: c.position }),
        h("div", { class: "where", text: "物理键 " + c.name + (c.kind === "layer" ? " · 当前查看：" + layerName + "层" : "") }),
        controlBlock(c));
    }
    box.append(h("div", { class: "saved" + (savedNote && savedNote.error ? " err" : ""), text: savedNote ? savedNote.text : "" }));
  }

  function controlBlock(c) {
    const i = info(c);
    if (c.kind === "fixed") {
      const label = c.id === "r5c4" ? "空" : i.label;
      return h("div", { class: "lock" }, LOCK(), h("div", {}, "固定键，任何应用里都不变",
        h("div", { class: "cur", text: "当前功能：" + label })));
    }
    const wrap = h("div", {});
    if (!S.can_edit) {
      wrap.append(h("div", { class: "hint", text: "当前键位方案只读，不能在面板里改。" }));
    }
    const options = S.editor[c.kind];
    const layered = c.kind !== "app";
    const current = layered ? (i.layered ? i.action : "default") : i.action;
    const exe = !layered && typeof current === "string" && current.startsWith("app exe:");
    const field = h("div", { class: "field" });
    let group = null;
    for (const option of options) {
      if (option.group && option.group !== group) field.append(h("div", { class: "grp", text: option.group }));
      group = option.group || null;
      const on = option.custom ? exe : option.value === current;
      let tag = null;
      if (option.value === "default") tag = "现在：" + i.default_label;
      else if (!layered && option.value === i.default_action) tag = "默认";
      field.append(h("button", { type: "button", class: "opt" + (on ? " on" : ""), disabled: !S.can_edit && "disabled",
        onclick: option.custom ? () => { const input = field.querySelector("input"); input.focus(); } : () => save(c, option.value) },
        h("span", { class: "radio" }), option.label, tag ? h("span", { class: "d", text: tag }) : null));
    }
    if (!layered) {
      const input = h("input", { type: "text", placeholder: "C:\\Program Files\\…\\程序.exe", spellcheck: "false",
        "aria-label": "程序的完整路径", value: exe ? current.slice(8) : "" });
      field.append(h("div", { class: "custom" }, input,
        h("button", { class: "btn", type: "button", text: "使用", disabled: !S.can_edit && "disabled",
          onclick: () => save(c, "app exe:" + input.value.trim()) })));
    }
    wrap.append(field);
    if (i.user && S.can_edit) {
      wrap.append(h("button", { class: "btn reset", type: "button", text: "恢复默认", onclick: () => save(c, "default") }));
    }
    return wrap;
  }

  function save(control, action) {
    const body = { id: control.id, layer: selLayer, action };
    api("/panel/api/key", body)
      .then((st) => { S = st; savedNote = { text: "已保存，立即生效", error: false }; render(); })
      .catch((e) => { savedNote = { text: e.message, error: true }; sig.detail = null; render(); });
  }

  function note(text, error) {
    savedNote = { text, error: !!error };
    sig.detail = null;
    if (S) renderDetail();
  }

  // ---- live key feedback --------------------------------------------------------
  function flash(event) {
    const cls = event.kind === "error" ? "bad" : event.kind === "noop" ? "none" : "";
    for (const el of document.querySelectorAll("[data-codes]")) {
      if (!el.dataset.codes.split(" ").includes(event.code)) continue;
      el.classList.remove("bad", "none");
      el.classList.add("hot");
      if (cls) el.classList.add(cls);
      setTimeout(() => el.classList.remove("hot", "bad", "none"), Math.max(60, FLASH_MS - event.age * 1000));
    }
    const live = $("live");
    live.className = "live " + (event.kind === "error" ? "error" : event.kind === "noop" ? "" : "success");
    $("live-text").textContent = event.position + " → " + event.text;
    clearTimeout(liveTimer);
    liveTimer = setTimeout(() => { live.className = "live"; $("live-text").textContent = LIVE_HINT; }, 6000);
  }

  function renderKeys() {
    const events = S.keys.events;
    if (lastSeq === null) {
      lastSeq = S.keys.last_seq;
      for (const e of events) if (e.age < FLASH_MS / 1000) flash(e);
      return;
    }
    for (const e of events) if (e.seq > lastSeq) flash(e);
    lastSeq = Math.max(lastSeq, S.keys.last_seq);
  }

  function render() {
    if (!S) return;
    if (!layerPicked || !S.layer_names[selLayer]) selLayer = S.layer;
    $("gate").hidden = true;
    renderBar();
    renderSessions();
    renderLayers();
    renderKeyboard();
    renderDetail();
  }

  // ---- polling -------------------------------------------------------------
  async function poll() {
    clearTimeout(timer);
    if (document.hidden || polling) { timer = setTimeout(poll, 600); return; }
    polling = true;
    try {
      S = await api("/panel/api/state");
      render();
      renderKeys();
    } catch (e) {
      if (e.message !== "login") {
        $("device-text").textContent = "与 AgentDeck 失去联系";
        $("device-dot").style.setProperty("background", "var(--err)");
      }
    }
    polling = false;
    if (!document.hidden) timer = setTimeout(poll, 600);
  }

  async function start() {
    for (const button of document.querySelectorAll("#hold button"))
      button.addEventListener("click", () => api("/panel/api/hold", { mode: button.dataset.mode })
        .then((st) => { S = st; render(); }).catch((e) => note(e.message, true)));
    document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
    const match = /(?:^|[#&])code=([^&]+)/.exec(location.hash);
    if (match) {
      try {
        const response = await fetch("/panel/login", { method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: decodeURIComponent(match[1]) }) });
        history.replaceState(null, "", location.pathname + location.search);
        if (!response.ok) { showGate("登录码已过期或已用过"); return; }
      } catch (e) {
        history.replaceState(null, "", location.pathname + location.search);
        showGate("连不上 AgentDeck");
        return;
      }
    }
    poll();
  }
  start();
})();
