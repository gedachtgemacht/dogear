// dogear UI, part 3: the conversation. Turns, tool cards, summaries, answer blocks, approvals, rating, plan card, memory UI.
/* ============================================================ chat */
function keepScroll() { const near = log.scrollHeight - log.scrollTop - log.clientHeight < 160; return () => { if (near) log.scrollTop = log.scrollHeight; }; }
/* The empty session: what this is, where it works, a few starting points and the sessions you had. */
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
  head.append(el("b", "", "Describe a task to get started"), el("small", "", S.root || ""));
  e.append(head);
  const tips = el("div", "es-tips");
  [["Review", "confirms every edit and command"], ["Edits", "writes files, confirms commands"], ["Auto", "never asks"], ["Plan", "proposes a board first"]]
    .forEach(([k, v]) => { const r = el("span"); r.append(el("b", "", k), " " + v); tips.append(r); });
  e.append(tips);
  const chips = el("div", "es-starters");
  STARTERS.forEach(([label, prompt]) => { const c = el("button", "es-chip", label); c.type = "button"; c.title = prompt;
    c.onclick = () => { const i = $("#input"); i.value = prompt; i.dispatchEvent(new Event("input")); i.focus(); }; chips.append(c); });
  e.append(chips);
  const recent = (S.st?.sessions || []).filter(x => x.id !== S.sid && x.turns > 0).slice(0, 5);
  if (recent.length) {
    const box = el("div", "es-recent"); box.append(el("h5", "", "Recent sessions"));
    recent.forEach(x => { const r = el("button", "es-row"); r.type = "button";
      r.append(el("span", "t", x.title), el("span", "m", `${plural(x.turns, "turn")} · ${ago(x.updated)} · ${baseName(x.root)}`));
      r.onclick = () => !S.busy && sendWS({ type: "open", id: x.id }); box.append(r); });
    e.append(box);
  }
  e.append(el("div", "es-keys", "Enter sends · Shift+Enter newline · Shift+Tab cycles the mode · Esc stops · / lists commands"));
  log.append(e);
}
const clearEmpty = () => $(".empty-state", log)?.remove();

/* ---- turns: one user message, its work (process) and the answer (focus) */
function newTurn(text, imgs = [], mode = S.mode) {
  clearEmpty();
  const t = { el: el("div", "turn"), work: el("div", "work"), answer: el("div", "answer"), after: el("div", "after"), sum: null, raw: "", pres: null, code: [],
              i: S.turns.length, text, mode };
  const u = el("div", "u"), i = el("div", "in"); i.append(el("span", "", text));
  if (imgs.length) { const g = el("div", "imgs"); imgs.forEach(src => { const im = el("img"); im.src = src; im.onclick = () => window.open(src, "_blank"); g.append(im); }); i.append(g); }
  u.append(i);
  t.work.hidden = true; t.el.append(u, t.work, t.answer, t.after); log.append(t.el);
  const bar = el("div", "tact"), btn = (txt, title, fn) => { const b = el("button", "", txt); b.title = title; b.type = "button"; b.onclick = e => { e.stopPropagation(); fn(b); }; bar.append(b); return b; };
  t.pinBtn = btn("★", "Pin this turn", b => { const on = !S.meta.pins.includes(t.i); sendWS({ type: "pin", turn: t.i, on }); });
  btn("⑂", "Branch from here (keep this turn and everything before)", () => !S.busy && sendWS({ type: "fork", turn: t.i, where: "after" }));
  btn("✎", "Edit this message and branch before it", () => !S.busy && sendWS({ type: "fork", turn: t.i, where: "before" }));
  btn("⑂⑂", "Run variants of this turn in parallel (own copy of the project each)", () => !S.busy && openVariants(t));
  t.el.append(bar); t.bar = bar;
  S.turns.push(t); S.turn = t; syncPin(t); renderOutline(); return t;
}
const turn = () => S.turn || newTurn("");
const workAdd = node => { const w = turn().work; w.hidden = false; w.append(node); };
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

function applySummary(t, sm) {
  const parts = [];
  if (sm.steps) parts.push(plural(sm.steps, "step"));
  if (sm.changes?.length) parts.push(plural(sm.changes.length, "file") + " changed");
  const failed = (sm.commands || []).filter(c => c.exit).length;
  if (sm.commands?.length) parts.push(plural(sm.commands.length, "command") + (failed ? ` (${failed} failed)` : ""));
  const pages = (sm.sources || []).filter(x => x.kind === "visited").length;
  if (pages) parts.push(plural(pages, "page"));
  if (sm.secs) parts.push(sm.secs + "s");
  t.sum?.remove(); t.sum = null;
  if (sm.steps) {
    const h = el("div", "wsum", parts.join(" · "));
    h.onclick = () => { t.work.hidden = !t.work.hidden; h.classList.toggle("open", !t.work.hidden); };
    t.el.insertBefore(h, t.answer); t.sum = h; t.work.hidden = true;
  }
  t.after.querySelectorAll(".undo").forEach(n => n.remove());
  if (sm.checkpoint?.before) {
    const u = el("button", "undo", "Undo this run"); let armed = false;
    u.onclick = () => { if (!armed) { armed = true; u.textContent = "Click again to restore the files"; setTimeout(() => { armed = false; u.textContent = "Undo this run"; }, 4000); return; }
      sendWS({ type: "undo", root: sm.checkpoint.root, to: sm.checkpoint.before }); u.remove(); };
    t.after.append(u);
  }
  t.after.querySelectorAll(".rate").forEach(n => n.remove());
  if (sm.steps && !(S.mode === "plan" && !sm.changes?.length)) rateBar(t, sm.rating);
  // deterministic context cards: what changed, where it came from
  t.after.querySelectorAll(".changes, .sources").forEach(n => n.remove());
  if (sm.changes?.length) {
    const box = el("div", "changes");
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

const KIND_LABEL = { fact: "Answer", "how-to": "How-to", "code-change": "Change", debugging: "Diagnosis", comparison: "Comparison", explanation: "Explanation", status: "Status" };
function renderBlocks(t, p) {
  const box = t.answer; box.innerHTML = ""; t.pres = p;
  if (KIND_LABEL[p.kind]) box.append(el("div", "kind", KIND_LABEL[p.kind]));
  if (p.headline) { const h = el("h3", "head"); h.innerHTML = md(p.headline).replace(/\n/g, " "); box.append(h); }
  for (const b of p.blocks) {
    const w = el("div", `blk ${b.type}${b.tone ? " " + b.tone : ""}`);
    if (b.title && b.type !== "callout") w.append(el("div", "btitle", b.title));
    if (b.type === "prose" || b.type === "callout") { const m = el("div", "md"); m.innerHTML = md(b.text); w.append(m); }
    else if (b.type === "defs") {
      const d = el("dl", "defs");
      for (const x of b.pairs) { const dd = el("dd"); dd.innerHTML = md(x.value); d.append(el("dt", "", x.label), dd); }
      w.append(d);
    }
    else if (b.type === "facts") { const d = el("dl", "facts"); for (const x of b.pairs) { const dd = el("dd"); dd.innerHTML = md(x.value); d.append(el("dt", "", x.label), dd); } w.append(d); }
    else if (b.type === "steps" || b.type === "list") {
      const l = el(b.type === "steps" ? "ol" : "ul", b.type); b.items.forEach(i => { const li = el("li"); li.innerHTML = md(i); l.append(li); }); w.append(l);
    } else if (b.type === "table") {
      const tb = el("table", "tbl"), h = el("tr"); const cell = (tag, c) => { const e = el(tag); e.innerHTML = md(c); return e; };
      b.columns.forEach(c => h.append(cell("th", c))); tb.append(h);
      b.rows.forEach(r => { const tr = el("tr"); r.forEach(c => tr.append(cell("td", c))); tb.append(tr); }); w.append(tb);
    } else if (b.type === "code") {
      const c = p.code[b.ref - 1]; if (!c) continue;
      const pre = el("pre"), code = el("code"); code.innerHTML = highlight(c.code, EXT[c.lang.toLowerCase()] || "md").join("\n"); pre.append(code);
      const cp = el("button", "copy", "Copy"); cp.onclick = () => navigator.clipboard?.writeText(c.code).then(() => { cp.textContent = "Copied"; setTimeout(() => cp.textContent = "Copy", 1200); });
      const sv = el("button", "copy", "Save snippet"); sv.onclick = () => snippetForm(sv, c);
      w.append(pre, cp, sv);
    }
    box.append(w);
  }
  t.after.querySelectorAll(".follow-ups, .rawtoggle").forEach(n => n.remove());
  if (p.followups?.length) {
    const f = el("div", "follow-ups"); f.append(el("span", "lbl", "Next"));
    for (const x of p.followups) { const c = el("button", "fu", x); c.onclick = () => { $("#input").value = x; $("#input").focus(); }; f.append(c); }
    t.after.append(f);
  }
  if (t.mode === "plan") {
    const items = p.blocks.filter(b => b.type === "steps" || b.type === "list").flatMap(b => b.items).slice(0, 20);
    if (items.length >= 2) {
      const u = el("button", "useplan", "Use as plan and switch to Edits");
      u.onclick = () => { sendWS({ type: "set_todos", items: items.map(x => ({ content: x.replace(/\*\*/g, "").slice(0, 200), status: "pending" })) });
        setMode("edit"); $("#input").value = "Carry out the plan, step by step, and keep the task list current."; $("#input").focus(); u.remove(); };
      t.after.append(u);
    }
  }
  const rt = el("button", "rawtoggle", "Show original");
  rt.onclick = () => { const raw = rt.dataset.on === "1";
    if (raw) { renderBlocks(t, t.pres); return; }
    box.innerHTML = ""; const m = el("div", "md"); m.innerHTML = md(t.raw); box.append(m); rt.textContent = "Show formatted"; rt.dataset.on = "1"; };
  t.after.append(rt);
}
function setAnswerText(t, text) { t.raw = text; t.answer.innerHTML = ""; const m = el("div", "md"); m.innerHTML = md(text); t.answer.append(m); }

function diffEl(diff, max = 16) {
  const box = el("div", "diff"); let n = 0; const hidden = [];
  diff.hunks.forEach((h, hi) => {
    if (hi) box.append(el("div", "gap", "⋯"));
    h.forEach(([sg, ln, tx]) => {
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
  const mcp = name.startsWith("mcp__"), kind = mcp ? "mcp" : (KIND[name] || "read");
  const shown = mcp ? name.split("__").slice(1).join(" · ") : name.startsWith("browser_") ? "browser · " + name.slice(8) : name;
  const card = el("div", `tc k-${kind} run`), th = el("div", "th"), tr = el("div", "tr"), tb = el("div", "tb");
  th.append(el("i"), el("b", "", shown), el("span", "arg", label ? `(${label.split(S.root + "/").join("")})` : ""));
  tr.append(el("span", "sum", "…"), el("em", "", "")); tr.hidden = true;
  card.append(th, tr, tb); workAdd(card);
  tr.onclick = () => card.classList.toggle("open");
  return (S.cards[id] = { card, tr, tb, name, args });
}

function summarize(name, ok, text, meta) {
  const first = (text.split("\n").find(l => l.trim()) || "").slice(0, 110);
  if (!ok) return first.replace(/^Error: /, "");
  switch (name) {
    case "Read": return `Read ${meta.lines ?? "?"} lines`;
    case "LS": return `Listed ${meta.entries ?? "?"} entries`;
    case "Glob": return `Found ${meta.files ?? 0} files`;
    case "Grep": return `${meta.matches ?? 0} matches`;
    case "Write": return meta.created ? `Created file, ${meta.diff.added} lines` : `Overwrote file (+${meta.diff.added} −${meta.diff.removed})`;
    case "Edit": case "MultiEdit": return `Updated: +${meta.diff?.added ?? 0} −${meta.diff?.removed ?? 0}`;
    case "Bash": return (first || "(no output)") + (meta.exit ? `  · exit ${meta.exit}` : "");
    case "TodoWrite": return `${meta.done}/${meta.total} tasks done`;
    case "WebFetch": return `Fetched · HTTP ${meta.status}`;
    default: return first || "done";
  }
}

function finishCard(c, ok, text, meta = {}) {
  c.card.classList.remove("run"); if (!ok) c.card.classList.add("bad");
  c.tr.hidden = false; c.tr.firstChild.textContent = summarize(c.name, ok, text, meta);
  const lines = text.split("\n").length;
  if (lines > 2 && !["Write", "Edit", "TodoWrite"].includes(c.name)) c.tr.lastChild.textContent = `+${lines - 1} lines`;
  if (meta.diff && ok) c.tb.append(diffEl(meta.diff)), c.tb.classList.add("show");
  else if (c.name !== "TodoWrite") { c.tb.append(el("pre", "", text.slice(0, 5000))); if (!ok) c.card.classList.add("open"); }
}

const GLYPH = { queued: "○", running: "◌", done: "●", failed: "✕" };
function ultraEvent(m) {
  const c = S.cards[m.call]; if (!c) return;
  c.card.classList.add("open"); c.tb.classList.add("show");
  let tree = c.ultra;
  if (!tree) { tree = c.ultra = { el: el("div", "utree"), phases: {}, rows: {} }; c.tb.prepend(tree.el); }
  const phase = m.phase || "run";
  if (!tree.phases[phase]) { const h = el("div", "uphase", phase); tree.el.append(h); tree.phases[phase] = h; }
  if (m.event === "phase") { tree.phases[phase].dataset.state = m.state; if (m.detail) tree.phases[phase].title = m.detail; return; }
  if (m.event === "log") { tree.el.append(el("div", "ulog", m.detail || "")); return; }
  if (m.event === "agent") {
    let row = tree.rows[m.id];
    if (!row) { row = tree.rows[m.id] = el("div", "uagent"); tree.phases[phase].after(row); }
    row.dataset.state = m.state; row.textContent = `${GLYPH[m.state] || "·"} ${m.label || m.id}` + (m.state === "failed" && m.detail ? ` — ${m.detail}` : "");
  }
}

function askBox(m) {
  const c = S.cards[m.id]; if (!c) return;
  const qs = m.questions || [{ question: m.question, options: (m.options || []).map(label => ({ label })) }];
  const box = el("div", "ask form"), state = qs.map(() => ({ selected: new Set(), other: "" }));
  const send = el("button", "sendans", "Send answers"); send.type = "button"; send.disabled = true;
  const refresh = () => { send.disabled = !state.every(st => st.selected.size || st.other.trim()); };
  qs.forEach((q, qi) => {
    const sec = el("div", "q"), head = el("div", "qhead");
    if (q.header) head.append(el("span", "qtag", q.header));
    head.append(el("span", "qtext", q.question)); if (q.multi) head.append(el("span", "qmulti", "choose any"));
    const list = el("div", "opts"), prev = el("pre", "preview"); prev.hidden = true;
    (q.options || []).forEach((o, oi) => {
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
  send.onclick = () => { sendWS({ type: "answer", id: m.id, value: state.map(st => ({ selected: [...st.selected], other: st.other })) }); box.remove(); };
  box.append(send); c.card.classList.add("open"); c.card.append(box);
  box.querySelector(".opt")?.focus();
}

function approvalBox(m) {
  const c = S.cards[m.id]; if (!c) return;
  const box = el("div", "ask"), a = m.args, mcp = m.name.startsWith("mcp__");
  const host = (() => { try { return new URL(/^[a-z]+:/i.test(a.url || "") ? a.url : "https://" + (a.url || "")).hostname; } catch { return ""; } })();
  const title = m.name === "browser_navigate" ? `Open ${host || a.url} in the browser?` : m.name === "browser_eval" ? "Run JavaScript in the page?"
    : m.name.startsWith("browser_") ? `Allow ${m.name.replace("browser_", "")} in the browser?` : m.name === "Bash" ? "Run this command?" : m.name === "Edit" ? `Edit ${rel(a.file_path || "")}?` : m.name === "Write" ? `Write ${rel(a.file_path || "")}?`
    : mcp ? `Call MCP tool ${m.name.split("__").slice(1).join(" · ")}?` : `Allow ${m.name}?`;
  box.append(el("p", "", title));
  if (m.name === "Bash") box.append(el("pre", "", "$ " + a.command));
  else if (m.name === "browser_navigate") box.append(el("pre", "", a.url));
  else if (m.name === "browser_eval") box.append(el("pre", "", a.expression));
  else if (m.name === "Edit") box.append(diffEl({ hunks: [[...String(a.old_string).split("\n").map(t => ["-", "", t]), ...String(a.new_string).split("\n").map(t => ["+", "", t])]] }, 14));
  else if (m.name === "Write") box.append(diffEl({ hunks: [String(a.content).split("\n").map((t, i) => ["+", i + 1, t])] }, 12));
  else box.append(el("pre", "", JSON.stringify(a, null, 2).slice(0, 800)));
  const o = el("div", "opts");
  const opt = (k, txt, ok, always) => { const b = el("button"); b.append(el("kbd", "", k), txt); b.onclick = () => answer(ok, always); return b; };
  const answer = (ok, always) => { sendWS({ type: "approve", id: m.id, ok, always, key: m.key || m.name }); box.remove(); S.ask = null; };
  o.append(opt("1", "Yes", true, false), opt("2", m.name === "browser_navigate" ? `Yes, and don't ask again for ${host}` : `Yes, and don't ask again for ${mcp ? "this MCP tool" : m.name} this session`, true, true), opt("3", "No, and tell the agent what to do differently", false, false));
  box.append(o); c.card.append(box);
  S.ask = { answer };
}


/* ============================================================ rating (phase 4): a good run may teach the library */
function rateBar(t, rating) {
  const box = el("div", "rate"); t.rateEl = box; t.after.append(box);
  const paint = (r, saved) => {
    box.innerHTML = "";
    if (r) {
      box.append(el("span", `rt ${r.value > 0 ? "good" : "bad"}`, r.value > 0 ? "Rated good" : "Rated not good"));
      if (r.value > 0 && !saved && r.saved) saved = { entries: r.saved };
      if (r.value > 0) box.append(el("span", "rs", saved ? (saved.error ? "Could not save snippets: " + saved.error : saved.entries.length
        ? `Saved to the library: ${saved.entries.map(e => e.problem.slice(0, 60) + (e.replaced ? " (updated)" : "")).join(" · ")}` : "No reusable snippet found in this run.") : "Looking for reusable code…"));
      else if (r.note) box.append(el("span", "rs", r.note));
      const ch = el("button", "link", "Change"); ch.onclick = () => paint(null); box.append(ch);
      return;
    }
    box.append(el("span", "rl", "Rate this run"));
    const up = el("button", "", "Good"), dn = el("button", "", "Not good");
    up.title = "Good runs teach the library: reusable code is saved and offered in later plans";
    up.onclick = () => { sendWS({ type: "rate", turn: t.i, value: 1 }); };
    dn.onclick = () => {
      box.innerHTML = ""; const inp = el("input"); inp.placeholder = "What went wrong? (optional)";
      const send = el("button", "", "Send"); send.onclick = () => sendWS({ type: "rate", turn: t.i, value: -1, note: inp.value });
      inp.onkeydown = e => { if (e.key === "Enter") send.click(); };
      box.append(inp, send); inp.focus();
    };
    box.append(up, dn);
  };
  t.ratePaint = paint; paint(rating);
}

/* ============================================================ plan approval (phase 2) */
function planCard(t, plan) {
  t.after.querySelectorAll(".plancard").forEach(n => n.remove());
  const box = el("div", "plancard"), head = el("div", "pc-h"), state = el("span", "pc-s");
  head.append(el("b", "", "Plan"), state);
  const why = el("details", "pc-why"); why.open = (plan.status || "proposed") === "proposed"; why.append(el("summary", "", "Reasoning"), el("div", "pc-r", plan.reasoning || ""));
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
      r.append(n, tx);
      if (x.detail) r.append(el("div", "pc-d", x.detail));
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
  const label = { proposed: "waiting for your approval", approved: "approved", rejected: "rejected" };
  const paint = () => {
    state.textContent = label[plan.status] || plan.status; state.className = "pc-s " + plan.status;
    act.innerHTML = "";
    if (plan.status === "proposed") {
      const mode = el("select"); [["edit", "Edits"], ["auto", "Auto"], ["ask", "Review"]].forEach(([v, l]) => mode.append(new Option(l, v)));
      mode.value = S.mode === "plan" ? (S.prevMode || "edit") : S.mode; mode.title = "Permission mode for the run";
      const go = el("button", "primary", "Approve and run");
      go.onclick = () => { if (!tasks.length) return; sendWS({ type: "plan_approve", tasks, mode: mode.value }); setMode(mode.value); setBusy(true); };
      const rej = el("button", "", "Revise…");
      rej.onclick = () => {
        act.innerHTML = ""; const ta = el("textarea"); ta.placeholder = "What should change? The model plans again with your feedback."; ta.rows = 3;
        const send = el("button", "primary", "Send feedback"), cancel = el("button", "", "Cancel");
        send.onclick = () => { sendWS({ type: "plan_reject", feedback: ta.value }); setBusy(true); };
        cancel.onclick = paint; act.append(ta, send, cancel); ta.focus();
      };
      act.append(mode, go, rej);
    } else if (plan.status === "rejected" && plan.feedback) act.append(el("div", "pc-fb", "Feedback: " + plan.feedback));
  };
  box.append(head, why, rows, act); t.after.append(box);
  plan.status = plan.status || "proposed";
  draw(); paint();
  S.planCard = {
    update: m => { plan.status = m.status; if (m.tasks) { tasks.length = 0; m.tasks.forEach(x => tasks.push({ content: x.content, detail: x.detail || "" })); } if (m.feedback) plan.feedback = m.feedback; draw(); paint(); },
  };
}

/* ============================================================ memory */
const MEM_LABEL = { memory: "note", snippet: "snippet", skill: "skill" };
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
function snippetForm(btn, c) {
  const w = el("span", "snip-f"), name = el("input"), ok = el("button", "copy", "Save"); name.placeholder = "snippet name"; name.value = "";
  ok.onclick = async () => { if (!name.value.trim()) return; if (await memSave({ kind: "snippet", name: name.value, content: c.code, language: c.lang || "", description: "", scope: "project" })) { w.replaceWith(el("span", "snip-ok", "Saved")); } };
  name.onkeydown = e => { if (e.key === "Enter") ok.click(); };
  w.append(name, ok); btn.replaceWith(w); name.focus();
}
/* notes and snippets the harness saved by itself after a longer run: one quiet line with Undo */
function autoSavedLine(t, items) {
  t.after.querySelectorAll(".autosaved").forEach(n => n.remove());
  const box = el("div", "autosaved"), what = items.map(i => i.name).join(" · ");
  box.append(el("span", "", `Saved to memory: ${what}`));
  const undo = el("button", "link", "Undo");
  undo.onclick = async () => {
    await Promise.all(items.map(i => fetch(`/api/memory?session=${encodeURIComponent(S.sid || "")}&kind=${i.kind}&name=${encodeURIComponent(i.id)}&scope=${i.scope}`, { method: "DELETE" })));
    box.innerHTML = ""; box.append(el("span", "", "Removed again.")); loadMemory();
  };
  box.append(undo); t.after.append(box);
}

/* code the harness added to the library by itself after a run that ended with passing tests: one quiet line with Undo */
function libraryAutoLine(t, entries) {
  t.after.querySelectorAll(".autosaved.lib").forEach(n => n.remove());
  const box = el("div", "autosaved lib");
  box.append(el("span", "", "Saved to the library (tests passed): " + entries.map(e => e.problem.slice(0, 50) + (e.replaced ? " (updated)" : "")).join(" · ")));
  const undo = el("button", "link", "Undo");
  undo.onclick = async () => {
    await Promise.all(entries.map(e => fetch(`/api/library/${e.id}`, { method: "DELETE" })));
    box.innerHTML = ""; box.append(el("span", "", "Removed again.")); sbBadges(); if (SB.tab === "memory") loadMemory();
  };
  box.append(undo); t.after.append(box);
}
