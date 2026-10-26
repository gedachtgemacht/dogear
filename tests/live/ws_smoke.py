"""The WebSocket handlers that need no model: sessions, board, fork, pin, mode, stop, MCP reload, and the answers
to requests that make no sense right now. usage: uv run python tests/live/ws_smoke.py   (needs the server on 7870)"""
import asyncio
import json
import sys

import websockets

URL, ORIGIN = "ws://127.0.0.1:7870/ws", "http://127.0.0.1:7870"
ok_all = True


def check(name, cond):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name)


async def main():
    async with websockets.connect(URL, max_size=None, origin=ORIGIN) as ws:
        async def recv(kind, timeout=10):
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                if m["type"] == kind:
                    return m
        await ws.send(json.dumps({"type": "b_sub"}))
        await ws.send(json.dumps({"type": "runs"}))
        check("runs answers", "runs" in await recv("runs"))
        await ws.send(json.dumps({"type": "new"}))
        s = await recv("session")
        check("new session is empty", s["session"]["messages"] == [])
        sid = s["session"]["id"]
        await ws.send(json.dumps({"type": "set_todos", "items": [{"content": "a", "status": "pending"}, {"content": "b", "status": "in_progress"}]}))
        check("set_todos round trip", [x["status"] for x in (await recv("todos"))["items"]] == ["pending", "in_progress"])
        await ws.send(json.dumps({"type": "open", "id": sid}))
        check("open a stored session", (await recv("session"))["session"]["id"] == sid)
        await ws.send(json.dumps({"type": "pin", "turn": 0, "on": True}))
        check("pin", (await recv("pins"))["pins"] == [0])
        await ws.send(json.dumps({"type": "mode", "mode": "auto"}))
        await ws.send(json.dumps({"type": "stop", "id": None}))
        check("stop with nothing running releases the window", (await recv("done"))["type"] == "done")
        await ws.send(json.dumps({"type": "mcp_reload"}))
        check("mcp reload answers", "servers" in await recv("mcp"))
        await ws.send(json.dumps({"type": "rate", "turn": 99, "value": 1}))
        check("rating a missing turn is explained", "no finished run" in (await recv("notice"))["text"])
        await ws.send(json.dumps({"type": "plan_approve", "tasks": []}))
        check("approving without a plan is explained", "no plan" in (await recv("notice"))["text"])
        await ws.send(json.dumps({"type": "fork", "turn": 0, "where": "after"}))
        check("fork without turns is refused politely", (await recv("notice"))["type"] == "notice")
    print("ALL PASS" if ok_all else "SOME FAILED")
    sys.exit(0 if ok_all else 1)


asyncio.run(main())
