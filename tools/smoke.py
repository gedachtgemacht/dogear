"""Smoke test of agent features through a running server. usage: uv run python tools/smoke.py"""
import asyncio, json, shutil, sys, time, websockets
from pathlib import Path
ROOT = Path("/home/user/dogear/projects/smoke")
URL = "ws://127.0.0.1:7870/ws"; ORIGIN = "http://127.0.0.1:7870"

async def run(prompt, mode="auto", answer=None, model="qwen3.6:35b-a3b", review=False, undo=False):
    t0, tools, summary, notes, asked = time.time(), [], None, [], None
    async with websockets.connect(URL, max_size=None, origin=ORIGIN) as ws:
        await ws.send(json.dumps({"type": "user", "text": prompt, "model": model, "think": False, "mode": mode,
                                  "root": str(ROOT), "num_ctx": 32768, "review": review}))
        done = False
        while True:
            try: m = json.loads(await asyncio.wait_for(ws.recv(), 20 if done else 400))
            except asyncio.TimeoutError: break
            t = m["type"]
            if t == "tool": tools.append(m["name"])
            elif t == "ask":
                qs = m.get("questions") or [{"question": m.get("question", ""), "options": [{"label": o} for o in m.get("options", [])]}]
                asked = [(q["question"], [o["label"] for o in q["options"]]) for q in qs]
                value = [{"selected": [q["options"][0]["label"]] if q["options"] and not answer else [], "other": answer or ""} for q in qs]
                await ws.send(json.dumps({"type": "answer", "id": m["id"], "value": value}))
            elif t == "notice": notes.append(m["text"])
            elif t == "summary": summary = m
            elif t == "done": done = True
            elif t == "present": break
            elif t == "error": notes.append("ERROR " + m["text"])
        if undo and summary and summary.get("checkpoint"):
            cp = summary["checkpoint"]
            await ws.send(json.dumps({"type": "undo", "root": cp["root"], "to": cp["before"]}))
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 20))
                if m["type"] == "undone": return {"tools": tools, "secs": int(time.time()-t0), "undone": m["files"], "summary": summary, "asked": asked, "notes": notes}
    return {"tools": tools, "secs": int(time.time() - t0), "summary": summary, "asked": asked, "notes": notes}

async def main():
    shutil.rmtree(ROOT, ignore_errors=True); ROOT.mkdir(parents=True)
    (ROOT / "lib.py").write_text("def add(a, b):\n    return a - b\n")
    (ROOT / "notes.txt").write_text("keep me\n")
    print("1) checkpoint + undo")
    r = await run("Fix the bug in lib.py (add must return the sum) and create hello.py that prints 'hi'. Then run both.", undo=True)
    print("  tools:", r["tools"], "| secs:", r["secs"], "| checkpoint:", bool((r["summary"] or {}).get("checkpoint")))
    print("  after undo -> lib.py:", (ROOT / "lib.py").read_text().strip().replace("\n", " "), "| hello.py exists:", (ROOT / "hello.py").exists(), "| undone:", r.get("undone"))
    print("2) AskUser")
    r = await run("I want a small color palette file palette.json but I have not decided between a warm and a cool palette. Use the AskUser tool to ask me, then create palette.json with 4 hex colors matching my answer.", answer="cool")
    print("  tools:", r["tools"], "| asked:", r["asked"], "| palette:", (ROOT / "palette.json").read_text()[:80].replace("\n", " ") if (ROOT / "palette.json").exists() else None)
    print("3) Task sub-agent")
    for i in range(3): (ROOT / f"mod{i}.py").write_text(f"# module {i}\ndef f{i}():\n    return {i}\n\nTODO_{i} = 'check f{i}'\n")
    r = await run("Use the Task tool to find out which files in this directory define functions and what they return, then tell me in two sentences.")
    print("  tools:", r["tools"], "| secs:", r["secs"])
    print("4) Skill tool")
    r = await run("Load the 'debugging' skill with the Skill tool and then tell me, in one sentence, what step 4 of it says.")
    print("  tools:", r["tools"])
    print("5) Plan mode (must not change anything)")
    before = sorted(p.name for p in ROOT.iterdir())
    r = await run("Add a subtract function to lib.py and write a test for it.", mode="plan")
    after = sorted(p.name for p in ROOT.iterdir())
    print("  tools:", r["tools"], "| files unchanged:", before == after, "| lib.py:", (ROOT / "lib.py").read_text().strip().replace("\n", " "))

asyncio.run(main())
