"""Parallel branch runs in worktrees, end to end. usage: uv run python tests/live/variants_test.py"""
import asyncio, json, shutil, sys, time, urllib.request
from pathlib import Path
import websockets
REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "projects" / "variants"
URL, ORIGIN = "ws://127.0.0.1:7870/ws", "http://127.0.0.1:7870"
PAGE = "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Demo</title><style>button{background:#ccc;padding:8px 14px}</style></head><body><h1>Demo</h1><button id='go'>Go</button></body></html>\n"

async def main():
    shutil.rmtree(ROOT, ignore_errors=True); ROOT.mkdir(parents=True); (ROOT / "index.html").write_text(PAGE)
    async with websockets.connect(URL, max_size=None, origin=ORIGIN) as ws:
        await ws.send(json.dumps({"type": "user", "text": "In one sentence: what does index.html contain?", "model": "qwen3.6:35b-a3b", "think": False, "mode": "auto",
                                  "root": str(ROOT), "num_ctx": 32768, "review": False}))
        while json.loads(await asyncio.wait_for(ws.recv(), 120))["type"] != "done": pass
        t0 = time.time()
        await ws.send(json.dumps({"type": "variants", "turn": 0, "where": "after", "prompts": [
            "Change the CSS of the button in index.html so its background is red (#d32f2f) and the text white. Edit only index.html.",
            "Change the CSS of the button in index.html so its background is green (#2e7d32), text white, and make it larger (font-size 20px). Edit only index.html."]}))
        runs, done = {}, set()
        while len(done) < 2:
            m = json.loads(await asyncio.wait_for(ws.recv(), 300))
            if m["type"] == "runs": runs = {r["id"]: r for r in m["runs"]}; print("started:", [r["title"] for r in m["runs"]])
            if m["type"] == "run_status" and m["info"]["status"] in ("done", "error", "stopped"):
                done.add(m["info"]["id"]); runs[m["info"]["id"]] = m["info"]; print(f"  {m['info']['title'][-12:]} -> {m['info']['status']} after {int(time.time()-t0)}s, {m['info']['steps']} steps")
        ids = sorted(done)
        sess = {i: json.load(open(f(REPO / "data" / "sessions" / "{i}.json"))) for i in ids}
        for i in ids:
            wt = Path(sess[i]["worktree"]["path"]); txt = (wt / "index.html").read_text()
            print(f"worktree {wt.parent.name[-22:]}: red={'d32f2f' in txt.lower()} green={'2e7d32' in txt.lower()} size20={'20px' in txt}")
        print("main untouched:", (ROOT / "index.html").read_text() == PAGE)
        with urllib.request.urlopen(f"http://127.0.0.1:7871/@{ids[0]}/index.html") as r:
            body = r.read().decode(); print("preview of first variant serves its own file:", ("d32f2f" in body.lower()) or ("2e7d32" in body.lower()))
        red = next(i for i in ids if "d32f2f" in (Path(sess[i]["worktree"]["path"]) / "index.html").read_text().lower())
        green = next(i for i in ids if i != red)
        await ws.send(json.dumps({"type": "adopt", "id": red}))
        while (m := json.loads(await asyncio.wait_for(ws.recv(), 60)))["type"] != "adopted": pass
        print("adopt red: applied", m["applied"], "conflicts", m["conflicts"], "| main now red:", "d32f2f" in (ROOT / "index.html").read_text().lower())
        await ws.send(json.dumps({"type": "adopt", "id": green}))
        while (m := json.loads(await asyncio.wait_for(ws.recv(), 60)))["type"] != "adopted": pass
        print("adopt green after red: applied", m["applied"], "conflicts", m["conflicts"], "(expected: conflict, nothing overwritten)")
        print("main still red:", "d32f2f" in (ROOT / "index.html").read_text().lower())
        for i in ids:
            await ws.send(json.dumps({"type": "discard", "id": i}))
        await asyncio.sleep(1.5)
        print("worktrees removed:", all(not Path(sess[i]["worktree"]["path"]).exists() for i in ids))

asyncio.run(main())
