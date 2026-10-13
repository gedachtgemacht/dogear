"""Drive the real UI: build a session with a plan and a revision through the agent, then check rail, outline, pins, branch, compare, diff.
usage: uv run python tools/ui_features_test.py"""
import asyncio, base64, json, shutil, sys, tempfile, time
from pathlib import Path
import websockets
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dogear.browser import Browser

ROOT = Path("/home/user/dogear/werkstatt/ui-features")
URL, ORIGIN = "ws://127.0.0.1:7870/ws", "http://127.0.0.1:7870"

async def turn(ws, text, mode="auto"):
    await ws.send(json.dumps({"type": "user", "text": text, "model": "qwen3.6:35b-a3b", "think": False, "mode": mode, "root": str(ROOT), "num_ctx": 32768, "review": False}))
    sid, done = None, False
    while True:
        try: m = json.loads(await asyncio.wait_for(ws.recv(), 20 if done else 300))
        except asyncio.TimeoutError: return
        if m["type"] == "done": done = True
        if m["type"] == "present": return

async def main():
    shutil.rmtree(ROOT, ignore_errors=True); ROOT.mkdir(parents=True)
    async with websockets.connect(URL, max_size=None, origin=ORIGIN) as ws:
        await turn(ws, "Use TodoWrite to create a plan with exactly three tasks: write a short product description for a pocket notebook, shorten it, translate it to German. Then do task 1: write the description (about 70 words) as plain text in your answer, do not create files.")
        await turn(ws, "Rewrite that description to be more playful and shorter, keep the same facts.")
        await turn(ws, "Now give it a one-line tagline.")
        await ws.send(json.dumps({"type": "titles"}))
        for _ in range(40):
            m = json.loads(await asyncio.wait_for(ws.recv(), 60))
            if m["type"] == "titles": break
    sid = sorted(Path("/home/user/dogear/data/sessions").glob("*.json"), key=lambda p: p.stat().st_mtime)[-1].stem
    print("session:", sid)
    b = Browser(Path(tempfile.mkdtemp())); b.vw, b.vh = 1500, 900; await b.ensure(); await b.set_viewport(1500, 900)
    await b.navigate(f"http://127.0.0.1:7870/?session={sid}"); await asyncio.sleep(2.5)
    ev = b.eval
    print("rail visible:", await ev("!document.querySelector('#rail').hidden"), "| rail text:", await ev("document.querySelector('#rail').innerText.replace(/\\n/g,' | ').slice(0,100)"))
    await ev("document.querySelector('#rail .rhead').click()"); await asyncio.sleep(0.4)
    print("lanes cards:", await ev("[...document.querySelectorAll('#rail .lane')].map(l => l.querySelector('h4').innerText.replace(/\\n/g,' ') + '=' + l.querySelectorAll('.card2').length).join(', ')"))
    Path("/tmp/uf_rail.jpg").write_bytes(base64.b64decode(await b.screenshot()))
    print("outline button visible:", await ev("!document.querySelector('#outline-btn').hidden"))
    await ev("document.querySelector('#outline-btn').click()"); await asyncio.sleep(0.5)
    print("outline rows:", await ev("[...document.querySelectorAll('#outline .oi')].map(r => r.innerText.replace(/\\n/g,' ')).join(' || ')"))
    await ev("document.querySelector('#outline .oi .star').click()"); await asyncio.sleep(0.6)
    print("pinned after click:", await ev("[...document.querySelectorAll('#outline h5')].map(h=>h.innerText).join(',')"), "| tact pinned:", await ev("document.querySelectorAll('.tact.pinned').length"))
    Path("/tmp/uf_outline.jpg").write_bytes(base64.b64decode(await b.screenshot()))
    await ev("document.querySelector('#outline-btn').click()")
    print("diff toggles:", await ev("[...document.querySelectorAll('.difftoggle')].map(x => x.innerText).join(' | ')"))
    await ev("document.querySelector('.difftoggle')?.click()"); await asyncio.sleep(0.4)
    print("diff ins/del:", await ev("[document.querySelectorAll('.dview ins').length, document.querySelectorAll('.dview del').length]"), "| stat:", await ev("document.querySelector('.dstat')?.innerText"))
    await ev("document.querySelectorAll('.turn')[1].scrollIntoView()"); await asyncio.sleep(0.3)
    Path("/tmp/uf_diff.jpg").write_bytes(base64.b64decode(await b.screenshot()))
    # branch from turn 1 (index 1) and compare
    await ev("document.querySelectorAll('.tact button')[1 * 3 + 1].click()"); await asyncio.sleep(1.5)
    print("branch bar:", await ev("document.querySelector('#branchbar').hidden ? 'hidden' : document.querySelector('#branchbar').innerText.replace(/\\n/g,' | ')"), "| turns in branch:", await ev("document.querySelectorAll('.turn').length"))
    await ev("[...document.querySelectorAll('#branchbar button')].find(b => b.innerText === 'Compare').click()"); await asyncio.sleep(1.5)
    print("compare:", await ev("document.querySelector('#cmp-meta').innerText"), "| cells:", await ev("document.querySelectorAll('#cmp-body .cell').length"))
    Path("/tmp/uf_cmp.jpg").write_bytes(base64.b64decode(await b.screenshot()))
    await b.close()

asyncio.run(main())
