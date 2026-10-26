// dogear UI, part 1: helpers, syntax highlighting, markdown and the shared state object S.
// Classic scripts in load order: core, sidebar, chat, workspace, board, app. Top-level const/let are shared.
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
  // small, predictable Markdown: fenced code, inline code, bold, italics, headings, bullets, numbered lists and pipe tables
  return src.split(/```/).map((p, i) => {
    if (i % 2) { const nl = p.indexOf("\n"), lang = EXT[p.slice(0, nl).trim().toLowerCase()] || langOf("x." + p.slice(0, nl).trim());
      return `<pre><code>${highlight(p.slice(nl + 1).replace(/\n$/, ""), lang).join("\n")}</code></pre>`; }
    const inline = t => esc(t).replace(/`([^`\n]+)`/g, "<code>$1</code>").replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    const out = [], lines = p.split("\n");
    for (let k = 0; k < lines.length; k++) {
      const l = lines[k];
      if (/^\s*\|.*\|\s*$/.test(l) && /^\s*\|?\s*:?-{2,}/.test(lines[k + 1] || "")) {          // a pipe table: header, separator, rows
        const cells = r => r.trim().replace(/^\||\|$/g, "").split("|").map(c => inline(c.trim()));
        let html = "<table><tr>" + cells(l).map(c => `<th>${c}</th>`).join("") + "</tr>";
        for (k += 2; k < lines.length && /^\s*\|.*\|\s*$/.test(lines[k]); k++) html += "<tr>" + cells(lines[k]).map(c => `<td>${c}</td>`).join("") + "</tr>";
        k--; out.push(html + "</table>"); continue;
      }
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(l)) { out.push("<hr>"); continue; }
      const h = /^#{1,4} +(.+)$/.exec(l); if (h) { out.push(`<strong class="h">${inline(h[1])}</strong>`); continue; }
      const li = /^(\s*)[-*] +(.+)$/.exec(l); if (li) { out.push(`${li[1]}• ${inline(li[2])}`); continue; }
      const ol = /^(\s*)(\d+)[.)] +(.+)$/.exec(l); if (ol) { out.push(`${ol[1]}${ol[2]}. ${inline(ol[3])}`); continue; }
      out.push(inline(l));
    }
    return out.join("\n").replace(/\n(<table>|<hr>)/g, "$1").replace(/(<\/table>|<hr>)\n/g, "$1");
  }).join("");
}

/* ============================================================ state */
const S = {
  // connection and session
  ws: null, sid: null, root: "", st: null,          // st: /api/state (settings, models, sessions)
  busy: false, viewOnly: false, opened: false,
  meta: { parent: null, note: "", lineage: null, worktree: null },
  // the conversation
  turns: [], turn: null, cards: {}, queue: [],       // queue: tool-call ids while a stored session is replayed
  cur: null, curText: "", think: null, thinkText: "",
  ask: null,                                         // the open approval (answered with keys 1/2/3)
  todos: [], draft: false, planCard: null,
  runs: {}, restore: null,
  // the workspace
  changed: new Map(), flash: new Set(), openDirs: new Set(), follow: true, webTouched: false,
  // the composer
  mode: "edit", hist: [], hi: 0, t0: 0, tok: 0, cost: 0,
  variants: false,                                   // settings: offer parallel variants
};
const log = $("#log");
const rel = p => (S.root && p.startsWith(S.root + "/")) ? p.slice(S.root.length + 1) : p;
const q = o => Object.entries(o).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
const api = (path, o) => fetch(`${path}?${q({ root: S.root, ...o })}`).then(r => r.ok ? r.json() : Promise.reject(r.status));
const KIND = { browser_navigate: "browser", browser_read: "browser", browser_click: "browser", browser_type: "browser", browser_key: "browser",
  browser_scroll: "browser", browser_screenshot: "browser", browser_console: "browser", browser_eval: "browser", browser_wait: "browser", browser_resize: "browser", browser_audit: "browser", browser_handoff: "browser", browser_flow: "browser", WebSearch: "net", Task: "agent", Ultra: "agent", Skill: "read", ViewImage: "read", MultiEdit: "write", Outline: "read", FindSymbol: "read", RunTests: "shell", Git: "shell", AskUser: "read", Read: "read", LS: "read", Glob: "read", Grep: "read", BashOutput: "read", Write: "write", Edit: "write", Bash: "shell", KillBash: "shell", WebFetch: "net", TodoWrite: "todo", Remember: "read", Recall: "read", SaveSnippet: "read", SaveSkill: "read", Forget: "read" };
const sendWS = o => S.ws && S.ws.readyState === 1 && S.ws.send(JSON.stringify(o));
