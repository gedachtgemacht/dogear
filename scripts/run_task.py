"""Run one task through a running dogear server and print a compact log.
usage: uv run python scripts/run_task.py TASKFILE PROJECT_DIR [model] [mode]"""
import asyncio, json, sys, time, websockets

async def main():
    task = open(sys.argv[1]).read(); root = sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else "qwen3.6:35b-a3b"
    mode = sys.argv[4] if len(sys.argv) > 4 else "auto"
    t0 = time.time()
    async with websockets.connect("ws://127.0.0.1:7870/ws", max_size=None, origin="http://127.0.0.1:7870") as ws:
        await ws.send(json.dumps({"type": "b_sub"}))
        await ws.send(json.dumps({"type": "user", "text": task, "model": model, "think": False, "mode": mode,
                                  "root": root, "num_ctx": 65536}))
        done = False
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), 30 if done else 2400)
            except asyncio.TimeoutError:
                break
            m = json.loads(raw); t = m["type"]; el = int(time.time() - t0)
            if t in ("token", "thinking", "term", "frame", "usage", "b_nav", "b_status", "b_act", "b_marks", "mcp",
                     "b_log", "term_start", "term_end", "fs", "todos", "turn_start"):
                continue
            if t == "tool":
                print(f"[{el:>4}s] {m['name']:<18} {m['label'][:90]}", flush=True)
            elif t == "result":
                print(f"         -> {'ok ' if m['ok'] else 'ERR'} {m['text'].splitlines()[0][:110] if m['text'] else ''}", flush=True)
            elif t == "summary":
                print("SUMMARY", json.dumps({k: v for k, v in m.items() if k not in ('type', 'sources', 'commands')})[:300], flush=True)
            elif t == "present":
                print("PRESENT", m["kind"], [b["type"] for b in m["blocks"]], flush=True); break
            elif t == "done":
                done = True; print(f"[{el}s] done", flush=True)
            elif t in ("error", "notice"):
                print(t, m["text"], flush=True)

asyncio.run(main())
