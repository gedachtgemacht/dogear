// dogear UI, part 4: the on-demand workspace. Editor with live typing and edit diffs, the shared live browser, the terminal.
/* ============================================================ workspace: only open when needed */
function openWS(tab) {
  $("#work").hidden = false; $("#ide").classList.add("ws"); $("#ws-toggle").classList.add("on");
  S.follow = true;
  if (tab) activate(tab, false);
  fit();
  return true;
}
function closeWS() {
  $("#work").hidden = true; $("#ide").classList.remove("ws"); $("#ws-toggle").classList.remove("on");
}
const wsOpen = () => !$("#work").hidden;
function drawer(open) { $("#drawer").hidden = !open; if (open) renderPane(); $("#menu").classList.toggle("on", open); }

/* ============================================================ editor */
const E = { files: {}, tabs: ["@preview"], active: "@preview", playing: null, eyeTimer: 0 };
const badge = p => S.changed.get(p);

function renderTabs() {
  const nav = $("#etabs"); nav.innerHTML = "";
  for (const t of E.tabs) {
    const b = el("button", `tab ${t === E.active ? "on" : ""}`); b.dataset.p = t;
    if (t === "@preview") { const i = el("i", "live"); b.append(i, "Browser"); }
    else { b.append(t.split("/").pop()); if (badge(t)) b.append(el("span", "dot")); const x = el("span", "x", "✕"); x.onclick = e => { e.stopPropagation(); closeTab(t); }; b.append(x); b.title = t; }
    b.onclick = () => activate(t, true); nav.append(b);
  }
  if (!S.follow) { const f = el("button", "tab follow", "Follow the agent"); f.title = "Show again what the agent opens and changes"; f.onclick = () => { S.follow = true; renderTabs(); }; nav.append(f); }
  const x = el("button", "tab close", "✕"); x.title = "Close workspace"; x.onclick = () => closeWS(); nav.append(x);
}
function activate(t, byUser = true) {
  if (byUser && wsOpen() && t !== E.active) S.follow = false;   // the user looks at something: stop switching tabs under them
  E.active = t; if (!E.tabs.includes(t)) E.tabs.push(t);
  $("#v-preview").classList.toggle("on", t === "@preview"); $("#v-code").classList.toggle("on", t !== "@preview");
  renderTabs(); document.querySelectorAll("#tree .n").forEach(n => n.classList.toggle("sel", n.dataset.p === t));
  if (t !== "@preview") paintFile(t);
}
function closeTab(t) { E.tabs = E.tabs.filter(x => x !== t); if (E.active === t) activate(E.tabs[E.tabs.length - 1] || "@preview"); else renderTabs(); }

async function loadFile(p) {
  if (!E.files[p]) { const j = await api("/api/file", { path: p }); E.files[p] = { text: j.binary ? "(binary file)" : j.text, lang: langOf(p) }; }
  return E.files[p];
}
function lineEl(i, html) { const d = el("div", "l"), n = el("span", "n", i), t = el("span", "t"); t.innerHTML = html; d.append(n, t); return d; }
function status(t, agent = "") { $("#cstat").innerHTML = `<span>${esc(t)}</span><span class="agent">${esc(agent)}</span>`; }

async function paintFile(p, { fresh = new Set(), eye = null } = {}) {
  if (E.playing) E.playing.skip = true;
  const f = await loadFile(p); if (E.active !== p) return;
  const code = $("#code"), lines = highlight(f.text, f.lang), frag = document.createDocumentFragment();
  lines.slice(0, 5000).forEach((h, i) => { const d = lineEl(i + 1, h); if (fresh.has(i + 1)) d.classList.add("fresh"); if (eye && i + 1 >= eye[0] && i + 1 <= eye[1]) d.classList.add("eye"); frag.append(d); });
  code.innerHTML = ""; code.append(frag);
  status(`${p}  ·  ${lines.length} lines  ·  ${f.lang}`);
  const target = $(".fresh, .eye", code); if (target) target.scrollIntoView({ block: "center" });
}

// New file: the code is typed in line by line.
async function typeIn(p, text) {
  if (E.playing) E.playing.skip = true;
  E.files[p] = { text, lang: langOf(p) };
  if (E.active !== p) activate(p);
  const lines = highlight(text, langOf(p)), code = $("#code"), run = { skip: false };
  E.playing = run; code.innerHTML = ""; let i = 0; const per = Math.max(1, Math.ceil(lines.length / 70));
  status(`${p}  ·  writing…`, "Writing");
  await new Promise(done => {
    const tick = () => {
      code.querySelector(".caret")?.classList.remove("caret");
      const upto = run.skip ? lines.length : Math.min(lines.length, i + per), frag = document.createDocumentFragment();
      for (; i < upto; i++) { const d = lineEl(i + 1, lines[i]); d.classList.add("fresh"); frag.append(d); }
      code.append(frag); code.lastChild?.classList.add("caret"); code.scrollTop = code.scrollHeight;
      if (i < lines.length) requestAnimationFrame(tick); else { code.querySelector(".caret")?.classList.remove("caret"); done(); }
    };
    tick();
  });
  if (E.playing === run) E.playing = null;
  status(`${p}  ·  ${lines.length} lines  ·  ${langOf(p)}`);
}

// Edit: repaint the file and flash the lines the diff added.
async function showEdit(p, text, diff) {
  E.files[p] = { text, lang: langOf(p) };
  if (E.active !== p) activate(p);
  const fresh = new Set(); (diff?.hunks || []).forEach(h => h.forEach(([sg, ln]) => { if (sg === "+") fresh.add(ln); }));
  await paintFile(p, { fresh }); status(`${p}  ·  ${text.split("\n").length} lines  ·  edited`, `+${diff?.added || 0} −${diff?.removed || 0}`);
}

async function eyeOn(p, a, b) {
  const f = await loadFile(p).catch(() => null); if (!f) return;
  if (E.active !== p) activate(p);
  await paintFile(p, { eye: [a, b] }); status(`${p}  ·  ${f.text.split("\n").length} lines`, "Reading");
  clearTimeout(E.eyeTimer); E.eyeTimer = setTimeout(() => document.querySelectorAll("#code .eye").forEach(n => n.classList.remove("eye")), 2500);
}

/* ============================================================ browser (live, shared with the agent) */
const B = { vw: 1280, vh: 800, scale: 1, hideT: 0, blank: true, recording: false };
const bcv = $("#bscreen"), bg = bcv.getContext("2d"), bbox = $("#bbox"), bov = $("#bov");
function fit() {
  const s = $("#screen"), W = s.clientWidth - 28, H = s.clientHeight - 28; if (W <= 0 || H <= 0) return;
  B.scale = Math.min(W / B.vw, H / B.vh); bbox.style.width = Math.floor(B.vw * B.scale) + "px"; bbox.style.height = Math.floor(B.vh * B.scale) + "px";
}
new ResizeObserver(fit).observe($("#screen"));
const bpt = e => { const r = bbox.getBoundingClientRect(); return { x: (e.clientX - r.left) / B.scale, y: (e.clientY - r.top) / B.scale }; };
const bmods = e => (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);
function drawFrame(m) {
  const img = new Image();
  img.onload = () => { if (bcv.width !== m.w || bcv.height !== m.h) { bcv.width = m.w; bcv.height = m.h; } bg.drawImage(img, 0, 0); };
  img.src = "data:image/jpeg;base64," + m.d;
  if (B.vw !== m.w || B.vh !== m.h) { B.vw = m.w; B.vh = m.h; fit(); }
  if (!B.blank) { $("#bempty").hidden = true; bbox.classList.remove("wait"); }
}
function agentAt(x, y, label) {
  const c = $("#bcur"); c.hidden = false; c.style.transform = `translate(${x * B.scale}px, ${y * B.scale}px)`; $("#bcur-l").textContent = label || "";
  clearTimeout(B.hideT); B.hideT = setTimeout(() => { c.hidden = true; }, 6000);
}
function ripple(x, y) { const r = el("div", "rip"); r.style.left = x * B.scale + "px"; r.style.top = y * B.scale + "px"; bov.append(r); setTimeout(() => r.remove(), 700); }
function recState(m) {
  B.recording = !!m.on;
  const b = $("#b-rec"); b.classList.toggle("on", B.recording); b.textContent = B.recording ? "■ Stop recording" : "● Record";
  if (!B.recording) $("#b-recname").hidden = true;
}
function browserEvent(m) {
  if (m.type === "b_rec") return recState(m);
  switch (m.type) {
    case "frame": drawFrame(m); break;
    case "b_status": { if (m.state === "error") { $("#bempty").hidden = false; $("#bempty span").textContent = `Browser error: ${m.error}`; }
      else if (m.state === "starting") $("#bempty span").textContent = "Starting browser…"; break; }
    case "b_nav": { const u = $("#b-url"); B.blank = !m.url || m.url === "about:blank";
      if (document.activeElement !== u) u.value = B.blank ? "" : m.url;
      bbox.classList.toggle("wait", B.blank); $("#bempty").hidden = !B.blank; break; }
    case "b_act":
      if (m.kind === "click") { agentAt(m.x, m.y, m.label ? `click · ${m.label}` : "click"); setTimeout(() => ripple(m.x, m.y), 340); }
      else if (m.kind === "scroll") agentAt(m.x, m.y, "scroll");
      else if (m.kind === "type") $("#bcur-l").textContent = `typing "${m.label}"`;
      break;
    case "b_scroll": B.sc = m; drawScrollbars(); break;
    case "b_marks": { const few = m.rects.length <= 12;   // dense pages: quiet outlines only, no chips
      for (const r of m.rects.slice(0, 80)) {
        const d = el("div", few ? "mark" : "mark quiet"); d.style.cssText = `left:${r.x * B.scale}px;top:${r.y * B.scale}px;width:${r.w * B.scale}px;height:${r.h * B.scale}px`;
        if (few) d.append(el("b", "", r.ref)); bov.append(d); setTimeout(() => d.remove(), 1500); } break; }
    case "b_log": logLine(m.level, m.text); break;
    case "b_handoff": $("#need-t").textContent = m.reason; $("#need").hidden = false; document.title = "● Your turn";
      openWS("@preview"); bov.focus(); break;
    case "b_handoff_done": $("#need").hidden = true; document.title = S.st?.name || "dogear"; break;
  }
}
let blogEl = null;
function logLine(level, text) {
  $("#term-wrap").hidden = false;
  const body = $("#term");
  if (!blogEl || !blogEl.isConnected) { const h = el("div", "tcmd"); h.append(el("span", "", "Browser console")); blogEl = el("div", "tout"); body.append(h, blogEl); }
  const stick = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
  blogEl.append(el("div", `lg-${level}`, text)); if (stick) body.scrollTop = body.scrollHeight;
}
let pvTimer = 0;
function reloadPreview() { clearTimeout(pvTimer); pvTimer = setTimeout(() => sendWS({ type: "b_reload_preview" }), 250); }
/* scrollbars for the live view: the headless page hides its own, so draw them from the page metrics */
function drawScrollbars() {
  const m = B.sc; if (!m) return;
  const set = (bar, on, pos, size) => {
    bar.hidden = !on; if (!on) return;
    const th = bar.firstElementChild, v = bar.classList.contains("v");
    th.style[v ? "top" : "left"] = pos + "%"; th.style[v ? "height" : "width"] = size + "%";
  };
  const vy = m.h > m.vh + 2, hx = m.w > m.vw + 2;
  set($("#vbar"), vy, (m.y / m.h) * 100, Math.max(8, (m.vh / m.h) * 100));
  set($("#hbar"), hx, (m.x / m.w) * 100, Math.max(8, (m.vw / m.w) * 100));
}
function initScrollbars() {
  for (const [id, vert] of [["#vbar", true], ["#hbar", false]]) {
    const bar = $(id), th = bar.firstElementChild;
    let drag = null, lastSend = 0;
    const len = () => (vert ? bar.clientHeight : bar.clientWidth);
    th.onpointerdown = e => { e.stopPropagation(); e.preventDefault(); th.setPointerCapture(e.pointerId);
      drag = { p: vert ? e.clientY : e.clientX, o: vert ? B.sc.y : B.sc.x }; };
    th.onpointermove = e => {
      if (!drag || !B.sc) return;
      const n = performance.now(); if (n - lastSend < 40) return; lastSend = n;
      const d = ((vert ? e.clientY : e.clientX) - drag.p) / len() * (vert ? B.sc.h : B.sc.w);
      sendWS({ type: "b_scrollto", [vert ? "y" : "x"]: Math.max(0, drag.o + d) });
    };
    th.onpointerup = th.onpointercancel = () => { drag = null; };
    bar.onpointerdown = e => {                       // click on the track: one page up or down
      if (e.target !== bar || !B.sc) return;
      const r = bar.getBoundingClientRect(), at = ((vert ? e.clientY - r.top : e.clientX - r.left) / len());
      const cur = (vert ? B.sc.y / B.sc.h : B.sc.x / B.sc.w), dir = at > cur ? 1 : -1;
      sendWS({ type: "b_scrollto", [vert ? "dy" : "dx"]: dir * (vert ? B.sc.vh : B.sc.vw) * 0.9 });
    };
  }
}
function agentBusy(on) { $("#ban").hidden = !on; }
function initBrowser() {
  initScrollbars();
  let last = 0;
  // Touch: a drag scrolls the page, a tap is a click. Mouse and pen are forwarded as they are.
  let touch = null;
  bov.addEventListener("pointermove", e => {
    if (touch && e.pointerId === touch.id) {
      const dy = (touch.y - e.clientY) / B.scale, dx = (touch.x - e.clientX) / B.scale;
      touch.y = e.clientY; touch.x = e.clientX; touch.moved += Math.abs(dy) + Math.abs(dx);
      if (touch.moved > 8 / B.scale) sendWS({ type: "b_mouse", kind: "wheel", dx, dy, ...bpt(e) });
      return;
    }
    const n = performance.now(); if (n - last < 40) return; last = n; sendWS({ type: "b_mouse", kind: "move", ...bpt(e) });
  });
  bov.addEventListener("pointerdown", e => { bov.focus(); bov.setPointerCapture(e.pointerId); e.preventDefault();
    if (e.pointerType === "touch") { touch = { id: e.pointerId, x: e.clientX, y: e.clientY, moved: 0, pt: bpt(e) }; return; }
    sendWS({ type: "b_mouse", kind: "down", button: ["left", "middle", "right"][e.button] || "left", clicks: e.detail || 1, mods: bmods(e), ...bpt(e) }); });
  bov.addEventListener("pointerup", e => {
    if (touch && e.pointerId === touch.id) {
      const t = touch; touch = null;
      if (t.moved <= 8 / B.scale) { sendWS({ type: "b_mouse", kind: "down", button: "left", clicks: 1, mods: 0, ...t.pt }); sendWS({ type: "b_mouse", kind: "up", button: "left", clicks: 1, mods: 0, ...t.pt }); }
      return;
    }
    sendWS({ type: "b_mouse", kind: "up", button: ["left", "middle", "right"][e.button] || "left", clicks: e.detail || 1, mods: bmods(e), ...bpt(e) });
  });
  bov.addEventListener("pointercancel", () => { touch = null; });
  // deltaMode 1 (lines, Firefox wheel) and 2 (pages) must be converted to pixels, otherwise a notch scrolls 3 px.
  bov.addEventListener("wheel", e => {
    e.preventDefault();
    const k = e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? B.vh * .9 : 1;
    sendWS({ type: "b_mouse", kind: "wheel", dx: e.deltaX * k, dy: e.deltaY * k, ...bpt(e) });
  }, { passive: false });
  bov.addEventListener("contextmenu", e => e.preventDefault());
  bov.addEventListener("paste", e => { e.preventDefault(); sendWS({ type: "b_text", text: e.clipboardData.getData("text") }); });
  const key = kind => e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v") return;   // paste event handles it
    e.preventDefault();
    const text = e.key.length === 1 && !e.ctrlKey && !e.metaKey ? e.key : (e.key === "Enter" ? "\r" : "");
    sendWS({ type: "b_key", kind, key: e.key, code: e.code, vk: e.keyCode, mods: bmods(e), text });
  };
  bov.addEventListener("keydown", key("down")); bov.addEventListener("keyup", key("up"));
  $("#need-go").onclick = () => sendWS({ type: "b_resume" });
  $("#b-back").onclick = () => sendWS({ type: "b_back" }); $("#b-fwd").onclick = () => sendWS({ type: "b_fwd" });
  $("#b-reload").onclick = () => sendWS({ type: "b_reload" });
  $("#b-url").onkeydown = e => { if (e.key === "Enter") { sendWS({ type: "b_nav", url: e.target.value.trim() }); bov.focus(); } };
  const home = () => { sendWS({ type: "b_open" }); sendWS({ type: "b_nav", url: (S.st?.preview || "http://127.0.0.1:7871") + "/" }); };
  $("#b-home").onclick = home; $("#b-start").onclick = home;
  $("#b-ext").onclick = () => { const u = $("#b-url").value; if (u) window.open(u, "_blank", "noopener"); };
  // flows: record what the user does in the live view, name it, the agent replays it with browser_flow
  $("#b-rec").onclick = () => {
    if (B.recording) { $("#b-recname").hidden = false; $("#b-recinput").focus(); return; }
    sendWS({ type: "b_open" }); sendWS({ type: "b_rec_start" });
  };
  $("#b-recsave").onclick = () => { sendWS({ type: "b_rec_stop", name: $("#b-recinput").value.trim() }); $("#b-recname").hidden = true; $("#b-recinput").value = ""; };
  $("#b-recdrop").onclick = () => { sendWS({ type: "b_rec_stop", discard: true }); $("#b-recname").hidden = true; $("#b-recinput").value = ""; };
  $("#b-recinput").onkeydown = e => { if (e.key === "Enter") $("#b-recsave").click(); if (e.key === "Escape") $("#b-recdrop").click(); };
  document.querySelectorAll(".devs button").forEach(b => b.onclick = () => {
    document.querySelectorAll(".devs button").forEach(x => x.classList.toggle("on", x === b));
    sendWS({ type: "b_viewport", w: +b.dataset.w, h: +b.dataset.h }); });
}

/* ============================================================ terminal */
const T = {};
const ANSI = /\x1b\[[0-9;?]*[A-Za-z]/g;
function termStart(m) {
  $("#term-wrap").hidden = false;
  const body = $("#term"), head = el("div", "tcmd"), out = el("div", "tout");
  head.append(el("span", "", "$ " + m.command));
  if (m.background) { head.append(el("span", "bgtag", "BG")); const k = el("button", "kill", "stop"); k.onclick = () => sendWS({ type: "kill", id: m.id }); head.append(k); }
  head.append(el("span", "code")); body.append(head, out); T[m.id] = { head, out, bg: m.background, live: true }; termRun(); body.scrollTop = body.scrollHeight;
}
function termWrite(id, text) { const t = T[id]; if (!t) return; const b = $("#term"), stick = b.scrollHeight - b.scrollTop - b.clientHeight < 40;
  t.out.textContent += text.replace(ANSI, ""); if (stick) b.scrollTop = b.scrollHeight; }
function termEnd(id, code) { const t = T[id]; if (!t) return; t.live = false; const c = $(".code", t.head);
  c.textContent = `exit ${code}`; c.className = "code " + (code === 0 ? "code-ok" : "code-bad"); $(".kill", t.head)?.remove(); termRun(); }
function termRun() { const n = Object.values(T).filter(t => t.live && t.bg).length; $("#term-run").textContent = n ? `● ${n} running` : ""; }

/* ============================================================ left column */
let treeTimer = 0;
const scheduleTree = () => { clearTimeout(treeTimer); treeTimer = setTimeout(renderTree, 150); };
