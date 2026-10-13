"""Project memory, snippets and learned skills. usage: uv run python tools/memory_test.py [--live]
Unit checks run offline; --live also runs two real sessions through the server and the helper model's suggestions."""
import asyncio, json, shutil, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx
from dogear import memory as M, agent as A

ok_all = True
def check(name, cond, extra=""):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

def unit():
    root = Path(tempfile.mkdtemp(prefix="memtest-"))
    M.GLOBAL = Path(tempfile.mkdtemp(prefix="memglobal-"))
    A.mem.GLOBAL = M.GLOBAL
    r = M.save(root, "memory", "Deploy command", "Deploy with `make ship`; never npm publish here because the registry is private.", type="command")
    check("save memory", r["id"] == "deploy-command" and (root / ".dogear/memory/deploy-command.md").is_file())
    check("update flagged", M.save(root, "memory", "Deploy command", "Deploy with `make ship` only.", type="command")["updated"])
    for bad in ["api_key = sk-abcdefghijklmnopqrstuvwx", "password: hunter2hunter2hunter2", "-----BEGIN RSA PRIVATE KEY-----\nabc"]:
        try: M.save(root, "memory", "x", bad); check("secret rejected: " + bad[:16], False)
        except M.MemoryError_: check("secret rejected: " + bad[:16], True)
    try: M.save(root, "memory", "big", "x" * 5000); check("size limit", False)
    except M.MemoryError_: check("size limit", True)
    try: M.save(root, "skill", "s", "do it", description="d", triggers=""); check("skill needs triggers", False)
    except M.MemoryError_: check("skill needs triggers", True)
    M.save(root, "snippet", "Debounce", "function debounce(fn, ms) {\n  let t;\n  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };\n}", language="js", description="Delay calls until input settles", tags="javascript, timing, input")
    M.save(root, "memory", "Prefers short answers", "The user wants short answers without preamble.", scope="global", type="preference")
    M.save(root, "skill", "Release checklist", "1. Run the tests\n2. Bump VERSION\n3. Tag with git tag vX", scope="project", description="How we cut a release", triggers="release, ship it")
    es = M.entries(root)
    check("entries across kinds and scopes", {(e["kind"], e["scope"]) for e in es} == {("memory", "project"), ("memory", "global"), ("snippet", "project"), ("skill", "project")}, str([(e["kind"], e["scope"]) for e in es]))
    check("search by keyword", [e["name"] for e in M.search(root, "how do I deploy")][:1] == ["Deploy command"])
    check("search snippet by tag", [e["kind"] for e in M.search(root, "javascript timing")][:1] == ["snippet"])
    check("search miss", M.search(root, "kubernetes helm") == [])
    block, counts = M.prompt_block(root, "add a debounce to the search box")
    check("prompt has notes", "make ship" in block and "short answers" in block and "all projects" in block)
    check("matching snippet attached", "clearTimeout(t)" in block, block[-300:])
    block2, _ = M.prompt_block(root, "write a haiku")
    check("unrelated request attaches no code", "clearTimeout(t)" not in block2 and "Debounce" in block2)
    text, names = A.load_skills("we want to ship it today, release please", root)
    check("learned skill loads on trigger", "Bump VERSION" in text and "Release checklist" in names, str(names))
    check("learned skill in index", any(k["name"] == "Release checklist" for k in A.list_skills(root)))
    # tools
    from dogear import tools
    ctx = tools.Ctx(root)
    check("Remember tool", "Saved" in M.Remember(ctx, title="Port", content="Dev server runs on 8123, not 3000."))
    check("Recall tool", "8123" in M.Recall(ctx, query="which port"))
    (root / "util.py").write_text("def slug(s):\n    import re\n    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')\n")
    M.SaveSnippet(ctx, name="slug helper", file_path="util.py", start=1, end=3, tags="string")
    check("SaveSnippet copies file lines verbatim", "re.sub(r'[^a-z0-9]+'" in M.Recall(ctx, query="slug helper") and any(e["language"] == "py" for e in M.entries(root, ("snippet",))))
    check("Forget", "Deleted" in M.Forget(ctx, kind="memory", name="Port") and not M.search(root, "8123"))
    try: M.Forget(ctx, kind="memory", name="nothing here"); check("Forget unknown", False)
    except tools.ToolError: check("Forget unknown", True)
    try: M.Remember(ctx, title="k", content="token = ghp_abcdefghijklmnopqrstuvwxyz0123456789"); check("Remember rejects secret", False)
    except tools.ToolError: check("Remember rejects secret", True)
    check("path traversal in name stays inside", M.save(root, "memory", "../../etc/passwd", "harmless note text")["path"].startswith(str(root / ".dogear/memory")))
    shutil.rmtree(root); shutil.rmtree(M.GLOBAL)

async def live():
    root = Path("/home/user/dogear/projects/memory-live"); shutil.rmtree(root, ignore_errors=True); root.mkdir(parents=True)
    (root / "slugify.py").write_text('import re\n\n\ndef slugify(text):\n    """Lowercase, ASCII-only, dash-separated."""\n    text = re.sub(r"[^a-z0-9]+", "-", text.lower())\n    return text.strip("-")\n')
    import websockets
    async def run(text, label):
        notices, tools_, content = [], [], ""
        async with websockets.connect("ws://127.0.0.1:7870/ws", max_size=None, origin="http://127.0.0.1:7870") as ws:
            await ws.send(json.dumps({"type": "new"}))
            await ws.send(json.dumps({"type": "user", "text": text, "model": "qwen3.6:35b-a3b", "think": False, "mode": "auto", "root": str(root), "num_ctx": 32768, "review": False}))
            sugg = None
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 300))
                if m["type"] == "notice": notices.append(m["text"])
                elif m["type"] == "tool": tools_.append(m["name"])
                elif m["type"] == "token": content += m["text"]
                elif m["type"] == "done": break
        print(f"[{label}] tools={tools_} notices={[n for n in notices if 'Memory' in n]}")
        return content, tools_
    await run("Remember for this project: deploys go out with `make ship` (never npm publish, our registry is private). Save that as a note, then confirm in one line.", "session 1")
    notes = list((root / ".dogear/memory").glob("*.md"))
    check("agent saved a note in project memory", bool(notes) and any("make ship" in f.read_text() for f in notes), str(notes))
    content, tools_ = await run("How do we deploy this project? Answer in one line, do not use any tools.", "session 2 (fresh)")
    check("new session knows the deploy command without tools", "make ship" in content and not tools_, content[:120])
    # suggestions from the helper model, snippet code must be verbatim from the file
    async with httpx.AsyncClient() as c:
        items = await M.suggest(c, "http://127.0.0.1:11434", "qwen3.5:4b", root,
            "Add a slugify helper and make sure umlauts are handled; also fix the CI failure caused by Python 3.12 removing distutils.",
            "Added slugify.py. The CI failure came from distutils being removed in Python 3.12; pinned setuptools in requirements-dev.txt instead of importing distutils.",
            ["slugify.py"], ["python -m pytest -q", "pip install setuptools"])
    print("suggestions:", json.dumps(items, ensure_ascii=False)[:700])
    for it in items:
        if it["kind"] == "snippet":
            check("snippet suggestion is verbatim file text", it["content"] in (root / "slugify.py").read_text())
        check("suggestion has no secret", not M.SECRET.search(it["content"]))
    check("suggest returns at most 3", len(items) <= 3)

unit()
if "--live" in sys.argv:
    asyncio.run(live())
print("ALL PASS" if ok_all else "SOME FAILED")
sys.exit(0 if ok_all else 1)
