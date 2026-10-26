// dogear UI, part 6: WebSocket events, the composer, slash commands and boot.

/* ============================================================ events */
const ON = {
  thinking(m) {
    if (!S.think) { const d = el("details", "think"); d.append(el("summary", "", "Reasoning")); S.think = el("div"); d.append(S.think); workAdd(d); S.thinkText = ""; }
    S.thinkText += m.text; S.think.textContent = S.thinkText; S.think.scrollTop = 1e6;
  },
  token(m) {
    if (S.think) { S.think = null; }
    if (!S.cur) { S.curText = ""; S.cur = el("div", "md"); turn().answer.append(S.cur); }
    S.curText += m.text; S.cur.innerHTML = md(S.curText);
  },
  tool(m) {
    const t = turn();
    if (S.cur) { S.cur.classList.add("narr"); t.work.append(S.cur); foldSteps(t); }   // text before a tool call is process, not the answer
    S.cur = null; S.think = null;
    const c = toolCard(m.id, m.name, m.args, m.label); c.turn = t;
    setStatus(t, t.st.state === "checking" ? "checking" : "working", { current: `${m.name === "TodoWrite" ? "Updating the task list" : m.label ? `${m.name} ${rel(m.label)}` : m.name}` });
    if (m.name.startsWith("browser_")) { agentBusy(true); addLink(t, "browser", "Watch the browser", () => openWS("@preview")); }
    if (S.follow && wsOpen() && m.name === "Read" && m.args.file_path) { const a = +m.args.offset || 1; eyeOn(rel(m.args.file_path), a, a + Math.min(+m.args.limit || 60, 80)); }
  },
  profile(m) {
    const o = [...$("#model").options].find(x => x.value === m.model);
    const caps = [m.tools ? "tools" : "no tools", m.vision ? "vision" : null, m.thinking ? "reasoning" : null].filter(Boolean).join(", ");
    if (o) o.title = `${m.params_b ? m.params_b.toFixed(1) + "B parameters" : "size unknown"}${m.moe ? " (MoE)" : ""}\ntoolbox: ${m.toolbox}, prompt: ${m.prompt}\n${caps}${m.notes.length ? "\n" + m.notes.join("\n") : ""}`;
    $("#model").title = o ? o.title : "";
  },
  approval(m) { approvalBox(m); },
  approval_done() { const t = S.turns.find(x => x.st.state === "waiting") || S.turn; S.ask = null; if (t && t.st.state === "waiting") waitingDone(t); },
  ask(m) { askBox(m); },
  sub(m) { const c = S.cards[m.id]; if (c) { c.tb.append(el("div", "subline", m.text)); } },
  result(m) {
    const c = S.cards[m.id]; if (!c) return;
    finishCard(c, m.ok, m.text, m.meta || {});
    if (c.name.startsWith("browser_")) agentBusy(false);
  },
  changed(m) {
    const p = rel(m.path), t = turn();
    S.changed.set(p, m.created ? "A" : (S.changed.get(p) || "M")); S.flash.add(p); setTimeout(() => { S.flash.delete(p); }, 2000);
    if (/\.(html?|css|js|mjs|svg)$/i.test(p)) S.webTouched = true;
    if (m.text != null && S.follow && wsOpen()) { m.created ? typeIn(p, m.text) : showEdit(p, m.text, m.diff); }
    else { delete E.files[p]; if (E.active === p) paintFile(p); }
    addLink(t, "file:" + p, `Open ${p.split("/").pop()}`, () => openWS(p));
    renderTabs(); scheduleTree(); reloadPreview();
  },
  fs() { scheduleTree(); reloadPreview(); },
  term_start(m) { termStart(m); if (m.background) addLink(turn(), "output", "Output", () => { openWS(null); $("#term-wrap").hidden = false; }); },
  term(m) { termWrite(m.id, m.text); },
  term_end(m) { termEnd(m.id, m.code); },
  todos(m) { renderTasks(m.items); },
  notice(m) { noticeLine(turn(), m.text); },
  error(m) { const e = el("div", "errbox"); e.append(el("b", "", "Error"), el("span", "", m.text)); turn().answer.append(e); },
  undone(m) { turn().after.append(el("div", "note", `Restored ${plural(m.files.length, "file")} to the state before the run.`)); scheduleTree(); },
  usage(m) {
    S.tok += m.out; const pct = m.prompt / m.ctx, i = $("#meter i"); $("#meter").classList.add("on");
    i.style.width = Math.min(100, pct * 100) + "%"; i.className = pct > .85 ? "hot" : pct > .6 ? "warn" : "";
    $("#meter b").textContent = pct > .6 ? `${Math.round(pct * 100)} %` : "";
    $("#meter").title = `Context: ${(m.prompt / 1000).toFixed(1)}k of ${m.ctx / 1024}k tokens · ${m.tps} tokens/s`;
  },
  summary(m) { const t = S.turns[m.user_idx] || S.turn; if (t) { if (S.cur && t === S.turn) t.raw = S.curText; applySummary(t, m); } },
  review_start() {
    const t = turn();
    if (S.cur) { S.cur.classList.add("narr"); t.work.append(S.cur); S.cur = null; S.curText = ""; }
    setStatus(t, "checking", { current: "" });
  },
  done() {
    if (S.cur && S.turn) S.turn.raw = S.curText;
    const t = S.turn;
    if (t && (t.st.state === "working" || t.st.state === "checking" || t.st.state === "waiting")) {
      // a turn that ended without a summary (a plan proposal, a plain answer): close the status quietly
      if (t.nsteps) setStatus(t, "done", { secs: Math.round((Date.now() - t.t0) / 1000) }); else t.status.hidden = true;
      t.work.classList.remove("live");
    }
    setBusy(false); agentBusy(false); refresh();
    S.webTouched = false;
  },
  session(m) {
    renderSession(m.session); S.viewOnly = !!m.live;
    if (m.live) { setBusy(true); $("#input").placeholder = "This session is still running in the background (view only)"; }
  },
  forked(m) {
    renderSession(m.session); S.restore = m.restore; renderBranchBar();
    if (m.prefill) { $("#input").value = m.prefill; $("#input").focus(); }
    note(m.prefill ? "New session based on this one. Edit the message and send it." : "New session based on this one; the original stays unchanged."); refresh();
  },
  renamed(m) { refresh(); if (m.id === S.sid) { S.meta.note = m.note || ""; renderBranchBar(); } },
  mcp(m) { renderMcp(m.servers); },
  plan_proposed(m) { const t = S.turns[m.user_idx] || S.turn; if (t) planCard(t, m.plan); S.draft = true; },
  plan_status(m) { const c = S.planCard; if (c) c.update(m); S.draft = false; },
  plan_task(m) {
    const c = S.planCard; if (c) c.task(m);
    if (m.status === "running") { S.cur = null; const t = newTurn(m.content, [], S.mode, { i: m.i, n: m.n }); setStatus(t, "working", {}); log.scrollTop = log.scrollHeight; }
  },
  runs(m) { S.runs = Object.fromEntries(m.runs.map(r => [r.id, r])); sbRuns(); },
  run_status(m) {
    S.runs[m.info.id] = { ...(S.runs[m.info.id] || {}), ...m.info }; sbRuns();
    if (S.viewOnly && m.info.id === S.sid && m.info.status !== "running" && m.info.status !== "waiting") { S.viewOnly = false; setBusy(false); sendWS({ type: "open", id: S.sid }); }
  },
  run_event(m) {
    const prev = S.runs[m.run] || {}; S.runs[m.run] = { ...prev, ...m.info, approval: prev.approval };
    if (m.event.type === "approval") S.runs[m.run].approval = m.event;
    if (m.event.type === "result" || m.event.type === "done") S.runs[m.run].approval = null;
    if (["tool", "approval", "result"].includes(m.event.type)) sbRuns();
    if (S.viewOnly && m.run === S.sid) handle(m.event);
  },
  adopted(m) { adoptCard(m); },
  compacted(m) {
    renderSession(m.session);
    note(`${m.auto ? "The context was nearly full, so " : ""}${m.replaced} messages were condensed: about ${Math.round(m.before / 1000)}k → ${Math.round(m.after / 1000)}k tokens.`);
  },
  turn_start(m) { if (!S.busy) { renderSession(m.session); setBusy(true); } },   // a run started in another window
  // events of features that are no longer shown: kept so old sessions and background runs never throw
  present() {}, pins() {}, titles() {}, rated() {}, library_saved() {}, auto_saved() {}, ultra() {},
};
function handle(m) {
  if (m.type === "frame" || m.type.startsWith("b_")) return browserEvent(m);
  const keep = keepScroll();
  ON[m.type]?.(m);
  keep();
}
function keepScroll() { const near = log.scrollHeight - log.scrollTop - log.clientHeight < 160; return () => { if (near) log.scrollTop = log.scrollHeight; }; }

/* ---- a stored session: rebuild the turns, their status blocks and what the runs left behind */
function renderSession(s) {
  setTimeout(() => SB.tab === "memory" ? loadMemory() : sbBadges(), 0);
  S.sid = s.id; S.root = s.root; $("#root").value = s.root; S.cards = {}; S.queue = []; S.cur = null; S.changed.clear();
  S.draft = false; S.planCard = null;
  S.meta = { parent: s.parent || null, note: s.note || "", lineage: s.lineage || s.id, worktree: s.worktree && !s.worktree.removed ? s.worktree : null };
  $("#term").innerHTML = ""; for (const k in T) delete T[k]; termRun(); $("#term-wrap").hidden = true;
  log.innerHTML = ""; S.turns = []; S.turn = null; if (!s.messages.length) emptyState();
  let sawSummary = false;
  for (const m of s.messages) {
    if (m.role === "user") {
      if (m.compact) {
        const d = el("details", "compactmark"); d.append(el("summary", "", `Earlier conversation condensed (${m.replaced || "?"} messages)`), el("pre", "", m.content.replace(/^\[[^\]]*\]\n*/, "")));
        clearEmpty(); log.append(d); S.turn = null;
      } else if (!m.review) { newTurn(m.task ? m.task.content : m.content, (m.imgs || []).map(n => "/img/" + n), m.mode || "edit", m.task || null); sawSummary = false; }
    } else if (m.role === "assistant") {
      const t = turn(), calls = m.tool_calls || [];
      if (m.content && calls.length) { const n = el("div", "md narr"); n.innerHTML = md(m.content); t.work.append(n); }
      for (const c of calls) {
        const a = c.function.arguments || {}, id = "h" + Math.random().toString(36).slice(2, 8);
        const lbl = a.file_path || a.command || a.pattern || a.url || a.path || a.shell_id || Object.values(a)[0] || "";
        S.queue.push(id); toolCard(id, c.function.name, a, typeof lbl === "string" ? lbl.slice(0, 160) : "").turn = t;
      }
      if (!calls.length) {
        if (m.content && !m.plan) setAnswerText(t, m.content);
        if (m.summary) { applySummary(t, m.summary); sawSummary = true; }
        if (m.plan) { planCard(t, m.plan); S.draft = (m.plan.status || "proposed") === "proposed"; }
      }
    } else if (m.role === "tool") {
      const c = S.cards[S.queue.shift()];
      if (c) {
        const ok = m.ok !== false; finishCard(c, ok, m.content, m.meta || {});
        if (c.name === "Bash" && c.args.command) { const id = "r" + Math.random().toString(36).slice(2, 7); termStart({ id, command: c.args.command, background: false }); termWrite(id, m.content); termEnd(id, m.meta?.exit ?? 0); }
        if (ok && m.meta?.diff) S.changed.set(rel(m.meta.path || ""), m.meta.created ? "A" : "M");
      }
    }
  }
  // a turn that did work but never got its summary (older sessions, crashes): say so instead of looking alive
  for (const t of S.turns) {
    t.work.classList.remove("live");
    if (t.nsteps && t.st.state === "idle") setStatus(t, "stopped", { reason: "no final report", secs: null });
    else if (!t.nsteps) t.status.hidden = true;
  }
  renderTasks(s.todos || []); renderBranchBar();
  E.files = {}; E.tabs = ["@preview"]; activate("@preview"); renderFiles();
  log.scrollTop = log.scrollHeight; refresh();
  const tab = new URLSearchParams(location.search).get("tab"); if (tab) activate(tab);
}

/* ============================================================ input */
let spinTimer = 0;
function stopRun() {
  sendWS({ type: "stop", id: S.sid });
  const t = S.turn; if (t && t.st.state !== "done") setStatus(t, t.st.state, { current: "stopping…" });
}
function setBusy(b) {
  S.busy = b; document.body.classList.toggle("busy", b); $("#input").disabled = b;
  clearInterval(spinTimer);
  if (b) {
    S.t0 = Date.now(); S.tok = 0;
    const t = S.turn; if (t && t.st.state === "idle") { t.t0 = Date.now(); setStatus(t, "working", {}); }
    spinTimer = setInterval(() => { const t = S.turn; if (t && (t.st.state === "working" || t.st.state === "checking")) paintStatus(t); }, 1000);
  } else {
    S.cur = null; S.think = null; $("#input").focus(); $("#input").placeholder = "Describe a task, or type / for commands";
    const t = S.turn; if (t) paintStatus(t);
  }
}
const MODE_TXT = { ask: "Will ask before every edit and every command", edit: "Will ask before running commands", auto: "Will not ask" };
const MODES = ["ask", "edit", "auto"];
function setMode(v, tell = true) {
  if (!MODES.includes(v)) v = "edit";
  const changed = S.mode !== v;
  S.mode = v; document.querySelectorAll("#mode button").forEach(b => b.classList.toggle("on", b.dataset.v === v)); $("#h-mode").textContent = MODE_TXT[v];
  if (tell && changed) sendWS({ type: "mode", mode: v });   // applies at once, also to a running turn
}

const SLASHES = [
  ["/plan", "plan first: the model investigates and proposes a task board for approval  /plan <task>"],
  ["/new", "start a new session"],
  ["/remember", "save a note for future sessions: /remember <text>"],
  ["/compact", "condense the conversation to free context (optional focus)"],
  ["/init", "write a DOGEAR.md with project instructions for the agent"],
  ["/memory", "show notes, snippets, skills and the design library"],
  ["/mcp", "reload MCP servers"],
  ["/help", "list commands"],
];
function slashMenu(v) {
  const box = $("#slash"), items = v.startsWith("/") && !v.includes(" ") ? SLASHES.filter(s => s[0].startsWith(v)) : [];
  box.hidden = !items.length; box.innerHTML = "";
  items.forEach(([c, d]) => { const r = el("div", "", c); r.append(el("span", "", d)); r.onclick = () => { $("#input").value = c + " "; $("#input").focus(); slashMenu(""); }; box.append(r); });
}
function note(t) { clearEmpty(); log.append(el("div", "note wide", t)); log.scrollTop = log.scrollHeight; }
function command(text) {
  const [c, ...rest] = text.split(/\s+/), arg = rest.join(" ");
  switch (c) {
    case "/new": sendWS({ type: "new" }); break;
    case "/plan": $("#planfirst").checked = true; if (!arg) { note("Plan first is on for the next message: the model investigates and proposes a board for your approval."); break; } return arg;
    case "/mcp": sendWS({ type: "mcp_reload" }); note("Reloading MCP servers…"); break;
    case "/compact": if (S.busy) note("Wait for the current run to finish."); else { sendWS({ type: "compact", focus: arg }); note("Condensing the conversation…"); } break;
    case "/remember": if (!arg) { note("Usage: /remember <what to keep>"); break; }
      memSave({ kind: "memory", name: arg.split(/\s+/).slice(0, 5).join(" "), content: arg, scope: "project" }).then(ok => ok && note("Saved to project memory.")); break;
    case "/memory": drawer(true); sbTab("memory"); break;
    case "/init": return "Explore this project (LS, Glob, Read the key files) and write a concise DOGEAR.md in the project root: what it is, how to run, test and build it, the layout, and the conventions a coding agent must follow.";
    default: note("Commands: " + SLASHES.map(s => s[0]).join("  "));
  }
  return null;
}
const ATT = [];
async function addImage(file) {
  if (!file || !file.type.startsWith("image/") || ATT.length >= 4) return;
  try {
    const bmp = await createImageBitmap(file), k = Math.min(1, 1568 / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas"); c.width = Math.max(1, Math.round(bmp.width * k)); c.height = Math.max(1, Math.round(bmp.height * k));
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    const url = c.toDataURL("image/jpeg", 0.88); ATT.push({ b64: url.split(",")[1], url }); renderThumbs();
  } catch { note("That image could not be read."); }
}
function renderThumbs() {
  const box = $("#thumbs"); box.innerHTML = ""; box.hidden = !ATT.length;
  ATT.forEach((a, i) => { const t = el("div", "thumb"), im = el("img"); im.src = a.url; const x = el("button", "", "✕"); x.type = "button"; x.onclick = () => { ATT.splice(i, 1); renderThumbs(); }; t.append(im, x); box.append(t); });
}

function submit(e) {
  e?.preventDefault(); let t = $("#input").value.trim(); if ((!t && !ATT.length) || S.busy) return;
  if (!t) t = "Look at the attached image(s) and describe what is relevant for this project.";
  S.hist.push(t); S.hi = S.hist.length; $("#input").value = ""; $("#input").style.height = ""; slashMenu("");
  if (t.startsWith("/")) { t = command(t); if (!t) return; }
  const imgs = ATT.splice(0); renderThumbs();
  const planFirst = $("#planfirst").checked; $("#planfirst").checked = false;
  const mode = planFirst ? "plan" : S.mode;
  const tn = newTurn(t, imgs.map(a => a.url), mode); setStatus(tn, "working", {}); setBusy(true);
  sendWS({ type: "user", text: t, images: imgs.map(a => a.b64), model: $("#model").value, think: $("#think").checked, review: $("#review").checked, mode, root: $("#root").value.trim(), num_ctx: +$("#ctx").value, persist: true });
  S.root = $("#root").value.trim(); log.scrollTop = log.scrollHeight;
}

/* ============================================================ boot */
async function refresh() {
  S.st = await (await fetch("/api/state")).json();
  const { settings: c, models, sessions } = S.st, sel = $("#model");
  if (S.st.name) { document.title = document.title.startsWith("●") ? document.title : S.st.name; $(".brand span").textContent = S.st.name; }
  if (!sel.options.length) {
    const pf = S.st.profiles || {};
    for (const m of models.includes(c.model) ? models : [c.model, ...models]) {
      const o = new Option(m, m); o.title = [pf[m]?.label, ...(pf[m]?.notes || [])].filter(Boolean).join("\n"); sel.append(o);
    }
    sel.value = c.model; $("#think").checked = c.think; $("#review").checked = c.review !== false; $("#ctx").value = String(c.num_ctx); $("#root").value = S.root = c.root; setMode(c.mode, false);
  }
  renderSessions();
}
function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`); S.ws = ws;
  ws.onopen = () => { sendWS({ type: "b_sub" }); sendWS({ type: "runs" }); const id = new URLSearchParams(location.search).get("session"); if (id && !S.opened) { S.opened = 1; sendWS({ type: "open", id }); } };
  ws.onmessage = ev => handle(JSON.parse(ev.data));
  ws.onclose = () => { setBusy(false); setTimeout(connect, 1500); };
}

(async function init() {
  document.documentElement.dataset.theme = new URLSearchParams(location.search).get("theme") || store.get("dogear-theme", "dark");
  S.variants = store.get("dogear-variants", "0") === "1"; $("#variants").checked = S.variants;
  $("#variants").onchange = () => { S.variants = $("#variants").checked; store.set("dogear-variants", S.variants ? "1" : "0"); };
  $("#theme").onclick = () => { const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = t; store.set("dogear-theme", t); };
  document.querySelectorAll("#mode button").forEach(b => b.onclick = () => setMode(b.dataset.v));
  $("#composer").onsubmit = submit;
  $("#attach").onclick = () => $("#file").click();
  $("#file").onchange = async e => { for (const f of e.target.files) await addImage(f); e.target.value = ""; };
  $("#input").addEventListener("paste", e => {
    const files = [...(e.clipboardData?.items || [])].filter(i => i.kind === "file" && i.type.startsWith("image/")).map(i => i.getAsFile());
    if (files.length) { e.preventDefault(); files.forEach(addImage); }
  });
  const chat = $(".chat");
  ["dragenter", "dragover"].forEach(ev => chat.addEventListener(ev, e => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { e.preventDefault(); chat.classList.add("drop"); } }));
  ["dragleave", "drop"].forEach(ev => chat.addEventListener(ev, e => { if (ev === "dragleave" && chat.contains(e.relatedTarget)) return; chat.classList.remove("drop"); }));
  chat.addEventListener("drop", e => { e.preventDefault(); [...e.dataTransfer.files].forEach(addImage); });
  const inp = $("#input");
  inp.oninput = () => { inp.style.height = "auto"; inp.style.height = Math.min(inp.scrollHeight, innerHeight * .38) + "px"; slashMenu(inp.value); };
  inp.onkeydown = e => {
    if (e.key === "Enter" && !e.shiftKey) submit(e);
    else if (e.key === "ArrowUp" && !inp.value && S.hist.length) { S.hi = Math.max(0, S.hi - 1); inp.value = S.hist[S.hi]; e.preventDefault(); }
  };
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !$("#drawer").hidden) drawer(false);
    else if (e.key === "Escape" && S.busy && document.activeElement !== bov) stopRun();
    else if (e.key === "Tab" && e.shiftKey) { e.preventDefault(); setMode(MODES[(MODES.indexOf(S.mode) + 1) % MODES.length]); }
    else if (S.ask && "123".includes(e.key) && e.key.length === 1 && !(e.target === inp && inp.value)) { e.preventDefault(); S.ask.answer(e.key !== "3", e.key === "2"); }
  });
  $("#root").onchange = () => { S.root = $("#root").value.trim(); sendWS({ type: "root", root: S.root }); S.changed.clear(); E.files = {}; renderFiles(); };
  $("#new").onclick = $("#new-top").onclick = () => !S.busy && sendWS({ type: "new" });
  $("#refresh").onclick = renderTree; $("#mcp-reload").onclick = () => sendWS({ type: "mcp_reload" }); $("#mem-add").onclick = memForm;
  $("#open-memory").onclick = () => { $("#pop").hidden = true; drawer(true); sbTab("memory"); };
  $("#open-models").onclick = () => { $("#pop").hidden = true; drawer(true); sbTab("models"); };
  $("#models-reload").onclick = () => renderModels();
  $("#open-mcp").onclick = () => { $("#pop").hidden = true; drawer(true); sbTab("mcp"); };
  initBrowser();
  $("#cmp-x").onclick = () => { $("#cmp").hidden = true; };
  $("#var-x").onclick = () => { $("#var").hidden = true; };
  $("#var").addEventListener("pointerdown", e => { if (e.target === $("#var")) $("#var").hidden = true; });
  $("#cmp").addEventListener("pointerdown", e => { if (e.target === $("#cmp")) $("#cmp").hidden = true; });
  $("#menu").onclick = e => { e.stopPropagation(); drawer($("#drawer").hidden); };
  $("#ws-toggle").onclick = () => wsOpen() ? closeWS() : openWS(null);
  $("#gear").onclick = e => { e.stopPropagation(); $("#pop").hidden = !$("#pop").hidden; };
  document.addEventListener("pointerdown", e => {
    if (!$("#drawer").hidden && !e.target.closest("#drawer, #menu")) drawer(false);
    if (!$("#pop").hidden && !e.target.closest("#pop, #gear")) $("#pop").hidden = true;
  });
  $("#term-clear").onclick = () => { $("#term").innerHTML = ""; for (const k in T) delete T[k]; termRun(); $("#term-wrap").hidden = true; };
  await refresh(); emptyState(); renderTabs(); sbInit(); renderMcp([]); connect(); setBusy(false);
})();
