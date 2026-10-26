"""Plan phase 3 end to end: propose -> approve -> the harness runs one task per turn -> every task is closed by the
model (complete_current_task) -> log in the session -> review after the last task only.
usage: uv run python tests/live/plan_exec_test.py [model] [mode]      (needs the server on 7870; mode edit auto-approves commands)"""
import asyncio
import json
import subprocess
import shutil
import sys
import time
from pathlib import Path

import websockets

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "projects" / "plan_exec"
URL, ORIGIN = "ws://127.0.0.1:7870/ws", "http://127.0.0.1:7870"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen3.6:35b-a3b"
MODE = sys.argv[2] if len(sys.argv) > 2 else "edit"
ok_all = True


def check(name, cond, extra=""):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


async def until(ws, kinds, timeout=600, seen=None):
    """Wait for one of `kinds`; approvals on the way are granted (the test plays the user)."""
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if seen is not None:
            seen.append(m)
        if m["type"] == "approval":
            await ws.send(json.dumps({"type": "approve", "id": m["id"], "ok": True}))
        if m["type"] in kinds:
            return m


async def main():
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    (ROOT / "README.md").write_text("# plan_exec\nEmpty project for the phase 3 test.\n")
    base = {"model": MODEL, "think": False, "root": str(ROOT), "num_ctx": 32768, "review": True}
    async with websockets.connect(URL, max_size=None, origin=ORIGIN) as ws:
        await ws.send(json.dumps({"type": "new"}))
        await ws.send(json.dumps({"type": "user", "mode": "plan", "text":
            "Create a tiny Python module slug.py with a function slugify(text) (lowercase, spaces and punctuation to single dashes, "
            "no leading or trailing dash) and a test file test_slug.py with pytest-style tests. Look at the folder first.", **base}))
        p1 = await until(ws, {"plan_proposed", "done"})
        check("phase 1 ends with a proposed board", p1["type"] == "plan_proposed", p1["type"])
        if p1["type"] != "plan_proposed":
            print("ABORTED")
            return
        await until(ws, {"done"})
        tasks = p1["plan"]["tasks"]
        print("  board:", [t["content"][:70] for t in tasks])
        await ws.send(json.dumps({"type": "plan_approve", "tasks": tasks, "mode": MODE}))
        st = await until(ws, {"plan_status"}, 30)
        check("approval acknowledged", st["status"] == "approved")
        events, t0 = [], time.time()
        fin = await until(ws, {"plan_status"}, 1500, seen=events)       # the next plan_status is done | replan | stopped
        while fin["type"] == "plan_status" and fin.get("status") == "approved":
            fin = await until(ws, {"plan_status"}, 1500, seen=events)
        print(f"  execution: {fin.get('status')} after {round(time.time() - t0)}s")
        tasks_ev = [e for e in events if e["type"] == "plan_task"]
        running = [e for e in tasks_ev if e["status"] == "running"]
        closed = [e for e in tasks_ev if e["status"] != "running"]
        check("one running event per task, in order", [e["i"] for e in running] == list(range(len(tasks))), str([e["i"] for e in running]))
        check("every task was closed", len(closed) == len(tasks), f"{len(closed)}/{len(tasks)}")
        check("all tasks closed by the model with a summary", all(e["status"] == "done" and e.get("summary") for e in closed),
              str([(e["i"], e["status"], e.get("summary", "")[:40]) for e in closed]))
        check("plan ends with status done", fin.get("status") == "done", fin.get("status"))
        tool_names = [e["name"] for e in events if e["type"] == "tool"]
        check("TodoWrite was not used to tick tasks (the harness keeps the board)", "TodoWrite" not in tool_names)
        check("complete_current_task called once per task", tool_names.count("complete_current_task") == len(tasks), str(tool_names.count("complete_current_task")))
        reviews = [e for e in events if e["type"] == "review_start"]
        check("at most one review pass (after the last task)", len(reviews) <= 1, str(len(reviews)))
        check("files were written", (ROOT / "slug.py").exists() and (ROOT / "test_slug.py").exists(), str(sorted(p.name for p in ROOT.iterdir())))
        if (ROOT / "slug.py").exists():
            r = subprocess.run([sys.executable, "-c", "from slug import slugify; print(slugify('Hello, World!  Again'))"], cwd=ROOT, capture_output=True, text=True)
            check("slugify works", r.stdout.strip() == "hello-world-again", r.stdout + r.stderr)
        await until(ws, {"done"}, 600)
    files = sorted((REPO / "data" / "sessions").glob("*.json"), key=lambda p: p.stat().st_mtime)
    s = json.load(open(files[-1]))
    pm = next((m for m in reversed(s["messages"]) if m.get("plan")), None)
    log = (pm or {}).get("plan", {}).get("log", [])
    check("log in the session: one entry per task with status, summary, steps and seconds",
          len(log) == len(tasks) and all({"status", "summary", "steps", "secs"} <= set(e) for e in log), json.dumps(log)[:300])
    task_turns = [m for m in s["messages"] if m["role"] == "user" and m.get("task")]
    check("each task is its own turn with a task marker", len(task_turns) == len(tasks), str(len(task_turns)))
    board = [t["status"] for t in s.get("todos", [])]
    check("board fully completed", board and all(x == "completed" for x in board), str(board))
    print("ALL PASS" if ok_all else "SOME FAILED")
    sys.exit(0 if ok_all else 1)


asyncio.run(main())
