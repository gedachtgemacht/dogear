"""MCP over Streamable HTTP against a tiny in-process server: plain JSON answers, SSE answers with a server
ping on the way, session id echo, tool call, error mapping. usage: uv run python tests/check_mcp_http.py"""
import asyncio
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from dogear.mcp import MCP, HttpServer, MCPError  # noqa: E402

ok_all = True


def check(name, cond, extra=""):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


def make_app(sse: bool):
    app = FastAPI()
    seen = {"sessions": set(), "notified": 0, "auth": []}

    @app.post("/mcp")
    async def mcp(req: Request):
        m = await req.json()
        seen["auth"].append(req.headers.get("authorization", ""))
        if "id" not in m:                                   # notification
            seen["notified"] += 1
            return Response(status_code=202)
        if "method" not in m:                               # the client's answer to our ping
            seen["pong"] = m.get("id")
            return Response(status_code=202)
        rid, method, params = m["id"], m["method"], m.get("params") or {}
        headers = {}
        if method == "initialize":
            res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "toy", "version": "1"}}
            headers["Mcp-Session-Id"] = "sess-42"
        elif method == "tools/list":
            seen["sessions"].add(req.headers.get("mcp-session-id", ""))
            res = {"tools": [{"name": "add", "description": "adds", "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}}]}
        elif method == "tools/call":
            if params["name"] != "add":
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "unknown tool"}}
            if params["arguments"].get("a") == "boom":
                res = {"content": [{"type": "text", "text": "it broke"}], "isError": True}
            else:
                res = {"content": [{"type": "text", "text": str(params["arguments"]["a"] + params["arguments"]["b"])}]}
        else:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "no such method"}}
        answer = {"jsonrpc": "2.0", "id": rid, "result": res}
        if not sse:
            return Response(json.dumps(answer), media_type="application/json", headers=headers)

        async def gen():
            yield "event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": 999, "method": "ping"}) + "\n\n"   # server request first
            yield ": keep-alive\n\n"
            yield "data: " + json.dumps(answer) + "\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)

    @app.delete("/mcp")
    async def end(req: Request):
        seen["deleted"] = req.headers.get("mcp-session-id", "")
        return Response(status_code=204)

    return app, seen


def serve(app, port):
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    return srv


async def run(sse: bool, port: int):
    app, seen = make_app(sse)
    srv = serve(app, port)
    await asyncio.sleep(0.8)
    try:
        s = HttpServer("toy", {"url": f"http://127.0.0.1:{port}/mcp", "headers": {"Authorization": "Bearer t0k"}}, Path("."))
        await s.start()
        tag = "sse" if sse else "json"
        check(f"{tag}: ready", s.state == "ready", s.error)
        check(f"{tag}: tool listed", [t["name"] for t in s.tools] == ["add"])
        check(f"{tag}: session id echoed", seen["sessions"] == {"sess-42"}, str(seen["sessions"]))
        check(f"{tag}: initialized notification sent", seen["notified"] == 1, str(seen["notified"]))
        check(f"{tag}: custom header sent", all(a == "Bearer t0k" for a in seen["auth"]))
        check(f"{tag}: call works", await s.call("add", {"a": 2, "b": 3}) == "5")
        try:
            await s.call("add", {"a": "boom", "b": 1})
            check(f"{tag}: isError raises", False)
        except MCPError as e:
            check(f"{tag}: isError raises", "it broke" in str(e))
        try:
            await s.call("nope", {})
            check(f"{tag}: jsonrpc error raises", False)
        except MCPError as e:
            check(f"{tag}: jsonrpc error raises", "unknown tool" in str(e))
        await s.close()
        check(f"{tag}: session deleted on close", seen.get("deleted") == "sess-42")
        if sse:
            check("sse: server ping on the stream was answered", seen.get("pong") == 999, str(seen.get("pong")))
    finally:
        srv.should_exit = True


async def main():
    await run(False, 18765)
    await run(True, 18766)
    # config routing: url -> HttpServer, command -> stdio Server, neither -> unsupported
    m = MCP()
    cfg = {"h": {"url": "http://127.0.0.1:1/mcp"}, "bad": {}}
    m._config = staticmethod(lambda root: cfg)   # type: ignore[method-assign]
    st = {x["name"]: x for x in await m.sync(Path("."))}
    check("url config becomes an HTTP server", isinstance(m.servers["h"], HttpServer) and st["h"]["state"] == "error")
    check("empty config is reported, not crashed", st["bad"]["state"] == "unsupported")
    await m.close()


asyncio.run(main())
print("ALL PASS" if ok_all else "SOME FAILED")
sys.exit(0 if ok_all else 1)
