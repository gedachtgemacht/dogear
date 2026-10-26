"""New tools through a running server: multiple choice form, Outline/FindSymbol/MultiEdit/RunTests, Git, Ultra.
usage: uv run python tests/live/smoke_tools.py [ultra]"""
import asyncio, json, shutil, subprocess, sys, time
from pathlib import Path
import websockets
ROOT = REPO / "projects" / "tools-smoke"
URL, ORIGIN = "ws://127.0.0.1:7870/ws", "http://127.0.0.1:7870"

async def run(prompt, mode="auto", select=None, ask_log=None, timeout=420):
    t0, tools, notes, ultra_events, final = time.time(), [], [], 0, ""
    async with websockets.connect(URL, max_size=None, origin=ORIGIN) as ws:
        await ws.send(json.dumps({"type": "user", "text": prompt, "model": "qwen3.6:35b-a3b", "think": False, "mode": mode,
                                  "root": str(ROOT), "num_ctx": 32768, "review": False}))
        done = False
        while True:
            try: m = json.loads(await asyncio.wait_for(ws.recv(), 15 if done else timeout))
            except asyncio.TimeoutError: break
            t = m["type"]
            if t == "tool": tools.append(m["name"])
            elif t == "token": final += m["text"]
            elif t == "ask":
                if ask_log is not None: ask_log.append(m["questions"])
                value = [{"selected": (select[i] if select and i < len(select) else [q["options"][0]["label"]] if q["options"] else []), "other": ""}
                         for i, q in enumerate(m["questions"])]
                await ws.send(json.dumps({"type": "answer", "id": m["id"], "value": value}))
            elif t == "approval": await ws.send(json.dumps({"type": "approve", "id": m["id"], "ok": True}))
            elif t == "ultra": ultra_events += 1
            elif t == "notice": notes.append(m["text"])
            elif t == "done": done = True
            elif t == "present": break
    return {"tools": tools, "secs": int(time.time() - t0), "notes": notes, "ultra_events": ultra_events, "final": final.strip()}

BIG = '''"""Inventory helpers."""
import json
REPO = Path(__file__).resolve().parents[2]


class Store:
    def __init__(self, path):
        self.path = path
        self.rows = []

    def load(self):
        for line in open(self.path):
            self.rows.append(parse_line(line))

    def total(self):
        return sum(r["qty"] for r in self.rows)


def parse_line(line):
    name, qty = line.rsplit(",", 1)
    return {"name": name.strip(), "qty": int(qty)}


def report(store):
    return json.dumps([parse_line(f"{r['name']},{r['qty']}") for r in store.rows])
'''
async def main():
    shutil.rmtree(ROOT, ignore_errors=True); ROOT.mkdir(parents=True)
    print("1) multiple choice form, two questions, multi-select")
    log = []
    r = await run("Ask me two questions in ONE AskUser call. Question 1 (multi-select): which features to include: dark mode, export, search. "
                  "Question 2 (single): which language: Python or JavaScript. Each option needs a short description. Afterwards write my answers into choices.txt.",
                  select=[["dark mode", "search"], ["Python"]], ask_log=log)
    qs = log[0] if log else []
    ct = (ROOT / "choices.txt").read_text().strip().replace("\n", " | ") if (ROOT / "choices.txt").exists() else None
    print("  tools:", r["tools"], "| questions:", len(qs), "| multi flags:", [q.get("multi") for q in qs], "| options w/ description:", sum(1 for q in qs for o in q["options"] if o.get("description")))
    print("  choices.txt:", ct)
    print("2) Outline / FindSymbol / MultiEdit / RunTests")
    (ROOT / "inventory.py").write_text(BIG); (ROOT / "data.csv").write_text("apple, 3\npear, 5\n")
    (ROOT / "test_inventory.py").write_text("import unittest\nfrom inventory import Store, parse_line\n\nclass T(unittest.TestCase):\n    def test_total(self):\n        s = Store('data.csv'); s.load(); self.assertEqual(s.total(), 8)\n    def test_parse(self):\n        self.assertEqual(parse_line('a, 2'), {'name': 'a', 'qty': 2})\n\nif __name__ == '__main__':\n    unittest.main()\n")
    r = await run("In inventory.py: first use Outline to see its structure and FindSymbol to find every use of parse_line. Then rename parse_line to parse_row everywhere "
                  "(inventory.py and test_inventory.py) using a single MultiEdit per file, and finally run the tests with RunTests.")
    src = (ROOT / "inventory.py").read_text() + (ROOT / "test_inventory.py").read_text()
    print("  tools:", r["tools"], "| secs:", r["secs"], "| parse_line left:", src.count("parse_line"), "| parse_row uses:", src.count("parse_row"))
    print("3) Git (commit needs approval; auto-approved here)")
    subprocess.run("git init -q && git add -A && git -c user.name=t -c user.email=t@t commit -qm init && echo hello > notes.md", shell=True, cwd=ROOT)
    r = await run("Use the Git tool: show the status, then add notes.md and commit it with the message 'add notes'. Finally show the log.", mode="edit")
    log_out = subprocess.run("git log --oneline", shell=True, cwd=ROOT, capture_output=True, text=True).stdout.strip().replace("\n", " | ")
    print("  tools:", r["tools"], "| git log:", log_out)
    if len(sys.argv) > 1 and sys.argv[1] == "ultra":
        print("4) Ultra review on a file with planted bugs")
        (ROOT / "bad.py").write_text('import subprocess\n\ndef run_user_cmd(name):\n    return subprocess.run("echo hello " + name, shell=True, capture_output=True, text=True).stdout\n\n'
                                     'def last_items(xs, n):\n    out = []\n    for i in range(len(xs) - n, len(xs) + 1):\n        out.append(xs[i])\n    return out\n')
        r = await run("Use the Ultra tool with pattern review on bad.py and give me the confirmed findings.", timeout=900)
        print("  tools:", r["tools"], "| secs:", r["secs"], "| ultra events:", r["ultra_events"])
        print("  answer:", r["final"][:900])

if __name__ == "__main__":
    asyncio.run(main())
