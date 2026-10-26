"""Plan mode phases 1+2 end to end: propose -> reject with feedback -> revised proposal -> approve -> execution.
usage: uv run python tests/live/plan_test.py [model]"""
import asyncio, json, shutil, subprocess, sys, time
from pathlib import Path
import websockets
REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "projects" / "plan_e2e"
URL, ORIGIN = "ws://127.0.0.1:7870/ws", "http://127.0.0.1:7870"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen3.6:35b-a3b"
ok_all = True
def check(name, cond, extra=""):
    global ok_all; ok_all &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

async def until(ws, kinds, timeout=300, log=None):
    t0 = time.time()
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if log is not None and m["type"] == "tool": log.append(m["name"])
        if m["type"] in kinds: return m

async def main():
    shutil.rmtree(ROOT, ignore_errors=True); ROOT.mkdir(parents=True)
    (ROOT / "README.md").write_text("# plan_e2e\nEmpty project for the plan test.\n")
    base = {"model": MODEL, "think": False, "root": str(ROOT), "num_ctx": 32768, "review": False}
    async with websockets.connect(URL, max_size=None, origin=ORIGIN) as ws:
        await ws.send(json.dumps({"type": "new"}))
        await ws.send(json.dumps({"type": "user", "mode": "plan", "text":
            "Build a small Python command line tool wc.py in this folder that counts lines, words and characters of a text file, "
            "plus a test file test_wc.py with pytest-style tests. Look at the folder first.", **base}))
        tools1 = []
        p1 = await until(ws, {"plan_proposed", "done"}, log=tools1)
        check("phase 1 ends with a proposed board", p1["type"] == "plan_proposed", p1["type"])
        if p1["type"] != "plan_proposed": print("PLAN TEST ABORTED"); return
        plan = p1["plan"]
        print("  tools used:", tools1); print("  reasoning:", plan["reasoning"][:200].replace("\n", " "))
        for i, t in enumerate(plan["tasks"], 1): print(f"  {i}. {t['content'][:100]}")
        check("3-8 tasks", 3 <= len(plan["tasks"]) <= 8, len(plan["tasks"]))
        check("reasoning present", len(plan["reasoning"]) > 40)
        check("the model could only read in phase 1 (no files written)", sorted(p.name for p in ROOT.iterdir()) == ["README.md"], str(list(ROOT.iterdir())))
        check("no write or shell tool was used", not any(n in ("Write", "Edit", "Bash", "MultiEdit") for n in tools1), str(tools1))
        await until(ws, {"done"})
        # reject with feedback -> revised plan
        await ws.send(json.dumps({"type": "plan_reject", "feedback": "Also support reading from stdin when no file argument is given, and add a task for that."}))
        p2 = await until(ws, {"plan_proposed", "done"})
        check("revised proposal after rejection", p2["type"] == "plan_proposed")
        txt = json.dumps(p2["plan"], ensure_ascii=False).lower()
        check("feedback is reflected (stdin)", "stdin" in txt, txt[:200])
        await until(ws, {"done"})
        # approve, with an edit: drop nothing, add one task
        tasks = p2["plan"]["tasks"] + [{"content": "Run the tests and show the result", "detail": ""}]
        await ws.send(json.dumps({"type": "plan_approve", "tasks": tasks, "mode": "auto"}))
        st = await until(ws, {"plan_status"}, 30)
        check("approval acknowledged", st["status"] == "approved" and len(st["tasks"]) == len(tasks))
        calls = []
        await until(ws, {"done"}, 600, log=calls)
        check("execution wrote the files", (ROOT / "wc.py").exists() and (ROOT / "test_wc.py").exists(), str(sorted(p.name for p in ROOT.iterdir())))
        if (ROOT / "wc.py").exists():
            (ROOT / "x.txt").write_text("a b\nc\n")
            r = subprocess.run(["python3", "wc.py", "x.txt"], cwd=ROOT, capture_output=True, text=True)
            check("wc.py works", r.returncode == 0 and "2" in r.stdout and "3" in r.stdout, r.stdout + r.stderr)
            r2 = subprocess.run(["python3", "wc.py"], cwd=ROOT, input="a b\nc\n", capture_output=True, text=True)
            check("stdin mode from the feedback works", r2.returncode == 0 and "3" in r2.stdout, r2.stdout + r2.stderr)
    s = json.load(open(sorted(REPO / "data" / "sessions".glob("*.json"), key=lambda p: p.stat().st_mtime)[-1]))
    states = [t["status"] for t in s.get("todos", [])]
    print("  board at the end:", states)
    check("board was kept current during execution", states.count("completed") >= len(states) - 1, str(states))
    print("PASS" if ok_all else "FAIL")
asyncio.run(main())
