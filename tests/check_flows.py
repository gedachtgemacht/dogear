"""Flows: what the user does in the live view becomes steps with locators; a replay repeats them on a fresh page;
a failing step and console errors are reported; files round-trip. usage: uv run python tests/check_flows.py  (needs Chrome)"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dogear import flows  # noqa: E402
from dogear.browser import Browser  # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures" / "flow.html"
ok_all = True


def check(name, cond, extra=""):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


async def main():
    b = Browser(Path(tempfile.mkdtemp()))
    await b.ensure()
    await b.set_viewport(1280, 800)
    await b.navigate(FX.as_uri())
    await asyncio.sleep(0.4)
    # record: the UI forwards a click into the field, typed text, Enter, then a click on the link
    b.recorder = flows.Recorder(b.url)
    q = await b.eval("(()=>{const r=document.getElementById('q').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
    await b.user_mouse({"kind": "down", "x": q["x"], "y": q["y"], "button": "left"})
    await b.user_mouse({"kind": "up", "x": q["x"], "y": q["y"], "button": "left"})
    for ch in "bread":
        await b.user_key({"kind": "down", "key": ch, "text": ch, "code": "Key" + ch.upper(), "vk": ord(ch.upper())})
        await b.user_key({"kind": "up", "key": ch, "code": "Key" + ch.upper(), "vk": ord(ch.upper())})
    await b.user_key({"kind": "down", "key": "Enter", "code": "Enter", "vk": 13})
    await asyncio.sleep(0.3)
    m = await b.eval("(()=>{const r=document.getElementById('more').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
    await b.user_mouse({"kind": "down", "x": m["x"], "y": m["y"], "button": "left"})
    await b.user_mouse({"kind": "up", "x": m["x"], "y": m["y"], "button": "left"})
    rec, b.recorder = b.recorder, None
    rec.flush()
    acts = [s["action"] for s in rec.steps]
    check("recorded click, type, key, click", acts == ["click", "type", "key", "click"], str(acts))
    check("the typed text is one step", next((s for s in rec.steps if s["action"] == "type"), {}).get("text") == "bread")
    check("locators carry id / name / text", rec.steps[0]["target"].get("id") == "q" and rec.steps[-1]["target"].get("text") == "More", str(rec.steps[-1]["target"]))
    check("steps describe themselves", "type \"bread\"" in flows.describe_step(rec.steps[1]))
    # save and load
    root = Path(tempfile.mkdtemp())
    f = flows.save(root, "Search for bread", rec.steps, rec.start_url)
    check("saved under .dogear/flows", f.exists() and f.parent.name == "flows")
    lst = flows.list_flows(root)
    check("listed with step count", lst and lst[0]["name"] == "Search for bread" and lst[0]["steps"] == 4, str(lst))
    flow = flows.load(root, "Search for bread")
    check("loaded by name", flow and len(flow["steps"]) == 4)
    check("check flag round-trips", flows.set_check(root, "Search for bread", True) and flows.list_flows(root)[0]["check"])
    # replay on a fresh page: the result text proves every step ran
    await b.navigate(FX.as_uri())
    await asyncio.sleep(0.3)
    r = await flows.replay(b, flow, pause=0.3)
    out = await b.eval("document.getElementById('out').textContent")
    check("replay runs every step", r["ok"] and r["done"] == 4, str(r))
    check("replay reproduces the result", out == "You searched: bread · more", out)
    # a flow whose element vanished fails at that step, with a reason
    broken = {"name": "broken", "url": flow["url"], "steps": [{"action": "click", "target": {"tag": "button", "text": "Does not exist", "css": "#nope"}}]}
    r2 = await flows.replay(b, broken, pause=0.2)
    check("a missing element fails the step with a reason", not r2["ok"] and r2["failed"] == 0 and "not found" in r2["detail"], str(r2))
    check("the report reads well", "FAILED" in flows.format_report(broken, r2))
    await b.close()


asyncio.run(main())
print("ALL PASS" if ok_all else "SOME FAILED")
sys.exit(0 if ok_all else 1)
