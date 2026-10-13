"""Project memory and learned skills/snippets that survive between sessions.

Three kinds of entries, each a small markdown file with a front matter:
  memory   facts, decisions, gotchas, commands, preferences about a project or about the user
  snippet  reusable code (verbatim) with a description and tags
  skill    written guidance with triggers; loaded like the built-in skills in skills/

Scopes: "project" lives in <project>/.dogear/<kind>s/ (travels with the repo, the user can read and edit it),
"global" lives in data/learned/<kind>s/ (follows the user across projects).
"""
import re
import time
from pathlib import Path

from .tools import ToolError

DATA = Path(__file__).resolve().parent.parent / "data"
GLOBAL = DATA / "learned"
KINDS = {"memory": "memory", "snippet": "snippets", "skill": "skills"}
MEMORY_TYPES = ("fact", "preference", "decision", "gotcha", "command")
LIMITS = {"memory": 2000, "snippet": 8000, "skill": 6000}
PROMPT_MEMORY_CHARS = 3000          # budget for memory text in the system prompt
PROMPT_SNIPPET_CHARS = 3000         # budget for auto-attached snippet code
SECRET = re.compile(r"(?i)(?:api[_-]?key|secret|passw(?:or)?d|token|authorization)\W{0,3}\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+=]{12,}"
                    r"|\bsk-[A-Za-z0-9_-]{16,}|\bghp_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b")


class MemoryError_(ValueError):
    pass


def folder(root: Path, kind: str, scope: str) -> Path:
    if kind not in KINDS:
        raise MemoryError_(f"kind must be one of {', '.join(KINDS)}")
    if scope == "global":
        return GLOBAL / KINDS[kind]
    if scope == "project":
        return Path(root).resolve() / ".dogear" / KINDS[kind]
    raise MemoryError_("scope must be 'project' or 'global'")


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].strip("-")
    if not s:
        raise MemoryError_("give it a name made of letters or digits")
    return s


def _one_line(s: str, n: int = 200) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def _split(raw: str) -> tuple[dict, str]:
    m = re.match(r"---\n(.*?)\n---\n?(.*)", raw, re.S)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep:
            meta[k.strip()] = v.strip()
    return meta, m.group(2).strip()


def _entry(f: Path, kind: str, scope: str) -> dict | None:
    try:
        raw = f.read_text()
        mtime = f.stat().st_mtime
    except OSError:
        return None
    meta, body = _split(raw)
    return {"kind": kind, "scope": scope, "id": f.stem, "name": meta.get("name", f.stem), "description": meta.get("description", ""),
            "type": meta.get("type", ""), "language": meta.get("language", ""), "tags": [t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
            "triggers": [t.strip() for t in meta.get("triggers", "").split(",") if t.strip()],
            "created": meta.get("created", ""), "body": body, "mtime": mtime}


def entries(root: Path, kinds=("memory", "snippet", "skill")) -> list[dict]:
    out = []
    for kind in kinds:
        for scope in ("project", "global"):
            d = folder(root, kind, scope)
            if d.is_dir():
                out += [e for f in sorted(d.glob("*.md")) if (e := _entry(f, kind, scope))]
    return sorted(out, key=lambda e: -e["mtime"])


def public(e: dict) -> dict:
    return {k: v for k, v in e.items() if k != "mtime"} | {"age": int(time.time() - e["mtime"])}


# ------------------------------------------------------------------ writing

def save(root: Path, kind: str, name: str, body: str, scope: str = "project", **meta) -> dict:
    body = str(body or "").strip()
    if not body:
        raise MemoryError_("nothing to save: content is empty")
    if len(body) > LIMITS[kind]:
        raise MemoryError_(f"too long ({len(body)} characters, limit {LIMITS[kind]}): save the essence")
    if SECRET.search(body) or SECRET.search(str(meta.get("description", ""))):
        raise MemoryError_("this looks like it contains a secret (key, token or password); secrets are never stored")
    sid = slug(name)
    d = folder(root, kind, scope)
    f = d / f"{sid}.md"
    existed = f.exists()
    d.mkdir(parents=True, exist_ok=True)
    fm = {"name": _one_line(name, 80) or sid}
    if kind == "memory":
        t = str(meta.get("type") or "fact").lower()
        fm["type"] = t if t in MEMORY_TYPES else "fact"
        fm["description"] = _one_line(meta.get("description") or body, 160)
    elif kind == "snippet":
        fm["description"] = _one_line(meta.get("description"), 200)
        fm["language"] = _one_line(meta.get("language"), 20).lower()
        tags = meta.get("tags") or []
        fm["tags"] = ", ".join(_one_line(t, 24) for t in (tags.split(",") if isinstance(tags, str) else tags) if str(t).strip())[:200]
    else:
        fm["description"] = _one_line(meta.get("description"), 200)
        trig = meta.get("triggers") or []
        trig = [t.strip().lower() for t in (trig.split(",") if isinstance(trig, str) else trig) if str(t).strip()]
        if not trig:
            raise MemoryError_("a skill needs triggers: the words in a request that should load it")
        fm["triggers"] = ", ".join(trig[:12])
    fm["created"] = time.strftime("%Y-%m-%d")
    head = "\n".join(f"{k}: {v}" for k, v in fm.items() if v != "")
    f.write_text(f"---\n{head}\n---\n{body}\n")
    return {"id": sid, "kind": kind, "scope": scope, "updated": existed, "path": str(f)}


def delete(root: Path, kind: str, name: str, scope: str | None = None) -> dict:
    sid = slug(name)
    for sc in ([scope] if scope else ["project", "global"]):
        f = folder(root, kind, sc) / f"{sid}.md"
        if f.is_file():
            f.unlink()
            return {"id": sid, "kind": kind, "scope": sc}
    raise MemoryError_(f"no {kind} named {name!r}")


# ------------------------------------------------------------------ searching

def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-zäöüß0-9_]{3,}", s.lower())]


def score(e: dict, q: list[str]) -> float:
    name, desc, tags = e["name"].lower(), e["description"].lower(), " ".join(e["tags"] + e["triggers"]).lower()
    body = e["body"].lower()
    s = 0.0
    for w in q:
        s += 3 * (w in name) + 2 * (w in tags) + 2 * (w in desc) + 1 * (w in body)
    return s


def search(root: Path, query: str, kinds=("memory", "snippet", "skill"), limit: int = 5) -> list[dict]:
    q = _words(query)
    if not q:
        return []
    ranked = sorted(((score(e, q), e) for e in entries(root, kinds)), key=lambda x: (-x[0], -x[1]["mtime"]))
    return [e for s, e in ranked if s > 0][:limit]


# ------------------------------------------------------------------ prompt

def prompt_block(root: Path, text: str) -> tuple[str, dict]:
    """The notes and snippets that go into the system prompt. Returns (text, counts)."""
    mem = [e for e in entries(root, ("memory",))]
    snip = [e for e in entries(root, ("snippet",))]
    out, shown, rest = [], 0, []
    if mem:
        used = 0
        for e in mem:
            line = f"- [{e['type'] or 'fact'}] {e['name']}: {_one_line(e['body'], 400)}" + (" (about the user, all projects)" if e["scope"] == "global" else "")
            if used + len(line) <= PROMPT_MEMORY_CHARS:
                out.append(line)
                used += len(line)
                shown += 1
            else:
                rest.append(e["name"])
        block = ("\nNotes from earlier sessions (saved by you or the user; the current files win if they disagree):\n" + "\n".join(out) + "\n")
        if rest:
            block += f"More notes you can fetch with Recall: {', '.join(rest[:20])}\n"
        out = [block]
    if snip:
        q = _words(text)
        attach, used = [], 0
        for s, e in sorted(((score(e, q), e) for e in snip), key=lambda x: -x[0]):
            if s >= 3 and len(attach) < 2 and used + len(e["body"]) <= PROMPT_SNIPPET_CHARS:
                attach.append(e)
                used += len(e["body"])
        lines = [f"- {e['name']}" + (f" ({e['language']})" if e["language"] else "") + (f": {e['description']}" if e["description"] else "") for e in snip[:20]]
        block = "\nSaved code snippets (fetch the code with Recall):\n" + "\n".join(lines) + "\n"
        for e in attach:
            block += f"\nSnippet {e['name']} (matches this request):\n```{e['language']}\n{e['body']}\n```\n"
        out.append(block)
    return "".join(out), {"memory": len(mem), "snippets": len(snip), "shown": shown}


# ------------------------------------------------------------------ tools

def _fmt(e: dict, full: bool = True) -> str:
    head = f"{e['kind']} {e['name']} [{e['scope']}]" + (f" ({e['language']})" if e["language"] else "") + (f" tags: {', '.join(e['tags'])}" if e["tags"] else "")
    if not full:
        return head
    body = e["body"] if e["kind"] != "snippet" else f"```{e['language']}\n{e['body']}\n```"
    return f"{head}\n{e['description']}\n{body}".strip()


def _wrap(fn):
    def run(ctx, **kw):
        try:
            return fn(ctx, **kw)
        except MemoryError_ as e:
            raise ToolError(str(e))
    run.__name__ = fn.__name__
    return run


@_wrap
def Remember(ctx, title="", content="", type="fact", scope="project"):
    if not title.strip():
        title = _one_line(content, 50)
    r = save(ctx.root, "memory", title, content, scope, type=type)
    return f"{'Updated' if r['updated'] else 'Saved'} note {r['id']!r} ({r['scope']}). It will be in the prompt of future sessions."


@_wrap
def Recall(ctx, query=""):
    hits = search(ctx.root, query, limit=5)
    if not hits:
        names = ", ".join(e["name"] for e in entries(ctx.root)[:15]) or "nothing saved yet"
        return f"No match for {query!r}. Saved: {names}"
    return "\n\n".join(_fmt(e) for e in hits)[:9000]


@_wrap
def SaveSnippet(ctx, name="", code="", language="", description="", tags="", scope="project", file_path="", start=0, end=0):
    if file_path and not code:
        p = ctx.path(file_path)
        lines = p.read_text().splitlines()
        a, b = max(int(start or 1), 1), int(end or len(lines))
        code = "\n".join(lines[a - 1:b])
        language = language or p.suffix.lstrip(".")
    r = save(ctx.root, "snippet", name, code, scope, language=language, description=description, tags=tags)
    return f"{'Updated' if r['updated'] else 'Saved'} snippet {r['id']!r} ({r['scope']})."


@_wrap
def SaveSkill(ctx, name="", description="", triggers="", guidance="", scope="project"):
    r = save(ctx.root, "skill", name, guidance, scope, description=description, triggers=triggers)
    return f"{'Updated' if r['updated'] else 'Saved'} skill {r['id']!r} ({r['scope']}). It loads when a request mentions its triggers."


@_wrap
def Forget(ctx, kind="memory", name="", scope=""):
    r = delete(ctx.root, kind, name, scope or None)
    return f"Deleted {r['kind']} {r['id']!r} ({r['scope']})."


def _spec(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


_S = {"type": "string"}
_I = {"type": "integer"}
_p = lambda t, d: {**t, "description": d}
_SCOPE = _p(_S, "project (default, stays with this repo) or global (follows the user across projects)")

TOOLS = {
    "Remember": ("read", Remember, _spec("Remember",
        "Save a note for future sessions: a decision, a gotcha, a command, a convention, or a user preference that the files do not make obvious. "
        "One fact per note, concrete, no secrets. Do not save what the code or git history already shows.",
        {"title": _p(_S, "short name, 2-6 words"), "content": _p(_S, "the fact, one to three sentences, with the reason"),
         "type": _p(_S, "fact | preference | decision | gotcha | command"), "scope": _SCOPE}, ["title", "content"])),
    "Recall": ("read", Recall, _spec("Recall",
        "Search saved notes, code snippets and learned skills by keywords and return the matches in full.",
        {"query": _p(_S, "keywords")}, ["query"])),
    "SaveSnippet": ("read", SaveSnippet, _spec("SaveSnippet",
        "Save reusable code for later: either paste it as `code`, or point at lines of a project file with file_path/start/end (preferred: copied verbatim).",
        {"name": _p(_S, "short name"), "code": _p(_S, "the code"), "file_path": _p(_S, "project file to copy lines from"),
         "start": _p(_I, "first line"), "end": _p(_I, "last line"), "language": _p(_S, "e.g. python, js, sql"),
         "description": _p(_S, "when to use it, one line"), "tags": _p(_S, "comma-separated keywords"), "scope": _SCOPE}, ["name"])),
    "SaveSkill": ("read", SaveSkill, _spec("SaveSkill",
        "Save guidance you worked out (a procedure, a checklist, house rules) as a skill that loads automatically when a later request contains its triggers.",
        {"name": _p(_S, "short name"), "description": _p(_S, "one line: when to use it"), "triggers": _p(_S, "comma-separated words that should load it"),
         "guidance": _p(_S, "the instructions, in markdown, concrete and short"), "scope": _SCOPE}, ["name", "description", "triggers", "guidance"])),
    "Forget": ("read", Forget, _spec("Forget", "Delete a saved note, snippet or skill that is wrong or outdated.",
        {"kind": _p(_S, "memory | snippet | skill"), "name": _p(_S, "its name"), "scope": _p(_S, "project or global, default both")}, ["kind", "name"])),
}


# ------------------------------------------------------------------ suggestions after a run

SUGGEST_SYSTEM = (
    "You decide what from a finished coding session is worth keeping for FUTURE sessions in the same project. "
    "Propose at most 3 items, or none. Only durable, non-obvious knowledge: a decision with its reason, a gotcha that cost time, "
    "a command that works, a convention, or a reusable piece of code. Never propose what the code or git history already shows, "
    "never one-off task details, never secrets. Kinds: 'memory' (name, content, type fact|preference|decision|gotcha|command), "
    "'snippet' (name, description, tags, file and start/end line of reusable code that is shown below), "
    "'skill' (name, description, triggers, content: a short procedure you can state from this session). "
    "Write in the language of the request. An empty list is the right answer for most sessions.")

SUGGEST_SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["kind", "name"], "properties": {
        "kind": {"type": "string", "enum": ["memory", "snippet", "skill"]}, "name": {"type": "string"},
        "content": {"type": "string"}, "type": {"type": "string"}, "description": {"type": "string"},
        "tags": {"type": "string"}, "triggers": {"type": "string"}, "language": {"type": "string"},
        "file": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}}}}}}


async def suggest(client, url: str, helper: str, root: Path, request: str, answer: str, changed: list[str], commands: list[str]) -> list[dict]:
    """Ask the helper model for things worth saving. Everything is validated; snippet code is read from the file, never invented."""
    import json
    root = Path(root).resolve()
    shown, files = [], {}
    for p in changed[:3]:
        try:
            f = (root / p).resolve()
            if not f.is_relative_to(root) or not f.is_file() or f.stat().st_size > 20000:
                continue
            lines = f.read_text().splitlines()[:120]
            files[p] = f
            shown.append(f"--- {p} ---\n" + "\n".join(f"{i + 1}: {l}" for i, l in enumerate(lines)))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
    have = ", ".join(e["name"] for e in entries(root)[:40]) or "nothing"
    user = (f"Request:\n{request[:1200]}\n\nFinal report:\n{answer[:1500]}\n\nCommands run: {'; '.join(commands[-6:]) or 'none'}\n"
            f"Already saved: {have}\n\nChanged files:\n" + ("\n\n".join(shown) or "none"))
    body = {"model": helper, "stream": False, "think": False, "format": SUGGEST_SCHEMA, "options": {"temperature": 0, "num_ctx": 8192},
            "messages": [{"role": "system", "content": SUGGEST_SYSTEM}, {"role": "user", "content": user}]}
    r = await client.post(f"{url}/api/chat", json=body, timeout=90)
    raw = json.loads(r.json()["message"]["content"]).get("items", [])
    seen = {(e["kind"], slug(e["name"])) for e in entries(root)}
    out = []
    for it in raw[:3]:
        try:
            kind = it.get("kind")
            if kind not in KINDS or not str(it.get("name", "")).strip():
                continue
            key = (kind, slug(it["name"]))
            if key in seen:
                continue
            item = {"kind": kind, "name": _one_line(it["name"], 60), "scope": "project", "description": _one_line(it.get("description"), 200)}
            if kind == "snippet":
                f = files.get(str(it.get("file", "")))
                if not f:
                    continue
                lines = f.read_text().splitlines()
                a, b = max(int(it.get("start") or 1), 1), min(int(it.get("end") or len(lines)), len(lines))
                code = "\n".join(lines[a - 1:b]).strip()
                if len(code) < 40 or b - a > 80:
                    continue
                item.update(content=code, language=(it.get("language") or f.suffix.lstrip(".")).lower(), tags=_one_line(it.get("tags"), 100))
            else:
                text = str(it.get("content") or "").strip()
                if len(text) < 12:
                    continue
                item["content"] = text[:LIMITS[kind]]
                if kind == "memory":
                    item["type"] = it.get("type") if it.get("type") in MEMORY_TYPES else "fact"
                else:
                    item["triggers"] = _one_line(it.get("triggers"), 120)
                    if not item["triggers"]:
                        continue
            if SECRET.search(item["content"]):
                continue
            seen.add(key)
            out.append(item)
        except (TypeError, ValueError, OSError):
            continue
    return out


def apply(root: Path, item: dict) -> dict:
    """Store a suggestion or a hand-written entry from the UI."""
    kind, scope = item.get("kind"), item.get("scope") or "project"
    meta = {k: item.get(k) for k in ("type", "description", "language", "tags", "triggers")}
    return save(root, kind, str(item.get("name", "")), item.get("content", ""), scope, **meta)
