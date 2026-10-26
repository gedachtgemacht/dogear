"""Snippet library: proven solutions from runs the user rated as good.

Each entry pairs the problem (what task it solves) with the solution code, so a later request can find it by meaning:
the embedding is computed over both. Code is always read from the project files, never written by the model.
Stored locally in data/library.db (SQLite); search is cosine similarity over qwen3-embedding, with a keyword fallback.
"""
import hashlib
import json
import math
import re
import sqlite3
import time
from pathlib import Path

from .memory import SECRET
from .tools import ToolError, _spec

DATA = Path(__file__).resolve().parent.parent / "data"
DB = DATA / "library.db"
EMBED_MODEL = "qwen3-embedding:0.6b"
REPLACE_AT = 0.90          # cosine similarity above which a new entry replaces the old one
MIN_SCORE = 0.40           # below this a search hit is not shown
MAX_LINES, MIN_LINES, MAX_PER_RUN = 120, 3, 5


def _db() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, problem TEXT NOT NULL, solution TEXT NOT NULL, language TEXT DEFAULT '',
        framework TEXT DEFAULT '', project TEXT DEFAULT '', source TEXT DEFAULT '', created REAL, updated REAL,
        uses INTEGER DEFAULT 1, digest TEXT, embedding TEXT)""")
    for col in ("extra TEXT DEFAULT ''",                                      # bulk text that is not embedded (e.g. the full HTML of a design plan)
                "auto INTEGER DEFAULT 0"):                                    # 1 = saved by the harness from a weak signal, not rated by the user
        try:
            c.execute("ALTER TABLE entries ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass
    return c


def _row(r) -> dict:
    return {"id": r[0], "problem": r[1], "solution": r[2], "language": r[3], "framework": r[4], "project": r[5],
            "source": r[6], "created": r[7], "updated": r[8], "uses": r[9], "auto": bool(r[10])}


COLS = "id, problem, solution, language, framework, project, source, created, updated, uses, auto"


async def embed(client, url: str, texts: list[str]) -> list[list[float]] | None:
    try:
        r = await client.post(f"{url}/api/embed", json={"model": EMBED_MODEL, "input": [t[:3000] for t in texts]}, timeout=60)
        r.raise_for_status()
        e = r.json()["embeddings"]
        return e if len(e) == len(texts) else None
    except Exception:
        return None


def _cos(a: list[float], b: list[float]) -> float:
    d = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / d if d else 0.0


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-zäöüß0-9_]{3,}", s.lower()))


def _text(problem: str, solution: str) -> str:
    return problem.strip() + "\n\n" + solution.strip()[:700]


async def add(client, url: str, item: dict, dedupe: bool = True) -> dict:
    """Store an entry. A near-duplicate (same problem, similar code) is replaced instead of appended."""
    problem, solution = str(item["problem"]).strip(), str(item["solution"]).strip("\n")
    if not problem or not solution:
        raise ValueError("problem and solution are required")
    if SECRET.search(solution) or SECRET.search(problem):
        raise ValueError("looks like it contains a secret")
    digest = hashlib.sha256(solution.encode()).hexdigest()[:16]
    vecs = await embed(client, url, [_text(problem, solution)])
    emb = vecs[0] if vecs else None
    now = time.time()
    db = _db()
    try:
        hit, best = None, 0.0
        for r in (db.execute(f"SELECT {COLS}, embedding, digest FROM entries WHERE language = ?", (item.get("language", ""),)) if dedupe else []):
            if r[-1] == digest:
                hit, best = r[0], 1.0
                break
            if emb and r[-2]:
                sim = _cos(emb, json.loads(r[-2]))
                if sim > best:
                    hit, best = r[0], sim
            elif not emb:
                inter = len(_words(problem) & _words(r[1])) / max(1, len(_words(problem) | _words(r[1])))
                if inter > best:
                    hit, best = r[0], inter + 0.2
        if hit and best >= (REPLACE_AT if emb else 0.95):
            db.execute("UPDATE entries SET problem=?, solution=?, framework=?, project=?, source=?, updated=?, uses=uses+1, digest=?, embedding=?, extra=?, auto=MIN(auto, ?) WHERE id=?",
                       (problem, solution, item.get("framework", ""), item.get("project", ""), item.get("source", ""), now, digest,
                        json.dumps(emb) if emb else None, item.get("extra", ""), int(bool(item.get("auto"))), hit))
            db.commit()
            return {"id": hit, "replaced": True}
        cur = db.execute("INSERT INTO entries (problem, solution, language, framework, project, source, created, updated, digest, embedding, extra, auto) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (problem, solution, item.get("language", ""), item.get("framework", ""), item.get("project", ""),
                          item.get("source", ""), now, now, digest, json.dumps(emb) if emb else None, item.get("extra", ""),
                          int(bool(item.get("auto")))))
        db.commit()
        return {"id": cur.lastrowid, "replaced": False}
    finally:
        db.close()


async def search(client, url: str, query: str, k: int = 3, language: str = "") -> list[dict]:
    query = query.strip()
    if not query:
        return []
    db = _db()
    try:
        rows = db.execute(f"SELECT {COLS}, extra, embedding FROM entries" + (" WHERE language = ?" if language else ""),
                          (language,) if language else ()).fetchall()
    finally:
        db.close()
    if not rows:
        return []
    qv = await embed(client, url, [query])
    out = []
    for r in rows:
        if qv and r[-1]:
            sc = _cos(qv[0], json.loads(r[-1]))
        else:
            a, b = _words(query), _words(r[1] + " " + r[3] + " " + r[4])
            sc = len(a & b) / max(1, len(a)) * 0.8
        if sc >= MIN_SCORE:
            out.append({**_row(r[:-2]), "extra": r[-2] or "", "score": round(sc, 3)})
    out.sort(key=lambda e: -e["score"])
    return out[:k]


def get(entry_id: int, full: bool = False) -> dict | None:
    """One entry by id; with full=True the bulk text (the page of a design plan) comes along."""
    db = _db()
    try:
        r = db.execute(f"SELECT {COLS}{', extra' if full else ''} FROM entries WHERE id = ?", (int(entry_id),)).fetchone()
    finally:
        db.close()
    if not r:
        return None
    d = _row(r[:11])
    if full:
        d["extra"] = r[11] or ""
    return d


def entries(limit: int = 200) -> list[dict]:
    db = _db()
    try:
        return [_row(r) for r in db.execute(f"SELECT {COLS} FROM entries ORDER BY updated DESC LIMIT ?", (limit,))]
    finally:
        db.close()


def delete(entry_id: int) -> bool:
    db = _db()
    try:
        n = db.execute("DELETE FROM entries WHERE id = ?", (entry_id,)).rowcount
        db.commit()
        return n > 0
    finally:
        db.close()


def delete_many(ids: list[int], only_auto: bool = False) -> int:
    """Remove entries; with only_auto an entry the user has since confirmed by rating is kept."""
    ids = [int(i) for i in ids]
    if not ids:
        return 0
    db = _db()
    try:
        q = ",".join("?" * len(ids))
        n = db.execute(f"DELETE FROM entries WHERE id IN ({q})" + (" AND auto = 1" if only_auto else ""), ids).rowcount
        db.commit()
        return n
    finally:
        db.close()


def confirm(ids: list[int]) -> None:
    """The user rated the run as good: entries saved automatically become ordinary ones."""
    ids = [int(i) for i in ids]
    if ids:
        db = _db()
        try:
            db.execute(f"UPDATE entries SET auto = 0 WHERE id IN ({','.join('?' * len(ids))})", ids)
            db.commit()
        finally:
            db.close()


async def learn(client, url: str, model: str, root: Path, request: str, answer: str, changed: list[str], auto: bool = False) -> list[dict]:
    """Extract snippets from a finished run and store them. Returns what was saved."""
    saved = []
    for it in await extract(client, url, model, root, request, answer, changed):
        if auto and re.search(r"(^|/)(test_[^/]*|[^/]*_test\.\w+|[^/]*\.test\.\w+|tests?/[^/]*)$", it["source"].split(":")[0]):
            continue                                         # tests are not worth keeping without a rating
        r = await add(client, url, {**it, "auto": auto})
        saved.append({"id": r["id"], "problem": it["problem"], "language": it["language"], "replaced": r["replaced"]})
    return saved


def format_hits(hits: list[dict], full: bool = False) -> str:
    out = []
    for h in hits:
        meta = ", ".join(x for x in (h["language"], h["framework"], h["project"], time.strftime("%Y-%m-%d", time.localtime(h["updated"]))) if x)
        if h["language"] == "design-plan":                     # a plan is prose; the full page is only shown on request
            block = f"[{h['id']}] Brief: {h['problem']}  ({meta})\n{h['solution']}"
            if full and h.get("extra"):
                block += "\n```html\n" + h["extra"][:14000] + "\n```"
        else:
            block = f"[{h['id']}] {h['problem']}  ({meta})\n```{h['language']}\n{h['solution']}\n```"
        out.append(block)
    return "\n\n".join(out)


# ------------------------------------------------------------------ extraction after a run rated as good

EXTRACT_SYSTEM = (
    "A coding task was completed and the user rated it as good. Nominate up to 5 pieces of code from the changed files that are worth "
    "keeping for FUTURE tasks: reusable functions, patterns, configuration, a working way to do something non-obvious. For each give:\n"
    "problem: one or two sentences saying which task this solves, written so that a future request can be matched to it (what it does and for "
    "whom, not how it is built); language; framework (or empty); file, start and end line of the code, using the line numbers shown.\n"
    "Skip glue code, boilerplate, trivial tests, one-off content, anything with secrets. Prefer whole self-contained functions or blocks. "
    "An empty list is a fine answer. Write the problem in the language of the user's request.")

EXTRACT_SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["problem", "file", "start", "end"], "properties": {
        "problem": {"type": "string"}, "language": {"type": "string"}, "framework": {"type": "string"},
        "file": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}}}}}}


async def extract(client, url: str, model: str, root: Path, request: str, answer: str, changed: list[str]) -> list[dict]:
    """Nominate snippets with the model; the code itself is read from the files (verbatim, never generated)."""
    root = Path(root).resolve()
    files, shown = {}, []
    for p in changed[:6]:
        try:
            f = (root / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
            if not f.is_relative_to(root) or not f.is_file() or f.stat().st_size > 60000:
                continue
            lines = f.read_text().splitlines()[:250]
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        rel = str(f.relative_to(root))
        files[rel] = f
        shown.append(f"--- {rel} ---\n" + "\n".join(f"{i + 1}: {l}" for i, l in enumerate(lines)))
    if not files:
        return []
    user = f"Request:\n{request[:1500]}\n\nFinal report:\n{answer[:1200]}\n\nChanged files:\n" + "\n\n".join(shown)
    body = {"model": model, "stream": False, "think": False, "format": EXTRACT_SCHEMA, "keep_alive": "30m",
            "options": {"temperature": 0, "num_ctx": 16384},
            "messages": [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": user}]}
    r = await client.post(f"{url}/api/chat", json=body, timeout=240)
    items = json.loads(r.json()["message"]["content"]).get("items", [])
    out, seen = [], set()
    for it in items[:MAX_PER_RUN + 3]:
        try:
            f = files.get(str(it.get("file", "")))
            if not f:
                continue
            lines = f.read_text().splitlines()
            a, b = max(int(it.get("start") or 1), 1), min(int(it.get("end") or len(lines)), len(lines))
            code = "\n".join(lines[a - 1:b]).strip("\n")
            if b - a + 1 < MIN_LINES or b - a + 1 > MAX_LINES or SECRET.search(code):
                continue
            problem = " ".join(str(it.get("problem", "")).split())[:400]
            if len(problem) < 12 or code in seen:
                continue
            seen.add(code)
            out.append({"problem": problem, "solution": code, "language": (it.get("language") or f.suffix.lstrip(".")).lower()[:20],
                        "framework": " ".join(str(it.get("framework", "")).split())[:40], "project": root.name,
                        "source": f"{f.relative_to(root)}:{a}-{b}"})
        except (TypeError, ValueError, OSError):
            continue
    return out[:MAX_PER_RUN]


# ------------------------------------------------------------------ the model's tool

async def library_search(ctx, query="", limit=3, full=False):
    if not getattr(ctx, "library", None):
        raise ToolError("The library is not available here")
    full = full in (True, "true", "True", 1, "1")
    hits = await ctx.library(str(query), max(1, min(int(limit or 3), 6)))
    if not hits:
        return f"No proven solution in the library matches {query!r}."
    return ("Proven solutions and reference designs (reuse code where it fits; use design plans for direction, do not copy them):\n\n"
            + format_hits(hits, full)[:16000])


TOOLS = {
    "library_search": ("read", library_search, _spec(
        "library_search",
        "Search the library of proven solutions: code from earlier runs that the user rated as good, found by what the task is about. "
        "Use it in the planning phase and before you write something that may already exist.",
        {"query": {"type": "string", "description": "what you need to build, in plain words"},
         "limit": {"type": "integer", "description": "results, default 3"},
         "full": {"type": "boolean", "description": "for design plans: also return the complete HTML of the reference page"}}, ["query"])),
}
