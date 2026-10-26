// dogear UI, part 5: the plan board (kanban), parallel variants, outline, pins, branches, compare and word diff.
/* ============================================================ plan rail */
const LANES = [["pending", "To do", "todo"], ["in_progress", "Doing", "doing"], ["completed", "Done", "done"]];
let railSeen = {};
function railUltra(m) {
  if (m.event === "phase") S.ultra = { ...(S.ultra || { running: 0, done: 0, failed: 0 }), phase: m.phase };
  else if (m.event === "agent") {
    const u = S.ultra = S.ultra || { phase: m.phase, running: 0, done: 0, failed: 0, ag: {} };
    u.ag = u.ag || {}; u.ag[m.id] = m.state;
    const v = Object.values(u.ag); u.running = v.filter(x => x === "running").length; u.done = v.filter(x => x === "done").length; u.failed = v.filter(x => x === "failed").length;
  }
  renderRail(S.todos);
}
function planShow(on, user = false) {
  S.planOpen = on; if (user) store.set("dogear-plan", on ? "1" : "0");
  $("#plan").hidden = !on; $("#ide").classList.toggle("pl", on); $("#plan-toggle").classList.toggle("on", on);
}
function renderRail(items) {
  S.todos = items || [];
  const box = $("#plan"), done = S.todos.filter(t => t.status === "completed").length;
  $("#plan-toggle").classList.toggle("has", S.todos.length > 0);
  // the first plan of a session opens the board by itself (unless the user closed it)
  if (S.todos.length && !S.planOpen && store.get("dogear-plan", "") !== "0") planShow(true);
  if (!S.planOpen) return;
  const keepAdd = box.querySelector(".add")?.value || "", hadFocus = document.activeElement === box.querySelector(".add");
  box.innerHTML = "";
  const send = list => sendWS({ type: "set_todos", items: list });
  const head = el("div", "ph");
  head.append(el("b", "", "Plan"), el("span", "cnt", `${done}/${S.todos.length}`), el("span", "sp"));
  if (done) { const c = el("button", "", "Clear done"); c.onclick = () => send(S.todos.filter(t => t.status !== "completed")); head.append(c); }
  const x = el("button", "", "✕"); x.title = "Hide the board"; x.onclick = () => planShow(false, true); head.append(x);
  const prog = el("div", "pbar"), bar = el("i"); bar.style.width = (S.todos.length ? done / S.todos.length * 100 : 0) + "%"; prog.append(bar);
  box.append(head, prog);
  if (S.draft) box.append(el("div", "kdraft", "Draft plan. Review it in the chat and approve to start."));
  const body = el("div", "pbody");
  const add = el("input", "add"); add.placeholder = "Add a task…"; add.value = keepAdd;
  add.onkeydown = e => { if (e.key === "Enter" && add.value.trim()) { send([...S.todos, { content: add.value.trim(), status: "pending" }]); add.value = ""; } };
  body.append(add);
  if (!S.todos.length) body.append(el("div", "kempty", "No plan yet. For multi-step work the agent writes one and keeps it current; you can also add tasks here and drag them between columns."));
  let drag = null;
  for (const [st, name, cls] of LANES) {
    const lane = el("div", `klane ${cls}`), h = el("h4", ""), list = S.todos.map((t, i) => ({ t, i })).filter(o => o.t.status === st);
    h.append(el("span", "", name), el("span", "", String(list.length))); lane.append(h);
    lane.ondragover = e => { e.preventDefault(); lane.classList.add("over"); };
    lane.ondragleave = () => lane.classList.remove("over");
    lane.ondrop = e => {
      e.preventDefault(); lane.classList.remove("over"); if (drag == null) return;
      const moved = { ...S.todos[drag], status: st }, rest = S.todos.filter((_, k) => k !== drag), before = e.target.closest(".kcard")?.dataset.i;
      const at = before != null && +before !== drag ? rest.findIndex(o => o === S.todos[+before]) : -1;
      if (at >= 0) rest.splice(at, 0, moved); else rest.push(moved);
      send(rest);
    };
    for (const { t, i } of list) {
      const c = el("div", "kcard"); c.draggable = true; c.dataset.i = i;
      c.append(el("div", "kt", t.content));
      if (railSeen[t.content] && railSeen[t.content] !== st) c.classList.add("moved");
      const rm = el("button", "kx", "✕"); rm.title = "Remove"; rm.onclick = () => send(S.todos.filter((_, k) => k !== i)); c.append(rm);
      const mv = el("div", "kmv"), step = d => { const o = ["pending", "in_progress", "completed"], n = o[Math.max(0, Math.min(2, o.indexOf(st) + d))];
        send(S.todos.map((x, k) => k === i ? { ...x, status: n } : x)); };
      if (st !== "pending") { const b = el("button", "", "◀"); b.onclick = () => step(-1); mv.append(b); }
      if (st !== "completed") { const b = el("button", "", "▶"); b.onclick = () => step(1); mv.append(b); }
      c.append(mv);
      c.ondragstart = e => { drag = i; c.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", t.content); };
      c.ondragend = () => { c.classList.remove("dragging"); drag = null; };
      lane.append(c);
    }
    body.append(lane);
  }
  const runs = runsSection(); if (runs) { const h = el("div", "klane runs"); h.append(el("h4", "", "Parallel runs")); h.append(runs); body.prepend(h); }
  if (S.ultra) { const u = S.ultra; body.append(el("div", "kultra", `Ultra · ${u.phase || "starting"} · ${u.running || 0} running · ${u.done || 0} done${u.failed ? ` · ${u.failed} failed` : ""}`)); }
  box.append(body);
  if (hadFocus) box.querySelector(".add")?.focus();
  railSeen = Object.fromEntries(S.todos.map(t => [t.content, t.status]));
}

/* ============================================================ parallel variants */
function openVariants(t) {
  const dlg = $("#var"), body = $("#var-body"); dlg.hidden = false; body.innerHTML = "";
  const rep = el("label", "vopt"), cb = el("input"); cb.type = "checkbox"; cb.checked = true; rep.append(cb, "These are alternatives to this message (branch before it). Uncheck to continue after this turn.");
  body.append(rep);
  const areas = [];
  const addArea = (val = "") => { const l = el("label", "v", `Variant ${String.fromCharCode(65 + areas.length)}`), ta = el("textarea"); ta.value = val;
    ta.placeholder = areas.length ? "A different direction, e.g. “Do it with a table instead”" : ""; l.append(ta); areas.push(ta); add.before(l); };
  const row = el("div", "vrow"), add = el("button", "add", "+ Add variant"); add.type = "button";
  const go = el("button", "go", "Start in parallel"); go.type = "button";
  add.onclick = () => areas.length < 4 && addArea();
  go.onclick = () => { const prompts = areas.map(a => a.value.trim()).filter(Boolean); if (prompts.length < 1) return;
    sendWS({ type: "variants", turn: t.i, where: cb.checked ? "before" : "after", prompts }); dlg.hidden = true; planShow(true); };
  row.append(add, go); body.append(row); addArea(t.text || ""); addArea();
  areas[1].focus();
}
function adoptCard(m) {
  const c = el("div", "adoptcard");
  c.append(el("b", "", `Adopted ${m.applied.length} file${m.applied.length === 1 ? "" : "s"} into the project`));
  if (m.applied.length) c.append(el("code", "", m.applied.slice(0, 8).join("\n")));
  if (m.conflicts.length) c.append(el("div", "", `${m.conflicts.length} file${m.conflicts.length === 1 ? "" : "s"} changed in both places and were left alone:`), el("code", "", m.conflicts.slice(0, 8).join("\n")));
  if (m.undo) { const u = el("button", "difftoggle", "Undo adoption"); u.onclick = () => { sendWS({ type: "undo", root: m.undo.root, to: m.undo.sha }); u.remove(); }; c.append(u); }
  log.append(c); log.scrollTop = log.scrollHeight;
}
function runsSection() {
  const list = Object.values(S.runs); if (!list.length) return null;
  const live = list.filter(r => r.status === "running" || r.status === "waiting").length, waiting = list.filter(r => r.status === "waiting").length;
  const box = el("div", "kruns"), c = el("div", `krun ${live ? "running" : "done"}`), top = el("div", "rt");
  top.append(el("span", "dot"), el("span", "rn", `${plural(list.length, "parallel run")}`));
  c.append(top, el("div", "rl", `${live} running${waiting ? ` · ${waiting} need${waiting === 1 ? "s" : ""} approval` : ""} · ${list.length - live} finished`));
  const rb = el("div", "rb"), b = el("button", "", "Manage in Sessions"); b.onclick = () => { drawer(true); sbTab("sessions"); }; rb.append(b);
  c.append(rb); box.append(c); return box;
}

/* ============================================================ outline, pins, branches */
const firstLine = s => { const l = (s || "").trim().split("\n")[0]; return l.length > 60 ? l.slice(0, 58) + "…" : l; };
const turnTitle = t => S.meta.titles?.[t.i] || firstLine(t.text) || `Turn ${t.i + 1}`;
function syncPin(t) { const on = S.meta.pins.includes(t.i); t.pinBtn?.classList.toggle("on", on); t.bar?.classList.toggle("pinned", on); }
function jumpTo(t) { t.el.scrollIntoView({ block: "start", behavior: "smooth" }); t.el.classList.remove("flash"); void t.el.offsetWidth; t.el.classList.add("flash"); }
function renderOutline() {
  const btn = $("#outline-btn"), box = $("#outline");
  btn.hidden = S.turns.length < 2; if (btn.hidden) { box.hidden = true; return; }
  if (box.hidden) return;
  const q = box.querySelector("input")?.value || ""; box.innerHTML = "";
  const inp = el("input"); inp.placeholder = "Filter turns…"; inp.value = q; inp.oninput = renderOutline; box.append(inp);
  const match = t => !inp.value || (turnTitle(t) + " " + t.text).toLowerCase().includes(inp.value.toLowerCase());
  const row = t => { const r = el("div", "oi"), st = el("button", `star${S.meta.pins.includes(t.i) ? " on" : ""}`, "★");
    st.onclick = e => { e.stopPropagation(); sendWS({ type: "pin", turn: t.i, on: !S.meta.pins.includes(t.i) }); };
    const meta = [t.sum && t.sum.dataset.n ? t.sum.dataset.n : ""].filter(Boolean).join(" ");
    r.append(el("span", "n", String(t.i + 1)), el("span", "t", turnTitle(t)), el("span", "meta", meta), st); r.onclick = () => { jumpTo(t); box.hidden = true; $("#outline-btn").classList.remove("on"); }; return r; };
  const pinned = S.turns.filter(t => S.meta.pins.includes(t.i) && match(t));
  if (pinned.length) { box.append(el("h5", "", "Pinned")); pinned.forEach(t => box.append(row(t))); }
  box.append(el("h5", "", "All turns")); S.turns.filter(match).forEach(t => box.append(row(t)));
}
function renderBranchBar() {
  const b = $("#branchbar"), p = S.meta.parent; b.hidden = !p; if (!p) return; b.innerHTML = "";
  b.append(el("span", "", `Branch of “${p.title}” · ${p.where === "before" ? `edited at turn ${p.turn + 1}` : `from turn ${p.turn + 1}`}${S.meta.worktree ? " · own worktree" : ""}${S.meta.note ? " — " + S.meta.note : ""}`));
  const add = (txt, fn, title) => { const x = el("button", "", txt); if (title) x.title = title; x.onclick = fn; b.append(x); };
  add("Compare", () => openCompare());
  if (S.meta.worktree) {
    add("Adopt into project", () => sendWS({ type: "adopt", id: S.sid }), "Copies the files this branch changed into the original project. Files changed in both places are left alone and listed.");
    add("Discard worktree", () => sendWS({ type: "discard", id: S.sid }));
  }
  add("Open original", () => !S.busy && sendWS({ type: "open", id: p.id }));
  if (S.restore) add("Restore this branch's files", () => { sendWS({ type: "undo", root: S.restore.root, to: S.restore.sha }); S.restore = null; renderBranchBar(); }, "Puts the project files back to the state at the branch point (a safety checkpoint is made first)");
}

const userPos = msgs => msgs.map((m, i) => (m.role === "user" && !m.review && !m.compact) ? i : -1).filter(i => i >= 0);
function turnsOf(s) {
  const msgs = s.messages, pos = userPos(msgs);
  return pos.map((i, n) => { const end = pos[n + 1] ?? msgs.length, part = msgs.slice(i, end);
    const ans = [...part].reverse().find(m => m.role === "assistant" && m.content && !(m.tool_calls || []).length);
    return { user: msgs[i].content, answer: ans ? ans.content : "", summary: ans?.summary || part.find(m => m.summary)?.summary || null }; });
}
async function openCompare() {
  const dlg = $("#cmp"), sel = $("#cmp-sel"), body = $("#cmp-body"); dlg.hidden = false; body.innerHTML = "Loading…";
  const list = (await (await fetch(`/api/branches?id=${S.sid}`)).json()).filter(b => b.id !== S.sid);
  sel.innerHTML = ""; list.forEach(b => sel.append(new Option(`${b.title} · ${b.turns} turns`, b.id)));
  if (S.meta.parent && list.some(b => b.id === S.meta.parent.id)) sel.value = S.meta.parent.id;
  const draw = async () => {
    if (!sel.value) { body.innerHTML = "No other branch to compare with yet. Branch from any turn with ⑂."; return; }
    const [a, b] = await Promise.all([S.sid, sel.value].map(id => fetch(`/api/session/${id}`).then(r => r.json())));
    const A = turnsOf(a), B = turnsOf(b); let k = 0; while (k < A.length && k < B.length && A[k].user === B[k].user && A[k].answer === B[k].answer) k++;
    $("#cmp-meta").textContent = `${k} shared turn${k === 1 ? "" : "s"}`; body.innerHTML = "";
    body.append(el("div", "colh", `${a.title} (this)`), el("div", "colh", b.title));
    if (k) body.append(el("div", "same", `The first ${k} turn${k === 1 ? " is" : "s are"} identical.`));
    const files = x => x && x.changes && x.changes.length ? x.changes.map(c => `${c.created ? "+" : "~"} ${c.path.split("/").slice(-2).join("/")}`).join("  ") : "no file changes";
    for (let i = k; i < Math.max(A.length, B.length); i++) {
      const cell = (T, side) => { const c = el("div", "cell"); if (!T) { c.append(el("div", "q", "(no turn)")); return c; }
        const q = el("div", "q", T.user.slice(0, 160)), an = el("div", "a"); an.innerHTML = T.answer ? md(T.answer) : "(no answer)";
        c.append(q, an, el("div", "m", `${T.summary ? `${plural(T.summary.steps || 0, "step")} · ${T.summary.secs || 0}s · ` : ""}${files(T.summary)}`)); c._ans = an; return c; };
      const ca = cell(A[i]), cb = cell(B[i]);
      if (A[i] && B[i] && A[i].answer && B[i].answer) {
        const t = el("button", "difftoggle", "Show differences"); t.onclick = () => { const on = t.classList.toggle("on"); if (on) { const d = diffWords(A[i].answer, B[i].answer);
            if (d) { cb._ans.innerHTML = d.html; cb._ans.classList.add("dview"); } } else { cb._ans.innerHTML = md(B[i].answer); cb._ans.classList.remove("dview"); } };
        body.append(ca, cb, t); continue;
      }
      body.append(ca, cb);
    }
  };
  sel.onchange = draw; await draw();
}

/* ---- word diff for revisions */
function diffWords(aText, bText) {
  const tok = s => s.match(/\n|[^\s]+/g) || [], A = tok(aText), B = tok(bText);
  let p = 0; while (p < A.length && p < B.length && A[p] === B[p]) p++;
  let ea = A.length, eb = B.length; while (ea > p && eb > p && A[ea - 1] === B[eb - 1]) { ea--; eb--; }
  const a = A.slice(p, ea), b = B.slice(p, eb), n = a.length, m = b.length;
  if (n * m > 12e6) return null;
  const W = m + 1, dp = new Uint16Array((n + 1) * W);
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i * W + j] = a[i] === b[j] ? dp[(i + 1) * W + j + 1] + 1 : Math.max(dp[(i + 1) * W + j], dp[i * W + j + 1]);
  const ops = A.slice(0, p).map(x => ["=", x]); let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { ops.push(["=", a[i]]); i++; j++; }
    else if (dp[(i + 1) * W + j] >= dp[i * W + j + 1]) ops.push(["-", a[i++]]); else ops.push(["+", b[j++]]);
  }
  while (i < n) ops.push(["-", a[i++]]); while (j < m) ops.push(["+", b[j++]]);
  A.slice(ea).forEach(x => ops.push(["=", x]));
  let html = "", add = 0, del = 0, run = null, lead = false;   // lead: a separating space is needed before the next piece
  const flush = () => {
    if (!run) return;
    const t = esc(run.w.join(" "));
    html += (lead ? " " : "") + (run.k === "=" ? t : `<${run.k === "+" ? "ins" : "del"}>${t}</${run.k === "+" ? "ins" : "del"}>`);
    lead = true; run = null;
  };
  for (const [k, w] of ops) {
    if (w === "\n") { flush(); html += "\n"; lead = false; continue; }
    if (k === "+") add++; if (k === "-") del++;
    if (!run || run.k !== k) { flush(); run = { k, w: [] }; }
    run.w.push(w);
  }
  flush();
  return { html, add, del };
}
const wordSet = s => new Set((s.toLowerCase().match(/\p{L}[\p{L}\p{N}]+/gu) || []));
const REVISION = /\b(rewrite|revise|rephrase|reword|polish|improve|shorter|longer|tweak|edit|change|update|redo|again|überarbeit\w*|kürzer|länger|umschreib\w*|umformulier\w*|verbessere|ändere|nochmal|anders)\b/i;
function offerDiff(t) {
  t.after.querySelectorAll(".difftoggle").forEach(n => n.remove());
  if (!t.raw || t.raw.length < 100) return;
  const earlier = S.turns.slice(0, t.i).filter(o => o.raw && o.raw.length >= 100), isRev = REVISION.test(t.text || "");
  let best = null;
  if (isRev && earlier.length) best = earlier[earlier.length - 1];          // a revision request: compare with the latest version
  else {                                                                      // otherwise only when the texts are clearly related
    const mine = wordSet(t.raw); let bs = 0;
    for (const o of earlier) {
      const theirs = wordSet(o.raw); let inter = 0; for (const w of mine) if (theirs.has(w)) inter++;
      const j = inter / (mine.size + theirs.size - inter); if (j > bs) { bs = j; best = o; }
    }
    if (bs < 0.3) best = null;
  }
  if (!best || t.raw === best.raw) return;
  const btn = el("button", "difftoggle", `Show changes vs turn ${best.i + 1}`);
  btn.onclick = () => {
    const on = btn.classList.toggle("on");
    if (!on) { t.pres ? renderBlocks(t, t.pres) : setAnswerText(t, t.raw); t.after.append(btn); return; }
    const d = diffWords(best.raw, t.raw); if (!d) { btn.textContent = "Too large to diff"; return; }
    t.answer.innerHTML = ""; const st = el("div", "dstat"); st.innerHTML = `Turn ${best.i + 1} → turn ${t.i + 1}: <span class="a">+${d.add} words</span> <span class="d">−${d.del} words</span>`;
    const v = el("div", "dview"); v.innerHTML = d.html; t.answer.append(st, v);
  };
  t.after.append(btn);
}
