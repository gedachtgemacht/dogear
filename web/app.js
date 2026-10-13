"use strict";
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const store = { get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };

/* ============================================================ syntax highlighting */
const KW = {
  py: "and as assert async await break class continue def del elif else except finally for from global if import in is lambda None nonlocal not or pass raise return True False try while with yield self",
  js: "async await break case catch class const continue debugger default delete do else export extends finally for from function if import in instanceof let new null of return static super switch this throw true false try typeof undefined var void while with yield interface type enum implements private public readonly as abstract",
  go: "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var nil true false",
  rs: "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
  c: "auto break case char const continue default do double else enum extern float for goto if int long return short signed sizeof static struct switch typedef union unsigned void volatile while class public private protected new delete this true false null nullptr namespace using template",
  sh: "if then else elif fi for while do done case esac function in return export local echo cd exit",
  json: "true false null", yaml: "true false null",
};
const EXT = { py: "py", js: "js", mjs: "js", cjs: "js", jsx: "js", ts: "js", tsx: "js", go: "go", rs: "rs", c: "c", h: "c", cpp: "c", hpp: "c", java: "c", cs: "c",
  sh: "sh", bash: "sh", zsh: "sh", css: "css", scss: "css", html: "html", htm: "html", xml: "html", svg: "html", vue: "html", json: "json", yml: "yaml", yaml: "yaml", toml: "yaml", md: "md" };
const SLASH = "\\/\\/.*|\\/\\*[\\s\\S]*?\\*\\/", HASH = "#.*";
const COM = { py: HASH, sh: HASH, yaml: HASH, js: SLASH, go: SLASH, rs: SLASH, c: SLASH, css: "\\/\\*[\\s\\S]*?\\*\\/", html: "<!--[\\s\\S]*?-->" };
const langOf = p => EXT[(p.split(".").pop() || "").toLowerCase()] || "md";
const reCache = {};
function highlight(text, lang) {
  const out = [""]; let line = 0;
  const emit = (cls, s) => { s.split("\n").forEach((piece, i) => { if (i) out[++line] = ""; if (piece) out[line] += cls ? `<span class="${cls}">${esc(piece)}</span>` : esc(piece); }); };
  if (lang === "md") { emit("", text); return out; }
  if (!reCache[lang]) {
    const P = [];
    if (COM[lang]) P.push(`(?<com>${COM[lang]})`);
    if (lang === "html") P.push(`(?<tag><\\/?[A-Za-z][\\w:-]*|\\/?>)`, `(?<str>(?<==)(?:"[^"\\n]*"|'[^'\\n]*'))`);
    else {
      P.push(`(?<str>"""[\\s\\S]*?"""|'''[\\s\\S]*?'''|"(?:\\\\.|[^"\\\\\\n])*"|'(?:\\\\.|[^'\\\\\\n])*'|\`(?:\\\\.|[^\`\\\\])*\`)`);
      P.push(lang === "css" ? `(?<num>#[0-9a-fA-F]{3,8}\\b|\\b\\d[\\d.]*(?:px|em|rem|%|vh|vw|s|ms)?)` : `(?<num>\\b\\d[\\d_]*(?:\\.\\d+)?\\b)`);
      P.push(`(?<id>@?[A-Za-z_$][\\w$-]*)`);
    }
    reCache[lang] = new RegExp(P.join("|"), "g");
  }
  const re = reCache[lang], kw = new Set((KW[lang] || "").split(" "));
  re.lastIndex = 0; let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) emit("", text.slice(last, m.index));
    const g = m.groups; let cls = "";
    if (g.com !== undefined) cls = "tk-c";
    else if (g.str !== undefined) cls = lang === "json" && /^\s*:/.test(text.slice(re.lastIndex, re.lastIndex + 20)) ? "tk-t" : "tk-s";
    else if (g.tag !== undefined) cls = "tk-k";
    else if (g.num !== undefined) cls = "tk-n";
    else if (g.id !== undefined) {
      const nx = text.slice(re.lastIndex).match(/^\s*(.)/)?.[1];
      if (kw.has(g.id)) cls = "tk-k";
      else if (lang === "css" && nx === ":") cls = "tk-t";
      else if (g.id[0] === "@") cls = "tk-g";
      else if (nx === "(") cls = "tk-f";
      else if (/^[A-Z]/.test(g.id) && lang !== "css") cls = "tk-t";
    }
    emit(cls, m[0]); last = re.lastIndex;
    if (m[0] === "") re.lastIndex++;
  }
  if (last < text.length) emit("", text.slice(last));
  return out;
}

function md(src) {
  return src.split(/```/).map((p, i) => {
    if (i % 2) { const nl = p.indexOf("\n"), lang = EXT[p.slice(0, nl).trim().toLowerCase()] || langOf("x." + p.slice(0, nl).trim());
      return `<pre><code>${highlight(p.slice(nl + 1).replace(/\n$/, ""), lang).join("\n")}</code></pre>`; }
    return esc(p).replace(/`([^`\n]+)`/g, "<code>$1</code>").replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/^#{1,4} +(.+)$/gm, '<strong class="h">$1</strong>').replace(/^[-*] +/gm, "• ");
  }).join("");
}

/* ============================================================ state */
const S = { meta: { parent: null, pins: [], titles: {}, lineage: null }, todos: [], ultra: null, restore: null, railOpen: false, wsAuto: false, wsDismissed: false, turns: [], turn: null, curWrap: null, ws: null, busy: false, root: "", mode: "edit", cur: null, curText: "", think: null, thinkText: "", cards: {}, queue: [],
  changed: new Map(), flash: new Set(), openDirs: new Set(), sid: null, ask: null, t0: 0, tok: 0, follow: true, st: null, hist: [], hi: 0, webTouched: false };
const log = $("#log");
const rel = p => (S.root && p.startsWith(S.root + "/")) ? p.slice(S.root.length + 1) : p;
const q = o => Object.entries(o).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
const api = (path, o) => fetch(`${path}?${q({ root: S.root, ...o })}`).then(r => r.ok ? r.json() : Promise.reject(r.status));
const KIND = { browser_navigate: "browser", browser_read: "browser", browser_click: "browser", browser_type: "browser", browser_key: "browser",
  browser_scroll: "browser", browser_screenshot: "browser", browser_console: "browser", browser_eval: "browser", browser_wait: "browser", browser_resize: "browser", browser_audit: "browser", browser_handoff: "browser", WebSearch: "net", Task: "agent", Ultra: "agent", Skill: "read", ViewImage: "read", MultiEdit: "write", Outline: "read", FindSymbol: "read", RunTests: "shell", Git: "shell", AskUser: "read", Read: "read", LS: "read", Glob: "read", Grep: "read", BashOutput: "read", Write: "write", Edit: "write", Bash: "shell", KillBash: "shell", WebFetch: "net", TodoWrite: "todo" };
const sendWS = o => S.ws && S.ws.readyState === 1 && S.ws.send(JSON.stringify(o));

/* ============================================================ chat */
function keepScroll() { const near = log.scrollHeight - log.scrollTop - log.clientHeight < 160; return () => { if (near) log.scrollTop = log.scrollHeight; }; }
function emptyState() {
  log.innerHTML = ""; const e = el("div", "empty-state", "Describe a task to get started");
  e.append(el("small", "", S.root)); log.append(e);
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
      w.append(pre, cp);
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

/* ============================================================ workspace: only open when needed */
function openWS(tab, auto = false) {
  if (auto && S.wsDismissed) return false;
  const first = $("#work").hidden;
  $("#work").hidden = false; $("#ide").classList.add("ws"); $("#ws-toggle").classList.add("on");
  if (first) S.wsAuto = auto;
  if (tab) activate(tab);
  fit();
  return true;
}
function closeWS(user = false) {
  $("#work").hidden = true; $("#ide").classList.remove("ws"); $("#ws-toggle").classList.remove("on");
  if (user) S.wsDismissed = true;
}
const wsOpen = () => !$("#work").hidden;
function drawer(open) { $("#drawer").hidden = !open; $("#menu").classList.toggle("on", open); }

/* ============================================================ editor */
const E = { files: {}, tabs: ["@preview"], active: "@preview", playing: null, eyeTimer: 0 };
const badge = p => S.changed.get(p);

function renderTabs() {
  const nav = $("#etabs"); nav.innerHTML = "";
  for (const t of E.tabs) {
    const b = el("button", `tab ${t === E.active ? "on" : ""}`); b.dataset.p = t;
    if (t === "@preview") { const i = el("i", "live"); b.append(i, "Browser"); }
    else { b.append(t.split("/").pop()); if (badge(t)) b.append(el("span", "dot")); const x = el("span", "x", "✕"); x.onclick = e => { e.stopPropagation(); closeTab(t); }; b.append(x); b.title = t; }
    b.onclick = () => activate(t); nav.append(b);
  }
  const f = el("label", "tab follow");
  const cb = el("input"); cb.type = "checkbox"; cb.checked = S.follow; cb.onchange = () => S.follow = cb.checked; f.append(cb, "Follow agent"); nav.append(f);
  const x = el("button", "tab close", "✕"); x.title = "Close workspace"; x.onclick = () => closeWS(true); nav.append(x);
}
function activate(t) {
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
const B = { vw: 1280, vh: 800, scale: 1, hideT: 0, blank: true };
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
function browserEvent(m) {
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
    case "b_marks": { const few = m.rects.length <= 12;   // dense pages: quiet outlines only, no chips
      for (const r of m.rects.slice(0, 80)) {
        const d = el("div", few ? "mark" : "mark quiet"); d.style.cssText = `left:${r.x * B.scale}px;top:${r.y * B.scale}px;width:${r.w * B.scale}px;height:${r.h * B.scale}px`;
        if (few) d.append(el("b", "", r.ref)); bov.append(d); setTimeout(() => d.remove(), 1500); } break; }
    case "b_log": logLine(m.level, m.text); break;
    case "b_handoff": $("#need-t").textContent = m.reason; $("#need").hidden = false; document.title = "● Your turn";
      S.wsDismissed = false; openWS("@preview"); bov.focus(); break;
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
function agentBusy(on) { $("#ban").hidden = !on; }
function initBrowser() {
  let last = 0;
  bov.addEventListener("pointermove", e => { const n = performance.now(); if (n - last < 40) return; last = n; sendWS({ type: "b_mouse", kind: "move", ...bpt(e) }); });
  bov.addEventListener("pointerdown", e => { bov.focus(); bov.setPointerCapture(e.pointerId); e.preventDefault();
    sendWS({ type: "b_mouse", kind: "down", button: ["left", "middle", "right"][e.button] || "left", clicks: e.detail || 1, mods: bmods(e), ...bpt(e) }); });
  bov.addEventListener("pointerup", e => sendWS({ type: "b_mouse", kind: "up", button: ["left", "middle", "right"][e.button] || "left", clicks: e.detail || 1, mods: bmods(e), ...bpt(e) }));
  bov.addEventListener("wheel", e => { e.preventDefault(); sendWS({ type: "b_mouse", kind: "wheel", dx: e.deltaX, dy: e.deltaY, ...bpt(e) }); }, { passive: false });
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
async function renderTree() {
  const box = $("#tree"), fresh = document.createElement("div");
  await fillTree(fresh, "."); box.replaceChildren(...fresh.childNodes);
}
async function fillTree(box, path) {
  let list; try { list = await api("/api/tree", { path }); } catch { box.append(el("div", "empty", "Cannot read project directory")); return; }
  if (!list.length && path === ".") { const e = el("div", "empty", "Empty project."); box.append(e); return; }
  for (const e of list) {
    const n = el("div", `n ${e.dir ? "dir" : "file"}${S.openDirs.has(e.path) ? " open" : ""}${E.active === e.path ? " sel" : ""}`); n.dataset.p = e.path; n.append(el("span", "", e.name)); n.title = e.path;
    const b = !e.dir && badge(e.path); if (b) n.append(el("span", `b ${b}`, b));
    if (S.flash.has(e.path)) n.classList.add("flash");
    box.append(n);
    if (e.dir) {
      n.onclick = () => { S.openDirs.has(e.path) ? S.openDirs.delete(e.path) : S.openDirs.add(e.path); renderTree(); };
      if (S.openDirs.has(e.path)) { const k = el("div", "kids"); box.append(k); await fillTree(k, e.path); }
    } else n.onclick = () => { openWS(e.path); drawer(false); };
  }
}
function renderTodos(items) {
  $("#todo-sec").hidden = !items.length;
  const ul = $("#todos"); ul.innerHTML = ""; items.forEach(t => ul.append(el("li", t.status, t.content)));
  $("#todo-count").textContent = `${items.filter(t => t.status === "completed").length}/${items.length}`;
}
function renderMcp(servers) {
  const box = $("#mcp"); box.innerHTML = "";
  if (!servers.length) { const d = el("div", "mcp-none"); d.innerHTML = "No servers. Add <code>.mcp.json</code> to the project or <code>~/dogear/mcp.json</code>."; box.append(d); return; }
  for (const s of servers) {
    const d = el("div", `mcp-s ${s.state}`), h = el("div"); h.innerHTML = `<i></i><b>${esc(s.name)}</b> <span class="meta">${s.state === "ready" ? s.tools.length + " tools" : s.state}</span>`;
    d.append(h);
    const sm = el("small", "", s.error || s.tools.join(", ")); sm.hidden = !s.error; d.append(sm);
    d.onclick = () => sm.hidden = !sm.hidden; box.append(d);
  }
}
function renderHistory(list) {
  const ul = $("#hist"); ul.innerHTML = "";
  for (const s of list.slice(0, 25)) {
    const li = el("li", s.id === S.sid ? "on" : ""); li.append(el("span", "", s.title)); li.title = s.root;
    const x = el("button", "", "✕"); x.onclick = async e => { e.stopPropagation(); await fetch(`/api/session/${s.id}`, { method: "DELETE" }); refresh(); };
    li.append(x); li.onclick = () => { if (!S.busy) { sendWS({ type: "open", id: s.id }); drawer(false); } }; ul.append(li);
  }
}

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
    case "todos": renderTodos(m.items); renderRail(m.items); break;
    case "pins": S.meta.pins = m.pins; S.turns.forEach(syncPin); renderOutline(); break;
    case "titles": if (m.session === S.sid) { S.meta.titles = m.titles; renderOutline(); } break;
    case "forked": renderSession(m.session); S.restore = m.restore; renderBranchBar();
      if (m.prefill) { $("#input").value = m.prefill; $("#input").focus(); }
      log.append(el("div", "empty", m.prefill ? "Branched before this message. Edit it and send." : "Branched. This is a copy; the original stays unchanged.")); log.scrollTop = log.scrollHeight; refresh(); break;
    case "mcp": renderMcp(m.servers); break;
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
    case "session": renderSession(m.session); break;
    case "review_start": if (S.cur) { S.cur.classList.add("narr"); workAdd(S.cur); S.cur = null; S.curText = ""; } turn().after.querySelectorAll(".follow-ups").forEach(n => n.remove()); break;
    case "compacted": renderSession(m.session);
      log.append(el("div", "empty", `${m.auto ? "Context was nearly full, so " : ""}${m.replaced} messages were condensed: about ${Math.round(m.before / 1000)}k → ${Math.round(m.after / 1000)}k tokens.`));
      log.scrollTop = log.scrollHeight; break;
    case "turn_start": if (!S.busy) { renderSession(m.session); setBusy(true); } break;   // a run started in another window
  }
  keep();
}

function renderSession(s) {
  S.sid = s.id; S.root = s.root; $("#root").value = s.root; S.cards = {}; S.queue = []; S.cur = null; S.changed.clear();
  S.meta = { parent: s.parent || null, pins: s.pins || [], titles: s.titles || {}, lineage: s.lineage || s.id }; S.ultra = null;
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
        setAnswerText(t, m.content);
        if (m.summary) applySummary(t, m.summary);
        if (m.present) renderBlocks(t, m.present);
      }
    } else if (m.role === "tool") {
      const c = S.cards[S.queue.shift()];
      if (c) { const ok = m.ok !== false; finishCard(c, ok, m.content, m.meta || {});
        if (c.name === "Bash" && c.args.command) { const id = "r" + Math.random().toString(36).slice(2, 7);
          termStart({ id, command: c.args.command, background: false }); termWrite(id, m.content); termEnd(id, m.meta?.exit ?? 0); }
        if (ok && m.meta?.diff) S.changed.set(rel(m.meta.path || ""), m.meta.created ? "A" : "M"); }
    }
  }
  renderTodos(s.todos || []); renderRail(s.todos || []); renderBranchBar(); renderOutline();
  S.turns.forEach(t => { syncPin(t); if (t.raw) offerDiff(t); });
  E.files = {}; E.tabs = ["@preview"]; activate("@preview"); renderTree();
  log.scrollTop = log.scrollHeight; refresh();
  const tab = new URLSearchParams(location.search).get("tab"); if (tab) activate(tab);
}

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
function renderRail(items) {
  S.todos = items || [];
  const r = $("#rail"); r.innerHTML = "";
  const active = S.todos.length > 0 || !!S.ultra;
  r.hidden = !active; if (!active) return;
  r.classList.toggle("open", S.railOpen); r.classList.toggle("hasultra", !!S.ultra);
  const done = S.todos.filter(t => t.status === "completed").length, now = S.todos.find(t => t.status === "in_progress");
  const head = el("div", "rhead");
  const prog = el("div", "rprog"), bar = el("i"); bar.style.width = (S.todos.length ? done / S.todos.length * 100 : 0) + "%"; prog.append(bar);
  head.append(el("b", "", "Plan"), el("span", "rcount", `${done}/${S.todos.length}`), prog);
  if (now && !S.railOpen) head.append(el("span", "rnow", now.content));
  head.append(el("button", "rtog", S.railOpen ? "▾" : "▸"));
  head.onclick = () => { S.railOpen = !S.railOpen; store.set("dogear-rail", S.railOpen ? "1" : "0"); renderRail(S.todos); };
  r.append(head);
  const lanes = el("div", "rlanes");
  for (const [st, name, cls] of LANES) {
    const lane = el("div", `lane ${cls}`), list = S.todos.map((t, i) => ({ t, i })).filter(x => x.t.status === st);
    const h = el("h4", ""); h.append(el("span", "", name), el("span", "", String(list.length))); lane.append(h);
    for (const { t, i } of list) {
      const c = el("div", "card2", t.content); c.title = "Click to move to the next column";
      if (railSeen[t.content] && railSeen[t.content] !== st) c.classList.add("moved");
      c.onclick = () => { const next = { pending: "in_progress", in_progress: "completed", completed: "pending" }[st];
        sendWS({ type: "set_todos", items: S.todos.map((x, k) => k === i ? { ...x, status: next } : x) }); };
      lane.append(c);
    }
    lanes.append(lane);
  }
  r.append(lanes);
  if (S.ultra) { const u = S.ultra; r.append(el("div", "rultra", `Ultra · ${u.phase || "starting"} · ${u.running || 0} running · ${u.done || 0} done${u.failed ? ` · ${u.failed} failed` : ""}`)); }
  railSeen = Object.fromEntries(S.todos.map(t => [t.content, t.status]));
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
  b.append(el("span", "", `Branch of “${p.title}” · ${p.where === "before" ? `edited at turn ${p.turn + 1}` : `from turn ${p.turn + 1}`}`));
  const add = (txt, fn, title) => { const x = el("button", "", txt); if (title) x.title = title; x.onclick = fn; b.append(x); };
  add("Compare", () => openCompare());
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

/* ============================================================ input */
let spinTimer = 0;
function setBusy(b) {
  S.busy = b; document.body.classList.toggle("busy", b); $("#spin").hidden = !b; $("#input").disabled = b;
  clearInterval(spinTimer);
  if (b) { S.t0 = Date.now(); S.tok = 0; const tick = () => { const s = Math.round((Date.now() - S.t0) / 1000);
      $("#spin-t").textContent = `Working · ${s}s · ${S.tok} tokens`; };
    tick(); spinTimer = setInterval(tick, 500); }
  else { S.cur = null; S.think = null; $("#input").focus(); }
}
const MODE_TXT = { ask: "Confirms edits and commands", edit: "Confirms commands", auto: "No confirmations", plan: "Read-only: proposes a plan" };
function setMode(v) { S.mode = v; document.querySelectorAll("#mode button").forEach(b => b.classList.toggle("on", b.dataset.v === v)); $("#h-mode").textContent = MODE_TXT[v]; }

const SLASHES = [
  ["/new", "start a new session"], ["/ultra", "multi-agent run: review | research | design | audit  <task>"], ["/compact", "condense the conversation to free context (optional focus)"], ["/clear", "clear this session"], ["/mode", "ask | edit | auto"], ["/model", "switch model"],
  ["/mcp", "reload MCP servers"], ["/init", "write a KERF.md for this project"], ["/help", "list commands"],
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
    case "/mcp": sendWS({ type: "mcp_reload" }); note("Reloading MCP servers…"); break;
    case "/ultra": { const [pat, ...rest] = arg.split(/\s+/); if (!["review", "research", "design", "audit"].includes(pat)) { note("Usage: /ultra review|research|design|audit <task>"); break; }
      return `Use the Ultra tool with pattern "${pat}" for this task: ${rest.join(" ") || "the whole project"}`; }
    case "/compact": if (S.busy) note("Wait for the current run to finish."); else { sendWS({ type: "compact", focus: arg }); note("Condensing the conversation…"); } break;
    case "/init": return "Explore this project (LS, Glob, Read the key files) and write a concise KERF.md in the project root: what it is, how to run, test and build it, the layout, and the conventions a coding agent must follow.";
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
  renderHistory(sessions);
}
function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`); S.ws = ws;
  ws.onopen = () => { sendWS({ type: "b_sub" }); const id = new URLSearchParams(location.search).get("session"); if (id && !S.opened) { S.opened = 1; sendWS({ type: "open", id }); } };
  ws.onmessage = ev => handle(JSON.parse(ev.data));
  ws.onclose = () => { setBusy(false); setTimeout(connect, 1500); };
}

(async function init() {
  document.documentElement.dataset.theme = new URLSearchParams(location.search).get("theme") || store.get("dogear-theme", "dark");
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
    else if (e.key === "Escape" && S.busy && document.activeElement !== bov) sendWS({ type: "stop" });
    else if (e.key === "Tab" && e.shiftKey) { e.preventDefault(); const m = ["ask", "edit", "auto", "plan"]; setMode(m[(m.indexOf(S.mode) + 1) % 4]); }
    else if (S.ask && "123".includes(e.key) && e.key.length === 1 && !(e.target === inp && inp.value)) { e.preventDefault(); S.ask.answer(e.key !== "3", e.key === "2"); }
  });
  $("#root").onchange = () => { S.root = $("#root").value.trim(); sendWS({ type: "root", root: S.root }); S.changed.clear(); E.files = {}; renderTree(); };
  $("#new").onclick = () => !S.busy && sendWS({ type: "new" });
  $("#refresh").onclick = renderTree; $("#mcp-reload").onclick = () => sendWS({ type: "mcp_reload" });
  initBrowser();
  S.railOpen = store.get("dogear-rail", "0") === "1";
  $("#outline-btn").onclick = e => { e.stopPropagation(); const b = $("#outline"); b.hidden = !b.hidden; $("#outline-btn").classList.toggle("on", !b.hidden);
    if (!b.hidden) { renderOutline(); sendWS({ type: "titles" }); b.querySelector("input")?.focus(); } };
  $("#cmp-x").onclick = () => { $("#cmp").hidden = true; };
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
  await refresh(); emptyState(); renderTabs(); renderTree(); renderMcp([]); connect(); setBusy(false);
})();
