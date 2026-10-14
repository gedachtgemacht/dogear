"""Import the design dataset (plans + pages) into the library as 'design-plan' entries.
The brief is the problem, the plan is the embedded solution text, the full HTML is kept as bulk extra.
usage: uv run python tools/import_design_dataset.py [DATASET_DIR]"""
import asyncio, json, re, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx
from dogear import library as L

D = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data" / "design-dataset-300")

async def main():
    tasks = json.loads((D / "tasks_all.json").read_text())
    db = sqlite3.connect(L.DB)
    have = {r[0] for r in db.execute("SELECT source FROM entries WHERE project = 'design-dataset'")} if db.execute(
        "SELECT name FROM sqlite_master WHERE name='entries'").fetchone() else set()
    db.close()
    n = skipped = 0
    async with httpx.AsyncClient() as c:
        for t in tasks:
            src = f"dataset:{t['id']}"
            plan_f, html_f = D / "solutions" / f"{t['id']}.plan.md", D / "solutions" / f"{t['id']}.html"
            if src in have or not plan_f.is_file() or not html_f.is_file():
                skipped += 1
                continue
            plan = plan_f.read_text().strip()
            fw = t.get("stack", "") + (f", {t['style']}" if t.get("style") else "")
            await L.add(c, "http://127.0.0.1:11434", {
                "problem": t["prompt"], "solution": plan, "language": "design-plan", "framework": fw,
                "project": "design-dataset", "source": src, "extra": html_f.read_text()}, dedupe=False)
            n += 1
            if n % 50 == 0: print("imported", n, flush=True)
    print(f"imported {n}, skipped {skipped}")

asyncio.run(main())
