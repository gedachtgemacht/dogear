"""HTTP + WebSocket + live preview. Binds to 127.0.0.1 only."""
import asyncio
import json
import os
import time
from collections import deque
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
from . import library
from .brand import NAME

WEB = Path(__file__).resolve().parent.parent / "web"
SETTINGS = A.DATA / "settings.json"
DEFAULTS = {"model": "qwen3.6:35b-a3b", "think": False, "mode": "edit", "num_ctx": 32768, "review": True,
            "root": str(A.DATA.parent / "projects")}
OLD_MODES = {"vorsicht": "ask", "werkeln": "edit", "frei": "auto"}
client: httpx.AsyncClient
preview_root = {"path": DEFAULTS["root"]}
BROWSER: br.Browser
AGENTS: set = set()      # one Agent per open UI connection, plus the background branch runs


class Run:
    """A branch run that works in its own worktree, independent of any browser window."""
    def __init__(self, sid: str, title: str, agent):
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
    s["mode"] = OLD_MODES.get(s["mode"], s["mode"])
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


@app.websocket("/ws")
async def ws(sock: WebSocket):
    # Only the UI served by this very host may drive the agent (blocks other web pages and DNS rebinding).
    host, origin = sock.headers.get("host", ""), sock.headers.get("origin", "")
    if origin != f"http://{host}" or not host.split(":")[0] in ("127.0.0.1", "localhost"):
        await sock.close(code=1008)
        return
    await sock.accept()

    # Every connection has its own outbound queue and writer task, so a slow or throttled window
    # can never stall the agent (or another window). Frames are dropped first when a client lags.
    outq: asyncio.Queue = asyncio.Queue()

    async def writer():
        try:
            while True:
                await sock.send_json(await outq.get())
        except Exception:
            pass

    async def direct(m):
        if m.get("type") == "frame" and outq.qsize() > 60:
            return
        outq.put_nowait(m)

    async def mirror(m):
        for d in list(MIRROR.values()):
            if d is not direct:
                await d(m)

    async def send(m):
        await direct(m)
        await mirror(m)

    async def browser_msg(m, send):
        t = m["type"]
        try:
            if t == "b_sub":
                BROWSER.subs.add(send)
                if BROWSER.alive:
                    for msg in await BROWSER.snapshot():
                        await send(msg)
            elif t == "b_open":
                BROWSER.subs.add(send)
                await BROWSER.ensure()
                for msg in await BROWSER.snapshot():
                    await send(msg)
            elif t == "b_resume":
                if BROWSER.handoff and not BROWSER.handoff.done():
                    BROWSER.handoff.set_result(True)
            elif t == "b_nav":
                BROWSER.subs.add(send)
                await BROWSER.navigate(m["url"])      # starts the browser if needed
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
            await send({"type": "b_status", "state": "error", "error": str(e)})

    wtask = asyncio.create_task(writer())
    async def broadcast(msg):
        for d in list(MIRROR.values()):
            await d(msg)

    async def start_variants(base: dict, turn: int, where: str, prompts: list[str]):
        out = []
        for i, prompt in enumerate([p for p in prompts if p.strip()][:4]):
            new, restore = A.fork_session(base, turn, where)
            origin = Path(base["root"])
            proj, basesha = await asyncio.to_thread(W.create, origin, new["id"], restore["sha"] if restore else None)
            new["root"] = str(proj)
            new["worktree"] = {"path": str(proj), "base": basesha, "origin": str(origin)}
            new["title"] = f"Variant {chr(65 + i)} · {prompt.strip().splitlines()[0]}"[:60]
            A.save(new)
            holder = {}

            async def sink(ev, holder=holder):
                run = holder["run"]
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
                await broadcast({"type": "run_event", "run": run.sid, "event": ev, "info": run.info()})

            agent = A.Agent(sink, client, BROWSER)
            agent.session = new
            run = Run(new["id"], new["title"], agent)
            run.last = prompt.strip().replace("\n", " ")[:80]
            holder["run"] = run
            RUNS[new["id"]] = run
            AGENTS.add(agent)

            async def drive(run=run, prompt=prompt):
                try:
                    await run.agent.turn(prompt, cfg["model"], bool(cfg["think"]), cfg["mode"], cfg["num_ctx"], bool(cfg.get("review", True)), False, None)
                    run.status = "done"
                except asyncio.CancelledError:
                    run.status = "stopped"
                except Exception as e:
                    run.status, run.last = "error", str(e)[:80]
                finally:
                    AGENTS.discard(run.agent)
                    await broadcast({"type": "run_status", "info": run.info()})

            run.task = asyncio.create_task(drive())
            out.append(run.info())
        return out

    async def _titles(agent, send_):
        s = agent.session
        titles = await agent.make_titles(s)
        await send_({"type": "titles", "titles": titles, "session": s["id"]})

    ag = A.Agent(send, client, BROWSER)
    ag.mirror = mirror
    MIRROR[id(direct)] = direct
    AGENTS.add(ag)
    for other in AGENTS:                      # joining while a turn runs: show it from the start
        if other is not ag and other.running:
            await direct({"type": "turn_start", "session": other.session})
    cfg = settings()
    ag.session = A.new_session(cfg["root"])
    task: asyncio.Task | None = None
    busy = lambda: bool(task and not task.done())

    def start_turn(text, mode=None, images=()):
        nonlocal task
        ag.session["root"] = preview_root["path"] = cfg["root"]
        task = asyncio.create_task(ag.turn(text, cfg["model"], bool(cfg["think"]), mode or cfg["mode"], cfg["num_ctx"],
                                           bool(cfg.get("review", True)), False, list(images)))
        ag.turn_task = task

    def last_plan_message():
        return next((m for m in reversed(ag.session["messages"]) if m.get("plan")), None)
    asyncio.create_task(ag.sync_mcp(cfg["root"]))
    try:
        while True:
            m = await sock.receive_json()
            t = m.get("type")
            if t == "user" and not busy():
                cfg.update({k: m[k] for k in ("model", "think", "mode", "root", "review") if k in m})
                cfg["num_ctx"] = int(m.get("num_ctx", cfg["num_ctx"]))
                if "mozilla" in sock.headers.get("user-agent", "").lower():
                    SETTINGS.write_text(json.dumps(cfg))
                if not Path(cfg["root"]).is_dir():
                    await send({"type": "error", "text": f"Project directory does not exist: {cfg['root']}"})
                    await send({"type": "done"})
                    continue
                ag.session["root"] = preview_root["path"] = cfg["root"]
                task = asyncio.create_task(
                    ag.turn(m["text"], cfg["model"], bool(cfg["think"]), cfg["mode"], cfg["num_ctx"],
                            bool(cfg.get("review", True)), False, [i for i in m.get("images", []) if isinstance(i, str)][:4]))
                ag.turn_task = task
            elif t in ("plan_approve", "plan_reject") and not busy():
                pm = last_plan_message()
                if not pm or pm["plan"].get("status") != "proposed":
                    await send({"type": "notice", "text": "There is no plan waiting for approval."})
                    continue
                if t == "plan_approve":
                    edited = []
                    for it in (m.get("tasks") or [])[:20]:
                        c = " ".join(str(it.get("content", "") if isinstance(it, dict) else it).split())[:300]
                        if len(c) >= 2:
                            edited.append({"content": c, "detail": " ".join(str(it.get("detail", "") if isinstance(it, dict) else "").split())[:600]})
                    if not edited:
                        await send({"type": "notice", "text": "The plan has no tasks left."})
                        continue
                    pm["plan"].update(status="approved", tasks=edited)
                    ag.session["todos"] = [{"content": t_["content"], "status": "pending"} for t_ in edited]
                    A.save(ag.session)
                    await send({"type": "plan_status", "status": "approved", "tasks": edited})
                    await send({"type": "todos", "items": ag.session["todos"]})
                    mode = m.get("mode") if m.get("mode") in ("ask", "edit", "auto") else "edit"
                    cfg["mode"] = mode
                    detail = "\n".join(f"- {t_['content']}" + (f" ({t_['detail']})" if t_["detail"] else "") for t_ in edited)
                    start_turn("The plan is approved. Carry it out task by task, in order, and keep the task list current with TodoWrite "
                               "(exactly one task in_progress). Do not add scope.\n\nApproved plan:\n" + detail, mode)
                else:
                    fb = str(m.get("feedback", "")).strip()[:2000] or "The user did not like the plan. Rethink it."
                    pm["plan"].update(status="rejected", feedback=fb)
                    A.save(ag.session)
                    await send({"type": "plan_status", "status": "rejected", "feedback": fb})
                    start_turn("The plan was rejected. Feedback from the user:\n" + fb +
                               "\n\nRevise the plan and submit it again with kanban_create_tasks.", "plan")
            elif t == "rate":
                # rating the finished run is the gate for the library: only good runs may teach
                pos = A.user_positions(ag.session["messages"])
                i = int(m.get("turn", -1))
                if not (0 <= i < len(pos)):
                    continue
                end = pos[i + 1] if i + 1 < len(pos) else len(ag.session["messages"])
                msgs = ag.session["messages"]
                sm_msg = next((x for x in reversed(msgs[pos[i]:end]) if x.get("summary")), None)
                if not sm_msg:
                    await send({"type": "notice", "text": "That turn has no finished run to rate."})
                    continue
                val = 1 if float(m.get("value", 0)) > 0 else -1
                prev = sm_msg.get("rating") or {}
                rating = {"value": val, "note": str(m.get("note", ""))[:500], "at": time.time(), "extracted": bool(prev.get("extracted"))}
                sm_msg["rating"] = rating
                sm_msg["summary"]["rating"] = rating
                A.save(ag.session)
                await send({"type": "rated", "turn": i, "rating": rating})
                if val > 0 and not rating["extracted"]:
                    rating["extracted"] = True
                    A.save(ag.session)
                    request = msgs[pos[i]]["content"]
                    changed = [c["path"] for c in sm_msg["summary"].get("changes", [])]
                    root_, model_ = ag.session["root"], cfg["model"]

                    async def learn(i=i, request=request, answer=sm_msg.get("content", ""), changed=changed, root_=root_, model_=model_, rating=rating, sess=ag.session):
                        try:
                            items = await library.extract(client, llm.URL, model_, Path(root_), request, answer, changed)
                            saved = []
                            for it in items:
                                r = await library.add(client, llm.URL, it)
                                saved.append({"id": r["id"], "problem": it["problem"], "language": it["language"], "replaced": r["replaced"]})
                            rating["saved"] = saved
                            A.save(sess)
                            await send({"type": "library_saved", "turn": i, "entries": saved})
                        except Exception as e:
                            await send({"type": "library_saved", "turn": i, "entries": [], "error": str(e)[:120]})
                    asyncio.create_task(learn())
            elif t == "approve":
                for a in AGENTS:              # the approval may belong to a turn started in another window
                    if m["id"] in a.pending:
                        a.answer(m["id"], bool(m["ok"]), bool(m.get("always")), m.get("key", ""))
            elif t == "answer":
                for a in AGENTS:
                    if m["id"] in a.asks:
                        a.answer_ask(m["id"], m.get("value", ""))
            elif t == "undo" and not busy():
                root = Path(m.get("root", ""))
                if str(root) in (ag.session["root"], cfg["root"]):
                    touched = await asyncio.to_thread(cpt.restore, root, str(m["to"]))
                    await send({"type": "undone", "files": touched})
                    await send({"type": "fs"})
            elif t == "variants" and not busy():
                try:
                    runs = await start_variants(ag.session, int(m.get("turn", 0)), "before" if m.get("where") == "before" else "after",
                                                [str(x) for x in m.get("prompts", [])])
                    await broadcast({"type": "runs", "runs": [r.info() for r in RUNS.values()]})
                except Exception as e:
                    await send({"type": "notice", "text": f"Cannot start variants: {e}"})
            elif t == "runs":
                await send({"type": "runs", "runs": [r.info() for r in RUNS.values()]})
            elif t == "stop_run":
                r = RUNS.get(m.get("id", ""))
                if r and r.task and not r.task.done():
                    r.task.cancel()
            elif t == "adopt":
                s2 = A.load(m.get("id", ""))
                wt = (s2 or {}).get("worktree")
                if not wt or wt.get("removed"):
                    await send({"type": "notice", "text": "That branch has no worktree to adopt."})
                else:
                    res = await asyncio.to_thread(W.adopt, Path(wt["origin"]), Path(wt["path"]), wt["base"])
                    await send({"type": "adopted", "id": s2["id"], **res})
                    await send({"type": "fs"})
            elif t == "discard":
                s2 = A.load(m.get("id", ""))
                wt = (s2 or {}).get("worktree")
                if wt and not wt.get("removed"):
                    r = RUNS.get(s2["id"])
                    if r and r.task and not r.task.done():
                        r.task.cancel()
                    await asyncio.to_thread(W.remove, Path(wt["path"]))
                    wt["removed"] = True
                    A.save(s2)
                    RUNS.pop(s2["id"], None)
                    await broadcast({"type": "runs", "runs": [r.info() for r in RUNS.values()]})
                    await send({"type": "notice", "text": "Worktree removed. The conversation of that branch is kept."})
            elif t == "fork" and not busy():
                try:
                    new, restore = A.fork_session(ag.session, int(m.get("turn", 0)), "before" if m.get("where") == "before" else "after")
                    A.save(new)
                    ag.session = new
                    prefill = ""
                    if m.get("where") == "before":
                        pos = A.user_positions(A.load(new["parent"]["id"])["messages"])
                        prefill = A.load(new["parent"]["id"])["messages"][pos[new["parent"]["turn"]]]["content"]
                    await send({"type": "forked", "session": new, "restore": restore, "prefill": prefill})
                except Exception as e:
                    await send({"type": "notice", "text": f"Cannot branch: {e}"})
            elif t == "pin":
                pins = set(ag.session.get("pins", []))
                (pins.add if m.get("on") else pins.discard)(int(m["turn"]))
                ag.session["pins"] = sorted(pins)
                A.save(ag.session)
                await send({"type": "pins", "pins": ag.session["pins"]})
            elif t == "titles":
                asyncio.create_task(_titles(ag, send))
            elif t == "set_todos":
                items = [{"content": str(i.get("content", ""))[:300], "status": i.get("status") if i.get("status") in ("pending", "in_progress", "completed") else "pending"}
                         for i in m.get("items", []) if str(i.get("content", "")).strip()][:40]
                ag.session["todos"] = items
                A.save(ag.session)
                await send({"type": "todos", "items": items})
            elif t == "compact" and not busy():
                try:
                    r = await ag.compact(cfg["model"], cfg["num_ctx"], str(m.get("focus", "")))
                    await send({"type": "compacted", "session": ag.session, "auto": False, **r})
                except Exception as e:
                    await send({"type": "notice", "text": f"Compact failed: {e}"})
            elif t == "stop":
                # a window can stop its own turn and also a turn that another window or a script started (view-only mirror)
                sid, stopped = m.get("id"), 0
                if busy() and (not sid or sid == ag.session["id"]):
                    task.cancel(); stopped += 1
                for a in list(AGENTS):
                    tt = getattr(a, "turn_task", None)
                    if a is not ag and a.running and tt and not tt.done() and (not sid or a.session["id"] == sid):
                        tt.cancel(); stopped += 1
                if sid in RUNS and RUNS[sid].task and not RUNS[sid].task.done():
                    RUNS[sid].task.cancel(); stopped += 1
                if not stopped:
                    await send({"type": "done"})        # nothing was running: release the window
            elif t.startswith("b_"):
                if t in ("b_mouse", "b_key", "b_text", "b_resume", "b_scrollto"):   # fast, keep ordered
                    await browser_msg(m, send)
                else:                                      # may take seconds (launch, navigation)
                    asyncio.create_task(browser_msg(m, send))
            elif t == "kill":
                ag.procs.kill(m["id"])
            elif t == "root" and not busy():
                cfg["root"] = preview_root["path"] = m["root"]
                asyncio.create_task(ag.sync_mcp(m["root"]))
            elif t == "mcp_reload" and not busy():
                asyncio.create_task(ag.sync_mcp(cfg["root"]))
            elif t == "open" and not busy() and RUNS.get(m["id"]) and RUNS[m["id"]].status in ("running", "waiting"):
                await send({"type": "session", "session": RUNS[m["id"]].agent.session, "live": True})
            elif t == "open" and not busy():
                s = A.load(m["id"])
                if s:
                    ag.session = s
                    cfg["root"] = preview_root["path"] = s["root"]
                    await send({"type": "session", "session": s})
                    asyncio.create_task(ag.sync_mcp(s["root"]))
            elif t == "new" and not busy():
                ag.session = A.new_session(cfg["root"])
                await send({"type": "session", "session": ag.session})
    except WebSocketDisconnect:
        pass
    finally:
        BROWSER.subs.discard(send)
        MIRROR.pop(id(direct), None)
        AGENTS.discard(ag)
        wtask.cancel()
        if busy():
            task.cancel()
        await ag.shutdown()


app.mount("/static", StaticFiles(directory=WEB), name="static")
