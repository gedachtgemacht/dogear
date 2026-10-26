"""Ultra: a deterministic multi-agent orchestrator on local Ollama models.

Primitives: agent (one worker), parallel, pipeline, an event emitter.
Patterns compose them: review, research, design, audit. Code decides the flow; models only fill in steps.
Workers never raise: a failed or timed-out worker yields None, the run goes on and the drop is logged."""
import asyncio
import contextvars
import difflib
import inspect
import json
import os
import re
import time
from pathlib import Path

import httpx

from . import llm

READONLY = ("Read", "LS", "Glob", "Grep", "WebSearch", "WebFetch")
FILE_TOOLS = ("Read", "LS", "Glob", "Grep")
AGENT_TIMEOUT = 300       # wall clock per worker, seconds
TEMPERATURE = 0.2
NUM_PREDICT = 4096        # token cap per model turn, a guard against runaway generations
HELPER_CTX = 16384
TOOL_OUT = 6000
MAX_FILES, MAX_FILE_BYTES, EMBED_CHARS = 60, 200_000, 36_000
MAX_PER_FINDER, MAX_VERIFY, MAX_AREAS, MAX_CLAIMS = 8, 12, 6, 10
SEVERITY = {"high": 0, "medium": 1, "low": 2}
CUT_MARK = "[output cut off at the token cap]"

RULES = ("Rules: report only what you verified in the files; cite file:line for every claim; "
         "never invent files, line numbers, APIs or URLs; if you could not verify something, leave it out or say so. "
         "Your tools are read-only. Be concise.")

_depth: contextvars.ContextVar[int] = contextvars.ContextVar("ultra_depth", default=0)


# ------------------------------------------------------------------ small helpers

def validate(value, schema: dict, path: str = "$") -> str:
    """Empty string when value fits the JSON-schema subset used here (type, enum, required, properties, items)."""
    t = schema.get("type")
    py = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
    if t == "integer":
        good = isinstance(value, int) and not isinstance(value, bool)
    elif t == "number":
        good = isinstance(value, (int, float)) and not isinstance(value, bool)
    else:
        good = t not in py or isinstance(value, py[t])
    if not good:
        return f"{path}: expected {t}, got {type(value).__name__}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: must be one of {schema['enum']}"
    if t == "object":
        for k in schema.get("required", []):
            if k not in value:
                return f"{path}: missing key {k!r}"
        for k, sub in schema.get("properties", {}).items():
            if k in value and (e := validate(value[k], sub, f"{path}.{k}")):
                return e
    if t == "array" and "items" in schema:
        for i, v in enumerate(value):
            if e := validate(v, schema["items"], f"{path}[{i}]"):
                return e
    return ""


def similarity(a: str, b: str) -> float:
    """Title similarity in 0..1: the better of character ratio and word overlap."""
    a, b = a.lower().strip(), b.lower().strip()
    wa, wb = set(re.findall(r"[a-z0-9_]{3,}", a)), set(re.findall(r"[a-z0-9_]{3,}", b))
    jac = len(wa & wb) / len(wa | wb) if wa | wb else 0.0
    return max(difflib.SequenceMatcher(None, a, b).ratio(), jac)


def dedupe(findings: list[dict]) -> list[dict]:
    """Merge findings on the same file and nearby line with near-identical titles; the highest severity survives.
    Different defects on one line must stay apart, so the bar is high and an empty title never merges."""
    out: list[dict] = []
    for f in sorted(findings, key=lambda x: SEVERITY.get(x["severity"], 3)):
        for g in out:
            near = abs(g["line"] - f["line"])
            if (g["file"] == f["file"] and near <= 3 and g["title"].strip() and f["title"].strip()
                    and similarity(g["title"], f["title"]) >= (0.6 if near == 0 else 0.7)):
                g["dimensions"] = sorted(set(g["dimensions"]) | set(f["dimensions"]))
                break
        else:
            out.append(dict(f, dimensions=list(f["dimensions"])))
    return out


def _text(v) -> str:
    """Tool arguments from small models: a list for a comma separated string, null for empty."""
    if v is None:
        return ""
    return ", ".join(str(x) for x in v) if isinstance(v, (list, tuple, set)) else str(v)


def parse_where(where: str) -> tuple[str, int] | None:
    """(path, line) from 'src/a.py:12', 'a.py line 12', 'a.py#L12', '**a.py:12**', 'File: my file.py:12' and the like."""
    w = re.sub(r"[`*'\"]", "", where or "").strip()
    w = re.sub(r"^(?:file|path|in|at)\s*:?\s+", "", w, flags=re.I)
    m = re.match(r"(.+?)\s*(?:[:#,(]|\s)\s*(?:lines?\b\s*:?\s*)?L?(\d+)(?!\w|\.\w)", w, re.I)
    return (m.group(1).strip().removeprefix("./"), int(m.group(2))) if m else None


class _Tuned:
    """Facade over the httpx client: llm.stream builds the request, this sets temperature, token cap and `format`,
    in Ollama's shape or, through `tune_remote`, in the OpenAI shape a remote provider expects."""

    def __init__(self, client, fmt=None):
        self.client, self.fmt = client, fmt

    def stream(self, method, url, json=None, timeout=None, **kw):
        body = dict(json)
        if url.endswith("/api/chat"):
            body["options"] = {**body.get("options", {}), "temperature": TEMPERATURE, "num_predict": NUM_PREDICT}
            if self.fmt:
                body["format"] = self.fmt
        return self.client.stream(method, url, json=body, timeout=timeout, **kw)

    def tune_remote(self, body: dict):
        body["temperature"], body["max_tokens"] = TEMPERATURE, NUM_PREDICT
        if self.fmt:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": self.fmt}}


FINDINGS_SCHEMA = {"type": "object", "required": ["findings"], "properties": {"findings": {"type": "array", "items": {
    "type": "object", "required": ["title", "where", "severity", "evidence", "fix"],
    "properties": {"title": {"type": "string"}, "where": {"type": "string"},
                   "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                   "evidence": {"type": "string"}, "fix": {"type": "string"}}}}}}
VERDICT_SCHEMA = {"type": "object", "required": ["verdict", "reason"], "properties": {
    "verdict": {"type": "string", "enum": ["confirmed", "refuted"]}, "reason": {"type": "string"}, "trace": {"type": "string"}}}

DIMENSIONS = {
    "correctness": ("wrong results: off-by-one, bad conditions, unhandled None or empty input, wrong types, crashes, resource leaks",
                    ("bug", "correct", "wrong", "crash", "logic", "defect", "broken")),
    "security": ("injection (shell, SQL, path), unvalidated input reaching a dangerous call, secrets in code, unsafe deserialization, missing access checks",
                 ("secur", "inject", "vulnerab", "exploit", "unsafe", "secret", "sanitiz", "auth")),
    "performance": ("avoidable quadratic work, repeated I/O in loops, needless copies, blocking calls in async code, unbounded memory",
                    ("perform", "slow", "speed", "memory", "optimi", "latency", "scal")),
    "readability": ("code a maintainer would misread: misleading names, dead code, hidden side effects, duplicated logic",
                    ("readab", "clean", "naming", "style", "maintain", "refactor", "complex")),
    "tests": ("missing or ineffective tests for the risky paths, assertions that cannot fail, untested error handling",
              ("test", "coverage", "assert")),
}
LENSES = (
    ("reproduce", "Your lens: does it reproduce. Open the cited code, take a concrete input and trace what the code actually does. "
                  "If the claim misreads the code or the described failure does not happen, refute it."),
    ("impact", "Your lens: is it really a problem. Assume the code is described correctly. Decide whether it is a real defect that matters in use, "
               "or intended behaviour, handled elsewhere, unreachable, or only a style preference. If it is not a real problem, refute it."),
)


class Ultra:
    def __init__(self, client: httpx.AsyncClient, model: str, root: Path, emit=None,
                 helper_model: str = "qwen3.5:4b", concurrency: int = 3, num_ctx: int = 32768):
        self.client, self.model, self.root = client, model, Path(root).resolve()
        self.emit, self.helper_model, self.num_ctx = emit, helper_model, num_ctx
        self.concurrency = max(1, int(concurrency))
        self.sem = asyncio.Semaphore(self.concurrency)    # model calls in flight
        self.psem = asyncio.Semaphore(self.concurrency)   # top-level parallel thunks in flight
        self.agent_timeout = AGENT_TIMEOUT
        self.phase = ""
        self._cache: dict[str, list[str]] = {}
        self._reset()

    def _reset(self):
        self.agents = self.failed = self.running = self.peak_agents = self.thunks = self.peak_thunks = 0
        self.notes: list[str] = []
        self.last_why = ""

    # -- events -------------------------------------------------------------------
    async def _ev(self, event: str, **kw):
        if not self.emit:
            return
        try:
            r = self.emit({"type": "ultra", "event": event, **kw})
            if inspect.isawaitable(r):
                await r
        except Exception:
            pass   # a broken UI must not stop the run

    async def _note(self, text: str):
        self.notes.append(text)
        await self._ev("log", phase=self.phase, detail=text)

    async def _phase(self, name: str, state: str = "running", detail: str = ""):
        if state == "running":
            self.phase = name
        await self._ev("phase", phase=name, state=state, detail=detail)

    # -- primitives ---------------------------------------------------------------
    async def agent(self, prompt: str, schema: dict | None = None, tools=True, max_steps: int = 10, label: str = "",
                    *, model: str | None = None, phase: str | None = None):
        """One worker. Returns text, or the parsed object when schema is given; None when it failed or timed out.
        tools: True (all read-only tools), False, or a tuple of tool names."""
        self.agents += 1
        base = {"phase": phase or self.phase, "id": f"a{self.agents}", "label": label or f"agent {self.agents}"}
        use = model or self.model
        await self._ev("agent", state="queued", **base)
        try:
            async with self.sem:
                self.running += 1
                self.peak_agents = max(self.peak_agents, self.running)
                await self._ev("agent", state="running", **base)
                try:
                    res = await asyncio.wait_for(self._work(prompt, schema, tools, max_steps, use), self.agent_timeout)
                finally:
                    self.running -= 1
        except asyncio.TimeoutError:
            why = f"timed out after {self.agent_timeout:g} s"
        except Exception as e:
            why = f"{type(e).__name__}: {e}"[:200]
        else:
            await self._ev("agent", state="done", **base)
            if isinstance(res, str) and res.endswith(CUT_MARK):
                await self._note(f"worker {base['label']!r}: output cut off at the {NUM_PREDICT} token cap")
            return res
        self.failed += 1
        self.last_why = why
        await self._ev("agent", state="failed", detail=why, **base)
        await self._note(f"worker {base['label']!r} dropped: {why}")
        return None

    async def parallel(self, thunks: list) -> list:
        """Run zero-argument callables (coroutine functions) together. Results keep their order, failures are None.
        Top-level thunks are capped by the concurrency setting; model calls are capped by it at any depth."""
        depth = _depth.get()

        async def guard(th):
            try:
                r = th()
                return await r if inspect.isawaitable(r) else r
            except Exception as e:
                await self._note(f"task dropped: {type(e).__name__}: {e}"[:240])
                return None

        async def one(th):
            tok = _depth.set(depth + 1)
            try:
                if depth:
                    return await guard(th)
                async with self.psem:
                    self.thunks += 1
                    self.peak_thunks = max(self.peak_thunks, self.thunks)
                    try:
                        return await guard(th)
                    finally:
                        self.thunks -= 1
            finally:
                _depth.reset(tok)

        return list(await asyncio.gather(*(one(t) for t in thunks)))

    async def pipeline(self, items: list, *stages) -> list:
        """Every item flows through the stages in order (each stage gets the previous result); items run in parallel.
        An item whose stage returns None or raises ends there as None."""
        async def flow(item):
            val = item
            for i, st in enumerate(stages, 1):
                r = st(val)
                val = await r if inspect.isawaitable(r) else r
                if val is None:
                    await self._note(f"pipeline item dropped at stage {i}")
                    return None
            return val

        return await self.parallel([lambda it=it: flow(it) for it in items])

    # -- the worker loop ----------------------------------------------------------
    def _ctx_for(self, model: str) -> int:
        return min(self.num_ctx, HELPER_CTX) if model == self.helper_model and model != self.model else self.num_ctx

    async def _turn_full(self, model, msgs, specs, fmt=None):
        """One model turn: (content, tool calls, cut). cut is True when the token cap ended the reply."""
        content, calls, cut = "", [], False
        async for kind, p in llm.stream(_Tuned(self.client, fmt), model, msgs, specs or None, False, self._ctx_for(model)):
            if kind == "content":
                content += p
            elif kind == "call":
                calls.append(p)
            elif kind == "done":
                cut = (p or {}).get("done_reason") == "length"
        return content, calls, cut

    async def _turn(self, model, msgs, specs, fmt=None):
        content, calls, _ = await self._turn_full(model, msgs, specs, fmt)
        return content, calls

    @staticmethod
    def _final(content: str, cut: bool) -> str:
        text = content.strip()
        if not text:
            raise ValueError("returned nothing")
        return text + (f"\n\n{CUT_MARK}" if cut else "")

    async def _work(self, prompt, schema, tool_sel, max_steps, model):
        names = list(READONLY if tool_sel is True else tool_sel or ())
        system = f"You are a worker in a multi-agent pipeline. Project directory: {self.root}\n{RULES}"
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        if names:
            ctx, specs = tools.Ctx(self.root), [tools.TOOLS[n][2] for n in names]
            for _ in range(max(1, int(max_steps))):
                content, calls, cut = await self._turn_full(model, msgs, specs)
                msgs.append({"role": "assistant", "content": content, **({"tool_calls": calls} if calls else {})})
                if not calls:
                    break
                for c in calls:
                    out = await self._call(ctx, names, c)
                    msgs.append({"role": "tool", "tool_name": c["function"]["name"], "content": out})
            else:
                msgs.append({"role": "user", "content": "Step limit reached. Reply now with what you have verified so far."})
                content, _, cut = await self._turn_full(model, msgs, None)
                msgs.append({"role": "assistant", "content": content})
            if not schema:
                return self._final(content, cut)
            msgs.append({"role": "user", "content": "Now return your final result as JSON only. Include only what you verified."})
        elif not schema:
            content, _, cut = await self._turn_full(model, msgs, None)
            return self._final(content, cut)
        return await self._structured(msgs, schema, model)

    async def _call(self, ctx, names, c) -> str:
        name, args = c["function"]["name"], c["function"].get("arguments") or {}
        try:
            if isinstance(args, str):
                args = json.loads(args or "{}")
            if name not in names:
                raise tools.ToolError(f"{name} is not available to this worker")
            if name == "Glob":
                self._check_glob(args)
            out = tools.TOOLS[name][1](ctx, **args)
            if inspect.isawaitable(out):
                out = await out
            if name == "Glob":
                out = self._inside_only(ctx, str(out))
        except Exception as e:
            out = f"Error: {e}"
        out = str(out)
        if len(out) > TOOL_OUT:   # keep head and tail (Read's "[showing lines ...]" note sits at the end)
            out = tools._clip(out, TOOL_OUT) + "\n[tool output shortened; use offset/limit or a narrower pattern to see the rest]"
        return out

    @staticmethod
    def _check_glob(args: dict):
        """tools.Glob lists whatever the pattern reaches, so keep patterns inside the project."""
        pat = str(args.get("pattern", ""))
        if os.path.isabs(pat) or pat.startswith("~") or ".." in re.split(r"[\\/]", pat):
            raise tools.ToolError("Glob patterns must be relative to the project and must not contain '..'")

    @staticmethod
    def _inside_only(ctx, text: str) -> str:
        """Drop Glob hits that resolve outside the project (symlinked directories)."""
        keep = [l for l in text.splitlines() if (ctx.root / l).resolve().is_relative_to(ctx.root)]
        return "\n".join(keep) or "No files matched"

    async def _structured(self, msgs, schema, model):
        """Ollama structured output via `format`; validated, one retry with the error fed back."""
        msgs = list(msgs) + [{"role": "user", "content": "Reply with JSON only, matching this schema:\n" + json.dumps(schema)}]
        err = ""
        for _ in range(2):
            text, _ = await self._turn(model, msgs, None, fmt=schema)
            try:
                val = json.loads(text)
                err = validate(val, schema)
            except ValueError as e:
                err = f"not valid JSON ({e})"
            if not err:
                return val
            msgs += [{"role": "assistant", "content": text},
                     {"role": "user", "content": f"That reply was rejected: {err}. Reply again with valid JSON only."}]
        raise ValueError(f"structured output invalid after retry: {err}")

    # -- project files ------------------------------------------------------------
    def _lines(self, rel: str) -> list[str]:
        if rel not in self._cache:
            p = tools.Ctx(self.root).path(rel)   # the same boundary the Read tool enforces
            self._cache[rel] = p.read_text("utf-8", "replace").splitlines()
        return self._cache[rel]

    def _scan(self, scope: str) -> tuple[list[str], list[str]]:
        """Blocking part of _scope_files, run in a thread: (files in scope, notes about what was left out)."""
        ctx, found, notes = tools.Ctx(self.root), {}, []
        skipped = {"big": 0, "binary": 0, "symlink": 0}

        def show(p) -> str:
            try:
                return ctx.rel(Path(p))
            except ValueError:
                return str(p)

        def add(p: Path) -> int:
            if p.is_symlink() or not p.resolve().is_relative_to(ctx.root):
                skipped["symlink"] += 1   # a link can point anywhere; workers must not read through it
                return 0
            rel = ctx.rel(p)
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    skipped["big"] += 1
                    return 0
                with p.open("rb") as fh:
                    head = fh.read(4096)
            except OSError as e:
                notes.append(f"scope: skipped {rel!r}: {e.strerror or e}")
                return 0
            if b"\0" in head:
                skipped["binary"] += 1
                return 0
            found[rel] = None
            return 1

        def walk(d: Path) -> int:
            n = 0
            bad = lambda e: notes.append(f"scope: cannot read directory {show(e.filename)!r}: {e.strerror or e}")
            for dp, dns, fns in os.walk(d, onerror=bad):
                dns[:] = sorted(x for x in dns if x not in tools.SKIP_DIRS and not x.startswith("."))   # prune before descending
                n += sum(add(Path(dp) / f) for f in sorted(fns))
            return n

        def take(h: Path, explicit: bool) -> int:
            parts = Path(show(h)).parts
            if not explicit and (".." in parts or set(parts) & tools.SKIP_DIRS or any(x.startswith(".") for x in parts)):
                return 0
            return walk(h) if h.is_dir() else add(h) if h.is_file() else 0

        glob_ch = lambda t: any(ch in t for ch in "*?[")
        literal = lambda t: (ctx.root / t).exists()
        toks: list[str] = []
        for piece in (x.strip() for x in re.split(r"[,\n]+", scope or "")):
            if piece:   # a piece that names an existing path stays whole (spaces, brackets); otherwise split on whitespace
                toks += [piece] if literal(piece) or not re.search(r"\s", piece) else piece.split()
        for tok in toks or ["."]:
            try:
                if glob_ch(tok) and not literal(tok):
                    hits, explicit = sorted(ctx.root.glob(tok)), False
                    if not hits:
                        notes.append(f"scope item {tok!r}: no file matches this pattern")
                        continue
                else:
                    h = ctx.path(tok)
                    if not h.exists():
                        notes.append(f"scope item {tok!r}: no such file or directory")
                        continue
                    hits, explicit = [h], True
                if not explicit and any(".." in Path(show(h)).parts for h in hits):
                    notes.append(f"scope item {tok!r}: outside the project")
                    continue
                if not sum(take(h, explicit) for h in hits):
                    notes.append(f"scope item {tok!r}: no readable text files "
                                 "(hidden and ignored directories are skipped unless named exactly)")
            except Exception as e:
                notes.append(f"scope item {tok!r} skipped: {e}")
        files = sorted(found)
        if skipped["big"] or skipped["binary"] or skipped["symlink"]:
            notes.append(f"scope: skipped {skipped['big']} files over {MAX_FILE_BYTES // 1000} KB, {skipped['binary']} binary files "
                         f"and {skipped['symlink']} symlinks")
        if len(files) > MAX_FILES:
            notes.append(f"scope: {len(files)} files, only the first {MAX_FILES} are reviewed (dropped: {', '.join(files[MAX_FILES:][:8])}"
                         f"{' ...' if len(files) - MAX_FILES > 8 else ''})")
            files = files[:MAX_FILES]
        return files, notes

    async def _scope_files(self, scope: str) -> list[str]:
        files, notes = await asyncio.to_thread(self._scan, scope)   # a big tree must not stall the host's event loop
        for n in notes:
            await self._note(n)
        return files

    def _numbered(self, rel: str, a: int = 1, b: int = 0) -> str:
        lines = self._lines(rel)
        b = b or len(lines)
        return "\n".join(f"{i:>4}\t{l[:300]}" for i, l in enumerate(lines[a - 1:b], a))

    def _source(self, files: list[str]) -> str | None:
        """Numbered source of all files when it fits the prompt budget, else None (workers then read on demand)."""
        if sum(len("\n".join(self._lines(f))) for f in files) > EMBED_CHARS:
            return None
        return "\n\n".join(f"=== {f} ({len(self._lines(f))} lines) ===\n{self._numbered(f)}" for f in files)

    def _view(self, rel: str, line: int) -> str:
        lines = self._lines(rel)
        if len(lines) <= 300 and sum(map(len, lines)) <= 14000:
            return f"=== {rel} ({len(lines)} lines) ===\n{self._numbered(rel)}"
        a, b = max(1, line - 70), min(len(lines), line + 70)
        return f"=== {rel}, lines {a}-{b} of {len(lines)} ===\n{self._numbered(rel, a, b)}"

    def _tree(self, files: list[str]) -> str:
        return "\n".join(f"{f} ({len(self._lines(f))} lines)" for f in files)

    # -- finding workers shared by review and audit ------------------------------------
    def _finder_prompt(self, focus: str, task: str, files: list[str]) -> str:
        src = self._source(files)
        body = (f"Source files (line numbers on the left):\n\n{src}" if src else
                f"Files in scope:\n{self._tree(files)}\n\nRead the files you need with the Read tool before you report anything.")
        return (f"Find real defects. Focus: {focus}\nTask from the user: {task or '(none given)'}\n\n{body}\n\n"
                "For each defect give: title (short), where (path:line, one line number inside the file, the line where the defect is), "
                "severity (high, medium or low), evidence (quote the code and say why it is wrong), fix (concrete). "
                "Report only defects you verified in the code above. Do not report style preferences as high or medium. "
                "A pattern that looks suspicious but is correct is not a defect. If you find nothing, return an empty list.")

    def _locate(self, cand: str, files: list[str]) -> tuple[str | None, str]:
        """Map a path a worker cited to one file in scope: (file, "") or (None, reason)."""
        root = str(self.root)
        if cand.startswith("/"):
            if cand != root and not cand.startswith(root + "/"):
                return None, "outside the project"
            cand = cand[len(root):].lstrip("/")
        elif cand.startswith(self.root.name + "/") and cand not in files:
            cand = cand[len(self.root.name) + 1:]
        if cand in files:
            return cand, ""
        hits = [f for f in files if f.endswith("/" + cand)] or [f for f in files if Path(f).name == cand]
        if len(hits) == 1:
            return hits[0], ""
        if hits:
            return None, f"ambiguous: matches {', '.join(hits[:5])}; give the full path"
        return None, "no such file in the scope"

    async def _ground(self, raw, files: list[str], dim: str, who: str) -> list[dict]:
        """Turn a finder's JSON into finding dicts; drop what does not point at a real file and line."""
        out, items = [], (raw or {}).get("findings", [])
        if len(items) > MAX_PER_FINDER:
            await self._note(f"{who}: kept the first {MAX_PER_FINDER} of {len(items)} findings, dropped: "
                             + "; ".join(i["title"][:50] for i in items[MAX_PER_FINDER:]))
            items = items[:MAX_PER_FINDER]
        for it in items:
            loc = parse_where(it["where"])
            rel, why = self._locate(loc[0], files) if loc else (None, "no path:line found")
            if rel and not 1 <= loc[1] <= len(self._lines(rel)):
                rel, why = None, f"{rel} has {len(self._lines(rel))} lines"
            if not rel:
                await self._note(f"{who}: dropped finding {it['title'][:60]!r}: location {it['where']!r}: {why}")
                continue
            out.append({"title": it["title"].strip(), "where": f"{rel}:{loc[1]}", "file": rel, "line": loc[1],
                        "severity": it["severity"], "evidence": it["evidence"].strip(), "fix": it["fix"].strip(), "dimensions": [dim]})
        return out

    async def _skeptic(self, f: dict, lens: tuple[str, str], label: str, phase: str | None = None):
        prompt = ("A reviewer claims this defect. Your job is to REFUTE it if you honestly can; confirm only if it survives your attempt.\n\n"
                  f"Title: {f['title']}\nWhere: {f['where']}\nSeverity: {f['severity']}\nEvidence: {f['evidence']}\nProposed fix: {f['fix']}\n\n"
                  f"{lens[1]}\n\n{self._view(f['file'], f['line'])}\n\n"
                  "Answer with verdict (confirmed or refuted), reason (cite file:line), trace (the concrete input and what the code does).")
        return await self.agent(prompt, VERDICT_SCHEMA, FILE_TOOLS, 6, label, phase=phase)

    @staticmethod
    def _decide(votes: list[dict | None]) -> tuple[str, list[str]]:
        """confirmed: all valid votes confirm and there are two. rejected: refuted by every valid vote.
        disputed: split, or only one vote came back and it confirmed."""
        valid = [v for v in votes if v]
        why = [f"{v['verdict']}: {v['reason'].strip()}"[:300] for v in valid]
        yes = sum(v["verdict"] == "confirmed" for v in valid)
        if len(valid) == 2 and yes == 2:
            return "confirmed", why
        if valid and yes == 0:
            return "rejected", why
        return "disputed", why or ["no skeptic answered"]

    async def _verify(self, f: dict, phase: str, n: int) -> dict:
        votes = await self.parallel([lambda l=l: self._skeptic(f, l, f"skeptic:{l[0]} #{n}", phase) for l in LENSES])
        status, why = self._decide(votes)
        return dict(f, status=status, verification=why)

    # -- patterns -----------------------------------------------------------------
    async def review(self, task: str, scope: str):
        files = await self._scope_files(scope)
        if not files:
            return "# Review\n\nNo readable files in scope.\n", []
        low = task.lower()
        first = {d: min((low.find(k) for k in kw if k in low), default=-1) for d, (_, kw) in DIMENSIONS.items()}
        dims = sorted((d for d in first if first[d] >= 0), key=first.get)
        has_tests = any(re.search(r"(^|/)(test_|tests?/)|_test\.", f) for f in files)
        for d in ("correctness", "security", "performance", "readability", "tests"):
            if len(dims) >= 3 or (d == "tests" and not has_tests):
                continue
            if d not in dims:
                dims.append(d)
        dims = dims[:5]
        embedded = self._source(files) is not None
        await self._ev("log", phase="find", detail=f"{len(files)} files, dimensions: {', '.join(dims)}, "
                       f"source {'embedded in the prompt' if embedded else 'read on demand'}")

        await self._phase("find")
        raw = await self.parallel([lambda d=d: self.agent(
            self._finder_prompt(f"{d}: {DIMENSIONS[d][0]}", task, files), FINDINGS_SCHEMA, FILE_TOOLS, 8, f"find:{d}", phase="find") for d in dims])
        found = []
        for d, r in zip(dims, raw):
            found += await self._ground(r, files, d, f"finder {d}") if r else []
        await self._phase("find", "done", f"{len(found)} findings")

        merged = dedupe(found)
        if len(merged) != len(found):
            await self._note(f"dedupe: {len(found)} findings became {len(merged)}")
        merged.sort(key=lambda x: (SEVERITY[x["severity"]], -len(x["dimensions"])))
        check, rest = merged[:MAX_VERIFY], merged[MAX_VERIFY:]
        if rest:
            await self._note(f"verification cap: {len(rest)} lower-ranked findings not verified: " + "; ".join(r["title"][:50] for r in rest))
        await self._phase("verify")
        done = await self.parallel([lambda f=f, i=i: self._verify(f, "verify", i) for i, f in enumerate(check, 1)])
        results = [d or dict(f, status="disputed", verification=["verification failed"]) for d, f in zip(done, check)]
        results += [dict(f, status="unverified", verification=["not checked (verification cap)"]) for f in rest]
        await self._phase("verify", "done", f"{sum(r['status'] == 'confirmed' for r in results)} confirmed")

        await self._phase("synthesize")
        confirmed = [r for r in results if r["status"] == "confirmed"]
        overview = None
        if confirmed:
            listing = "\n".join(f"- [{r['severity']}] {r['title']} ({r['where']}): {r['evidence'][:300]}" for r in confirmed)
            overview = await self.agent(
                "Write a short overview (3 to 5 sentences, plain prose, no headings) of these verified review findings: what matters most "
                f"and in which order to fix them. Use only the facts listed.\n\n{listing}", None, False, label="synthesize")
        await self._phase("synthesize", "done")
        return self._review_report(task, files, dims, results, overview), results

    @staticmethod
    def _finding_md(i: int, r: dict, notes: bool = True) -> str:
        head = f"### {i}. [{r['severity'].upper()}] {r['title']}\n`{r['where']}` · found by: {', '.join(r['dimensions'])}\n\n"
        body = f"**Evidence.** {r['evidence']}\n\n**Fix.** {r['fix']}\n"
        return head + body + ("\n" + "\n".join(f"- {w}" for w in r["verification"]) + "\n" if notes and r.get("verification") else "")

    def _review_report(self, task, files, dims, results, overview) -> str:
        by = {s: [r for r in results if r["status"] == s] for s in ("confirmed", "disputed", "rejected", "unverified")}
        md = [f"# Review\n\nTask: {task or '(none given)'}\n\nScope: {len(files)} files · dimensions: {', '.join(dims)} · "
              f"{len(results)} candidate findings, {len(by['confirmed'])} confirmed, {len(by['disputed'])} disputed, {len(by['rejected'])} rejected\n"]
        if overview:
            md.append(f"## Overview\n\n{overview}\n")
        md.append("## Confirmed findings\n\n" + ("\n".join(self._finding_md(i, r) for i, r in enumerate(by["confirmed"], 1))
                                                  or "None survived verification.\n"))
        if by["disputed"]:
            md.append("## Disputed (the skeptics disagreed, check by hand)\n\n"
                      + "\n".join(self._finding_md(i, r) for i, r in enumerate(by["disputed"], 1)))
        if by["rejected"]:
            md.append("## Rejected\n\n" + "\n".join(f"- `{r['where']}` {r['title']}: {r['verification'][0] if r['verification'] else ''}"
                                                    for r in by["rejected"]) + "\n")
        if by["unverified"]:
            md.append("## Not verified\n\n" + "\n".join(f"- [{r['severity']}] `{r['where']}` {r['title']}" for r in by["unverified"]) + "\n")
        return "\n".join(md)

    async def research(self, task: str, scope: str):
        await self._phase("plan")
        schema = {"type": "object", "required": ["angles"], "properties": {"angles": {"type": "array", "items": {
            "type": "object", "required": ["name", "query"], "properties": {"name": {"type": "string"}, "query": {"type": "string"}}}}}}
        plan = await self.agent("Split this research question into 3 to 5 distinct angles that together cover it. "
                                "Each angle has a short name and one specific question to research.\n\nQuestion: " + task,
                                schema, False, label="plan", model=self.helper_model, phase="plan")
        angles = (plan or {}).get("angles", [])
        if len(angles) > 5:
            await self._note("planner returned %d angles, kept 5; dropped: %s" % (len(angles), "; ".join(a["name"] for a in angles[5:])))
        angles = angles[:5]
        if not angles:
            await self._note("planner failed, researching the question as a single angle")
            angles = [{"name": "question", "query": task}]
        await self._phase("plan", "done", f"{len(angles)} angles")

        await self._phase("research")
        claim_schema = {"type": "object", "required": ["claims"], "properties": {"claims": {"type": "array", "items": {
            "type": "object", "required": ["claim", "source"], "properties": {
                "claim": {"type": "string"}, "source": {"type": "string"}, "quote": {"type": "string"}}}}}}
        res = await self.parallel([lambda a=a: self.agent(
            f"Research this angle of a larger question.\nLarger question: {task}\nAngle: {a['name']}: {a['query']}\n\n"
            "Use WebSearch to find sources and WebFetch to read the most promising pages (at most 3 fetches). "
            "If the question concerns this project, use Read and Grep. Return claims: each is one factual sentence, the source "
            "(full URL, or path:line for project files) and a short exact quote from that source. "
            "Only include claims you saw in a fetched page or search snippet. If you found nothing reliable, return an empty list.",
            claim_schema, True, 8, f"angle:{a['name'][:30]}", phase="research") for a in angles])
        claims: list[dict] = []
        for a, r in zip(angles, res):
            for c in (r or {}).get("claims", []):
                if not any(x["source"] == c["source"] and similarity(x["claim"], c["claim"]) > 0.8 for x in claims):
                    claims.append({"claim": c["claim"].strip(), "source": c["source"].strip(), "quote": c.get("quote", "").strip(),
                                   "angle": a["name"]})
        for i, c in enumerate(claims, 1):
            c["id"] = f"c{i}"
        await self._phase("research", "done", f"{len(claims)} claims")
        if not claims:
            return "# Research\n\nNo claims could be collected (web search may be unavailable). Nothing to verify.\n", []

        await self._phase("verify")
        order = sorted(claims, key=lambda c: (not c["quote"], c["id"]))
        key, rest = order[:MAX_CLAIMS], order[MAX_CLAIMS:]
        if rest:
            await self._note("verification cap: %d claims not cross-checked: %s" % (len(rest), ", ".join(c["id"] for c in rest)))
        chk_schema = {"type": "object", "required": ["checks"], "properties": {"checks": {"type": "array", "items": {
            "type": "object", "required": ["id", "verdict", "note"], "properties": {
                "id": {"type": "string"}, "verdict": {"type": "string", "enum": ["supported", "contradicted", "not_found"]},
                "note": {"type": "string"}}}}}}
        listing = "\n".join(f"{c['id']}: {c['claim']}\n   source: {c['source']}\n   quote: {c['quote'] or '(none)'}" for c in key)
        chk = await self.agent("Cross-check these claims. For each, open its source (WebFetch for URLs, Read for project files) and check that the "
                               "page really says it. verdict: supported, contradicted, or not_found (source unreachable or silent on it). "
                               f"Give the id and a one-line note.\n\n{listing}", chk_schema, True, 12, "verify claims", phase="verify")
        status = {c["id"]: ("unchecked", "") for c in claims}
        for k in (chk or {}).get("checks", []):
            if k["id"] in status:
                status[k["id"]] = (k["verdict"], k["note"].strip())
        for c in claims:
            c["status"], c["note"] = status[c["id"]]
        await self._phase("verify", "done", f"{sum(c['status'] == 'supported' for c in claims)} supported")

        await self._phase("write")
        facts = "\n".join(f"[{c['id']}] ({c['status']}) {c['claim']}" + (f" -- {c['note']}" if c["note"] else "") for c in claims)
        answer = await self.agent(
            f"Question: {task}\n\nFacts gathered, with their verification status:\n{facts}\n\n"
            "Write the answer in markdown with exactly two sections: '## Answer' (cite facts as [c1], [c2]) and '## Uncertainty' "
            "(what is contradicted, unchecked or missing, and what the answer therefore cannot claim). "
            "Use only the facts above. Never state a contradicted fact as true. Facts marked unchecked or not_found may be used "
            "but must be named as unverified in the Uncertainty section.", None, False, label="write answer", phase="write")
        await self._phase("write", "done")
        if not answer:
            answer = "## Answer\n\n(The writer failed; the verified claims are listed below.)\n\n## Uncertainty\n\nThe answer was not synthesized."
        src = "\n".join(f"- [{c['id']}] {c['source']} ({c['status']}): {c['claim']}" for c in claims)
        return f"# Research\n\n{answer}\n\n## Sources\n\n{src}\n", claims

    async def design(self, task: str, scope: str):
        files = await self._scope_files(scope) if scope.strip() else []
        ctx_note = f"Relevant files: {', '.join(files)}\n" if files else "Look at the project only as far as you need to.\n"
        angles = (("A", "minimal", "the smallest change that solves the task, fewest moving parts"),
                  ("B", "robust", "handles failure and edge cases, easy to maintain and test"),
                  ("C", "fastest to ship", "least effort and time, reuses what exists, accepts known limits"))
        plan_schema = {"type": "object", "required": ["title", "approach", "steps", "risks"], "properties": {
            "title": {"type": "string"}, "approach": {"type": "string"}, "steps": {"type": "array", "items": {"type": "string"}},
            "files": {"type": "array", "items": {"type": "string"}}, "tradeoffs": {"type": "string"},
            "risks": {"type": "array", "items": {"type": "string"}}}}
        await self._phase("propose")
        res = await self.parallel([lambda a=a: self.agent(
            f"Design a solution. Angle: {a[1]}: {a[2]}.\nTask: {task}\n{ctx_note}"
            "Inspect the project with the tools (at most 6 steps) so the plan fits the code that exists. "
            "Return title, approach (2-4 sentences), steps (ordered, concrete), files (paths you would touch, only ones you saw), "
            "tradeoffs, risks.", plan_schema, FILE_TOOLS, 6, f"plan:{a[1]}", phase="propose") for a in angles])
        plans = [dict(p, key=a[0], angle=a[1]) for a, p in zip(angles, res) if p]
        if len(plans) < len(angles):
            await self._note("design: %d of %d proposals failed" % (len(angles) - len(plans), len(angles)))
        await self._phase("propose", "done", f"{len(plans)} plans")
        if not plans:
            return "# Design\n\nNo proposal could be produced.\n", []

        await self._phase("judge")
        crit = ("fit", "simplicity", "safety", "speed")
        keys = [p["key"] for p in plans]
        score_schema = {"type": "object", "required": ["scores"], "properties": {"scores": {"type": "array", "items": {
            "type": "object", "required": ["plan", *crit, "comment"],
            "properties": {"plan": {"type": "string", "enum": keys}, **{c: {"type": "integer"} for c in crit}, "comment": {"type": "string"}}}}}}
        shown = "\n\n".join(f"Plan {p['key']} ({p['angle']}): {p['title']}\n{p['approach']}\nSteps: " + "; ".join(p["steps"])
                            + f"\nTradeoffs: {p.get('tradeoffs', '')}\nRisks: " + "; ".join(p["risks"]) for p in plans)
        judged = await self.parallel([lambda n=n, who=who: self.agent(
            f"You are judge {n}, {who}. Score every plan from 1 (poor) to 5 (excellent) on: fit (solves the task and suits the code), "
            "simplicity (few parts, easy to understand), safety (low risk of breaking things, 5 = very safe), speed (quick to ship, "
            f"5 = very quick). Give one comment per plan.\n\nTask: {task}\n\n{shown}", score_schema, False, label=f"judge {n}", phase="judge")
            for n, who in ((1, "a pragmatic engineer who values shipping"), (2, "a skeptical maintainer who values safety and clarity"))])
        for p in plans:
            rows = [s for j in judged if j for s in j["scores"] if s["plan"] == p["key"]]
            p["scores"] = {c: round(sum(min(5, max(1, r[c])) for r in rows) / len(rows), 2) for c in crit} if rows else {}
            p["total"] = round(2 * p["scores"]["fit"] + sum(p["scores"][c] for c in crit[1:]), 2) if rows else -1
            p["comments"] = [r["comment"] for r in rows]
        plans.sort(key=lambda p: -p["total"])
        if all(p["total"] < 0 for p in plans):
            await self._note("both judges failed: plans are unscored, the first proposal is used")
        await self._phase("judge", "done", f"winner: plan {plans[0]['key']}")

        await self._phase("synthesize")
        win, others = plans[0], plans[1:]
        dump = lambda p: json.dumps({k: p[k] for k in ("title", "approach", "steps", "files", "tradeoffs", "risks") if k in p}, indent=1)
        synth = await self.agent(
            f"Task: {task}\n\nWinning plan ({win['angle']}):\n{dump(win)}\n\nRunner-up plans:\n"
            + "\n".join(f"Plan {p['key']} ({p['angle']}):\n{dump(p)}" for p in others) + "\n\n"
            "Write the final plan in markdown with these sections: '## Plan' (ordered steps, based on the winner), "
            "'## Grafted from other plans' (only ideas that appear in the runner-ups, name the plan; say 'none' if nothing fits), "
            "'## Risks' (each with a mitigation). Do not invent steps unrelated to the plans above. No citation markers like [1].", None, False, label="synthesize", phase="synthesize")
        await self._phase("synthesize", "done")
        table = "| Plan | Angle | Fit | Simplicity | Safety | Speed | Total |\n|---|---|---|---|---|---|---|\n" + "\n".join(
            f"| {p['key']} | {p['angle']} | " + " | ".join(str(p["scores"].get(c, "-")) for c in crit) + f" | {p['total']} |" for p in plans)
        if not synth:
            synth = "## Plan\n\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(win["steps"], 1)) + \
                    "\n\n## Risks\n\n" + "\n".join(f"- {r}" for r in win["risks"]) + "\n\n(The synthesis worker failed; this is the winning proposal as is.)"
        for i, p in enumerate(plans):
            p["winner"] = i == 0
        return (f"# Design\n\nTask: {task}\n\nWinner: plan {win['key']} ({win['angle']}), {win['title']}\n\n"
                f"## Scores\n\n{table}\n\n{synth}\n"), plans

    async def audit(self, task: str, scope: str):
        files = await self._scope_files(scope)
        if not files:
            return "# Audit\n\nNo readable files in scope.\n", []
        await self._phase("map")
        shown = files[:200]
        area_schema = {"type": "object", "required": ["areas"], "properties": {"areas": {"type": "array", "items": {
            "type": "object", "required": ["name", "paths"], "properties": {
                "name": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}, "focus": {"type": "string"}}}}}}
        mapped = await self.agent("Group these project files into 3 to 6 coherent areas (modules or layers) for an audit. "
                                  "Every area: a short name, the file paths it contains (copied exactly from the list), what to look for.\n\n"
                                  + self._tree(shown), area_schema, False, label="map areas", model=self.helper_model, phase="map")
        areas, seen = [], set()
        for a in (mapped or {}).get("areas", []):
            paths = [p for p in a["paths"] if p in files and p not in seen]
            seen.update(paths)
            if paths:
                areas.append({"name": a["name"], "files": paths, "focus": a.get("focus", "")})
        left = [f for f in files if f not in seen]
        if not areas:
            await self._note("mapper failed or gave unusable areas, grouping by top-level directory")
            groups: dict[str, list[str]] = {}
            for f in files:
                groups.setdefault(Path(f).parts[0] if len(Path(f).parts) > 1 else "(root files)", []).append(f)
            areas, left = [{"name": k, "files": v, "focus": ""} for k, v in groups.items()], []
        if left:
            areas.append({"name": "other files", "files": left, "focus": ""})
        if len(areas) > MAX_AREAS:
            await self._note(f"area cap: {len(areas)} areas, only {MAX_AREAS} audited; dropped: " + ", ".join(a["name"] for a in areas[MAX_AREAS:]))
            areas = areas[:MAX_AREAS]
        await self._phase("map", "done", f"{len(areas)} areas")

        await self._phase("audit")

        async def audit_stage(a):
            raw = await self.agent(self._finder_prompt(f"audit of area {a['name']!r}. {a['focus']}", task, a["files"]),
                                   FINDINGS_SCHEMA, FILE_TOOLS, 8, f"audit:{a['name'][:30]}", phase="audit")
            if raw is None:
                return None
            fs = dedupe(await self._ground(raw, a["files"], "audit", f"auditor {a['name']}"))
            fs.sort(key=lambda x: SEVERITY[x["severity"]])
            return {"area": a, "findings": fs}

        async def verify_stage(r):
            top, rest = r["findings"][:3], r["findings"][3:]
            vs = await self.parallel([lambda f=f, i=i: self._skeptic(f, ("both", LENSES[0][1] + " " + LENSES[1][1] + " Confirm only if you can name a concrete input or attack that goes wrong; "
                                                         "a design choice, a missing option or a possible extension is not a defect."), f"skeptic {r['area']['name'][:20]} #{i}", "audit")
                                      for i, f in enumerate(top, 1)])
            out = []
            for f, v in zip(top, vs):
                st = "unverified" if v is None else ("confirmed" if v["verdict"] == "confirmed" else "rejected")
                out.append(dict(f, area=r["area"]["name"], status=st, verification=[f"{v['verdict']}: {v['reason']}"[:300]] if v else ["skeptic failed"]))
            out += [dict(f, area=r["area"]["name"], status="unverified", verification=["not checked (only the top 3 per area are verified)"]) for f in rest]
            return {"area": r["area"], "findings": out}

        done = await self.pipeline(areas, audit_stage, verify_stage)
        await self._phase("audit", "done")
        results = [d for d in done if d]
        if len(results) < len(areas):
            await self._note("audit: %d of %d areas produced no result: %s" % (
                len(areas) - len(results), len(areas), ", ".join(a["name"] for a, d in zip(areas, done) if not d)))
        allf = [f for r in results for f in r["findings"]]
        md = [f"# Audit\n\nTask: {task or '(none given)'}\n\n{len(files)} files in {len(areas)} areas · {len(allf)} candidate findings, "
              f"{sum(f['status'] == 'confirmed' for f in allf)} confirmed, {sum(f['status'] == 'rejected' for f in allf)} rejected, "
              f"{sum(f['status'] == 'unverified' for f in allf)} unverified\n"]
        for r in results:
            fs = r["findings"]
            md.append(f"## {r['area']['name']}\n\n" + ", ".join(f"`{f}`" for f in r["area"]["files"][:12]) + "\n")
            good = [f for f in fs if f["status"] == "confirmed"]
            md.append("\n".join(self._finding_md(i, f) for i, f in enumerate(good, 1)) or "No confirmed findings.\n")
            md.append("\n".join(f"- ({f['status']}) [{f['severity']}] `{f['where']}` {f['title']}" for f in fs if f["status"] != "confirmed"))
        return "\n".join(md) + "\n", allf

    # -- entry point ----------------------------------------------------------------
    async def run(self, pattern: str, task: str, scope: str = "") -> dict:
        self._reset()
        task, scope = _text(task), _text(scope)
        t0 = time.monotonic()
        fn = {"review": self.review, "research": self.research, "design": self.design, "audit": self.audit}.get(pattern)
        findings: list = []
        if not fn:
            report = f"# Ultra\n\nUnknown pattern {pattern!r}. Available: {', '.join(PATTERNS)}.\n"
        else:
            try:
                report, findings = await fn(task, scope)
            except Exception as e:   # a bug in a pattern must not take the host down
                await self._note(f"{pattern} aborted: {type(e).__name__}: {e}")
                report = f"# {pattern.capitalize()}\n\nThe run aborted: {type(e).__name__}: {e}\n"
        if self.agents and self.failed == self.agents:   # an empty result here must not read as "nothing found"
            report = (f"FAILED: no worker produced a result ({self.last_why}). Nothing was checked; this is not a clean result.\n\n"
                      f"# {pattern.capitalize()}\n\nAll {self.agents} workers failed, see the run notes.\n")
        elif self.failed:
            report = (f"WARNING: {self.failed} of {self.agents} workers failed, so this result may be incomplete (see the run notes).\n\n"
                      + report)
        if self.notes:
            report = report.rstrip() + "\n\n## Run notes\n\n" + "\n".join(f"- {n}" for n in self.notes) + "\n"
        return {"pattern": pattern, "report": report, "findings": findings,
                "stats": {"agents": self.agents, "secs": round(time.monotonic() - t0, 1), "failed": self.failed,
                          "peak_agents": self.peak_agents, "notes": len(self.notes)}}


PATTERNS = ("review", "research", "design", "audit")


# ------------------------------------------------------------------ tool entry (wired by the host through ctx.ultra)

async def _ultra_tool(ctx, pattern, task, scope=""):
    runner = getattr(ctx, "ultra", None)
    if runner is None:
        raise tools.ToolError("Ultra is not available here")
    if pattern not in PATTERNS:
        raise tools.ToolError(f"Unknown pattern {pattern!r}. Use one of: {', '.join(PATTERNS)}")
    res = await runner(pattern, _text(task), _text(scope))
    ctx.meta = {"pattern": pattern, **res["stats"], "findings": len(res["findings"])}
    return res["report"]


TOOLS = {
    "Ultra": ("agent", _ultra_tool, {"type": "function", "function": {
        "name": "Ultra",
        "description": ("Run a slow multi-agent workflow (several minutes) and get a markdown report. Use only when the user asks for a thorough "
                        "job. review: find defects in files and verify each with skeptics. research: web research, claims cross-checked. "
                        "design: compare three plans and pick one. audit: map the project and audit each area."),
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "enum": list(PATTERNS), "description": "which workflow"},
            "task": {"type": "string", "description": "what to review, research, design or audit"},
            "scope": {"type": "string", "description": "files or directories, comma separated; empty means the whole project"}},
            "required": ["pattern", "task"]}}}),
}


# Imported last: tools.py imports this module at its own end, so either import order works.
from . import tools  # noqa: E402
