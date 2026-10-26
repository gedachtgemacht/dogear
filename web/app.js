// dogear UI, part 6: WebSocket events, the composer, slash commands and boot.
/* ============================================================ events */
function handle(m) {
  if (m.type === "frame" || m.type.startsWith("b_")) return browserEvent(m);
  const keep = keepScroll();
  switch (m.type) {
    case "thinking":
      if (!S.think) { const d = el("details", "think"); d.open = true; d.append(el("summary", "", "Reasoning")); S.think = el("div"); d.append(S.think); workAdd(d); S.thinkText = ""; }
      S.thinkText += m.text; S.think.textContent = S.thinkText; S.think.scrollTop = 1e6; break;
    case "token":
      if (S.think) { S.think.parentElement.open = false; S.think = null; }
      if (!S.cur) { S.curText = ""; S.cur = el("div", "md"); turn().answer.append(S.cur); }
      S.curText += m.text; S.cur.innerHTML = md(S.curText); break;
    case "tool": {
      if (S.cur) { S.cur.classList.add("narr"); workAdd(S.cur); }   // text before a tool call is process, not the answer
      S.cur = null; S.think = null;
      const c = toolCard(m.id, m.name, m.args, m.label);
      if (m.name.startsWith("browser_")) { agentBusy(true); if (S.follow) openWS("@preview", true); }
      if (S.follow && wsOpen() && m.name === "Read" && m.args.file_path) {
        const a = +m.args.offset || 1; eyeOn(rel(m.args.file_path), a, a + Math.min(+m.args.limit || 60, 80));
      }
      break;
    }
    case "profile": { const o = [...$("#model").options].find(x => x.value === m.model);
      const caps = [m.tools ? "tools" : "no tools", m.vision ? "vision" : null, m.thinking ? "reasoning" : null].filter(Boolean).join(", ");
      if (o) o.title = `${m.params_b ? m.params_b.toFixed(1) + "B parameters" : "size unknown"}${m.moe ? " (MoE)" : ""}\ntoolbox: ${m.toolbox}, prompt: ${m.prompt}\n${caps}${m.notes.length ? "\n" + m.notes.join("\n") : ""}`;
      $("#model").title = o ? o.title : ""; break; }
    case "approval": approvalBox(m); break;
    case "sub": { const c = S.cards[m.id]; if (c) { c.card.classList.add("open"); c.tb.classList.add("show"); c.tb.append(el("div", "subline", m.text)); } break; }
    case "ask": askBox(m); break;
    case "ultra": ultraEvent(m); railUltra(m); break;
    case "undone": turn().after.append(el("div", "empty", `Restored ${m.files.length} file${m.files.length === 1 ? "" : "s"} to the state before the run.`)); scheduleTree(); break;
    case "result": { const c = S.cards[m.id]; if (c && c.name === "Ultra") { S.ultra = null; renderRail(S.todos); } if (c) { finishCard(c, m.ok, m.text, m.meta || {}); if (c.name.startsWith("browser_")) agentBusy(false); } break; }
    case "changed": {
      const p = rel(m.path); S.changed.set(p, m.created ? "A" : (S.changed.get(p) || "M")); S.flash.add(p); setTimeout(() => { S.flash.delete(p); }, 2000);
      if (/\.(html?|css|js|mjs|svg)$/i.test(p)) S.webTouched = true;
      if (m.text != null && S.follow && !S.wsDismissed) { openWS(null, true); m.created ? typeIn(p, m.text) : showEdit(p, m.text, m.diff); }
      else { delete E.files[p]; if (E.active === p) paintFile(p); }
      renderTabs(); scheduleTree(); reloadPreview(); break;
    }
    case "fs": scheduleTree(); reloadPreview(); break;
    case "term_start": if (m.background) openWS(null, true); termStart(m); break;
    case "term": termWrite(m.id, m.text); break;
    case "term_end": termEnd(m.id, m.code); break;
    case "todos": renderRail(m.items); break;
    case "pins": S.meta.pins = m.pins; S.turns.forEach(syncPin); renderOutline(); break;
    case "titles": if (m.session === S.sid) { S.meta.titles = m.titles; renderOutline(); } break;
    case "forked": renderSession(m.session); S.restore = m.restore; renderBranchBar();
      if (m.prefill) { $("#input").value = m.prefill; $("#input").focus(); }
      log.append(el("div", "empty", m.prefill ? "Branched before this message. Edit it and send." : "Branched. This is a copy; the original stays unchanged.")); log.scrollTop = log.scrollHeight; refresh(); break;
    case "mcp": renderMcp(m.servers); break;
    case "rated": { const t = S.turns[m.turn]; if (t?.ratePaint) t.ratePaint(m.rating, null); break; }
    case "library_saved": { const t = S.turns[m.turn];
      if (m.auto) { if (t && m.entries.length) libraryAutoLine(t, m.entries); sbBadges(); if (SB.tab === "memory") loadMemory(); break; } if (t?.ratePaint && t.rateEl) t.ratePaint({ value: 1 }, m); sbBadges(); if (SB.tab === "memory") loadMemory(); break; }
    case "plan_proposed": { const t = S.turns[m.user_idx] || S.turn; if (t) planCard(t, m.plan); S.draft = true; renderRail(S.todos); if (!S.planOpen) planShow(true); break; }
    case "plan_status": { const c = S.planCard; if (c) c.update(m); S.draft = false; renderRail(S.todos); break; }
    case "auto_saved": { const t = S.turns[m.user_idx] || S.turn; if (t) autoSavedLine(t, m.items); loadMemory(); break; }
    case "usage": {
      S.tok += m.out; const pct = m.prompt / m.ctx, i = $("#meter i");
      i.style.width = Math.min(100, pct * 100) + "%"; i.className = pct > .85 ? "hot" : pct > .6 ? "warn" : "";
      $("#meter b").textContent = `${(m.prompt / 1000).toFixed(1)}k / ${m.ctx / 1024}k · ${m.tps} t/s`; break;
    }
    case "notice": { turn().after.append(el("div", "empty", m.text)); break; }
    case "error": { const e = el("div", "errbox"); e.append(el("b", "", "Error"), el("span", "", m.text)); turn().answer.append(e); break; }
    case "summary": { const t = S.turns[m.user_idx] || S.turn; if (t) { if (S.cur && t === S.turn) t.raw = S.curText; applySummary(t, m); offerDiff(t); } break; }
    case "present": { const t = S.turns[m.user_idx] || S.turn; if (t) { if (!t.raw && t.answer.textContent) t.raw = t.answer.textContent; renderBlocks(t, m); offerDiff(t); } break; }
    case "done": if (S.cur && S.turn) S.turn.raw = S.curText; if (S.turns.length >= 4) sendWS({ type: "titles" }); setBusy(false); agentBusy(false); refresh(); if (S.follow && S.webTouched) openWS("@preview", true); S.webTouched = false; break;
    case "session": renderSession(m.session); S.viewOnly = !!m.live;
      if (m.live) { setBusy(true); $("#input").placeholder = "This branch is still running in the background (view only)"; } break;
    case "renamed": refresh(); if (m.id === S.sid) { S.meta.note = m.note || ""; renderBranchBar(); } break;
    case "runs": S.runs = Object.fromEntries(m.runs.map(r => [r.id, r])); if (m.runs.length && !S.planOpen) planShow(true); renderRail(S.todos); sbRuns(); break;
    case "run_status": S.runs[m.info.id] = { ...(S.runs[m.info.id] || {}), ...m.info }; renderRail(S.todos); sbRuns();
      if (S.viewOnly && m.info.id === S.sid && m.info.status !== "running" && m.info.status !== "waiting") { S.viewOnly = false; setBusy(false); sendWS({ type: "open", id: S.sid }); } break;
    case "run_event": { const prev = S.runs[m.run] || {}; S.runs[m.run] = { ...prev, ...m.info, approval: prev.approval };
      if (m.event.type === "approval") S.runs[m.run].approval = m.event;
      if (m.event.type === "result" || m.event.type === "done") S.runs[m.run].approval = null;
      if (m.event.type === "tool" || m.event.type === "approval" || m.event.type === "result") { renderRail(S.todos); sbRuns(); } }
      if (S.viewOnly && m.run === S.sid) handle(m.event); break;
    case "adopted": adoptCard(m); break;
    case "review_start": if (S.cur) { S.cur.classList.add("narr"); workAdd(S.cur); S.cur = null; S.curText = ""; } turn().after.querySelectorAll(".follow-ups").forEach(n => n.remove()); break;
    case "compacted": renderSession(m.session);
      log.append(el("div", "empty", `${m.auto ? "Context was nearly full, so " : ""}${m.replaced} messages were condensed: about ${Math.round(m.before / 1000)}k → ${Math.round(m.after / 1000)}k tokens.`));
      log.scrollTop = log.scrollHeight; break;
    case "turn_start": if (!S.busy) { renderSession(m.session); setBusy(true); } break;   // a run started in another window
  }
  keep();
}

function renderSession(s) {
  setTimeout(() => SB.tab === "memory" ? loadMemory() : sbBadges(), 0);
  S.sid = s.id; S.root = s.root; $("#root").value = s.root; S.cards = {}; S.queue = []; S.cur = null; S.changed.clear();
  S.draft = false; S.meta = { parent: s.parent || null, note: s.note || "", pins: s.pins || [], titles: s.titles || {}, lineage: s.lineage || s.id, worktree: s.worktree && !s.worktree.removed ? s.worktree : null }; S.ultra = null;
  $("#term").innerHTML = ""; for (const k in T) delete T[k]; termRun(); $("#term-wrap").hidden = true;
  log.innerHTML = ""; S.turns = []; S.turn = null; if (!s.messages.length) emptyState();
  for (const m of s.messages) {
    if (m.role === "user") {
      if (m.compact) {
        const d = el("details", "compactmark"); d.append(el("summary", "", `Earlier conversation condensed (${m.replaced || "?"} messages)`), el("pre", "", m.content.replace(/^\[[^\]]*\]\n*/, "")));
        clearEmpty(); log.append(d); S.turn = null;
      } else if (!m.review) newTurn(m.content, (m.imgs || []).map(n => "/img/" + n), m.mode || "edit");
    }
    else if (m.role === "assistant") {
      const t = turn(), calls = m.tool_calls || [];
      if (m.content && calls.length) { const n = el("div", "md narr"); n.innerHTML = md(m.content); workAdd(n); }
      for (const c of calls) {
        const a = c.function.arguments || {}, id = "h" + Math.random().toString(36).slice(2, 8);
        const lbl = a.file_path || a.command || a.pattern || a.url || a.path || a.shell_id || Object.values(a)[0] || "";
        S.queue.push(id); toolCard(id, c.function.name, a, typeof lbl === "string" ? lbl.slice(0, 160) : "");
      }
      if (!calls.length && m.content) {
        if (!m.plan) setAnswerText(t, m.content);
        if (m.summary) applySummary(t, m.summary);
        if (m.present) renderBlocks(t, m.present);
        if (m.plan) { planCard(t, m.plan); S.draft = (m.plan.status || "proposed") === "proposed"; }
      }
    } else if (m.role === "tool") {
      const c = S.cards[S.queue.shift()];
      if (c) { const ok = m.ok !== false; finishCard(c, ok, m.content, m.meta || {});
        if (c.name === "Bash" && c.args.command) { const id = "r" + Math.random().toString(36).slice(2, 7);
          termStart({ id, command: c.args.command, background: false }); termWrite(id, m.content); termEnd(id, m.meta?.exit ?? 0); }
        if (ok && m.meta?.diff) S.changed.set(rel(m.meta.path || ""), m.meta.created ? "A" : "M"); }
    }
  }
  renderRail(s.todos || []); renderBranchBar(); renderOutline();
  S.turns.forEach(t => { syncPin(t); if (t.raw) offerDiff(t); });
  E.files = {}; E.tabs = ["@preview"]; activate("@preview"); renderFiles();
  log.scrollTop = log.scrollHeight; refresh();
  const tab = new URLSearchParams(location.search).get("tab"); if (tab) activate(tab);
}


/* ============================================================ input */
let spinTimer = 0;
function stopRun() {
  const b = $("#stop"); b.disabled = true; b.textContent = "Stopping…";
  sendWS({ type: "stop", id: S.sid });
  clearTimeout(stopRun.t);
  stopRun.t = setTimeout(() => { if (S.busy) { b.disabled = false; b.textContent = "■ Stop"; } }, 8000);   // let the user try again
}
function setBusy(b) {
  if (!b) { const sb = $("#stop"); sb.disabled = false; sb.textContent = "■ Stop"; }
  S.busy = b; document.body.classList.toggle("busy", b); $("#spin").hidden = !b; $("#input").disabled = b;
  clearInterval(spinTimer);
  if (b) { S.t0 = Date.now(); S.tok = 0; const tick = () => { const s = Math.round((Date.now() - S.t0) / 1000);
      $("#spin-t").textContent = `Working · ${s}s · ${S.tok} tokens`; };
    tick(); spinTimer = setInterval(tick, 500); }
  else { S.cur = null; S.think = null; $("#input").focus(); }
}
const MODE_TXT = { ask: "Confirms edits and commands", edit: "Confirms commands", auto: "No confirmations", plan: "Read-only: proposes a plan" };
function setMode(v) { if (S.mode && S.mode !== "plan" && v === "plan") S.prevMode = S.mode; S.mode = v; document.querySelectorAll("#mode button").forEach(b => b.classList.toggle("on", b.dataset.v === v)); $("#h-mode").textContent = MODE_TXT[v]; }

const SLASHES = [
  ["/new", "start a new session"], ["/ultra", "multi-agent run: review | research | design | audit  <task>"], ["/compact", "condense the conversation to free context (optional focus)"], ["/clear", "clear this session"], ["/mode", "ask | edit | auto"], ["/model", "switch model"],
  ["/plan", "plan first: the model investigates and proposes a task board for approval  /plan <task>"], ["/mcp", "reload MCP servers"], ["/remember", "save a note for future sessions: /remember <text>"], ["/memory", "show saved notes, snippets and skills"], ["/init", "write a DOGEAR.md with project instructions for the agent"], ["/help", "list commands"],
];
function slashMenu(v) {
  const box = $("#slash"), items = v.startsWith("/") && !v.includes(" ") ? SLASHES.filter(s => s[0].startsWith(v)) : [];
  box.hidden = !items.length; box.innerHTML = "";
  items.forEach(([c, d]) => { const r = el("div", "", c); r.append(el("span", "", d)); r.onclick = () => { $("#input").value = c + " "; $("#input").focus(); slashMenu(""); }; box.append(r); });
}
function note(t) { clearEmpty(); log.append(el("div", "empty", t)); log.scrollTop = log.scrollHeight; }
function command(text) {
  const [c, ...rest] = text.split(/\s+/), arg = rest.join(" ");
  switch (c) {
    case "/new": case "/clear": sendWS({ type: "new" }); break;
    case "/mode": if (["ask", "edit", "auto"].includes(arg)) { setMode(arg); note(`Mode: ${arg}`); } else note("Usage: /mode ask | edit | auto"); break;
    case "/model": { const o = [...$("#model").options].find(o => o.value.includes(arg)); if (o && arg) { $("#model").value = o.value; note(`Model: ${o.value}`); } else note("Models: " + [...$("#model").options].map(o => o.value).join(", ")); break; }
    case "/plan": setMode("plan"); if (!arg) { note("Plan mode on. Describe the task; the model will investigate and propose a board for your approval."); break; } return arg;
    case "/mcp": sendWS({ type: "mcp_reload" }); note("Reloading MCP servers…"); break;
    case "/ultra": { const [pat, ...rest] = arg.split(/\s+/); if (!["review", "research", "design", "audit"].includes(pat)) { note("Usage: /ultra review|research|design|audit <task>"); break; }
      return `Use the Ultra tool with pattern "${pat}" for this task: ${rest.join(" ") || "the whole project"}`; }
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
  S.wsDismissed = false; if (S.wsAuto && wsOpen()) closeWS();
  S.hist.push(t); S.hi = S.hist.length; $("#input").value = ""; $("#input").style.height = ""; slashMenu("");
  if (t.startsWith("/")) { t = command(t); if (!t) return; }
  const imgs = ATT.splice(0); renderThumbs();
  newTurn(t, imgs.map(a => a.url)); setBusy(true);
  sendWS({ type: "user", text: t, images: imgs.map(a => a.b64), model: $("#model").value, think: $("#think").checked, review: $("#review").checked, mode: S.mode, root: $("#root").value.trim(), num_ctx: +$("#ctx").value });
  S.root = $("#root").value.trim(); log.scrollTop = log.scrollHeight;
}

/* ============================================================ boot */
async function refresh() {
  S.st = await (await fetch("/api/state")).json();
  const { settings: c, models, sessions } = S.st, sel = $("#model");
  if (S.st.name) { document.title = S.st.name; $(".brand span").textContent = S.st.name; }
  if (!sel.options.length) {
    const pf = S.st.profiles || {};
    for (const m of models.includes(c.model) ? models : [c.model, ...models]) {
      const o = new Option(pf[m] ? `${m}  ·  ${pf[m].label}` : m, m); o.title = (pf[m]?.notes || []).join("\n"); sel.append(o);
    }
    sel.value = c.model; $("#think").checked = c.think; $("#review").checked = c.review !== false; $("#ctx").value = String(c.num_ctx); $("#root").value = S.root = c.root; setMode(c.mode);
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
  $("#theme").onclick = () => { const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = t; store.set("dogear-theme", t); };
  document.querySelectorAll("#mode button").forEach(b => b.onclick = () => setMode(b.dataset.v));
  $("#composer").onsubmit = submit; $("#stop").onclick = stopRun;
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
    else if (e.key === "Tab" && e.shiftKey) { e.preventDefault(); const m = ["ask", "edit", "auto", "plan"]; setMode(m[(m.indexOf(S.mode) + 1) % 4]); }
    else if (S.ask && "123".includes(e.key) && e.key.length === 1 && !(e.target === inp && inp.value)) { e.preventDefault(); S.ask.answer(e.key !== "3", e.key === "2"); }
  });
  $("#root").onchange = () => { S.root = $("#root").value.trim(); sendWS({ type: "root", root: S.root }); S.changed.clear(); E.files = {}; renderFiles(); };
  $("#new").onclick = () => !S.busy && sendWS({ type: "new" });
  $("#refresh").onclick = renderTree; $("#mcp-reload").onclick = () => sendWS({ type: "mcp_reload" }); $("#mem-add").onclick = memForm;
  initBrowser();
  $("#plan-toggle").onclick = () => { planShow(!S.planOpen, true); if (S.planOpen) renderRail(S.todos); };
  if (store.get("dogear-plan", "") === "1") planShow(true), renderRail(S.todos);
  $("#outline-btn").onclick = e => { e.stopPropagation(); const b = $("#outline"); b.hidden = !b.hidden; $("#outline-btn").classList.toggle("on", !b.hidden);
    if (!b.hidden) { renderOutline(); sendWS({ type: "titles" }); b.querySelector("input")?.focus(); } };
  $("#cmp-x").onclick = () => { $("#cmp").hidden = true; };
  $("#var-x").onclick = () => { $("#var").hidden = true; };
  $("#var").addEventListener("pointerdown", e => { if (e.target === $("#var")) $("#var").hidden = true; });
  $("#cmp").addEventListener("pointerdown", e => { if (e.target === $("#cmp")) $("#cmp").hidden = true; });
  $("#menu").onclick = e => { e.stopPropagation(); drawer($("#drawer").hidden); };
  $("#ws-toggle").onclick = () => wsOpen() ? closeWS(true) : (S.wsDismissed = false, openWS(null, false));
  $("#gear").onclick = e => { e.stopPropagation(); $("#pop").hidden = !$("#pop").hidden; };
  $("#work").addEventListener("pointerdown", () => { S.wsAuto = false; });
  document.addEventListener("pointerdown", e => {
    if (!$("#drawer").hidden && !e.target.closest("#drawer, #menu")) drawer(false);
    if (!$("#pop").hidden && !e.target.closest("#pop, #gear")) $("#pop").hidden = true;
    if (!$("#outline").hidden && !e.target.closest("#outline, #outline-btn")) { $("#outline").hidden = true; $("#outline-btn").classList.remove("on"); }
  });
  $("#term-clear").onclick = () => { $("#term").innerHTML = ""; for (const k in T) delete T[k]; termRun(); $("#term-wrap").hidden = true; };
  await refresh(); emptyState(); renderTabs(); sbInit(); renderMcp([]); connect(); setBusy(false);
})();
