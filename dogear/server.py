"""HTTP + WebSocket + live preview. Binds to 127.0.0.1 only."""
import asyncio
import json
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import uvicorn

from . import agent as A
from . import browser as br
from . import checkpoint as cpt
from . import worktrees as W
from . import llm, profiles, tools
from . import memory as mem
from . import library, learning, flows
from .brand import NAME

WEB = Path(__file__).resolve().parent.parent / "web"
SETTINGS = A.DATA / "settings.json"
DEFAULTS = {"model": "qwen3.6:35b-a3b", "think": False, "mode": "edit", "num_ctx": 32768, "review": True,
            "root": os.environ.get("DOGEAR_ROOT") or str(A.DATA.parent / "projects")}
client: httpx.AsyncClient
preview_root = {"path": DEFAULTS["root"]}
BROWSER: br.Browser
AGENTS: set = set()      # one Agent per open UI connection, plus the background branch runs


class Run:
    """A branch run that works in its own worktree, independent of any browser window."""
    def __init__(self, sid: str, title: str, agent=None):
        self.sid, self.title, self.agent = sid, title, agent
        self.status, self.last, self.steps, self.task = "running", "starting", 0, None

    def info(self) -> dict:
        wt = (self.agent.session or {}).get("worktree") or {}
        return {"id": self.sid, "title": self.title, "status": self.status, "last": self.last, "steps": self.steps,
                "worktree": bool(wt) and not wt.get("removed")}


RUNS: dict[str, Run] = {}
MIRROR: dict = {}        # connection id -> direct sender; lets a second window watch a running turn
PREVIEW_URL = f"http://127.0.0.1:{br.PREVIEW_PORT}"
NOCACHE = {"Cache-Control": "no-store"}

# Project files are served from a different origin than the UI, so pages the agent writes
# (or visits) can never talk to the agent's own API or WebSocket.
preview_app = FastAPI()


def _serve(root: str, path: str):
    ctx = tools.Ctx(Path(root))
    try:
        p = ctx.path(path or ".")
        if path == "favicon.ico" and not p.exists():
            return Response(status_code=204)
        if p.is_dir():
            p = p / "index.html"
        if not p.is_file():
            return Response("<body style='font:14px monospace;padding:2em;color:#888'>Nothing here yet.<br>"
                            f"No {path or 'index.html'} in {ctx.root}</body>", 404, media_type="text/html", headers=NOCACHE)
    except tools.ToolError as e:
        raise HTTPException(400, str(e))
    return FileResponse(p, headers=NOCACHE)


@preview_app.get("/@{sid}/{path:path}")
async def preview_session(sid: str, path: str):
    return _serve(br.PREVIEW_ROOTS.get(sid) or preview_root["path"], path)


@preview_app.get("/{path:path}")
async def preview(path: str):
    return _serve(preview_root["path"], path)


def settings() -> dict:
    s = dict(DEFAULTS)
    if SETTINGS.exists():
        s.update(json.loads(SETTINGS.read_text()))
    if s["mode"] not in A.MODES:
        s["mode"] = "edit"
    return s


@asynccontextmanager
async def lifespan(_):
    global client, BROWSER
    client = httpx.AsyncClient()
    BROWSER = br.Browser(A.DATA / "chrome-profile")
    preview_root["path"] = settings()["root"]
    pserver = uvicorn.Server(uvicorn.Config(preview_app, host="127.0.0.1", port=br.PREVIEW_PORT, log_level="warning"))
    ptask = asyncio.create_task(pserver.serve())
    yield
    pserver.should_exit = True
    await ptask
    await BROWSER.close()
    await client.aclose()


app = FastAPI(lifespan=lifespan)

@app.get("/")
async def index():
    return FileResponse(WEB / "index.html", headers=NOCACHE)


@app.get("/api/state")
async def state():
    try:
        profs = await profiles.list_profiles(client)
    except Exception:
        profs = []
    return {"settings": settings(), "models": [p.model for p in profs], "profiles": {p.model: p.summary() for p in profs},
            "sessions": A.listing(), "name": NAME, "preview": PREVIEW_URL}


@app.get("/api/profile")
async def profile(model: str, reset: bool = False):
    if reset:
        profiles.invalidate(model)
    p = await profiles.get_profile(client, model)
    return {**p.summary(), "tools_loaded": p.tool_names(list(tools.TOOLS)) if p.tools else []}


THUMBS = A.DATA / "library-thumbs"
THUMB_BROWSER: br.Browser | None = None
_thumb_lock = asyncio.Lock()


@app.get("/api/thumb/{entry_id}")
async def thumb(entry_id: int):
    """A small picture of a design plan's page, rendered once in a browser of its own and cached."""
    global THUMB_BROWSER
    THUMBS.mkdir(parents=True, exist_ok=True)
    out = THUMBS / f"{entry_id}.jpg"
    if out.exists():
        return FileResponse(out, media_type="image/jpeg")
    e = library.get(entry_id, full=True)
    if not e or not e.get("extra"):
        raise HTTPException(404)
    page = THUMBS / f"{entry_id}.html"
    page.write_text(e["extra"])
    async with _thumb_lock:
        if THUMB_BROWSER is None:
            THUMB_BROWSER = br.Browser(A.DATA / "thumb-profile")
        b = THUMB_BROWSER
        await b.ensure()
        await b.set_viewport(1280, 800)
        await b.cdp.call("Page.navigate", {"url": page.as_uri()}, session=b.sess)
        await asyncio.sleep(0.8)
        r = await b.cdp.call("Page.captureScreenshot", {"format": "jpeg", "quality": 68,
                             "clip": {"x": 0, "y": 0, "width": 1280, "height": 800, "scale": 0.4}}, session=b.sess)
    import base64
    out.write_bytes(base64.b64decode(r["data"]))
    return FileResponse(out, media_type="image/jpeg")


@app.get("/api/models")
async def models_page():
    """Every installed model with what dogear knows and measured about it (for the Models pane)."""
    helper = await profiles.pick_helper(client)
    out = []
    for p in await profiles.list_profiles(client):
        d = p.summary()
        d["stats"] = profiles.stats_for(p.model)
        d["helper"] = p.model == helper
        d["tools_loaded"] = len(p.tool_names(list(tools.TOOLS))) if p.tools else 0
        out.append(d)
    return {"models": out, "default": settings()["model"], "num_ctx": settings()["num_ctx"]}


TREE_CAP = 300


@app.get("/api/tree")
async def tree(root: str, path: str = "."):
    ctx = tools.Ctx(Path(root))
    try:
        entries = sorted(ctx.path(path).iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    except (tools.ToolError, OSError) as e:
        raise HTTPException(400, str(e))
    shown = [e for e in entries if e.name not in tools.SKIP_DIRS and not e.name.startswith(".")]
    out = []
    for e in shown[:TREE_CAP]:
        item = {"name": e.name, "dir": e.is_dir(), "path": ctx.rel(e)}
        if item["dir"]:
            try:
                item["count"] = sum(1 for c in e.iterdir() if c.name not in tools.SKIP_DIRS and not c.name.startswith("."))
            except OSError:
                item["count"] = 0
        out.append(item)
    if len(shown) > TREE_CAP:
        out.append({"name": "", "more": len(shown) - TREE_CAP})
    return out


@app.get("/api/find")
async def find(root: str, q: str, limit: int = 40):
    """File name search for the explorer: every query word must occur in the path (case-insensitive)."""
    words = [w for w in q.lower().split() if w]
    if not words:
        return []
    base = Path(root).resolve()
    out, seen = [], 0
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in tools.SKIP_DIRS and not d.startswith(".")]
        for f in files:
            seen += 1
            if f.startswith("."):
                continue
            rel = str((Path(dirpath) / f).relative_to(base))
            low = rel.lower()
            if all(w in low for w in words):
                out.append(rel)
        if seen > 20000 or len(out) >= 400:
            break
    out.sort(key=lambda r: (not all(w in Path(r).name.lower() for w in words), len(r), r))
    return [{"name": Path(r).name, "path": r, "dir": False} for r in out[:max(1, min(limit, 100))]]


@app.get("/api/file")
async def file(root: str, path: str):
    ctx = tools.Ctx(Path(root))
    try:
        raw = ctx.path(path).read_bytes()
    except (tools.ToolError, OSError) as e:
        raise HTTPException(400, str(e))
    if b"\0" in raw[:4096]:
        return {"binary": True, "size": len(raw)}
    return {"text": raw[:300_000].decode("utf-8", "replace"), "truncated": len(raw) > 300_000}


@app.get("/img/{name}")
async def image(name: str):
    import re as _re
    f = A.IMAGES / name
    if not _re.fullmatch(r"[0-9a-f]{16}\.jpg", name) or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "max-age=31536000", "X-Content-Type-Options": "nosniff"})


def _mem_root(id: str | None) -> Path:
    s = A.load(id) if id else None
    return Path(s["root"]) if s else Path(settings().get("root") or ".")


@app.get("/api/memory")
async def memory_list(id: str = ""):
    root = _mem_root(id)
    return {"root": str(root), "items": [mem.public(e) for e in mem.entries(root)]}


@app.post("/api/memory")
async def memory_save(body: dict):
    try:
        return mem.apply(_mem_root(body.get("session")), body)
    except mem.MemoryError_ as e:
        raise HTTPException(400, str(e))


@app.delete("/api/memory")
async def memory_delete(session: str, kind: str, name: str, scope: str = ""):
    try:
        return mem.delete(_mem_root(session), kind, name, scope or None)
    except mem.MemoryError_ as e:
        raise HTTPException(404, str(e))


@app.get("/api/library")
async def library_list(q: str = "", limit: int = 100):
    if q.strip():
        return await library.search(client, llm.URL, q, min(max(limit, 1), 50))
    return library.entries(min(max(limit, 1), 300))


@app.delete("/api/library/{entry_id}")
async def library_delete(entry_id: int):
    if not library.delete(entry_id):
        raise HTTPException(404)
    return {"ok": True}


@app.get("/api/branches")
async def branches(id: str):
    base = A.load(id)
    if not base:
        raise HTTPException(404)
    lin = A.lineage_of(base)
    out = []
    for item in A.listing():
        if item["lineage"] == lin or item["id"] == lin:
            s = A.load(item["id"])
            out.append({"id": item["id"], "title": item["title"], "updated": item["updated"], "parent": item["parent"],
                        "turns": len(A.user_positions(s["messages"])) if s else 0})
    return out


@app.get("/api/session/{sid}")
async def get_session(sid: str):
    s = A.load(sid)
    if not s:
        raise HTTPException(404)
    return s


@app.delete("/api/session/{sid}")
async def del_session(sid: str):
    (A.SESSIONS / f"{Path(sid).name}.json").unlink(missing_ok=True)
    return {"ok": True}


# ------------------------------------------------------------------ the WebSocket: one connection, one agent, small handlers

class Conn:
    """One UI connection: its agent, its settings, the turn it is running, and how to reach its window and the others."""

    def __init__(self, sock: WebSocket):
        self.sock = sock
        self.outq: asyncio.Queue = asyncio.Queue()
        self.cfg = settings()
        self.task: asyncio.Task | None = None
        self.ag = A.Agent(self.send, client, BROWSER)
        self.ag.mirror = self.mirror

    async def writer(self):
        try:
            while True:
                await self.sock.send_json(await self.outq.get())
        except Exception:
            pass

    async def direct(self, m: dict):
        """To this window only. A lagging window drops screencast frames first and never stalls the agent."""
        if m.get("type") == "frame" and self.outq.qsize() > 60:
            return
        self.outq.put_nowait(m)

    async def mirror(self, m: dict):
        """To every other window, so a run started here is visible everywhere."""
        for cid, d in list(MIRROR.items()):
            if cid != id(self):
                await d(m)

    async def send(self, m: dict):
        await self.direct(m)
        await self.mirror(m)

    async def broadcast(self, m: dict):
        for d in list(MIRROR.values()):
            await d(m)

    def busy(self) -> bool:
        return bool(self.task and not self.task.done())

    def start(self, coro) -> None:
        self.task = asyncio.create_task(coro)
        self.ag.turn_task = self.task

    def start_turn(self, text: str, mode: str | None = None, images: list | None = None) -> None:
        cfg = self.cfg
        self.ag.session["root"] = preview_root["path"] = cfg["root"]
        self.start(self.ag.turn(text, cfg["model"], bool(cfg["think"]), mode or cfg["mode"], cfg["num_ctx"],
                                review_on=bool(cfg.get("review", True)), images=list(images or [])))

    def last_plan_message(self) -> dict | None:
        return next((m for m in reversed(self.ag.session["messages"]) if m.get("plan")), None)


HANDLERS: dict[str, Callable[[Conn, dict], Awaitable[None]]] = {}


def handler(name: str):
    def deco(fn):
        HANDLERS[name] = fn
        return fn
    return deco


@handler("user")
async def on_user(c: Conn, m: dict):
    if c.busy():
        return
    c.cfg.update({k: m[k] for k in ("model", "think", "mode", "root", "review") if k in m})
    c.cfg["num_ctx"] = int(m.get("num_ctx", c.cfg["num_ctx"]))
    if m.get("persist"):                                 # the UI persists its settings; scripts do not clobber them
        SETTINGS.write_text(json.dumps(c.cfg))
    if not Path(c.cfg["root"]).is_dir():
        await c.send({"type": "error", "text": f"Project directory does not exist: {c.cfg['root']}"})
        await c.send({"type": "done"})
        return
    c.start_turn(m["text"], None, [i for i in m.get("images", []) if isinstance(i, str)][:4])


@handler("plan_approve")
async def on_plan_approve(c: Conn, m: dict):
    """Phase 2 -> 3: the edited board is approved; the harness carries it out one task per turn."""
    if c.busy():
        return
    pm = c.last_plan_message()
    if not pm or pm["plan"].get("status") not in ("proposed", "replan"):
        await c.send({"type": "notice", "text": "There is no plan waiting for approval."})
        return
    edited = []
    for it in (m.get("tasks") or [])[:20]:
        content = " ".join(str(it.get("content", "") if isinstance(it, dict) else it).split())[:300]
        if len(content) >= 2:
            edited.append({"content": content, "detail": " ".join(str(it.get("detail", "") if isinstance(it, dict) else "").split())[:600]})
    if not edited:
        await c.send({"type": "notice", "text": "The plan has no tasks left."})
        return
    ref = m.get("reference")
    pm["plan"].update(status="approved", tasks=edited, log=[], reference=ref if ref in ("none", "surprise") or isinstance(ref, int) else None)
    c.ag.session["todos"] = [{"content": t["content"], "status": "pending"} for t in edited]
    A.save(c.ag.session)
    await c.send({"type": "plan_status", "status": "approved", "tasks": edited})
    await c.send({"type": "todos", "items": c.ag.session["todos"]})
    mode = m.get("mode") if m.get("mode") in ("ask", "edit", "auto") else "edit"
    c.cfg["mode"] = mode
    c.ag.session["root"] = preview_root["path"] = c.cfg["root"]
    c.start(c.ag.run_plan(pm, edited, c.cfg["model"], bool(c.cfg["think"]), mode, c.cfg["num_ctx"], bool(c.cfg.get("review", True))))


@handler("plan_reject")
async def on_plan_reject(c: Conn, m: dict):
    if c.busy():
        return
    pm = c.last_plan_message()
    if not pm or pm["plan"].get("status") not in ("proposed", "replan"):
        await c.send({"type": "notice", "text": "There is no plan waiting for approval."})
        return
    fb = str(m.get("feedback", "")).strip()[:2000] or "The user did not like the plan. Rethink it."
    pm["plan"].update(status="rejected", feedback=fb)
    A.save(c.ag.session)
    await c.send({"type": "plan_status", "status": "rejected", "feedback": fb})
    c.start_turn("The plan was rejected. Feedback from the user:\n" + fb + "\n\nRevise the plan and submit it again with kanban_create_tasks.", "plan")


@handler("approve")
async def on_approve(c: Conn, m: dict):
    for a in AGENTS:                                      # the approval may belong to a turn started in another window
        if m["id"] in a.pending:
            a.answer(m["id"], bool(m["ok"]), bool(m.get("always")), m.get("key", ""))


@handler("answer")
async def on_answer(c: Conn, m: dict):
    for a in AGENTS:
        if m["id"] in a.asks:
            a.answer_ask(m["id"], m.get("value", ""))


@handler("mode")
async def on_mode(c: Conn, m: dict):
    """A mode change applies at once, also to the turn that is running; "auto" grants what is waiting."""
    if m.get("mode") in ("ask", "edit", "auto"):
        c.cfg["mode"] = m["mode"]
        c.ag.set_mode(m["mode"])


@handler("stop")
async def on_stop(c: Conn, m: dict):
    """Stops this window's turn, a turn another window or script started on the same session, or a background run."""
    sid, stopped = m.get("id"), 0
    if c.busy() and (not sid or sid == c.ag.session["id"]):
        c.task.cancel()
        stopped += 1
    for a in list(AGENTS):
        tt = getattr(a, "turn_task", None)
        if a is not c.ag and a.running and tt and not tt.done() and (not sid or a.session["id"] == sid):
            tt.cancel()
            stopped += 1
    if sid in RUNS and RUNS[sid].task and not RUNS[sid].task.done():
        RUNS[sid].task.cancel()
        stopped += 1
    if not stopped:
        await c.send({"type": "done"})                    # nothing was running: release the window


@handler("rate")
async def on_rate(c: Conn, m: dict):
    """The rating under a finished run is the gate for the library: only good runs may teach."""
    res = learning.rate(c.ag.session, int(m.get("turn", -1)), int(float(m.get("value", 0))), str(m.get("note", "")))
    if not res:
        await c.send({"type": "notice", "text": "That turn has no finished run to rate."})
        return
    rating, sm_msg, removed = res
    if removed:
        await c.send({"type": "notice", "text": f"Removed {removed} automatically saved library entr{'y' if removed == 1 else 'ies'} of that run."})
    turn = int(m.get("turn", -1))
    await c.send({"type": "rated", "turn": turn, "rating": rating})
    if rating["value"] > 0 and not rating["extracted"]:
        async def learn():
            try:
                saved = await learning.learn_from_rating(client, c.ag.session, turn, sm_msg, c.cfg["model"])
                await c.send({"type": "library_saved", "turn": turn, "entries": saved})
            except Exception as e:
                await c.send({"type": "library_saved", "turn": turn, "entries": [], "error": str(e)[:120]})
        asyncio.create_task(learn())


@handler("undo")
async def on_undo(c: Conn, m: dict):
    if c.busy():
        return
    root = Path(m.get("root", ""))
    if str(root) not in (c.ag.session["root"], c.cfg["root"]):
        return
    touched = await asyncio.to_thread(cpt.restore, root, str(m["to"]))
    await c.send({"type": "undone", "files": touched})
    gone = learning.forget_undone(c.ag.session, str(m["to"]))
    if gone:
        await c.send({"type": "notice", "text": f"Removed {gone} automatically saved library entr{'y' if gone == 1 else 'ies'} of the undone run."})
    await c.send({"type": "fs"})


@handler("variants")
async def on_variants(c: Conn, m: dict):
    if c.busy():
        return
    try:
        await start_variants(c, c.ag.session, int(m.get("turn", 0)), "before" if m.get("where") == "before" else "after",
                             [str(x) for x in m.get("prompts", [])])
        await c.broadcast({"type": "runs", "runs": [r.info() for r in RUNS.values()]})
    except Exception as e:
        await c.send({"type": "notice", "text": f"Cannot start variants: {e}"})


@handler("runs")
async def on_runs(c: Conn, m: dict):
    await c.send({"type": "runs", "runs": [r.info() for r in RUNS.values()]})


@handler("stop_run")
async def on_stop_run(c: Conn, m: dict):
    r = RUNS.get(m.get("id", ""))
    if r and r.task and not r.task.done():
        r.task.cancel()


@handler("adopt")
async def on_adopt(c: Conn, m: dict):
    """Copy the files a variant changed into the original project; files changed in both places are left alone."""
    s2 = A.load(m.get("id", ""))
    wt = (s2 or {}).get("worktree")
    if not wt or wt.get("removed"):
        await c.send({"type": "notice", "text": "That session has no copy of the project to take files from."})
        return
    res = await asyncio.to_thread(W.adopt, Path(wt["origin"]), Path(wt["path"]), wt["base"])
    await c.send({"type": "adopted", "id": s2["id"], **res})
    await c.send({"type": "fs"})
    learning.learn_adopted_later(client, s2, wt)


@handler("discard")
async def on_discard(c: Conn, m: dict):
    s2 = A.load(m.get("id", ""))
    wt = (s2 or {}).get("worktree")
    if not wt or wt.get("removed"):
        return
    r = RUNS.get(s2["id"])
    if r and r.task and not r.task.done():
        r.task.cancel()
    await asyncio.to_thread(W.remove, Path(wt["path"]))
    wt["removed"] = True
    await asyncio.to_thread(learning.forget_session, s2)
    A.save(s2)
    RUNS.pop(s2["id"], None)
    await c.broadcast({"type": "runs", "runs": [r.info() for r in RUNS.values()]})
    await c.send({"type": "notice", "text": "The copy of the project was removed. The conversation of that session is kept."})


@handler("fork")
async def on_fork(c: Conn, m: dict):
    """A new session based on this one: keep the turns up to `turn` (after) or up to the one before it (before, edit and retry)."""
    if c.busy():
        return
    try:
        new, restore = A.fork_session(c.ag.session, int(m.get("turn", 0)), "before" if m.get("where") == "before" else "after")
        A.save(new)
        c.ag.session = new
        prefill = ""
        if m.get("where") == "before":
            parent = A.load(new["parent"]["id"])
            prefill = parent["messages"][A.user_positions(parent["messages"])[new["parent"]["turn"]]]["content"]
        await c.send({"type": "forked", "session": new, "restore": restore, "prefill": prefill})
    except Exception as e:
        await c.send({"type": "notice", "text": f"Cannot branch: {e}"})


@handler("pin")
async def on_pin(c: Conn, m: dict):
    pins = set(c.ag.session.get("pins", []))
    (pins.add if m.get("on") else pins.discard)(int(m["turn"]))
    c.ag.session["pins"] = sorted(pins)
    A.save(c.ag.session)
    await c.send({"type": "pins", "pins": c.ag.session["pins"]})


@handler("titles")
async def on_titles(c: Conn, m: dict):
    async def go():
        titles = await c.ag.make_titles(c.ag.session)
        await c.send({"type": "titles", "titles": titles, "session": c.ag.session["id"]})
    asyncio.create_task(go())


@handler("set_todos")
async def on_set_todos(c: Conn, m: dict):
    items = [{"content": str(i.get("content", ""))[:300], "status": i.get("status") if i.get("status") in ("pending", "in_progress", "completed") else "pending"}
             for i in m.get("items", []) if str(i.get("content", "")).strip()][:40]
    c.ag.session["todos"] = items
    A.save(c.ag.session)
    await c.send({"type": "todos", "items": items})


@handler("compact")
async def on_compact(c: Conn, m: dict):
    if c.busy():
        return
    try:
        r = await c.ag.compact(c.cfg["model"], c.cfg["num_ctx"], str(m.get("focus", "")))
        await c.send({"type": "compacted", "session": c.ag.session, "auto": False, **r})
    except Exception as e:
        await c.send({"type": "notice", "text": f"Compact failed: {e}"})


@handler("kill")
async def on_kill(c: Conn, m: dict):
    c.ag.procs.kill(m["id"])


@handler("root")
async def on_root(c: Conn, m: dict):
    if c.busy():
        return
    c.cfg["root"] = preview_root["path"] = m["root"]
    asyncio.create_task(c.ag.sync_mcp(m["root"]))


@handler("mcp_reload")
async def on_mcp_reload(c: Conn, m: dict):
    if not c.busy():
        asyncio.create_task(c.ag.sync_mcp(c.cfg["root"]))


@handler("open")
async def on_open(c: Conn, m: dict):
    if c.busy():
        return
    run = RUNS.get(m["id"])
    if run and run.status in ("running", "waiting"):
        await c.send({"type": "session", "session": run.agent.session, "live": True})
        return
    s = A.load(m["id"])
    if s:
        c.ag.session = s
        c.cfg["root"] = preview_root["path"] = s["root"]
        await c.send({"type": "session", "session": s})
        asyncio.create_task(c.ag.sync_mcp(s["root"]))


@handler("new")
async def on_new(c: Conn, m: dict):
    if c.busy():
        return
    c.ag.session = A.new_session(c.cfg["root"])
    await c.send({"type": "session", "session": c.ag.session})


# --- the live browser: the UI's own clicks, keys and navigation go to the shared Chrome
FAST_BROWSER = {"b_mouse", "b_key", "b_text", "b_resume", "b_scrollto", "b_rec_start", "b_rec_stop"}      # keep ordered; the rest may take seconds


async def browser_msg(c: Conn, m: dict):
    t = m["type"]
    try:
        if t == "b_sub":
            BROWSER.subs.add(c.send)
            if BROWSER.alive:
                for msg in await BROWSER.snapshot():
                    await c.send(msg)
        elif t == "b_open":
            BROWSER.subs.add(c.send)
            await BROWSER.ensure()
            for msg in await BROWSER.snapshot():
                await c.send(msg)
        elif t == "b_resume":
            if BROWSER.handoff and not BROWSER.handoff.done():
                BROWSER.handoff.set_result(True)
        elif t == "b_nav":
            BROWSER.subs.add(c.send)
            if BROWSER.recorder:
                BROWSER.recorder.navigate(m["url"])
            await BROWSER.navigate(m["url"])      # starts the browser if needed
        elif t == "b_rec_start":
            BROWSER.recorder = flows.Recorder(BROWSER.url)
            await c.broadcast({"type": "b_rec", "on": True, "steps": 0})
        elif t == "b_rec_stop":
            rec, BROWSER.recorder = BROWSER.recorder, None
            if rec:
                rec.flush()
                name = str(m.get("name") or f"flow {time.strftime('%H:%M')}")[:60]
                if rec.steps and not m.get("discard"):
                    f = flows.save(Path(c.cfg["root"]), name, rec.steps, rec.start_url, bool(m.get("check")))
                    await c.send({"type": "notice", "text": f"Flow \"{name}\" saved with {len(rec.steps)} steps ({f.relative_to(Path(c.cfg['root']))}). The agent can replay it with browser_flow."})
            await c.broadcast({"type": "b_rec", "on": False, "steps": len(rec.steps) if rec else 0})
        elif not BROWSER.alive:
            return
        elif t == "b_back":
            await BROWSER.history(-1)
        elif t == "b_fwd":
            await BROWSER.history(1)
        elif t == "b_reload":
            await BROWSER.reload()
        elif t == "b_reload_preview" and BROWSER.url.startswith(PREVIEW_URL):
            await BROWSER.reload()
        elif t == "b_viewport":
            await BROWSER.set_viewport(m["w"], m["h"])
        elif t == "b_mouse":
            await BROWSER.user_mouse(m)
        elif t == "b_key":
            await BROWSER.user_key(m)
        elif t == "b_text":
            await BROWSER.insert(m["text"])
        elif t == "b_scrollto":
            await BROWSER.scroll_to(m.get("x"), m.get("y"), m.get("dx", 0), m.get("dy", 0))
    except Exception as e:
        await c.send({"type": "b_status", "state": "error", "error": str(e)})


# --- parallel variants: sessions of their own, each in its own worktree, driven in the background
async def start_variants(c: Conn, base: dict, turn: int, where: str, prompts: list[str]) -> list[dict]:
    out = []
    for i, prompt in enumerate([p for p in prompts if p.strip()][:4]):
        new, restore = A.fork_session(base, turn, where)
        origin = Path(base["root"])
        proj, basesha = await asyncio.to_thread(W.create, origin, new["id"], restore["sha"] if restore else None)
        new["root"] = str(proj)
        new["worktree"] = {"path": str(proj), "base": basesha, "origin": str(origin)}
        new["title"] = f"Variant {chr(65 + i)} · {prompt.strip().splitlines()[0]}"[:60]
        A.save(new)
        run = Run(new["id"], new["title"], None)

        async def sink(ev, run=run):
            t = ev.get("type")
            if t == "tool":
                run.steps += 1
                run.last = f"{ev['name']} {ev.get('label', '')}"[:80]
            elif t == "approval":
                run.status, run.last = "waiting", f"waiting for approval: {ev['name']}"
            elif t == "result" and run.status == "waiting":
                run.status = "running"
            elif t == "notice":
                run.last = ev["text"][:80]
            await c.broadcast({"type": "run_event", "run": run.sid, "event": ev, "info": run.info()})

        run.agent = A.Agent(sink, client, BROWSER)
        run.agent.session = new
        run.last = prompt.strip().replace("\n", " ")[:80]
        RUNS[new["id"]] = run
        AGENTS.add(run.agent)
        cfg = c.cfg

        async def drive(run=run, prompt=prompt):
            try:
                await run.agent.turn(prompt, cfg["model"], bool(cfg["think"]), cfg["mode"], cfg["num_ctx"], review_on=bool(cfg.get("review", True)))
                run.status = "done"
            except asyncio.CancelledError:
                run.status = "stopped"
            except Exception as e:
                run.status, run.last = "error", str(e)[:80]
            finally:
                AGENTS.discard(run.agent)
                await c.broadcast({"type": "run_status", "info": run.info()})

        run.task = asyncio.create_task(drive())
        out.append(run.info())
    return out


@app.websocket("/ws")
async def ws(sock: WebSocket):
    # Only the UI served by this very host may drive the agent (blocks other web pages and DNS rebinding).
    host, origin = sock.headers.get("host", ""), sock.headers.get("origin", "")
    if origin != f"http://{host}" or not host.split(":")[0] in ("127.0.0.1", "localhost"):
        await sock.close(code=1008)
        return
    await sock.accept()
    c = Conn(sock)
    wtask = asyncio.create_task(c.writer())
    MIRROR[id(c)] = c.direct
    AGENTS.add(c.ag)
    for other in AGENTS:                      # joining while a turn runs: show it from the start, including what it waits for
        if other is not c.ag and other.running:
            await c.direct({"type": "turn_start", "session": other.session})
            for ev in list(other.pending_info.values()):
                await c.direct(ev)
    c.ag.session = A.new_session(c.cfg["root"])
    asyncio.create_task(c.ag.sync_mcp(c.cfg["root"]))
    try:
        while True:
            m = await sock.receive_json()
            t = m.get("type")
            if not isinstance(t, str):
                continue
            if t.startswith("b_"):
                if t in FAST_BROWSER:
                    await browser_msg(c, m)
                else:
                    asyncio.create_task(browser_msg(c, m))
            elif (h := HANDLERS.get(t)):
                await h(c, m)
    except WebSocketDisconnect:
        pass
    finally:
        BROWSER.subs.discard(c.send)
        MIRROR.pop(id(c), None)
        AGENTS.discard(c.ag)
        wtask.cancel()
        if c.busy():
            c.task.cancel()
        await c.ag.shutdown()


app.mount("/static", StaticFiles(directory=WEB), name="static")
