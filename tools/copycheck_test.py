"""Copy check against fixtures with known errors and a clean page. usage: uv run python tools/copycheck_test.py"""
import asyncio, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx
from dogear import copycheck as C
from dogear.browser import Browser
BRIEF = open(Path(__file__).with_name("task_design_roest.txt")).read()
FX = Path(__file__).parent / "fixtures"
ok_all = True
def check(name, cond, extra=""):
    global ok_all; ok_all &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
async def blocks_of(b, f):
    await b.navigate("file://" + str(FX / f)); await asyncio.sleep(0.4)
    return await b.eval(C.TEXT_JS)
async def main():
    b = Browser(Path(tempfile.mkdtemp())); await b.ensure()
    bad, clean = await blocks_of(b, "copy_bad.html"), await blocks_of(b, "copy_clean.html")
    check("text extraction gets headings, list items, links", "Hafen – dunkel, Schokolade und Nuss, 12,50 € / 250 g" in bad and "Kaffee" in bad and len(bad) >= 8, str(bad)[:300])
    async with httpx.AsyncClient() as c:
        for model in ("qwen3.6:35b-a3b",):
            fb = await C.check(c, "http://127.0.0.1:11434", model, BRIEF, bad)
            fc = await C.check(c, "http://127.0.0.1:11434", model, BRIEF, clean)
            print(model, "bad:", [(f["kind"], f["quote"]) for f in fb]); print(model, "clean:", [(f["kind"], f["quote"]) for f in fc])
            q = " ".join(f["quote"].lower() for f in fb)
            check("finds 'Jedes zweite Wochen'", "zweite wochen" in q)
            check("finds 'Kein Abo-Bindlichkeit'", "kein abo-bindlichkeit" in q or "abo-bindlichkeit" in q)
            check("flags invented delivery promise", "zwei wochen nach der röstung" in q or "versenden zwei wochen" in q)
            check("flags invented year/certification", "1987" in q or "bio" in q)
            check("does not flag prices or hours from the brief", not any(x in q for x in ("12,50", "13,90", "8–17")))
            check("clean page has no findings", not fc, str(fc))
    print("\n" + C.format_report(fb))
    print("ALL PASS" if ok_all else "SOME FAILED"); sys.exit(0 if ok_all else 1)
asyncio.run(main())
