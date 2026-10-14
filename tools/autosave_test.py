"""Auto-saved suggestions: memory and snippets are saved with source=auto, skills and secrets never. usage: uv run python tools/autosave_test.py"""
import asyncio, sys, tempfile, json
from pathlib import Path
sys.path.insert(0, "/home/user/dogear")
import httpx
from dogear import agent as A, memory as M
async def main():
    root = Path(tempfile.mkdtemp(prefix="autosave-"))
    events = []
    async def send(m): events.append(m)
    async def fake(*a, **k):
        return [{"kind": "memory", "name": "Deploy needs make ship", "content": "Deploys go out with make ship; npm publish is blocked by the private registry.", "type": "command", "scope": "project", "description": ""},
                {"kind": "snippet", "name": "slug helper", "content": "def slug(s):\n    import re\n    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')", "language": "py", "tags": "string", "scope": "project", "description": "slug"},
                {"kind": "skill", "name": "Release checklist", "content": "1. test 2. tag", "triggers": "release", "scope": "project", "description": ""},
                {"kind": "memory", "name": "leaks", "content": "api_key = sk-abcdefghijklmnopqrstuvwxyz", "type": "fact", "scope": "project", "description": ""}]
    M.suggest = fake
    async with httpx.AsyncClient() as c:
        ag = A.Agent(send, c, None)
        await ag._suggest(root, 3, "request", "answer", [], [])
    ev = [e for e in events if e["type"] == "auto_saved"]
    print("events:", [(e["user_idx"], [(i["kind"], i["name"]) for i in e["items"]]) for e in ev])
    files = sorted(str(p.relative_to(root)) for p in root.rglob("*.md"))
    print("files:", files)
    print("source marker:", (root / ".dogear/memory/deploy-needs-make-ship.md").read_text().splitlines()[1:6])
    ok = ev and len(ev[0]["items"]) == 2 and not any("skills" in f for f in files) and not any("leaks" in f for f in files)
    print("PASS" if ok else "FAIL")
asyncio.run(main())
