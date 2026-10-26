// dogear UI, part 5: the task strip (one line for the plan the model follows), sessions based on other sessions
// (branch bar, compare), optional parallel variants.

/* ============================================================ task strip */
function renderTasks(items) {
  S.todos = items || [];
  const box = $("#tasks"), n = S.todos.length, done = S.todos.filter(t => t.status === "completed").length;
  box.hidden = !n; if (!n) return;
  const open = box.classList.contains("open");
  box.innerHTML = "";
  const cur = S.todos.find(t => t.status === "in_progress") || S.todos.find(t => t.status === "pending");
  const head = el("div", "th");
  head.append(el("span", "tn", `${done}/${n}`), el("span", "tt", cur ? (done === n ? "All tasks done" : `${cur.content}`) : "All tasks done"), el("span", "chev"));
  head.onclick = () => { box.classList.toggle("open"); renderTasks(S.todos); };
  box.append(head);
  if (open) {
    const list = el("div", "tl");
    S.todos.forEach(t => {
      const r = el("div", `ti ${t.status}`);
      r.append(el("span", "mark", t.status === "completed" ? "✓" : t.status === "in_progress" ? "◌" : "○"), el("span", "", t.content));
      list.append(r);
    });
    box.append(list);
  }
}

/* ============================================================ sessions based on other sessions */
function renderBranchBar() {
  const b = $("#branchbar"), p = S.meta.parent; b.hidden = !p; if (!p) return; b.innerHTML = "";
  b.append(el("span", "", `Based on “${p.title}”, turn ${p.turn + 1}${S.meta.worktree ? " · own copy of the project" : ""}${S.meta.note ? " — " + S.meta.note : ""}`));
  const add = (txt, fn, title) => { const x = el("button", "", txt); if (title) x.title = title; x.onclick = fn; b.append(x); };
  add("Compare", () => openCompare());
  if (S.meta.worktree) {
    add("Keep these files", () => sendWS({ type: "adopt", id: S.sid }), "Copies the files this session changed into the original project. Files changed in both places are left alone and listed.");
    add("Discard copy", () => sendWS({ type: "discard", id: S.sid }));
  }
  add("Back to original", () => !S.busy && sendWS({ type: "open", id: p.id }));
  if (S.restore) add("Restore files to the branch point", () => { sendWS({ type: "undo", root: S.restore.root, to: S.restore.sha }); S.restore = null; renderBranchBar(); }, "Puts the project files back to the state at the branch point (a safety checkpoint is made first)");
}

function openVariants(t) {
  const dlg = $("#var"), body = $("#var-body"); dlg.hidden = false; body.innerHTML = "";
  const rep = el("label", "vopt"), cb = el("input"); cb.type = "checkbox"; cb.checked = true; rep.append(cb, "These are alternatives to this message (branch before it). Uncheck to continue after this turn.");
  body.append(rep);
  const areas = [];
  const addArea = (val = "") => {
    const l = el("label", "v", `Variant ${String.fromCharCode(65 + areas.length)}`), ta = el("textarea"); ta.value = val;
    ta.placeholder = areas.length ? "A different direction, e.g. “Do it with a table instead”" : ""; l.append(ta); areas.push(ta); add.before(l);
  };
  const row = el("div", "vrow"), add = el("button", "add", "+ Add variant"); add.type = "button";
  const go = el("button", "go", "Start in parallel"); go.type = "button";
  add.onclick = () => areas.length < 4 && addArea();
  go.onclick = () => {
    const prompts = areas.map(a => a.value.trim()).filter(Boolean); if (prompts.length < 1) return;
    sendWS({ type: "variants", turn: t.i, where: cb.checked ? "before" : "after", prompts }); dlg.hidden = true; drawer(true); sbTab("sessions");
  };
  row.append(add, go); body.append(row); addArea(t.text || ""); addArea();
  areas[1].focus();
}
function adoptCard(m) {
  const c = el("div", "adoptcard");
  c.append(el("b", "", `Kept ${plural(m.applied.length, "file")} in the project`));
  if (m.applied.length) c.append(el("code", "", m.applied.slice(0, 8).join("\n")));
  if (m.conflicts.length) c.append(el("div", "", `${plural(m.conflicts.length, "file")} changed in both places and were left alone:`), el("code", "", m.conflicts.slice(0, 8).join("\n")));
  if (m.undo) { const u = el("button", "undo", "Undo"); u.onclick = () => { sendWS({ type: "undo", root: m.undo.root, to: m.undo.sha }); u.remove(); }; c.append(u); }
  log.append(c); log.scrollTop = log.scrollHeight;
}

/* ---- compare two sessions side by side */
const userPos = msgs => msgs.map((m, i) => (m.role === "user" && !m.review && !m.compact) ? i : -1).filter(i => i >= 0);
function turnsOf(s) {
  const msgs = s.messages, pos = userPos(msgs);
  return pos.map((i, n) => {
    const end = pos[n + 1] ?? msgs.length, part = msgs.slice(i, end);
    const ans = [...part].reverse().find(m => m.role === "assistant" && m.content && !(m.tool_calls || []).length);
    return { user: msgs[i].content, answer: ans ? ans.content : "", summary: ans?.summary || part.find(m => m.summary)?.summary || null };
  });
}
async function openCompare() {
  const dlg = $("#cmp"), sel = $("#cmp-sel"), body = $("#cmp-body"); dlg.hidden = false; body.innerHTML = "Loading…";
  const list = (await (await fetch(`/api/branches?id=${S.sid}`)).json()).filter(b => b.id !== S.sid);
  sel.innerHTML = ""; list.forEach(b => sel.append(new Option(`${b.title} · ${b.turns} turns`, b.id)));
  if (S.meta.parent && list.some(b => b.id === S.meta.parent.id)) sel.value = S.meta.parent.id;
  const draw = async () => {
    if (!sel.value) { body.innerHTML = "No other session to compare with yet."; return; }
    const [a, b] = await Promise.all([S.sid, sel.value].map(id => fetch(`/api/session/${id}`).then(r => r.json())));
    const A = turnsOf(a), B = turnsOf(b); let k = 0; while (k < A.length && k < B.length && A[k].user === B[k].user && A[k].answer === B[k].answer) k++;
    $("#cmp-meta").textContent = `${plural(k, "shared turn")}`; body.innerHTML = "";
    body.append(el("div", "colh", `${a.title} (this)`), el("div", "colh", b.title));
    if (k) body.append(el("div", "same", `The first ${k} turn${k === 1 ? " is" : "s are"} identical.`));
    const files = x => x && x.changes && x.changes.length ? x.changes.map(c => `${c.created ? "+" : "~"} ${c.path.split("/").slice(-2).join("/")}`).join("  ") : "no file changes";
    for (let i = k; i < Math.max(A.length, B.length); i++) {
      const cell = T => {
        const c = el("div", "cell"); if (!T) { c.append(el("div", "q", "(no turn)")); return c; }
        const q = el("div", "q", T.user.slice(0, 160)), an = el("div", "a"); an.innerHTML = T.answer ? md(T.answer) : "(no answer)";
        c.append(q, an, el("div", "m", `${T.summary ? `${plural(T.summary.steps || 0, "step")} · ${T.summary.secs || 0}s · ` : ""}${files(T.summary)}`)); c._ans = an; return c;
      };
      const ca = cell(A[i]), cb = cell(B[i]);
      if (A[i] && B[i] && A[i].answer && B[i].answer) {
        const t = el("button", "difftoggle", "Show differences");
        t.onclick = () => {
          const on = t.classList.toggle("on");
          if (on) { const d = diffWords(A[i].answer, B[i].answer); if (d) { cb._ans.innerHTML = d.html; cb._ans.classList.add("dview"); } }
          else { cb._ans.innerHTML = md(B[i].answer); cb._ans.classList.remove("dview"); }
        };
        body.append(ca, cb, t); continue;
      }
      body.append(ca, cb);
    }
  };
  sel.onchange = draw; await draw();
}
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
  let html = "", add = 0, del = 0, run = null, lead = false;
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
