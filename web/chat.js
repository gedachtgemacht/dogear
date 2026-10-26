// dogear UI, part 3: the conversation.
// A turn is: the user's message, one status block (working / waiting for you / checking / done / stopped),
// the step list (folded), the answer, and what the run left behind (changed files, sources).

/* ============================================================ empty session */
const STARTERS = [
  ["Build something", "Build a small Pomodoro timer as a single index.html with start, pause and reset. Keep it clean and readable, then open it in the browser and check the console."],
  ["Explain this project", "Explore this project and explain how it is organised: entry points, main modules, how to run and test it. Do not change anything."],
  ["Find and fix a bug", "Run the tests, read the failures, find the cause and fix it. Show the diff and run the tests again."],
  ["Plan first", "/plan Add a settings page with light and dark theme and persist the choice."],
];
function emptyState() {
  log.innerHTML = "";
  const e = el("div", "empty-state");
  const head = el("div", "es-head");
  head.append(el("b", "", baseName(S.root) || "Describe a task to get started"), el("small", "", MODE_TXT[S.mode] || ""));
  e.append(head);
  const chips = el("div", "es-starters");
  STARTERS.forEach(([label, prompt]) => {
    const c = el("button", "es-chip", label); c.type = "button"; c.title = prompt;
    c.onclick = () => { const i = $("#input"); i.value = prompt; i.dispatchEvent(new Event("input")); i.focus(); };
    chips.append(c);
  });
  e.append(chips);
  const recent = (S.st?.sessions || []).filter(x => x.id !== S.sid && x.turns > 0).slice(0, 5);
  if (recent.length) {
    const box = el("div", "es-recent"); box.append(el("h5", "", "Recent sessions"));
    recent.forEach(x => {
      const r = el("button", "es-row"); r.type = "button";
      r.append(el("span", "t", x.title), el("span", "m", `${plural(x.turns, "turn")} · ${ago(x.updated)} · ${baseName(x.root)}`));
      r.onclick = () => !S.busy && sendWS({ type: "open", id: x.id });
      box.append(r);
    });
    e.append(box);
  }
  log.append(e);
}
const clearEmpty = () => $(".empty-state", log)?.remove();
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const mmss = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/* ============================================================ turns */
function newTurn(text, imgs = [], mode = S.mode, task = null) {
  clearEmpty();
  const t = {
    el: el("div", "turn"), status: el("div", "status"), work: el("div", "steps live"), answer: el("div", "answer"), after: el("div", "after"),
    i: S.turns.length, text, mode, task, raw: "", nsteps: 0, t0: Date.now(), links: new Map(),
    st: { state: "idle" },               // the status block's state; see paintStatus
  };
  const u = el("div", "u"), i = el("div", "in");
  if (task) i.append(el("span", "tbadge", `Task ${task.i + 1}/${task.n}`));
  i.append(el("span", "", text));
  if (imgs.length) {
    const g = el("div", "imgs");
    imgs.forEach(src => { const im = el("img"); im.src = src; im.onclick = () => window.open(src, "_blank"); g.append(im); });
    i.append(g);
  }
  u.append(i);
  t.status.hidden = true;
  t.el.append(u, t.status, t.work, t.answer, t.after);
  log.append(t.el);
  // actions on hover: retry with an edited message; variants are optional (settings)
  const bar = el("div", "tact");
  const btn = (txt, title, fn) => { const b = el("button", "", txt); b.title = title; b.type = "button"; b.onclick = e => { e.stopPropagation(); fn(b); }; bar.append(b); return b; };
  btn("Edit & retry", "Branch here: edit this message and send it again (the original session stays)", () => !S.busy && sendWS({ type: "fork", turn: t.i, where: "before" }));
  if (S.variants) btn("Variants…", "Run two to four variants of this message in parallel, each in its own copy of the project", () => !S.busy && openVariants(t));
  t.el.append(bar); t.bar = bar;
  S.turns.push(t); S.turn = t;
  return t;
}
const turn = () => S.turn || newTurn("");

/* ---- the step list: tool cards and the model's narration, folded while it runs and after it ends */
function workAdd(node) {
  const t = turn(), w = t.work;
  w.append(node);
  if (node.classList.contains("tc")) t.nsteps++;
  foldSteps(t);
}
function foldSteps(t) {
  const kids = [...t.work.children];
  kids.forEach((k, i) => k.classList.toggle("old", i < kids.length - 3));
  paintStatus(t, true);
}
function noticeLine(t, text) { const n = el("div", "note", text); t.work.append(n); foldSteps(t); }

/* ---- status block: the one place that says what is going on */
function setStatus(t, state, extra = {}) {
  t.st = { ...t.st, ...extra, state };
  t.status.hidden = false;
  paintStatus(t);
}
function paintStatus(t, light = false) {
  const st = t.st, box = t.status;
  if (st.state === "idle") return;
  if (light && box._state === st.state && box._n === t.nsteps && !st.current) return;
  box._state = st.state; box._n = t.nsteps;
  box.className = "status " + st.state;
  box.innerHTML = "";
  const head = el("div", "sh");
  const dot = el("i");
  const secs = st.secs ?? Math.round((Date.now() - t.t0) / 1000);
  const label = el("span", "sl"), meta = el("span", "sm"), cur = el("span", "sc");
  const stepsWord = t.nsteps ? plural(t.nsteps, "step") : "";
  if (st.state === "working") { label.textContent = "Working"; meta.textContent = [stepsWord, mmss(secs)].filter(Boolean).join(" · "); cur.textContent = st.current || ""; }
  if (st.state === "checking") { label.textContent = "Checking the result"; meta.textContent = [stepsWord, mmss(secs)].filter(Boolean).join(" · "); cur.textContent = st.current || ""; }
  if (st.state === "waiting") { label.textContent = "Waiting for you"; meta.textContent = st.what || ""; }
  if (st.state === "done") { label.textContent = RECEIPT_WORD[st.receipt?.status] || "Done"; meta.textContent = [stepsWord, st.secs != null ? mmss(st.secs) : ""].filter(Boolean).join(" · "); }
  if (st.state === "stopped") { label.textContent = "Stopped"; meta.textContent = [stepsWord, st.secs != null ? mmss(st.secs) : "", st.reason || ""].filter(Boolean).join(" · "); }
  head.append(dot, label, meta, cur);
  if ((st.state === "working" || st.state === "checking") && t === S.turn && S.busy) {
    const stop = el("button", "stopbtn", "Stop"); stop.type = "button"; stop.title = "Stop the model (Esc)"; stop.onclick = stopRun; head.append(stop);
  }
  box.append(head);
  if (st.state === "waiting" && st.box) box.append(st.box);
  if (st.state === "done" && st.receipt) box.append(receiptEl(st.receipt));
  // what there is to look at, and the steps
  const row = el("div", "srow");
  for (const [key, l] of t.links) { const a = el("button", "slink" + (l.fresh ? " fresh" : ""), l.label); a.type = "button"; a.onclick = () => { l.fresh = false; a.classList.remove("fresh"); l.go(); }; row.append(a); }
  if (t.nsteps) {
    const all = t.work.classList.contains("all"), live = st.state === "working" || st.state === "checking" || st.state === "waiting";
    const tg = el("button", "slink steps", all ? "Hide steps" : (live && t.nsteps > 3 ? `Show all ${t.nsteps} steps` : live ? "" : `Show ${plural(t.nsteps, "step")}`));
    tg.type = "button";
    if (tg.textContent) { tg.onclick = () => { t.work.classList.toggle("all"); paintStatus(t); }; row.append(tg); }
  }
  if (row.children.length) box.append(row);
  t.work.classList.toggle("live", st.state === "working" || st.state === "checking" || st.state === "waiting");
}
const RECEIPT_WORD = { verified: "Verified", unverified: "Unverified", stopped: "Stopped", done: "Done" };
function receiptEl(r) {
  const box = el("div", "receipt");
  const row = (k, v, tone) => { const d = el("div", "rr" + (tone ? " " + tone : "")); d.append(el("span", "rk", k), el("span", "rv", v)); box.append(d); };
  if (r.tests) {
    const ok = r.tests.passed && !r.tests.failed && !r.tests.errors && !r.tests.exit;
    row("Tests", `${r.tests.passed} passed` + (r.tests.failed ? `, ${r.tests.failed} failed` : "") + (r.tests.errors ? `, ${r.tests.errors} errors` : ""), ok ? "ok" : "bad");
  }
  if (r.page) {
    const cnt = x => x ? x.high + x.medium + x.source + x.copy : 0;
    const before = cnt(r.page.before), after = r.page.after ? cnt(r.page.after) : null;
    const txt = after == null ? (before ? `${plural(before, "finding")} measured` : "audit clean") : `${before} → ${after} after the fix pass`;
    row("Page", `${r.page.name}: ${txt}`, (after ?? before) ? "bad" : "ok");
  }
  if (r.console) row("Console", r.console.errors ? plural(r.console.errors, "error") : "no errors", r.console.errors ? "bad" : "ok");
  if (r.flows) row("Flows", `${r.flows.passed}/${r.flows.total} recorded flows still work` + (r.flows.failed?.length ? `: ${r.flows.failed.map(f => f.name + (f.detail ? " (" + f.detail + ")" : "")).join("; ")}` : ""), r.flows.failed?.length ? "bad" : "ok");
  if (r.status === "unverified" && !r.tests && !r.page) row("Checked", "nothing: no tests were run and no page was measured", "warn");
  if (r.status === "stopped") row("Reason", r.reason || "", "warn");
  return box;
}
function addLink(t, key, label, go) { t.links.set(key, { label, go, fresh: true }); paintStatus(t); }

/* ---- the run ended: summary line, receipt, changed files, sources */
function applySummary(t, sm) {
  const stopped = sm.receipt?.status === "stopped";
  t.nsteps = sm.steps || t.nsteps;
  setStatus(t, stopped ? "stopped" : "done", { secs: sm.secs, receipt: sm.receipt, reason: stopped ? sm.receipt.reason : "" });
  t.work.classList.remove("live", "all");
  t.after.querySelectorAll(".changes, .sources").forEach(n => n.remove());
  if (sm.changes?.length) {
    const box = el("div", "changes"), head = el("div", "chead");
    head.append(el("span", "", `${plural(sm.changes.length, "file")} changed`));
    if (sm.checkpoint?.before) {
      const u = el("button", "undo", "Undo this run"); let armed = false;
      u.onclick = () => {
        if (!armed) { armed = true; u.textContent = "Click again to restore the files"; setTimeout(() => { armed = false; u.textContent = "Undo this run"; }, 4000); return; }
        sendWS({ type: "undo", root: sm.checkpoint.root, to: sm.checkpoint.before }); u.remove();
      };
      head.append(u);
    }
    box.append(head);
    for (const c of sm.changes) {
      const r = el("div", "chg"); r.append(el("b", c.created ? "A" : "M", c.created ? "A" : "M"), el("span", "", rel(c.path)), el("em", "", `+${c.added} −${c.removed}`));
      r.onclick = () => openWS(rel(c.path)); box.append(r);
    }
    t.after.prepend(box);
  }
  if (sm.sources?.length) {
    const box = el("div", "sources"); box.append(el("span", "lbl", sm.sources.some(x => x.kind === "visited") ? "Sources" : "Found"));
    for (const x of sm.sources.slice(0, 4)) {
      let host = x.url; try { host = new URL(x.url).hostname.replace(/^www\./, ""); } catch {}
      const c = el("a", `src ${x.kind}`); c.href = x.url; c.title = x.url; c.append(el("i", "", host[0]?.toUpperCase() || "?"), el("span", "", x.title ? `${x.title.slice(0, 38)} · ${host}` : host));
      c.onclick = e => { if (e.shiftKey || e.metaKey || e.ctrlKey) return; e.preventDefault(); openWS("@preview"); sendWS({ type: "b_open" }); sendWS({ type: "b_nav", url: x.url }); };
      c.target = "_blank"; c.rel = "noopener"; box.append(c);
    }
    t.after.append(box);
  }
}
function setAnswerText(t, text) { t.raw = text; t.answer.innerHTML = ""; const m = el("div", "md"); m.innerHTML = md(text); t.answer.append(m); }

/* ============================================================ tool cards */
function diffEl(diff, max = 12, context = 2) {
  const box = el("div", "diff"); let n = 0; const hidden = [];
  diff.hunks.forEach((h, hi) => {
    if (hi) box.append(el("div", "gap", "⋯"));
    // keep `context` unchanged lines around every change; the rest is noise
    const keep = new Set();
    h.forEach(([sg], i) => { if (sg !== " ") for (let k = i - context; k <= i + context; k++) keep.add(k); });
    let skipped = 0;
    h.forEach(([sg, ln, tx], i) => {
      if (!keep.has(i) && h.some(([s]) => s !== " ")) { skipped++; return; }
      if (skipped) { box.append(el("div", "gap", "⋯")); skipped = 0; }
      const row = el("div", `dl ${sg === "+" ? "add" : sg === "-" ? "del" : ""}`);
      row.append(el("span", "ln", ln ?? ""), el("span", "sg", sg === " " ? "" : sg), el("span", "", tx));
      if (n++ >= max) { row.hidden = true; hidden.push(row); }
      box.append(row);
    });
  });
  if (hidden.length) { const m = el("div", "more", `Show ${hidden.length} more lines`); m.onclick = () => { hidden.forEach(r => r.hidden = false); m.remove(); }; box.append(m); }
  return box;
}

function toolCard(id, name, args, label) {
  clearEmpty();
  const mcp = name.startsWith("mcp__"), kind = name === "TodoWrite" ? "todo" : mcp ? "mcp" : (KIND[name] || "read");
  const shown = mcp ? name.split("__").slice(1).join(" · ") : name.startsWith("browser_") ? "Browser " + name.slice(8) : name;
  const card = el("div", `tc k-${kind} run`), th = el("div", "th"), tr = el("div", "tr"), tb = el("div", "tb");
  th.append(el("i"), el("b", "", shown), el("span", "arg", label ? label.split(S.root + "/").join("") : ""));
  tr.append(el("span", "sum", "…"), el("em", "", "")); tr.hidden = true;
  card.append(th, tr, tb); workAdd(card);
  th.onclick = tr.onclick = () => { if (tb.children.length) card.classList.toggle("open"); };
  return (S.cards[id] = { card, tr, tb, name, args });
}

function summarize(name, ok, text, meta) {
  const first = (text.split("\n").find(l => l.trim()) || "").slice(0, 110);
  if (first.startsWith("[old result truncated")) return "(result dropped from the context)";
  if (!ok) return first.replace(/^Error: /, "");
  switch (name) {
    case "Read": return `Read ${meta.lines ?? "?"} lines`;
    case "LS": return `Listed ${meta.entries ?? "?"} entries`;
    case "Glob": return `Found ${meta.files ?? 0} files`;
    case "Grep": return `${meta.matches ?? 0} matches`;
    case "Write": return meta.created ? `Created, ${meta.diff.added} lines` : `Overwrote (+${meta.diff.added} −${meta.diff.removed})`;
    case "Edit": case "MultiEdit": return `+${meta.diff?.added ?? 0} −${meta.diff?.removed ?? 0}`;
    case "Bash": return (first || "(no output)") + (meta.exit ? `  · exit ${meta.exit}` : "");
    case "TodoWrite": return `${meta.done}/${meta.total} tasks done`;
    case "WebFetch": return `Fetched · HTTP ${meta.status}`;
    case "browser_screenshot": return "Screenshot taken";
    case "complete_current_task": return "Task closed";
    case "request_replan": return "Asked for a new plan";
    default: return first || "done";
  }
}

function finishCard(c, ok, text, meta = {}) {
  c.card.classList.remove("run", "wait"); if (!ok) c.card.classList.add("bad");
  c.tr.hidden = false; c.tr.firstChild.textContent = summarize(c.name, ok, text, meta);
  const lines = text.split("\n").length;
  if (meta.diff && ok) { c.tb.append(diffEl(meta.diff)); c.tr.lastChild.textContent = "diff"; }
  else if (c.name !== "TodoWrite" && (lines > 1 || text.length > 110)) { c.tb.append(el("pre", "", text.slice(0, 5000))); c.tr.lastChild.textContent = `${lines} lines`; }
  const t = S.turn; if (t) paintStatus(t, true);
}

/* ============================================================ questions and permissions live in the status block */
function waitingBox(cardId, box, what) {
  const c = S.cards[cardId], t = c?.turn || S.turn || turn();
  if (c) c.card.classList.add("wait");
  setStatus(t, "waiting", { box, what, prev: t.st.state === "waiting" ? t.st.prev : t.st.state });
  document.title = "● dogear — waiting for you";
  t.status.scrollIntoView({ block: "nearest" });
  return t;
}
function waitingDone(t) {
  if (!t) return;
  document.title = S.st?.name || "dogear";
  setStatus(t, t.st.prev === "checking" ? "checking" : "working", { box: null, what: "" });
}

function askBox(m) {
  const qs = m.questions || [{ question: m.question, options: (m.options || []).map(label => ({ label })) }];
  const box = el("div", "ask form"), state = qs.map(() => ({ selected: new Set(), other: "" }));
  const send = el("button", "sendans", "Send answers"); send.type = "button"; send.disabled = true;
  const refresh = () => { send.disabled = !state.every(st => st.selected.size || st.other.trim()); };
  qs.forEach((q, qi) => {
    const sec = el("div", "q"), head = el("div", "qhead");
    if (q.header) head.append(el("span", "qtag", q.header));
    head.append(el("span", "qtext", q.question)); if (q.multi) head.append(el("span", "qmulti", "choose any"));
    const list = el("div", "opts"), prev = el("pre", "preview"); prev.hidden = true;
    (q.options || []).forEach(o => {
      const b = el("button", "opt"); b.type = "button"; b.dataset.l = o.label;
      const txt = el("span", "otxt"); txt.append(el("b", "", o.label)); if (o.description) txt.append(el("small", "", o.description));
      b.append(el("span", q.multi ? "mark box" : "mark dot"), txt);
      b.onclick = () => {
        const st = state[qi];
        if (q.multi) st.selected.has(o.label) ? st.selected.delete(o.label) : st.selected.add(o.label); else st.selected = new Set([o.label]);
        list.querySelectorAll(".opt").forEach(x => x.classList.toggle("on", st.selected.has(x.dataset.l)));
        if (o.preview) { prev.textContent = o.preview; prev.hidden = false; } else prev.hidden = true;
        refresh();
      };
      list.append(b);
    });
    const other = el("input"); other.placeholder = "Or write your own answer…"; other.oninput = () => { state[qi].other = other.value; refresh(); };
    other.onkeydown = e => { if (e.key === "Enter" && !send.disabled) send.click(); };
    sec.append(head, list, prev, other); box.append(sec);
  });
  const t = waitingBox(m.id, box, "the model has a question");
  send.onclick = () => { sendWS({ type: "answer", id: m.id, value: state.map(st => ({ selected: [...st.selected], other: st.other })) }); waitingDone(t); };
  box.append(send);
  box.querySelector(".opt")?.focus();
}

function approvalBox(m) {
  const box = el("div", "ask"), a = m.args, mcp = m.name.startsWith("mcp__");
  const host = (() => { try { return new URL(/^[a-z]+:/i.test(a.url || "") ? a.url : "https://" + (a.url || "")).hostname; } catch { return ""; } })();
  const title = m.name === "browser_navigate" ? `Open ${host || a.url} in the browser?` : m.name === "browser_eval" ? "Run JavaScript in the page?"
    : m.name.startsWith("browser_") ? `Allow ${m.name.replace("browser_", "")} in the browser?` : m.name === "Bash" ? "Run this command?"
    : m.name === "Edit" ? `Edit ${rel(a.file_path || "")}?` : m.name === "Write" ? `Write ${rel(a.file_path || "")}?`
    : mcp ? `Call MCP tool ${m.name.split("__").slice(1).join(" · ")}?` : `Allow ${m.name}?`;
  box.append(el("p", "", title));
  if (m.name === "Bash") box.append(el("pre", "", "$ " + a.command));
  else if (m.name === "browser_navigate") box.append(el("pre", "", a.url));
  else if (m.name === "browser_eval") box.append(el("pre", "", a.expression));
  else if (m.name === "Edit") box.append(diffEl({ hunks: [[...String(a.old_string).split("\n").map(t => ["-", "", t]), ...String(a.new_string).split("\n").map(t => ["+", "", t])]] }, 14, 99));
  else if (m.name === "Write") box.append(diffEl({ hunks: [String(a.content).split("\n").map((t, i) => ["+", i + 1, t])] }, 12, 99));
  else box.append(el("pre", "", JSON.stringify(a, null, 2).slice(0, 800)));
  const t = waitingBox(m.id, box, title);
  const o = el("div", "opts");
  const answer = (ok, always) => { sendWS({ type: "approve", id: m.id, ok, always, key: m.key || m.name }); S.ask = null; waitingDone(t); };
  const opt = (k, txt, ok, always) => { const b = el("button"); b.type = "button"; b.append(el("kbd", "", k), txt); b.onclick = () => answer(ok, always); return b; };
  o.append(opt("1", "Yes", true, false),
           opt("2", m.name === "browser_navigate" ? `Yes, and don't ask again for ${host}` : `Yes, and don't ask again for ${mcp ? "this MCP tool" : m.name} in this session`, true, true),
           opt("3", "No", false, false));
  box.append(o);
  S.ask = { answer };
}

/* ============================================================ plan approval card (phase 2) and its task log (phase 3) */
function planCard(t, plan) {
  t.after.querySelectorAll(".plancard").forEach(n => n.remove());
  const box = el("div", "plancard"), head = el("div", "pc-h"), state = el("span", "pc-s");
  head.append(el("b", "", "Plan"), state);
  const why = el("details", "pc-why"); why.open = false; why.append(el("summary", "", "Why this plan"), el("div", "pc-r", plan.reasoning || ""));
  const rows = el("div", "pc-rows"), tasks = (plan.tasks || []).map(x => ({ content: x.content, detail: x.detail || "" }));
  const act = el("div", "pc-a");
  const draw = () => {
    rows.innerHTML = "";
    const editable = plan.status === "proposed";
    tasks.forEach((x, i) => {
      const r = el("div", "pc-row"), n = el("span", "pc-n", String(i + 1));
      let tx;
      if (editable) { tx = el("input"); tx.value = x.content; tx.oninput = () => { x.content = tx.value; }; tx.spellcheck = false; }
      else tx = el("span", "pc-t", x.content);
      const e = (plan.log || [])[i];
      if (e && !editable) { r.classList.add("pc-" + e.status); n.textContent = { done: "✓", running: "◌", replan: "↺", stopped: "■", unfinished: "?" }[e.status] || String(i + 1); }
      r.append(n, tx);
      const closed = e && !editable && e.status !== "running" && e.summary;
      if (x.detail && !closed) r.append(el("div", "pc-d", x.detail));      // the plan's note until the task has its own summary
      if (closed) r.append(el("div", "pc-sum", `${e.summary}${e.secs ? ` · ${plural(e.steps || 0, "step")} · ${mmss(e.secs)}` : ""}${e.tokens ? ` · ${(e.tokens / 1000).toFixed(1)}k context` : ""}`));
      if (editable) {
        const up = el("button", "", "↑"), dn = el("button", "", "↓"), rm = el("button", "", "✕");
        up.title = "Move up"; dn.title = "Move down"; rm.title = "Remove";
        up.onclick = () => { if (i > 0) { [tasks[i - 1], tasks[i]] = [tasks[i], tasks[i - 1]]; draw(); } };
        dn.onclick = () => { if (i < tasks.length - 1) { [tasks[i + 1], tasks[i]] = [tasks[i], tasks[i + 1]]; draw(); } };
        rm.onclick = () => { tasks.splice(i, 1); draw(); };
        const ctl = el("span", "pc-c"); ctl.append(up, dn, rm); r.append(ctl);
      }
      rows.append(r);
    });
    if (editable) {
      const add = el("input", "pc-add"); add.placeholder = "Add a task…";
      add.onkeydown = e => { if (e.key === "Enter" && add.value.trim()) { tasks.push({ content: add.value.trim(), detail: "" }); draw(); rows.querySelector(".pc-add").focus(); } };
      rows.append(add);
    }
  };
  // the direction: three solved briefs that look like this one, as pictures; the chosen one goes into every task briefing
  let direction = plan.reference ?? null;
  const dir = el("div", "pc-dir");
  const drawDir = () => {
    dir.innerHTML = "";
    const refs = plan.references || [];
    if (!refs.length) { dir.hidden = true; return; }
    dir.hidden = false;
    const editable = plan.status === "proposed";
    dir.append(el("div", "pc-dh", editable ? "Direction: pick a look, or let the model choose" : "Direction"));
    const row = el("div", "pc-thumbs");
    const opt = (key, node, title) => {
      const b = el("button", "pc-th" + (direction === key ? " on" : "")); b.type = "button"; b.title = title || "";
      b.append(node, el("span", "pc-tl", title || ""));
      if (editable) b.onclick = () => { direction = key; drawDir(); }; else b.disabled = true;
      if (!editable && direction !== key) b.hidden = true;
      row.append(b);
    };
    refs.forEach(r => { const im = el("img"); im.loading = "lazy"; im.src = `/api/thumb/${r.id}`; im.alt = r.problem; opt(r.id, im, r.problem.slice(0, 60)); });
    opt("surprise", el("div", "pc-tx", "?"), "Surprise me: a distinctive look of its own");
    opt("none", el("div", "pc-tx", "–"), "No direction");
    dir.append(row);
  };
  const label = { proposed: "waiting for your approval", approved: "running task by task", rejected: "rejected", replan: "needs a new plan", done: "done", stopped: "stopped" };
  const paint = () => {
    state.textContent = label[plan.status] || plan.status; state.className = "pc-s " + plan.status;
    act.innerHTML = "";
    if (plan.status === "proposed") {
      const go = el("button", "primary", "Approve and run"); go.title = `Runs in the current mode (${MODE_TXT[S.mode]})`;
      go.onclick = () => { if (!tasks.length) return; plan.reference = direction; sendWS({ type: "plan_approve", tasks, mode: S.mode, reference: direction }); setBusy(true); };
      const rej = el("button", "", "Revise…");
      rej.onclick = () => {
        act.innerHTML = ""; const ta = el("textarea"); ta.placeholder = "What should change? The model plans again with your feedback."; ta.rows = 3;
        const send = el("button", "primary", "Send feedback"), cancel = el("button", "", "Cancel");
        send.onclick = () => { sendWS({ type: "plan_reject", feedback: ta.value }); setBusy(true); };
        cancel.onclick = paint; act.append(ta, send, cancel); ta.focus();
      };
      act.append(go, rej);
    } else if (plan.status === "rejected" && plan.feedback) act.append(el("div", "pc-fb", "Feedback: " + plan.feedback));
    else if (plan.status === "replan" && plan.feedback) act.append(el("div", "pc-fb", "Reason: " + plan.feedback));
  };
  box.append(head, why, dir, rows, act); t.after.append(box);
  plan.status = plan.status || "proposed";
  draw(); drawDir(); paint();
  S.planCard = {
    update: m => { plan.status = m.status; if (m.tasks) { tasks.length = 0; m.tasks.forEach(x => tasks.push({ content: x.content, detail: x.detail || "" })); } if (m.feedback) plan.feedback = m.feedback; draw(); drawDir(); paint(); },
    task: m => { plan.log = plan.log || []; plan.log[m.i] = m; draw(); },
  };
}

/* ============================================================ memory (drawer pane) */
async function memSave(item) {
  const r = await fetch("/api/memory", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ session: S.sid, ...item }) });
  if (!r.ok) { note("Not saved: " + ((await r.json().catch(() => ({}))).detail || r.status)); return false; }
  loadMemory(); return true;
}
function memForm() {
  const f = $("#memform"); if (!f.hidden) { f.hidden = true; return; }
  f.innerHTML = ""; f.hidden = false;
  const kind = el("select"), name = el("input"), text = el("textarea"), scope = el("select"), trig = el("input"), go = el("button", "", "Save");
  [["memory", "Note"], ["snippet", "Snippet"], ["skill", "Skill"]].forEach(([v, l]) => kind.append(new Option(l, v)));
  [["project", "This project"], ["global", "All projects"]].forEach(([v, l]) => scope.append(new Option(l, v)));
  name.placeholder = "Name"; text.placeholder = "Content"; text.rows = 4; trig.placeholder = "Triggers (comma-separated words)"; trig.hidden = true;
  kind.onchange = () => { trig.hidden = kind.value !== "skill"; };
  go.onclick = async () => { if (await memSave({ kind: kind.value, name: name.value, content: text.value, scope: scope.value, triggers: trig.value, description: kind.value === "skill" ? name.value : "" })) f.hidden = true; };
  const row = el("div", "mem-row"); row.append(kind, scope);
  f.append(row, name, trig, text, go); name.focus();
}
