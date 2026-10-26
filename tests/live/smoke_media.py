"""Image input, ViewImage and /compact through a running server. usage: uv run python tests/live/smoke_media.py"""
import asyncio, base64, json, shutil, sys, tempfile, time
from pathlib import Path
import websockets
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dogear.browser import Browser
REPO = Path(__file__).resolve().parents[2]

ROOT = REPO / "projects" / "media"
URL, ORIGIN = "ws://127.0.0.1:7870/ws", "http://127.0.0.1:7870"

async def make_image(path: Path):
    b = Browser(Path(tempfile.mkdtemp())); await b.ensure()
    html = "data:text/html,<body style='margin:0;background:%23fff'><div style='width:640px;height:360px;display:flex;align-items:center;justify-content:center;gap:40px;font:bold 120px sans-serif'><div style='width:150px;height:150px;border-radius:50%25;background:%23d32f2f'></div>7391</div></body>"
    await b.set_viewport(640, 360); await b.navigate(html); await asyncio.sleep(0.4)
    data = base64.b64decode(await b.screenshot()); path.write_bytes(data); await b.close()
    return data

class Chat:
    def __init__(self, ws): self.ws = ws
    async def say(self, text, images=None, mode="auto"):
        await self.ws.send(json.dumps({"type": "user", "text": text, "images": images or [], "model": "qwen3.6:35b-a3b", "think": False,
                                       "mode": mode, "root": str(ROOT), "num_ctx": 32768, "review": False}))
        out, tools, notes = "", [], []
        while True:
            m = json.loads(await asyncio.wait_for(self.ws.recv(), 240)); t = m["type"]
            if t == "token": out += m["text"]
            elif t == "tool": tools.append(m["name"])
            elif t == "notice": notes.append(m["text"])
            elif t == "done": return out, tools, notes

async def main():
    shutil.rmtree(ROOT, ignore_errors=True); ROOT.mkdir(parents=True)
    img = await make_image(ROOT / "mockup.jpg")
    async with websockets.connect(URL, max_size=None, origin=ORIGIN) as ws:
        c = Chat(ws)
        print("1) image attached to the message")
        out, tools, notes = await c.say("What number is written in the image and what color is the circle? Answer in one short sentence.", [base64.b64encode(img).decode()])
        print("  tools:", tools, "| answer:", out.strip()[:140], "| 7391:", "7391" in out, "| red:", "red" in out.lower() or "rot" in out.lower())
        print("2) ViewImage on a project file")
        out, tools, notes = await c.say("Use ViewImage to look at mockup.jpg and tell me the number in it.")
        print("  tools:", tools, "| answer:", out.strip()[:120], "| 7391:", "7391" in out)
    print("3) compact")
    async with websockets.connect(URL, max_size=None, origin=ORIGIN) as ws:
        c = Chat(ws)
        await c.say("Remember these facts: the project codename is HELIOTROPE and the dev server must run on port 8123. Write both into notes.txt.")
        await c.say("Create calc.py with a function add(a, b) and a function sub(a, b). Then run a quick check of both.")
        await c.say("Create README.md with a one-paragraph description of the project using the codename.")
        await ws.send(json.dumps({"type": "compact", "focus": "keep codename and port"}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 240))
            if m["type"] in ("compacted", "notice"): break
        if m["type"] == "compacted":
            print("  compacted:", m["replaced"], "msgs, ~", m["before"], "->", m["after"], "tokens | messages left:", len(m["session"]["messages"]))
            print("  summary starts:", m["session"]["messages"][0]["content"][100:330].replace("\n", " | "))
        else:
            print("  FAILED:", m["text"])
        out, tools, _ = await c.say("Without reading any file: what is the project codename and which port must the dev server use? One sentence.")
        print("  recall:", out.strip()[:150], "| tools used:", tools, "| HELIOTROPE:", "HELIOTROPE" in out.upper(), "| 8123:", "8123" in out)

asyncio.run(main())
