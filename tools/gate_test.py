"""End-to-end test of the automatic design-audit gate. usage: uv run python tools/gate_test.py"""
import asyncio, json, shutil, sys, tempfile, time
from pathlib import Path
import websockets
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dogear.browser import Browser
from dogear.audit import AUDIT_JS, format_report

ROOT = Path("/home/user/dogear/werkstatt/gate")
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Demo</title>
<style>body{margin:0;padding:24px;font:16px system-ui;background:#fff;color:#222}.note{color:#c4c4c4;font-size:11px}
.pad{display:grid;grid-template-columns:repeat(4,72px);grid-template-rows:repeat(3,56px);gap:8px;margin:16px 0}
.pad button{font-size:18px}.panel{height:260px;border:1px solid #ccd;background:#f3f4fa;border-radius:8px}</style></head><body>
<h1>Keypad demo</h1><p class="note">Press a key to see it appear in the panel below.</p>
<div class="pad">""" + "".join(f"<button>{k}</button>" for k in "1234567890") + """</div>
<div class="panel"><div></div></div></body></html>"""

async def audit(path):
    b = Browser(Path(tempfile.mkdtemp())); await b.ensure(); out = []
    for w, h in ((1280, 800), (390, 844)):
        await b.set_viewport(w, h); await b.navigate("file://" + str(path)); await asyncio.sleep(0.3); out.append(await b.eval(AUDIT_JS))
    await b.close(); return out

async def main():
    shutil.rmtree(ROOT, ignore_errors=True); ROOT.mkdir(parents=True); (ROOT / "index.html").write_text(PAGE)
    before = await audit(ROOT / "index.html")
    n = lambda rs: sum(1 for r in rs for f in r["findings"] if f["sev"] in ("high", "medium"))
    print("before: high/medium findings =", n(before))
    t0 = time.time(); notes, tools = [], []
    async with websockets.connect("ws://127.0.0.1:7870/ws", max_size=None, origin="http://127.0.0.1:7870") as ws:
        await ws.send(json.dumps({"type": "user", "text": "Change the page heading to 'Keypad playground'. Nothing else.", "model": "qwen3.6:35b-a3b",
                                  "think": False, "mode": "auto", "root": str(ROOT), "num_ctx": 32768, "review": False}))
        done = False
        while True:
            try: m = json.loads(await asyncio.wait_for(ws.recv(), 25 if done else 600))
            except asyncio.TimeoutError: break
            t = m["type"]
            if t == "tool": tools.append(m["name"])
            elif t == "notice": notes.append(m["text"])
            elif t == "done": done = True
            elif t == "present": break
    after = await audit(ROOT / "index.html")
    print(f"after:  high/medium findings = {n(after)}   ({int(time.time()-t0)}s)")
    print("notices:", notes); print("tools:", tools)
    print(format_report(after))

asyncio.run(main())
