"""Benchmark local models on small coding tasks with automatic grading.

usage: uv run python scripts/bench.py [model ...]      (default: all chat models in Ollama)
Results: data/bench/bench_results.json (appended per run) and a table at the end.
"""
import asyncio, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "projects" / "bench"
RESULTS = HERE.parent / "data" / "bench" / os.environ.get("BENCH_OUT", "bench_results.json")
PHASED = os.environ.get("BENCH_PHASED") == "1"      # plan phase (read-only, fills the board) -> approve -> execute
TASK_FILTER = set(filter(None, os.environ.get("BENCH_TASKS", "").split(",")))
URL, ORIGIN = "ws://127.0.0.1:7870/ws", "http://127.0.0.1:7870"
TIMEOUT = 480


def sh(cmd, cwd, timeout=30):
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


# ------------------------------------------------------------------ tasks: setup(dir), prompt, grade(dir) -> (score 0..1, note)

def t_fizzbuzz_grade(d):
    if not (d / "fizzbuzz.py").exists():
        return 0.0, "fizzbuzz.py missing"
    code = ("import importlib.util\nspec=importlib.util.spec_from_file_location('m','fizzbuzz.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n"
            "r=m.fizzbuzz(15)\nassert r[0]=='1' and r[2]=='Fizz' and r[4]=='Buzz' and r[14]=='FizzBuzz' and len(r)==15, r\nassert m.fizzbuzz(0)==[]\nprint('ok')")
    gf = Path(tempfile.mkdtemp()) / "grade.py"; gf.write_text(code)
    rc, out = sh(f"python3 {gf}", d)
    return (1.0, "ok") if rc == 0 else (0.0, out.strip().splitlines()[-1][:100] if out.strip() else "failed")


STATS = '''def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2]


def mean(xs):
    return sum(xs) / len(xs)
'''
STATS_TEST = '''from stats import median, mean

def raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    return False

assert median([3, 1, 2]) == 2
assert median([4, 1, 3, 2]) == 2.5
assert median([7]) == 7
assert raises(lambda: median([]), ValueError)
assert mean([1, 2, 3, 4]) == 2.5
assert raises(lambda: mean([]), ValueError)
print("all tests passed")
'''


def t_median_setup(d):
    (d / "stats.py").write_text(STATS); (d / "test_stats.py").write_text(STATS_TEST)


def t_median_grade(d):
    if hashlib.md5((d / "test_stats.py").read_bytes()).hexdigest() != hashlib.md5(STATS_TEST.encode()).hexdigest():
        return 0.0, "tests were modified"
    rc, out = sh("python3 test_stats.py", d)
    return (1.0, "ok") if rc == 0 else (0.0, out.strip().splitlines()[-1][:100])


TODO_FILES = {
    "app/main.py": "import os\n\n# TODO: handle missing config\ndef run():\n    pass  # TODO: implement run\n",
    "app/util.js": "// TODO: replace with lodash\nfunction a() {}\n\n/* nothing here */\n// TODO(sam): memoize\n",
    "docs/guide.md": "# Guide\n\n<!-- TODO: add screenshots -->\nSome text mentioning autodoc and todo lists.\n",
    "lib/deep/er/x.py": "x = 1\ny = 2\n\ndef f():\n    # TODO: edge case for empty input\n    return x\n",
    "README.md": "Project readme.\nDone: tests.\n",
}


def t_todo_setup(d):
    for p, c in TODO_FILES.items():
        f = d / p; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(c)


def t_todo_grade(d):
    want = set()
    for p, c in TODO_FILES.items():
        for i, line in enumerate(c.splitlines(), 1):
            if re.search(r"\bTODO\b", line):
                want.add((p, i))
    f = d / "TODOS.md"
    if not f.exists():
        return 0.0, "TODOS.md missing"
    got = set()
    for line in f.read_text().splitlines():
        m = re.search(r"([\w./-]+\.\w+):(\d+)", line)
        if m:
            got.add((m.group(1).lstrip("./"), int(m.group(2))))
    hit, extra = len(want & got), len(got - want)
    score = max(0.0, (hit - extra) / len(want))
    return score, f"{hit}/{len(want)} found, {extra} wrong"


def t_kv_grade(d):
    if not (d / "kv.py").exists():
        return 0.0, "kv.py missing"
    steps = [("set a 1", 0, ""), ("set b two", 0, ""), ("get a", 0, "1"), ("get b", 0, "two"), ("get nope", 1, ""),
             ("del a", 0, ""), ("get a", 1, ""), ("list", 0, "b")]
    ok = 0
    for cmd, rc_want, out_has in steps:
        rc, out = sh(f"python3 kv.py {cmd}", d)
        if (rc == 0) == (rc_want == 0) and out_has in out:
            ok += 1
    return ok / len(steps), f"{ok}/{len(steps)} commands right"


def t_web_setup(d):
    pass


def t_web_grade(d):
    import asyncio as aio
    from dogear.browser import Browser

    async def go():
        f = d / "index.html"
        if not f.exists():
            return 0.0, "index.html missing"
        b = Browser(Path(tempfile.mkdtemp()))
        try:
            await b.ensure()
            await b.navigate("file://" + str(f))
            await aio.sleep(0.3)
            r = await b.eval("""(() => { const btn = t => [...document.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === t);
                const c = document.getElementById('count'); if (!c || !btn('add') || !btn('reset')) return 'missing elements';
                const out = [c.textContent.trim()]; for (let i = 0; i < 3; i++) btn('add').click(); out.push(c.textContent.trim());
                btn('reset').click(); out.push(c.textContent.trim()); return out.join(','); })()""")
            return (1.0, "ok") if r == "0,3,0" else (0.0, str(r))
        finally:
            await b.close()
    return aio.run(go())


def t_rename_setup(d):
    (d / "shop").mkdir(); (d / "tests").mkdir()
    (d / "shop/__init__.py").write_text(""); (d / "tests/__init__.py").write_text("")
    (d / "shop/pricing.py").write_text("def calc_total(items, tax=0.2):\n    net = sum(p * q for p, q in items)\n    return round(net * (1 + tax), 2)\n")
    (d / "shop/cart.py").write_text("from shop.pricing import calc_total\n\n\ndef checkout(items):\n    return {'total': calc_total(items)}\n")
    (d / "main.py").write_text("from shop import pricing\n\nprint(pricing.calc_total([(10, 2), (5, 1)]))\n")
    (d / "tests/test_pricing.py").write_text("import unittest\nfrom shop.pricing import calc_total\nfrom shop.cart import checkout\n\n\nclass T(unittest.TestCase):\n"
                                              "    def test_total(self):\n        self.assertEqual(calc_total([(10, 2)]), 24.0)\n\n    def test_checkout(self):\n"
                                              "        self.assertEqual(checkout([(10, 2)])['total'], 24.0)\n\n\nif __name__ == '__main__':\n    unittest.main()\n")
    (d / "README.md").write_text("# Shop\n\nUse `calc_total(items)` to get the gross total.\n")


def t_rename_grade(d):
    rc, out = sh("grep -rIl calc_total . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__", d)
    left = [l for l in out.splitlines() if l.strip()]
    rc2, out2 = sh("python3 -m unittest discover -s tests -t . 2>&1 | tail -3", d)
    n = sum((d / p).read_text().count("compute_total") for p in ("shop/pricing.py", "shop/cart.py", "main.py", "tests/test_pricing.py", "README.md"))
    ok = not left and "OK" in out2 and n >= 6
    return (1.0, "ok") if ok else (0.5 if "OK" in out2 and not left else 0.0, f"left in {left[:3]}, tests {'ok' if 'OK' in out2 else 'FAIL'}, uses={n}")


WC = '''import sys
from collections import Counter


def count_words(text):
    return Counter(w.lower() for w in text.split())


def main(argv):
    text = open(argv[0]).read() if argv else sys.stdin.read()
    for word, n in count_words(text).most_common():
        print(f"{n} {word}")


if __name__ == "__main__":
    main(sys.argv[1:])
'''


def t_cli_setup(d):
    (d / "wc.py").write_text(WC)
    (d / "sample.txt").write_text("the cat and the dog and the bird\nThe end\n")


def t_cli_grade(d):
    rc, out = sh("python3 wc.py sample.txt --json --top 2", d)
    try:
        data = json.loads(out)
    except Exception:
        return 0.0, "no JSON: " + out.strip()[:60]
    flat = data if isinstance(data, dict) else dict(data) if data and isinstance(data[0], (list, tuple)) else {x.get("word"): x.get("count") for x in data}
    ok = len(flat) == 2 and flat.get("the") == 4 and flat.get("and") == 2
    rc2, out2 = sh("python3 wc.py sample.txt | head -1", d)
    plain = out2.strip() == "4 the"
    return (1.0, "ok") if ok and plain else (0.5 if ok or plain else 0.0, f"json {'ok' if ok else out.strip()[:50]}, plain {'ok' if plain else out2.strip()}")


TASKS = [
    ("fizzbuzz", None, "Create fizzbuzz.py with a function fizzbuzz(n) that returns a list of strings for the numbers 1..n: 'Fizz' for multiples of 3, 'Buzz' for multiples of 5, 'FizzBuzz' for both, otherwise the number as a string.", t_fizzbuzz_grade),
    ("fix_median", t_median_setup, "test_stats.py fails. Fix stats.py without changing the tests. Run them with `python3 test_stats.py` until they pass.", t_median_grade),
    ("todo_collect", t_todo_setup, "Find every TODO comment in this project (all subdirectories, all file types) and write TODOS.md: one markdown bullet per TODO in the form `- path:line: text`, sorted by path and line. Only real TODO comments, not words that merely contain 'todo'.", t_todo_grade),
    ("kv_cli", None, "Build a command line tool kv.py: `kv.py set KEY VALUE`, `kv.py get KEY` (prints the value, exit code 1 with an error message on stderr if the key is missing), `kv.py del KEY`, `kv.py list` (prints keys, one per line). Persist in kv.json next to the script. Test it by running it.", t_kv_grade),
    ("web_counter", None, "Create index.html: a heading, a span with id=count showing a number that starts at 0, a button labeled 'Add' that increments it by one, and a button labeled 'Reset' that sets it back to 0. Single file, clean readable styling. Open it in the browser and check that it works.", t_web_grade),
    ("rename_func", t_rename_setup, "Rename the function calc_total to compute_total everywhere in this project (code, tests, docs). Make sure `python3 -m unittest discover -s tests -t .` still passes.", t_rename_grade),
    ("cli_feature", t_cli_setup, "Extend wc.py: add a `--top N` option that limits the output to the N most frequent words, and a `--json` flag that prints the result as a JSON object mapping word to count instead of the plain lines. Keep the existing plain output unchanged. Try both options.", t_cli_grade),
]


# ------------------------------------------------------------------ runner

async def run_agent(model, d, prompt):
    stats = {"steps": 0, "tool_errors": 0, "tps": [], "error": ""}
    t0 = time.time()
    async with websockets.connect(URL, max_size=None, origin=ORIGIN) as ws:
        await ws.send(json.dumps({"type": "user", "text": prompt, "model": model, "think": False, "mode": "plan" if PHASED else "auto",
                                  "root": str(d), "num_ctx": 32768, "review": False}))
        stopped, plan, approved = False, None, False
        while True:
            left = TIMEOUT - (time.time() - t0)
            if left <= 0 and not stopped:
                await ws.send(json.dumps({"type": "stop"})); stopped = True; stats["error"] = "timeout"
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), max(5, left) if not stopped else 30))
            except asyncio.TimeoutError:
                stats["error"] = stats["error"] or "no response"; break
            t = m["type"]
            if t == "tool": stats["steps"] += 1
            elif t == "result" and not m["ok"]: stats["tool_errors"] += 1
            elif t == "usage": stats["tps"].append(m["tps"])
            elif t == "error": stats["error"] = m["text"][:80]
            elif t == "plan_proposed": plan = m["plan"]; stats["plan_tasks"] = len(plan["tasks"]); stats["plan_secs"] = int(time.time() - t0)
            elif t == "done":
                if PHASED and plan and not approved:        # phase 1 finished: approve the board unchanged and run it
                    approved = True
                    await ws.send(json.dumps({"type": "plan_approve", "tasks": plan["tasks"], "mode": "auto"}))
                    continue
                if PHASED and not plan:
                    stats["error"] = stats["error"] or "no plan was produced"
                break
    stats["secs"] = int(time.time() - t0)
    stats["tps"] = round(sum(stats["tps"]) / len(stats["tps"]), 1) if stats["tps"] else 0
    return stats


async def main():
    import httpx
    models = sys.argv[1:] or [n for n in (m["name"] for m in httpx.get("http://127.0.0.1:11434/api/tags").json()["models"]) if "embed" not in n]
    cfg_file = HERE.parent / "data" / "settings.json"
    saved = cfg_file.read_text() if cfg_file.exists() else None
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else []
    try:
        for model in models:
            for name, setup, prompt, grade in TASKS:
                if TASK_FILTER and name not in TASK_FILTER:
                    continue
                d = BASE / re.sub(r"[^\w.-]", "_", model) / name
                shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
                if setup: setup(d)
                try:
                    st = await run_agent(model, d, prompt)
                    score, note = await asyncio.to_thread(grade, d)
                except Exception as e:
                    st, score, note = {"secs": 0, "steps": 0, "tool_errors": 0, "tps": 0, "error": str(e)[:60]}, 0.0, "grader/run failed"
                row = {"model": model, "task": name, "score": score, "note": note, **st}
                results.append(row); RESULTS.parent.mkdir(parents=True, exist_ok=True); RESULTS.write_text(json.dumps(results, indent=1))
                print(f"{model:<22} {name:<13} score={score:.1f}  {st['secs']:>3}s  steps={st['steps']:<2} errs={st['tool_errors']} tps={st['tps']:<5} {note} {st['error']}", flush=True)
    finally:
        if saved is not None:
            cfg_file.write_text(saved)


if __name__ == "__main__":
    asyncio.run(main())
