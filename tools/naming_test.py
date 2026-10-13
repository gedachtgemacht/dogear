"""Automatic topic names and branch notes. usage: uv run python tools/naming_test.py"""
import asyncio, json, sys
import httpx, websockets
ROOT = "/home/user/dogear/projects/naming"
URL, ORIGIN = "ws://127.0.0.1:7870/ws", "http://127.0.0.1:7870"
M = {"model": "qwen3.6:35b-a3b", "think": False, "mode": "auto", "root": ROOT, "num_ctx": 32768, "review": False}

async def wait_for(ws, kinds, timeout=240):
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if m["type"] in kinds: return m

async def main():
    import os; os.makedirs(ROOT, exist_ok=True)
    async with websockets.connect(URL, max_size=None, origin=ORIGIN) as ws:
        await ws.send(json.dumps({"type": "new"}))
        await ws.send(json.dumps({"type": "user", "text": "Schreibe eine kurze Produktbeschreibung (etwa 60 Wörter) für ein Taschennotizbuch mit Leinenumschlag. Nur Text, keine Dateien.", **M}))
        await wait_for(ws, {"done"})
        r1 = await wait_for(ws, {"renamed"}, 60)
        print("root :", repr(r1["title"]), "| note:", repr(r1["note"]))
        await ws.send(json.dumps({"type": "fork", "turn": 0, "where": "after"}))
        await wait_for(ws, {"forked"})
        await ws.send(json.dumps({"type": "user", "text": "Schreibe stattdessen ein vierzeiliges Gedicht darüber, ohne Reime auf -ung.", **M}))
        await wait_for(ws, {"done"})
        r2 = await wait_for(ws, {"renamed"}, 60)
        print("branch:", repr(r2["title"]), "| note:", repr(r2["note"]))
    st = json.load(__import__("urllib.request").request.urlopen("http://127.0.0.1:7870/api/state"))
    for s in st["sessions"]:
        print(" -", s["title"], "| parent:", bool(s["parent"]), "| note:", s["note"])
    ok = r1["title"] and "(branch)" not in r2["title"] and r2["note"] and r1["note"] == ""
    print("PASS" if ok else "FAIL")
asyncio.run(main())
