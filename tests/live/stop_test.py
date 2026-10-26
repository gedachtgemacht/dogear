"""Stopping a run from another connection and via the UI. usage: uv run python tests/live/stop_test.py"""
import asyncio
from pathlib import Path, json, time, urllib.request
import websockets
REPO = Path(__file__).resolve().parents[2]
URL, ORIGIN = "ws://127.0.0.1:7870/ws", "http://127.0.0.1:7870"
ROOT = (REPO / "projects" / "stoptest")

async def main():
    import os; os.makedirs(ROOT, exist_ok=True)
    a = await websockets.connect(URL, max_size=None, origin=ORIGIN)
    await a.send(json.dumps({"type": "new"}))
    await a.send(json.dumps({"type": "user", "text": "Run the shell command `sleep 60; echo finished` with the Bash tool and tell me what it printed.",
                             "model": "qwen3.6:35b-a3b", "think": False, "mode": "auto", "root": ROOT, "num_ctx": 32768, "review": False}))
    while True:                                    # wait until the tool is running
        m = json.loads(await asyncio.wait_for(a.recv(), 120))
        if m["type"] == "tool" and m["name"] == "Bash": break
    sid = next(s["id"] for s in json.load(urllib.request.urlopen("http://127.0.0.1:7870/api/state"))["sessions"] if s["root"] == ROOT)
    b = await websockets.connect(URL, max_size=None, origin=ORIGIN)          # a second window / script
    t = time.time()
    await b.send(json.dumps({"type": "stop", "id": sid}))
    got = []
    while True:
        m = json.loads(await asyncio.wait_for(a.recv(), 30))
        if m["type"] in ("notice", "done"): got.append(m["type"] + (":" + m.get("text", "") if m["type"] == "notice" else ""))
        if m["type"] == "done": break
    dt = time.time() - t
    print("stopped from second connection after %.1fs" % dt, got)
    ok = dt < 12
    # stopping when nothing runs must not hang a window
    await b.send(json.dumps({"type": "stop", "id": sid}))
    while True:                                    # b also received the mirrored events of the stopped run
        m = json.loads(await asyncio.wait_for(b.recv(), 10))
        if m["type"] == "done": break
    ok = ok and m["type"] == "done"
    left = [l for l in os.popen('pgrep -xa sleep').read().splitlines() if l.endswith(' 60')]
    print("leftover shell processes:", left)
    ok = ok and not left
    print("idle stop answers:", m["type"])
    print("PASS" if ok else "FAIL")
asyncio.run(main())
