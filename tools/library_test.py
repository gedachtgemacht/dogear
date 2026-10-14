"""Snippet library: dedup/replace, semantic search, and the rating -> extraction -> plan-prefill loop.
usage: uv run python tools/library_test.py [--live]"""
import asyncio, json, shutil, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx
from dogear import library as L
URL = "http://127.0.0.1:11434"
ok_all = True
def check(name, cond, extra=""):
    global ok_all; ok_all &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

WC = '''def count_text(text):
    lines = text.count("\\n") + (0 if text.endswith("\\n") or not text else 1)
    return lines, len(text.split()), len(text)
'''
WC2 = '''def count_text(s):
    n_lines = s.count("\\n") + (0 if s.endswith("\\n") or not s else 1)
    return n_lines, len(s.split()), len(s)
'''
DEB = '''function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
'''
SLUG = '''import re
def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "untitled"
'''

async def unit():
    L.DB = Path(tempfile.mkdtemp()) / "lib.db"
    async with httpx.AsyncClient() as c:
        a = await L.add(c, URL, {"problem": "Count lines, words and characters of a text, like the wc command.", "solution": WC, "language": "python", "project": "wc"})
        b = await L.add(c, URL, {"problem": "Delay a function call until the user stops typing.", "solution": DEB, "language": "javascript", "project": "ui"})
        s = await L.add(c, URL, {"problem": "Turn a title into a URL-safe slug.", "solution": SLUG, "language": "python", "project": "blog"})
        check("three entries stored", len({a["id"], b["id"], s["id"]}) == 3 and not any(x["replaced"] for x in (a, b, s)))
        d = await L.add(c, URL, {"problem": "Count the lines, words and characters in a string (wc style).", "solution": WC2, "language": "python", "project": "wc2"})
        check("near-duplicate replaces instead of appending", d["replaced"] and d["id"] == a["id"] and len(L.entries()) == 3, str(d))
        sec = await L.add(c, URL, {"problem": "x" * 20, "solution": "api_key = 'sk-abcdefghijklmnopqrstuvwxyz'"}) if False else None
        for q, want in (("a wc-like counter for text files", a["id"]), ("wait until typing stops before calling the search", b["id"]),
                        ("make a url friendly name from a blog post title", s["id"])):
            hits = await L.search(c, URL, q, 3)
            print("  ", q[:48].ljust(48), [(h["id"], h["score"]) for h in hits])
            check(f"search finds the right entry for: {q[:40]}", hits and hits[0]["id"] == want)
        miss = await L.search(c, URL, "configure a kubernetes helm chart for postgres", 3)
        print("   unrelated query ->", [(h["id"], h["score"]) for h in miss])
        check("unrelated query returns nothing", not miss)
        try:
            await L.add(c, URL, {"problem": "leaks a key", "solution": "token = 'ghp_abcdefghijklmnopqrstuvwxyz0123456789'"}); check("secrets are refused", False)
        except ValueError:
            check("secrets are refused", True)
        check("delete", L.delete(a["id"]) and len(L.entries()) == 2)
        au = await L.add(c, URL, {"problem": "Parse a semver string into major, minor and patch numbers.", "solution": "def semver(v):\n    a, b, c = v.split('.')\n    return int(a), int(b), int(c)\n",
                                  "language": "python", "auto": True})
        check("auto entry carries the mark", next(e for e in L.entries() if e["id"] == au["id"])["auto"] is True)
        check("rated entries are not auto", not next(e for e in L.entries() if e["id"] == s["id"])["auto"])
        check("only_auto keeps rated entries", L.delete_many([s["id"]], only_auto=True) == 0 and any(e["id"] == s["id"] for e in L.entries()))
        L.confirm([au["id"]])
        check("confirm clears the mark", not next(e for e in L.entries() if e["id"] == au["id"])["auto"])
        au2 = await L.add(c, URL, {"problem": "Left-pad a number with zeros to a fixed width.", "solution": "def pad(n, w=3):\n    return str(n).zfill(w)\n", "language": "python", "auto": True})
        check("only_auto removes auto entries", L.delete_many([au2["id"]], only_auto=True) == 1)

async def live():
    import websockets
    root = Path("/home/user/dogear/projects/lib_e2e"); shutil.rmtree(root, ignore_errors=True); root.mkdir(parents=True)
    L.DB = Path("/home/user/dogear/data/library.db")
    before = len(L.entries())
    base = {"model": "qwen3.6:35b-a3b", "think": False, "root": str(root), "num_ctx": 32768, "review": False}
    async def until(ws, kinds, timeout=400):
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            if m["type"] in kinds: return m
    async with websockets.connect("ws://127.0.0.1:7870/ws", max_size=None, origin="http://127.0.0.1:7870") as ws:
        await ws.send(json.dumps({"type": "new"}))
        await ws.send(json.dumps({"type": "user", "mode": "auto", "text": "Create slugify.py with a function slugify(title) that turns a title into a URL slug: lowercase, ASCII letters and digits, words joined by single dashes, umlauts transliterated (ä->ae, ö->oe, ü->ue, ß->ss). Add a short self-test with asserts and run it.", **base}))
        sm = await until(ws, {"summary"})
        await until(ws, {"done"})
        check("run produced files", bool(sm.get("changes")), str(sm.get("changes")))
        await ws.send(json.dumps({"type": "rate", "turn": 0, "value": 1}))
        r = await until(ws, {"rated"}, 20)
        check("rating is stored", r["rating"]["value"] == 1)
        saved = await until(ws, {"library_saved"}, 300)
        print("  saved:", [(e["language"], e["problem"][:70], e["replaced"]) for e in saved["entries"]])
        check("snippets were extracted into the library", len(saved["entries"]) >= 1 and not saved.get("error"), str(saved))
        check("library grew or an entry was updated", len(L.entries()) >= before)
        # a second thumbs up must not extract again
        await ws.send(json.dumps({"type": "rate", "turn": 0, "value": 1}))
        await until(ws, {"rated"}, 20)
        n = len(L.entries())
        await asyncio.sleep(3)
        check("rating twice does not duplicate", len(L.entries()) == n)
    # the planning phase of a later, similar task gets the entry injected
    async with websockets.connect("ws://127.0.0.1:7870/ws", max_size=None, origin="http://127.0.0.1:7870") as ws:
        root2 = Path("/home/user/dogear/projects/lib_e2e2"); shutil.rmtree(root2, ignore_errors=True); root2.mkdir(parents=True)
        await ws.send(json.dumps({"type": "new"}))
        await ws.send(json.dumps({"type": "user", "mode": "plan", "text": "I need a helper that converts blog post titles into clean URL slugs, with German umlauts handled.", **{**base, "root": str(root2)}}))
        notes = []
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 300))
            if m["type"] == "notice": notes.append(m["text"])
            if m["type"] in ("plan_proposed", "done"): break
        print("  notices:", notes)
        check("planning phase saw library hits", any(n.startswith("Library:") for n in notes), str(notes))

if __name__ == "__main__":
    asyncio.run(unit())
    if "--live" in sys.argv:
        asyncio.run(live())
    print("ALL PASS" if ok_all else "SOME FAILED"); sys.exit(0 if ok_all else 1)
