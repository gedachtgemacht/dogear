"""Design benchmark: briefs from the design dataset, measured with dogear's own audit plus the dataset's static checks.

usage:
  uv run python tools/design_bench.py gold                     # measure the dataset's own solutions (the reference line)
  uv run python tools/design_bench.py run MODEL [N]            # let a model solve N briefs through the server, then measure
Outputs: data/design-bench/<label>/<id>.jpg screenshots, a contact sheet and results.json; prints a table.
"""
import asyncio, base64, json, os, re, shutil, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import websockets
from dogear.audit import AUDIT_JS
from dogear.browser import Browser

ROOT = Path(__file__).resolve().parent.parent
DS = ROOT / "data" / "design-dataset-300"
OUT = ROOT / "data" / "design-bench"
TASKS = {t["id"]: t for t in json.loads((DS / "tasks_all.json").read_text())}
# spread over the families: landing, dashboard, form, component, content, mobile, email, print, admin, 4 artstyles, de + en, plain + tailwind
IDS = ["001", "018", "026", "044", "060", "126", "104", "112", "151", "176", "206", "226", "251", "276"]
SUFFIX = {("plain", "en"): "Use plain HTML and CSS, no frameworks.", ("tailwind", "en"): "Use HTML with Tailwind CSS.",
          ("plain", "de"): "Verwende reines HTML und CSS, keine Frameworks.", ("tailwind", "de"): "Verwende HTML mit Tailwind CSS."}
URL, ORIGIN = "ws://127.0.0.1:7870/ws", "http://127.0.0.1:7870"
TIMEOUT = 600


def static_problems(html: str, task: dict) -> tuple[list[str], list[str]]:
    """(floor failures, generated-UI tells): the shared source checks of the quality gate."""
    from dogear.audit import static_check
    email = "email" in task["prompt"].lower() or "e-mail" in task["prompt"].lower()
    return static_check(html, email)


async def measure(browser: Browser, page: Path, task: dict, shot: Path) -> dict:
    html = page.read_text(errors="replace")
    floor, tells = static_problems(html, task)
    res = {"floor": floor, "tells": tells, "lines": html.count("\n"), "high": 0, "medium": 0, "kinds": [], "overflow": False, "js_errors": 0}
    errs = []
    for w, h in ((1280, 800), (390, 844)):
        await browser.set_viewport(w, h)
        await browser.navigate("file://" + str(page.resolve()))
        await asyncio.sleep(1.2)
        a = await browser.eval(AUDIT_JS)
        for f in a["findings"]:
            if f["sev"] == "high": res["high"] += 1
            elif f["sev"] == "medium": res["medium"] += 1
            if f["sev"] in ("high", "medium"): res["kinds"].append(f["kind"])
        if await browser.eval("document.documentElement.scrollWidth") > w + 2: res["overflow"] = True
        if w == 1280:
            shot.parent.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(base64.b64decode(await browser.screenshot()))
    res["kinds"] = sorted(set(res["kinds"]))
    return res


async def solve(model: str, task: dict, d: Path) -> dict:
    prompt = f"{task['prompt']} {SUFFIX[(task['stack'], task['lang'])]}\nWrite the result to index.html in this folder."
    st = {"secs": 0, "steps": 0, "error": ""}
    t0 = time.time()
    async with websockets.connect(URL, max_size=None, origin=ORIGIN) as ws:
        await ws.send(json.dumps({"type": "user", "text": prompt, "model": model, "think": False, "mode": "auto", "root": str(d), "num_ctx": 32768, "review": True}))
        while True:
            left = TIMEOUT - (time.time() - t0)
            if left <= 0:
                await ws.send(json.dumps({"type": "stop"})); st["error"] = "timeout"; left = 30
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), left))
            except asyncio.TimeoutError:
                st["error"] = st["error"] or "no response"; break
            if m["type"] == "tool": st["steps"] += 1
            elif m["type"] == "error": st["error"] = m["text"][:80]
            elif m["type"] == "done": break
    st["secs"] = int(time.time() - t0)
    return st


def summarize(label: str, rows: list[dict]):
    n = len(rows) or 1
    made = [r for r in rows if r.get("exists", True)]
    print(f"\n{label}: {len(made)}/{len(rows)} pages")
    print(f"{'id':<5} {'style':<11} {'secs':>5} {'high':>4} {'med':>4}  floor / tells")
    for r in rows:
        print(f"{r['id']:<5} {str(r.get('style') or ''):<11} {r.get('secs', 0):>5} {r.get('high', '-'):>4} {r.get('medium', '-'):>4}  "
              f"{', '.join(r.get('floor', [])) or 'ok'} | {', '.join(r.get('tells', [])) or '-'}" + (" | OVERFLOW" if r.get("overflow") else "")
              + (f" | {r['error']}" if r.get("error") else ""))
    print(f"mean audit high {sum(r.get('high', 0) for r in made)/max(len(made),1):.2f}, medium {sum(r.get('medium', 0) for r in made)/max(len(made),1):.2f}; "
          f"floor failures {sum(len(r.get('floor', [])) for r in made)}, tells {sum(len(r.get('tells', [])) for r in made)}, overflow {sum(1 for r in made if r.get('overflow'))}")


async def contact_sheet(label: str, rows: list[dict], browser: Browser):
    cells = "".join(f"<figure><img src='data:image/jpeg;base64,{base64.b64encode((OUT / label / (r['id'] + '.jpg')).read_bytes()).decode()}'><figcaption>{r['id']} {r.get('style') or ''}</figcaption></figure>"
                    for r in rows if (OUT / label / (r["id"] + ".jpg")).exists())
    html = f"<body style='margin:0;background:#222;display:grid;grid-template-columns:repeat(4,1fr);gap:6px;padding:6px'><style>img{{width:100%;display:block}}figure{{margin:0;color:#ccc;font:12px sans-serif}}</style>{cells}"
    f = OUT / label / "sheet.html"; f.write_text(html)
    await browser.set_viewport(1600, 900); await browser.navigate("file://" + str(f)); await asyncio.sleep(1.5)
    h = await browser.eval("document.documentElement.scrollHeight")
    await browser.set_viewport(1600, min(int(h), 4000)); await asyncio.sleep(0.5)
    (OUT / label / "sheet.jpg").write_bytes(base64.b64decode(await browser.screenshot()))


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "gold"
    model = sys.argv[2] if mode == "run" else "gold"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else len(IDS)
    label = re.sub(r"[^\w.-]", "_", model)
    (OUT / label).mkdir(parents=True, exist_ok=True)
    b = Browser(Path(tempfile.mkdtemp())); await b.ensure()
    rows = []
    prev = OUT / label / "results.json"
    if mode == "run" and prev.exists() and not os.environ.get("DESIGN_FRESH"):
        rows = [r for r in json.loads(prev.read_text()) if r["id"] in IDS[:n]]          # resume: keep the finished briefs
    for i in IDS[:n]:
        if any(r["id"] == i for r in rows):
            continue
        t = TASKS[i]
        if mode == "gold":
            page, st = DS / "solutions" / f"{i}.html", {"secs": 0}
        else:
            d = ROOT / "projects" / "design-bench" / label / i
            shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
            st = await solve(model, t, d)
            page = d / "index.html"
            if not page.exists():                         # fall back to any html the model wrote
                found = sorted(d.glob("*.html"))
                page = found[0] if found else page
        row = {"id": i, "style": t.get("style"), "stack": t["stack"], "lang": t["lang"], **st}
        if page.exists():
            row.update(await measure(b, page, t, OUT / label / f"{i}.jpg"))
        else:
            row.update(exists=False, error=row.get("error") or "no html file")
        rows.append(row)
        print(f"{i} done: high={row.get('high')} medium={row.get('medium')} floor={len(row.get('floor', []))} tells={len(row.get('tells', []))}", flush=True)
        (OUT / label / "results.json").write_text(json.dumps(rows, indent=1))
    summarize(label, rows)
    await contact_sheet(label, rows, b)

asyncio.run(main())
