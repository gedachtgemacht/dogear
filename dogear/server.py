"""HTTP + WebSocket + live preview. Binds to 127.0.0.1 only."""
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import uvicorn

from . import agent as A
from . import browser as br
from . import llm, tools
from .brand import NAME

WEB = Path(__file__).resolve().parent.parent / "web"
SETTINGS = A.DATA / "settings.json"
DEFAULTS = {"model": "qwen3.6:35b-a3b", "think": False, "mode": "edit", "num_ctx": 32768,
            "root": str(A.DATA.parent / "werkstatt")}
OLD_MODES = {"vorsicht": "ask", "werkeln": "edit", "frei": "auto"}
client: httpx.AsyncClient
preview_root = {"path": DEFAULTS["root"]}
BROWSER: br.Browser
AGENTS: set = set()      # one Agent per open UI connection
MIRROR: dict = {}        # connection id -> direct sender; lets a second window watch a running turn
PREVIEW_URL = f"http://127.0.0.1:{br.PREVIEW_PORT}"
NOCACHE = {"Cache-Control": "no-store"}

# Project files are served from a different origin than the UI, so pages the agent writes
# (or visits) can never talk to the agent's own API or WebSocket.
preview_app = FastAPI()


@preview_app.get("/{path:path}")
async def preview(path: str):
    ctx = tools.Ctx(Path(preview_root["path"]))
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
        ms = await llm.models(client)
    except Exception:
        ms = []
    return {"settings": settings(), "models": ms, "sessions": A.listing(), "name": NAME, "preview": PREVIEW_URL}


@app.get("/api/tree")
async def tree(root: str, path: str = "."):
    ctx = tools.Ctx(Path(root))
    try:
        entries = sorted(ctx.path(path).iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    except (tools.ToolError, OSError) as e:
        raise HTTPException(400, str(e))
    return [{"name": e.name, "dir": e.is_dir(), "path": ctx.rel(e)}
            for e in entries if e.name not in tools.SKIP_DIRS and not e.name.startswith(".")]


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
        except Exception as e:
            await send({"type": "b_status", "state": "error", "error": str(e)})

    wtask = asyncio.create_task(writer())
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
    asyncio.create_task(ag.sync_mcp(cfg["root"]))
    try:
        while True:
            m = await sock.receive_json()
            t = m.get("type")
            if t == "user" and not busy():
                cfg.update({k: m[k] for k in ("model", "think", "mode", "root") if k in m})
                cfg["num_ctx"] = int(m.get("num_ctx", cfg["num_ctx"]))
                SETTINGS.write_text(json.dumps(cfg))
                if not Path(cfg["root"]).is_dir():
                    await send({"type": "error", "text": f"Project directory does not exist: {cfg['root']}"})
                    await send({"type": "done"})
                    continue
                ag.session["root"] = preview_root["path"] = cfg["root"]
                task = asyncio.create_task(
                    ag.turn(m["text"], cfg["model"], bool(cfg["think"]), cfg["mode"], cfg["num_ctx"]))
            elif t == "approve":
                for a in AGENTS:              # the approval may belong to a turn started in another window
                    if m["id"] in a.pending:
                        a.answer(m["id"], bool(m["ok"]), bool(m.get("always")), m.get("key", ""))
            elif t == "stop" and busy():
                task.cancel()
            elif t.startswith("b_"):
                if t in ("b_mouse", "b_key", "b_text", "b_resume"):   # fast, keep ordered
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
