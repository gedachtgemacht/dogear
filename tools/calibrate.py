"""Measure which toolbox a model should get and store it in data/profiles.json.
For each toolbox (lean, standard, full) the benchmark tasks run through the live server; the smallest toolbox that
scores within one task of the best wins (ties go to the leaner one: shorter prompt, fewer ways to go wrong).
usage: uv run python tools/calibrate.py MODEL [MODEL ...]      (takes ~5-10 minutes per toolbox)"""
import asyncio, json, os, re, shutil, sys, time
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench                                  # noqa: E402  (reuses tasks, graders and the runner)
from dogear import profiles as P              # noqa: E402

API = "http://127.0.0.1:7870"

async def run_suite(model: str, toolbox: str) -> tuple[float, int, int]:
    ov = json.loads(P.OVERRIDES_FILE.read_text()) if P.OVERRIDES_FILE.exists() else {}
    ov.setdefault(model, {})["toolbox"] = toolbox
    P.OVERRIDES_FILE.write_text(json.dumps(ov, indent=1))
    httpx.get(f"{API}/api/profile", params={"model": model, "reset": "true"}, timeout=20)   # drop the server's cached profile
    total = steps = secs = 0
    for name, setup, prompt, grade in bench.TASKS:
        d = bench.BASE / "calibrate" / re.sub(r"[^\w.-]", "_", model) / toolbox / name
        shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
        if setup: setup(d)
        try:
            st = await bench.run_agent(model, d, prompt)
            score, note = await asyncio.to_thread(grade, d)
        except Exception as e:
            st, score, note = {"secs": 0, "steps": 0}, 0.0, str(e)[:60]
        total += score; steps += st["steps"]; secs += st["secs"]
        print(f"   {toolbox:<9} {name:<13} {score:.1f}  {st['secs']:>3}s  steps={st['steps']:<3} {note[:60]}", flush=True)
    return total, steps, secs

async def main():
    cfg = bench.HERE.parent / "data" / "settings.json"
    saved = cfg.read_text() if cfg.exists() else None
    try:
        for model in sys.argv[1:]:
            print(f"== {model}")
            results = {}
            for tb in P.ORDER:
                results[tb] = await run_suite(model, tb)
                print(f"   -> {tb}: {results[tb][0]:.1f}/{len(bench.TASKS)} in {results[tb][2]}s, {results[tb][1]} steps")
            best = max(r[0] for r in results.values())
            pick = next(tb for tb in P.ORDER if results[tb][0] >= best - 1.0)
            ov = json.loads(P.OVERRIDES_FILE.read_text())
            ov[model] = {"toolbox": pick, "prompt": "lean" if pick == "lean" else "full",
                         "calibrated": {tb: round(r[0], 1) for tb, r in results.items()}}
            P.OVERRIDES_FILE.write_text(json.dumps(ov, indent=1))
            httpx.get(f"{API}/api/profile", params={"model": model, "reset": "true"}, timeout=20)
            print(f"   PICK {pick}  (scores {ov[model]['calibrated']})\n")
    finally:
        if saved is not None: cfg.write_text(saved)

asyncio.run(main())
