"""Validate the audit against fixtures with known defects. usage: uv run python tools/audit_test.py"""
import asyncio, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dogear.browser import Browser
from dogear.audit import AUDIT_JS

FX = Path(__file__).resolve().parent / "fixtures"
EXPECT = {  # fixture: (kinds that must be found, size)
    "overflow.html": ({"overflow"}, 390), "contrast.html": ({"contrast", "text-size"}, 1280), "grid_hole.html": ({"grid-hole"}, 1280),
    "empty_box.html": ({"empty-area"}, 1280), "duplicate.html": ({"duplicate"}, 1280), "tiny.html": ({"target-size", "icon-size"}, 390),
    "overlap.html": ({"overlap"}, 1280), "emptybtn.html": ({"empty-control"}, 1280), "basics.html": ({"viewport", "alt", "label"}, 1280), "card_soup.html": ({"card-soup"}, 1280),
}

async def audit(b, url, w, h):
    await b.set_viewport(w, h); await b.navigate(url); await asyncio.sleep(0.3)
    return (await b.eval(AUDIT_JS))["findings"]

async def main():
    b = Browser(Path(tempfile.mkdtemp())); await b.ensure()
    ok = bad = 0
    for name, (want, size) in EXPECT.items():
        got = {f["kind"] for f in await audit(b, f"file://{FX/name}", size, 844 if size < 600 else 800)}
        miss = want - got
        print(f"{'PASS' if not miss else 'FAIL'}  {name:<18} found={sorted(got)}" + (f"  MISSING={sorted(miss)}" if miss else ""))
        ok, bad = ok + (not miss), bad + bool(miss)
    got = {f["kind"] for f in await audit(b, f"file://{FX/'dash_cards.html'}", 1280, 800)}
    print(f"{'PASS' if 'card-soup' not in got else 'FAIL'}  dash_cards.html    app-style card grid without footer is not flagged"); ok, bad = ok + ('card-soup' not in got), bad + ('card-soup' in got)
    for w, h in ((1280, 800), (390, 844)):
        fs = await audit(b, f"file://{FX/'clean.html'}", w, h)
        serious = [f for f in fs if f["sev"] in ("high", "medium")]
        print(f"{'PASS' if not serious else 'FAIL'}  clean.html @{w}  no false positives" + (f"  {[(f['kind'], f['msg']) for f in serious]}" if serious else ""))
        ok, bad = ok + (not serious), bad + bool(serious)
    print(f"\n{ok} passed, {bad} failed")
    await b.close()

asyncio.run(main())
