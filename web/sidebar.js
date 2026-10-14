/* ============================================================ sidebar
   One tabbed drawer instead of one long scroll: Files | Sessions | Memory | MCP.
   Loaded before app.js; this file only declares things, it reaches S, el, $, api ... when its functions run. */
const SB = { inbox: [], lib: [], tab: "files", view: "changed", fq: "", sq: "", mk: "all", mq: "", mem: [], mcp: [], exp: new Map(), older: false };
const sbStore = {
  get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private window */ } },
};
const baseName = p => (p || "").replace(/\/+$/, "").split("/").pop() || p || "";
const debounce = (fn, ms) => { let t = 0; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
function ago(t) {
  const s = Math.max(0, Date.now() / 1000 - t);
  return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : `${Math.floor(s / 86400)} d ago`;
}
function shortPath(p) {
  const parts = p.replace(/^\/home\/[^/]+/, "~").split("/").filter(Boolean);
  return parts.length > 3 ? "…/" + parts.slice(-2).join("/") : parts.join("/") || "/";
}
const plural2 = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

/* Suggestions from the helper model land here, not in the chat: nothing is saved until you press Save. */
function inboxLoad() {
  try { SB.inbox = JSON.parse(sessionStorage.getItem("dogear-inbox") || "[]"); } catch { SB.inbox = []; }
}
function inboxSave() { try { sessionStorage.setItem("dogear-inbox", JSON.stringify(SB.inbox.slice(-30))); } catch { /* private window */ } }
function inboxAdd(items) {
  const sid = S.sid;
  for (const it of items || []) if (!SB.inbox.some(x => x.kind === it.kind && x.name === it.name && x.session === sid)) SB.inbox.push({ ...it, session: sid });
  inboxSave(); sbBadges();
  if (SB.tab === "memory" && !$("#drawer").hidden) renderMemory();
}
function inboxCard(it) {
  const r = el("div", "ibx"), h = el("div", "ibx-h");
  h.append(el("span", `mem-k ${it.kind}`, MEM_LABEL[it.kind] || it.kind), el("b", "", it.name));
  const body = el("div", "ibx-b" + (it.kind === "snippet" ? " code" : ""));
  body.textContent = it.kind === "snippet" ? it.content.split("\n").slice(0, 6).join("\n") : it.content;
  const a = el("div", "ibx-a"), save = el("button", "", "Save"), no = el("button", "ghost", "Dismiss");
  const drop = () => { SB.inbox = SB.inbox.filter(x => x !== it); inboxSave(); renderMemory(); };
  save.onclick = async () => { if (await memSave(it)) drop(); };
  no.onclick = drop;
  a.append(save, no); r.append(h, body, a);
  return r;
}
function sbInit() {
  inboxLoad();
  SB.tab = sbStore.get("dogear-sb-tab", "files"); SB.view = sbStore.get("dogear-sb-view", "changed");
  document.querySelectorAll("#dtabs button").forEach(b => b.onclick = () => sbTab(b.dataset.t));
  document.querySelectorAll("#fseg button").forEach(b => b.onclick = () => { SB.view = b.dataset.v; sbStore.set("dogear-sb-view", SB.view); renderFiles(); });
  document.querySelectorAll("#mseg button").forEach(b => b.onclick = () => { SB.mk = b.dataset.v; renderMemory(); });
  $("#fq").oninput = debounce(e => { SB.fq = e.target.value; renderFiles(); }, 150);
  $("#sq").oninput = e => { SB.sq = e.target.value; renderSessions(); };
  $("#mq").oninput = e => { SB.mq = e.target.value; renderMemory(); };
  sbTab(SB.tab);
}
function sbTab(t) {
  if (!["files", "sessions", "memory", "mcp"].includes(t)) t = "files";
  SB.tab = t; sbStore.set("dogear-sb-tab", t);
  document.querySelectorAll("#dtabs button").forEach(b => { const on = b.dataset.t === t; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); });
  document.querySelectorAll(".dpane").forEach(p => { p.hidden = p.id !== "dp-" + t; });
  if (t === "memory") loadMemory();
  renderPane();
}
function renderPane() {
  ({ files: renderFiles, sessions: renderSessions, memory: renderMemory, mcp: renderMcp })[SB.tab]?.();
  sbBadges();
}
function sbBadges() {
  const live = Object.values(S.runs).filter(r => r.status === "running" || r.status === "waiting").length;
  const set = (id, n, cls = "") => { const i = $(id); if (!i) return; i.textContent = n ? String(n) : ""; i.className = cls; };
  set("#bd-files", S.changed.size);
  set("#bd-sessions", live || (S.st?.sessions || []).length, live ? "live" : "");
  set("#bd-memory", SB.inbox.length ? SB.inbox.length : SB.mem.length, SB.inbox.length ? "live" : "");
  $("#menu")?.classList.toggle("dot", SB.inbox.length > 0);
  const bad = SB.mcp.some(s => s.state === "error");
  set("#bd-mcp", SB.mcp.length, bad ? "bad" : "");
}
// called from the run events so the pane stays current while it is open
function sbRuns() { if (!$("#drawer").hidden && SB.tab === "sessions") renderSessions(); else sbBadges(); }

/* ---------------------------------------------------------------- files */
const fileRow = (path, badgeLetter, flash) => {
  const name = path.split("/").pop(), dir = path.includes("/") ? shortPath(path.slice(0, path.lastIndexOf("/"))) : "";
  const n = el("div", `frow${E.active === path ? " sel" : ""}${flash ? " flash" : ""}`); n.title = path; n.dataset.p = path;
  n.append(el("span", "fn", name));
  if (dir) n.append(el("span", "fd", dir));
  if (badgeLetter) n.append(el("span", `b ${badgeLetter}`, badgeLetter));
  n.onclick = () => { openWS(path); drawer(false); };
  return n;
};
async function renderFiles() {
  if (SB.tab !== "files" || $("#drawer").hidden) { sbBadges(); return; }
  const root = S.root || "";
  $("#proj-name").textContent = baseName(root) || "Project"; $("#proj-path").textContent = shortPath(root.slice(0, root.lastIndexOf("/")) || "/"); $("#proj-path").title = root;
  document.querySelectorAll("#fseg button").forEach(b => b.classList.toggle("on", b.dataset.v === SB.view));
  $("#fc-ch").textContent = S.changed.size ? String(S.changed.size) : "";
  const box = $("#flist"), q = SB.fq.trim(), fresh = document.createElement("div");
  if (q) {
    let rows;
    if (SB.view === "changed") rows = [...S.changed.keys()].filter(p => q.toLowerCase().split(/\s+/).every(w => p.toLowerCase().includes(w))).map(p => ({ path: p }));
    else { try { rows = await api("/api/find", { q }); } catch { rows = []; } }
    if ($("#fq").value.trim() !== q) return;                      // a newer query is on its way
    if (!rows.length) fresh.append(el("div", "dempty", `No file matches “${q}”.`));
    rows.forEach(r => fresh.append(fileRow(r.path, S.changed.get(r.path))));
  } else if (SB.view === "changed") {
    const items = [...S.changed.entries()].reverse();
    if (!items.length) {
      const d = el("div", "dempty"); d.append(el("p", "", "No changes in this session yet."), el("p", "dim", "Files the agent creates or edits appear here."));
      const b = el("button", "link", "Browse all files"); b.onclick = () => { SB.view = "all"; renderFiles(); }; d.append(b); fresh.append(d);
    }
    items.forEach(([p, b]) => fresh.append(fileRow(p, b, S.flash.has(p))));
  } else {
    await fillTree(fresh, ".");
  }
  box.replaceChildren(...fresh.childNodes);
}
const renderTree = renderFiles;
async function fillTree(box, path) {
  let list; try { list = await api("/api/tree", { path }); } catch { box.append(el("div", "dempty", "Cannot read the project directory.")); return; }
  if (!list.length && path === ".") { box.append(el("div", "dempty", "This folder is empty.")); return; }
  for (const e of list) {
    if (e.more) { box.append(el("div", "fmore", `… ${e.more} more not shown. Use the search to find a file.`)); continue; }
    const open = S.openDirs.has(e.path);
    const n = el("div", `n ${e.dir ? "dir" : "file"}${open ? " open" : ""}${E.active === e.path ? " sel" : ""}`); n.dataset.p = e.path; n.title = e.path;
    n.append(el("span", "", e.name));
    if (e.dir && e.count != null) n.append(el("span", "cnt", String(e.count)));
    const b = !e.dir && S.changed.get(e.path); if (b) n.append(el("span", `b ${b}`, b));
    if (S.flash.has(e.path)) n.classList.add("flash");
    box.append(n);
    if (e.dir) {
      n.onclick = () => { open ? S.openDirs.delete(e.path) : S.openDirs.add(e.path); renderFiles(); };
      if (open) { const k = el("div", "kids"); box.append(k); await fillTree(k, e.path); }
    } else n.onclick = () => { openWS(e.path); drawer(false); };
  }
}

/* ---------------------------------------------------------------- sessions, branches, parallel runs */
function runCards() {
  const list = Object.values(S.runs); if (!list.length) return null;
  const box = el("div", "kruns");
  for (const r of list) {
    const c = el("div", `krun ${r.status}`), top = el("div", "rt");
    top.append(el("span", "dot"), el("span", "rn", r.title)); c.append(top, el("div", "rl", `${plural2(r.steps || 0, "step")} · ${r.last || r.status}`));
    const rb = el("div", "rb"), btn = (txt, fn) => { const b = el("button", "", txt); b.onclick = fn; rb.append(b); };
    if (r.status === "waiting" && r.approval) {
      const a = r.approval, what = a.name === "Bash" ? "$ " + (a.args.command || "") : a.name + " " + JSON.stringify(a.args).slice(0, 80);
      c.append(el("div", "rl", what));
      btn("Allow", () => { sendWS({ type: "approve", id: a.id, ok: true, always: false, key: a.key || a.name }); r.approval = null; });
      btn("Always", () => { sendWS({ type: "approve", id: a.id, ok: true, always: true, key: a.key || a.name }); r.approval = null; });
      btn("Deny", () => { sendWS({ type: "approve", id: a.id, ok: false }); r.approval = null; });
    }
    btn("Open", () => { if (!S.busy || S.viewOnly) sendWS({ type: "open", id: r.id }); });
    if (r.status === "running" || r.status === "waiting") btn("Stop", () => sendWS({ type: "stop_run", id: r.id }));
    if (r.worktree && r.status !== "running" && r.status !== "waiting") btn("Adopt", () => sendWS({ type: "adopt", id: r.id }));
    if (r.worktree) btn("Discard", () => sendWS({ type: "discard", id: r.id }));
    c.append(rb); box.append(c);
  }
  return box;
}

// a thread is open when the user opened it, or by default when it holds the open session or a live run
let isOpen = () => true;
function sessionRow(s, kids, depth) {
  const run = S.runs[s.id], hasKids = kids.length > 0, expanded = hasKids && isOpen(s.id);
  const r = el("div", `srow${s.id === S.sid ? " on" : ""}${depth ? " branch" : ""}`);
  const ico = el("span", `sico${run ? " " + run.status : ""}`, run ? "" : depth ? "⑂" : "");
  if (hasKids) {
    ico.textContent = ""; ico.classList.add("chev"); ico.classList.toggle("openc", expanded);
    ico.onclick = e => { e.stopPropagation(); SB.exp.set(s.id, !expanded); renderSessions(); };
  }
  const main = el("div", "sm"), title = el("div", "st", s.title || "Untitled"); title.title = s.title;
  const meta = el("div", "sx");
  if (depth && s.parent_turn != null) meta.append(el("span", "", s.where === "before" ? `edited at turn ${s.parent_turn + 1}` : `from turn ${s.parent_turn + 1}`));
  meta.append(el("span", "", plural2(s.turns || 0, "turn")), el("span", "", ago(s.updated)));
  if (hasKids) meta.append(el("span", "", plural2(kids.length, "branch").replace(/branchs/, "branches")));
  if (s.worktree) meta.append(el("span", "chip", "worktree"));
  if (run) meta.append(el("span", `chip st-${run.status}`, run.status));
  main.append(title);
  if (s.note && depth) main.append(el("div", "snote", s.note));
  main.append(meta);
  const x = el("button", "sdel", "✕"); x.title = "Delete";
  let armed = 0;
  x.onclick = async e => {
    e.stopPropagation();
    if (!armed) { armed = 1; x.textContent = "Delete?"; x.classList.add("armed"); setTimeout(() => { armed = 0; x.textContent = "✕"; x.classList.remove("armed"); }, 2500); return; }
    await fetch(`/api/session/${s.id}`, { method: "DELETE" }); refresh();
  };
  r.append(ico, main, x);
  r.onclick = () => { if (S.busy && !run) return; sendWS({ type: "open", id: s.id }); drawer(false); };
  return r;
}

function renderSessions() {
  const box = $("#slist"), list = S.st?.sessions || [], q = SB.sq.trim().toLowerCase(), frag = document.createDocumentFragment();
  const runs = runCards();
  if (runs) { const h = el("div", "dgroup", "Parallel runs"); frag.append(h, runs); }
  const byId = new Map(list.map(s => [s.id, s])), kids = new Map();
  list.forEach(s => { if (s.parent && byId.has(s.parent)) { if (!kids.has(s.parent)) kids.set(s.parent, []); kids.get(s.parent).push(s); } });
  kids.forEach(a => a.sort((x, y) => x.updated - y.updated));
  const roots = list.filter(s => !(s.parent && byId.has(s.parent)));
  const latest = s => Math.max(s.updated, ...(kids.get(s.id) || []).map(latest));
  roots.sort((a, b) => latest(b) - latest(a));
  const match = s => !q || (s.title || "").toLowerCase().includes(q) || (kids.get(s.id) || []).some(match);
  const holdsLive = s => s.id === S.sid || (S.runs[s.id] && ["running", "waiting"].includes(S.runs[s.id].status)) || (kids.get(s.id) || []).some(holdsLive);
  isOpen = id => SB.exp.has(id) ? SB.exp.get(id) : holdsLive(byId.get(id));
  const shown = roots.filter(match);
  const draw = (s, depth, into) => {
    const ks = (kids.get(s.id) || []).filter(c => !q || match(c));
    into.append(sessionRow(s, ks, depth));
    if (ks.length && (q || isOpen(s.id))) { const k = el("div", "skids"); ks.forEach(c => draw(c, depth + 1, k)); into.append(k); }
  };
  const rootsOf = new Set(shown.map(s => s.root));
  const limit = SB.older || q ? shown.length : 12;
  let lastRoot = null;
  const ordered = rootsOf.size > 1 ? [...shown].sort((a, b) => (b.root === S.root) - (a.root === S.root)) : shown;
  ordered.slice(0, limit).forEach(s => {
    if (rootsOf.size > 1 && s.root !== lastRoot) { frag.append(el("div", "dgroup", baseName(s.root) || s.root)); lastRoot = s.root; }
    draw(s, 0, frag);
  });
  if (shown.length > limit) { const b = el("button", "link", `Show ${shown.length - limit} older`); b.onclick = () => { SB.older = true; renderSessions(); }; frag.append(b); }
  if (!shown.length) frag.append(el("div", "dempty", list.length ? `No session matches “${SB.sq}”.` : "No sessions yet. Describe a task to start."));
  box.replaceChildren(frag);
  sbBadges();
}
const renderHistory = renderSessions;

/* ---------------------------------------------------------------- memory */
async function loadLibrary() {
  try {
    const r = await fetch("/api/library"); if (!r.ok) return;
    SB.lib = await r.json();
    if (SB.tab === "memory") renderMemory(); else sbBadges();
  } catch { /* offline */ }
}
async function loadMemory() {
  loadLibrary();
  try {
    const r = await fetch("/api/memory?id=" + encodeURIComponent(S.sid || "")); if (!r.ok) return;
    SB.mem = (await r.json()).items;
    if (SB.tab === "memory") renderMemory(); else sbBadges();
  } catch { /* offline */ }
}
function renderLibrary(box, q) {
  const rows = SB.lib.filter(e => !q || (e.problem + " " + e.solution + " " + e.language + " " + e.framework + " " + e.project).toLowerCase().includes(q));
  box.innerHTML = "";
  if (!SB.lib.length) { box.append(el("div", "dempty", "The library is empty. Rate a finished run as good: reusable code from it is saved here and offered in later plans.")); return; }
  if (!rows.length) box.append(el("div", "dempty", "Nothing matches."));
  for (const e of rows) {
    const row = el("div", "mem-i"), head = el("div", "mem-h");
    head.append(el("b", "", e.problem));
    const x = el("button", "mini", "✕"); x.title = "Delete from the library";
    x.onclick = async ev => { ev.stopPropagation(); await fetch(`/api/library/${e.id}`, { method: "DELETE" }); loadLibrary(); };
    head.append(x);
    const meta = el("div", "lib-meta"); [e.language, e.framework, e.project, new Date(e.updated * 1000).toLocaleDateString()].filter(Boolean).forEach(v => meta.append(el("span", "chip", v)));
    if (e.uses > 1) meta.append(el("span", "chip", `used ${e.uses}x`));
    const body = el("pre", "mem-b", e.solution); body.hidden = true;
    head.onclick = () => body.hidden = !body.hidden;
    row.append(head, meta, body); box.append(row);
  }
}
function renderMemory() {
  const box = $("#mlist"), items = SB.mem, q = SB.mq.trim().toLowerCase();
  document.querySelectorAll("#mseg button").forEach(b => {
    b.classList.toggle("on", b.dataset.v === SB.mk);
    const n = b.dataset.v === "all" ? items.length : b.dataset.v === "library" ? SB.lib.length : items.filter(e => e.kind === b.dataset.v).length;
    b.dataset.n = n ? String(n) : "";
  });
  if (SB.mk === "library") { renderLibrary(box, q); sbBadges(); return; }
  box.innerHTML = "";
  if (SB.inbox.length && SB.mk === "all" && !q) {
    const head = el("div", "dgroup", `Suggestions (${SB.inbox.length})`);
    const clear = el("button", "link", "Dismiss all"); clear.onclick = () => { SB.inbox = []; inboxSave(); renderMemory(); };
    head.append(clear); box.append(head);
    SB.inbox.forEach(it => box.append(inboxCard(it)));
    box.append(el("div", "dgroup", "Saved"));
  }
  const rows = items.filter(e => (SB.mk === "all" || e.kind === SB.mk) && (!q || (e.name + " " + e.body + " " + e.tags.join(" ")).toLowerCase().includes(q)));
  if (!items.length) { box.append(el("div", "dempty", "Nothing saved yet. The agent saves what later sessions need; add notes yourself with ＋ or /remember.")); sbBadges(); return; }
  if (!rows.length) box.append(el("div", "dempty", "Nothing matches."));
  for (const e of rows) {
    const row = el("div", "mem-i"), head = el("div", "mem-h");
    head.append(el("span", "mem-k " + e.kind, MEM_LABEL[e.kind]), el("b", "", e.name));
    if (e.scope === "global") head.append(el("span", "mem-s", "all projects"));
    const x = el("button", "mini", "✕"); x.title = "Delete";
    x.onclick = async ev => { ev.stopPropagation(); await fetch(`/api/memory?session=${encodeURIComponent(S.sid || "")}&kind=${e.kind}&name=${encodeURIComponent(e.id)}&scope=${e.scope}`, { method: "DELETE" }); loadMemory(); };
    head.append(x);
    const body = el("pre", "mem-b", (e.description && e.kind !== "memory" ? e.description + "\n\n" : "") + e.body); body.hidden = true;
    head.onclick = () => body.hidden = !body.hidden;
    row.append(head, body); box.append(row);
  }
  sbBadges();
}

/* ---------------------------------------------------------------- MCP */
function renderMcp(servers) {
  if (servers) SB.mcp = servers;
  const box = $("#mcp"); box.innerHTML = "";
  if (!SB.mcp.length) { const d = el("div", "dempty"); d.innerHTML = "No MCP servers.<br>Add <code>.mcp.json</code> to the project or <code>~/dogear/mcp.json</code>."; box.append(d); sbBadges(); return; }
  for (const s of SB.mcp) {
    const d = el("div", `mcp-s ${s.state}`), h = el("div", "mh");
    h.innerHTML = `<i></i><b>${esc(s.name)}</b><span class="meta">${s.state === "ready" ? plural2(s.tools.length, "tool") : esc(s.state)}</span>`;
    d.append(h);
    const sm = el("small", "", s.error || s.tools.join(", ")); sm.hidden = !s.error; d.append(sm);
    d.onclick = () => sm.hidden = !sm.hidden; box.append(d);
  }
  sbBadges();
}
