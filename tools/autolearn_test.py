"""A run that ends with passing tests teaches the library by itself (auto mark), and the entries go away again on 'Not good'.
usage: uv run python tools/autolearn_test.py   (needs the server on 7870)"""
import asyncio, json, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import websockets
from dogear import library as L

ok_all = True
def check(name, cond, extra=""):
    global ok_all; ok_all &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

async def main():
    root = Path("/home/user/dogear/projects/autolearn_e2e"); shutil.rmtree(root, ignore_errors=True); root.mkdir(parents=True)
    base = {"model": "qwen3.6:35b-a3b", "think": False, "root": str(root), "num_ctx": 32768, "review": False}
    before = {e["id"] for e in L.entries(300)}
    async def until(ws, kinds, timeout=500):
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            if m["type"] in kinds: return m
    async with websockets.connect("ws://127.0.0.1:7870/ws", max_size=None, origin="http://127.0.0.1:7870") as ws:
        await ws.send(json.dumps({"type": "new"}))
        await ws.send(json.dumps({"type": "user", "mode": "auto", "text": "Create roman.py with to_roman(n) for 1..3999 and from_roman(s), and test_roman.py with pytest tests (including 4, 9, 14, 1994, 3999 and a round trip). Run the tests with RunTests until they pass.", **base}))
        await until(ws, {"summary"})
        saved = await until(ws, {"library_saved"}, 400)
        print("  saved:", [(e["language"], e["problem"][:70]) for e in saved["entries"]])
        check("event is marked auto", saved.get("auto") is True)
        check("entries were saved", len(saved["entries"]) >= 1)
        new = [e for e in L.entries(300) if e["id"] not in before or e["id"] in {x["id"] for x in saved["entries"]}]
        check("entries carry the auto mark", all(e["auto"] for e in new if e["id"] in {x["id"] for x in saved["entries"]} and e["id"] not in before) and new)
        await ws.send(json.dumps({"type": "rate", "turn": 0, "value": -1, "note": "test"}))
        await until(ws, {"rated"}, 20)
        await asyncio.sleep(1)
        gone = {x["id"] for x in saved["entries"] if x["id"] not in before}
        left = gone & {e["id"] for e in L.entries(300)}
        check("'Not good' removes the auto entries again", not left, str(left))
    shutil.rmtree(root, ignore_errors=True)
    print("ALL PASS" if ok_all else "SOME FAILED"); sys.exit(0 if ok_all else 1)

asyncio.run(main())
