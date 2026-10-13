"""Test dogear/ultra.py: primitives with the helper model, then pattern "review" on a project with planted bugs.
usage: uv run python tools/test_ultra.py             (needs Ollama with qwen3.5:4b and qwen3.6:35b-a3b; takes a few minutes)
       uv run python tools/test_ultra.py --offline   (only the tests that need no model, a few seconds)"""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx

from dogear import ultra
from dogear.tools import Ctx, ToolError
from dogear.ultra import Ultra

HELPER, BIG = "qwen3.5:4b", "qwen3.6:35b-a3b"
ok = bad = 0


def check(name: str, cond: bool, detail: str = ""):
    global ok, bad
    ok, bad = ok + bool(cond), bad + (not cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)


INVENTORY = '''"""Stock bookkeeping for the warehouse."""
from dataclasses import dataclass


@dataclass
class Item:
    sku: str
    quantity: int
    price: float


def total_value(items: list[Item]) -> float:
    """Total value of everything in stock."""
    return sum(i.quantity * i.price for i in items)


def last_n_quantities(items: list[Item], n: int) -> int:
    """Combined quantity of the last n items in the list."""
    total = 0
    start = max(len(items) - n, 0)
    for i in range(start, len(items) - 1):
        total += items[i].quantity
    return total


def low_stock(items: list[Item], threshold: int = 5) -> list[str]:
    """SKUs whose quantity is below the threshold."""
    return [i.sku for i in items if i.quantity < threshold]
'''

BACKUP = '''"""Create a backup archive of the data directory."""
import os
import subprocess
import sys

DATA_DIR = "/srv/data"
BACKUP_DIR = "/var/backups"


def archive(name: str) -> int:
    """Pack DATA_DIR into BACKUP_DIR/<name>.tgz and return the exit status."""
    command = "tar czf " + BACKUP_DIR + "/" + name + ".tgz " + DATA_DIR
    return os.system(command)


def disk_free(path: str = BACKUP_DIR) -> str:
    """Human readable free space of the backup volume."""
    result = subprocess.run(["df", "-h", path], capture_output=True, text=True, check=True)
    return result.stdout


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: backup.py NAME")
        return 2
    print(disk_free())
    return archive(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
'''

STATS = '''"""Small numeric helpers."""
import math


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean of empty list")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    if not values:
        raise ValueError("median of empty list")
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def pairwise_diffs(values: list[float]) -> list[float]:
    """Differences between neighbouring values; one fewer than the input."""
    return [values[i + 1] - values[i] for i in range(len(values) - 1)]


def clamp(x: float, lo: float, hi: float) -> float:
    if lo > hi:
        raise ValueError("lo must not exceed hi")
    return max(lo, min(x, hi))


def stddev(values: list[float]) -> float:
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def percent(part: float, whole: float) -> float:
    return 0.0 if whole == 0 else 100.0 * part / whole
'''


def make_project() -> tuple[Path, dict[str, tuple[str, int]]]:
    root = Path(tempfile.mkdtemp(prefix="ultra_test_"))
    files = {"inventory.py": INVENTORY, "backup.py": BACKUP, "stats.py": STATS}
    for n, t in files.items():
        (root / n).write_text(t)
    at = lambda f, needle: next(i for i, l in enumerate(files[f].splitlines(), 1) if needle in l)
    planted = {"off-by-one in last_n_quantities": ("inventory.py", at("inventory.py", "range(start, len(items) - 1)")),
               "shell command built from user input": ("backup.py", at("backup.py", "os.system(command)"))}
    return root, planted


# ------------------------------------------------------------------ pure parts

def test_pure():
    s = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}, "b": {"type": "string", "enum": ["x", "y"]},
                                                              "c": {"type": "array", "items": {"type": "number"}}}}
    check("validate accepts a good object", ultra.validate({"a": 1, "b": "x", "c": [1, 2.5]}, s) == "")
    check("validate rejects wrong type", "expected integer" in ultra.validate({"a": "1"}, s))
    check("validate rejects bool as integer", ultra.validate({"a": True}, s) != "")
    check("validate rejects missing key", "missing" in ultra.validate({}, s))
    check("validate rejects bad enum", "one of" in ultra.validate({"a": 1, "b": "z"}, s))
    check("validate rejects bad array item", "c[1]" in ultra.validate({"a": 1, "c": [1, "q"]}, s))
    check("parse_where handles path:line", ultra.parse_where("src/a.py:12") == ("src/a.py", 12))
    check("parse_where handles ranges and ticks", ultra.parse_where("`./a.py:7-9`") == ("a.py", 7))
    check("parse_where rejects prose", ultra.parse_where("somewhere in the loop") is None)
    f = lambda t, line, sev, d: {"title": t, "file": "a.py", "line": line, "severity": sev, "dimensions": [d]}
    out = ultra.dedupe([f("Off-by-one in loop skips last item", 10, "medium", "correctness"),
                        f("Loop skips the last item (off-by-one)", 10, "high", "readability"),
                        f("Shell injection via os.system", 30, "high", "security"),
                        f("Off-by-one in loop skips last item", 90, "low", "correctness")])
    check("dedupe merges same line + similar title, keeps highest severity",
          len(out) == 3 and out[0]["severity"] == "high" and out[0]["dimensions"] == ["correctness", "readability"], f"{len(out)} left")
    d = Ultra._decide
    v = lambda x: {"verdict": x, "reason": "r"}
    check("decide: two confirms -> confirmed", d([v("confirmed"), v("confirmed")])[0] == "confirmed")
    check("decide: two refutes -> rejected", d([v("refuted"), v("refuted")])[0] == "rejected")
    check("decide: split -> disputed", d([v("confirmed"), v("refuted")])[0] == "disputed")
    check("decide: one refute + one failure -> rejected", d([v("refuted"), None])[0] == "rejected")
    check("decide: no votes -> disputed", d([None, None])[0] == "disputed")


async def test_parallel_pipeline(client):
    u = Ultra(client, HELPER, Path("."), concurrency=2)
    live = peak = 0

    async def job(i):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.15)
        live -= 1
        if i == 3:
            raise RuntimeError("boom")
        return i * 10

    res = await u.parallel([lambda i=i: job(i) for i in range(8)])
    check("parallel keeps order and turns a raising thunk into None", res == [0, 10, 20, None, 40, 50, 60, 70], str(res))
    check("parallel respects the concurrency cap", peak == 2, f"max concurrent {peak}")

    async def nested():   # a thunk that itself fans out must not deadlock on the cap
        return sum(x for x in await u.parallel([lambda i=i: job(i + 100) for i in range(3)]) if x)

    t0 = time.monotonic()
    r = await asyncio.wait_for(u.parallel([nested, nested, nested]), 10)
    check("nested parallel does not deadlock", r == [3030, 3030, 3030], f"{r} in {time.monotonic() - t0:.1f}s")

    async def add(x):
        return x + 1

    async def dbl(x):
        if x == 2:
            raise ValueError("no")
        return x * 2

    out = await u.pipeline([1, 2, 3], add, dbl)
    check("pipeline runs stages in order, failing item becomes None", out == [None, 6, 8], str(out))


async def test_facade():
    seen = []

    def handler(request: httpx.Request):
        seen.append(json.loads(request.content))
        line = json.dumps({"message": {"role": "assistant", "content": "{}"}, "done": True})
        return httpx.Response(200, content=line + "\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        u = Ultra(c, "m", Path("."))
        await u._turn("m", [{"role": "user", "content": "hi"}], None, fmt={"type": "object"})
    b = seen[0]
    check("requests use temperature 0.2, a token cap and the format field",
          b["options"]["temperature"] == 0.2 and b["options"]["num_predict"] > 0 and b["format"] == {"type": "object"} and b["options"]["num_ctx"] == 32768,
          str(b["options"]))


# ------------------------------------------------------------------ primitives against the real model

async def test_primitives(client):
    events: list[dict] = []
    root = Path(tempfile.mkdtemp(prefix="ultra_prim_"))
    (root / "secret.txt").write_text("The launch code word is PELICAN-7.\n")
    u = Ultra(client, HELPER, root, emit=events.append, concurrency=2)

    t0 = time.monotonic()
    res = await u.parallel([lambda i=i: u.agent("Reply with the single word OK.", tools=False, label=f"ping{i}") for i in range(5)])
    check("agents in parallel all answer", all(isinstance(r, str) and r for r in res), f"{res} in {time.monotonic() - t0:.1f}s")
    check("agent concurrency cap holds (max concurrent agents)", u.peak_agents <= 2, f"max concurrent {u.peak_agents}")
    st = [e["state"] for e in events if e.get("label") == "ping0" and e.get("event") == "agent"]
    check("events: queued -> running -> done", st == ["queued", "running", "done"], str(st))
    check("events carry type/event/phase/id/label", all(e["type"] == "ultra" and {"event"} <= set(e) for e in events)
          and all({"phase", "id", "label", "state"} <= set(e) for e in events if e["event"] == "agent"))

    schema = {"type": "object", "required": ["city", "population_millions", "is_capital"], "properties": {
        "city": {"type": "string"}, "population_millions": {"type": "number"}, "is_capital": {"type": "boolean"}}}
    got = await u.agent("Give basic facts about the city of Paris.", schema, tools=False, label="schema")
    check("schema output validates", isinstance(got, dict) and ultra.validate(got, schema) == "" and "paris" in got["city"].lower(), str(got))

    got = await u.agent("Find the file secret.txt in the project, read it and tell me the code word.", tools=ultra.FILE_TOOLS, max_steps=6, label="tools")
    check("worker uses tools (LS/Glob/Read) to find a fact", isinstance(got, str) and "PELICAN" in got.upper(), str(got)[:100])

    u.agent_timeout = 0.3
    t0 = time.monotonic()
    try:
        got = await u.agent("Write a detailed 800 word essay about the history of the bicycle.", tools=False, label="slow")
        raised = None
    except Exception as e:
        got, raised = "x", e
    el = time.monotonic() - t0
    check("timeout yields None, not an exception", got is None and raised is None and el < 5, f"{el:.1f}s, raised={raised!r}")
    check("timeout is reported as a failed event and a log line",
          any(e.get("state") == "failed" and e.get("label") == "slow" for e in events) and any(e["event"] == "log" and "slow" in e["detail"] for e in events))
    u.agent_timeout = 300
    again = await u.agent("Reply with the single word OK.", tools=False, label="after")
    check("the orchestrator keeps working after a timeout", isinstance(again, str) and again)


# ------------------------------------------------------------------ the review pattern

async def test_review(client):
    root, planted = make_project()
    events: list[dict] = []
    u = Ultra(client, BIG, root, emit=events.append, helper_model=HELPER, concurrency=3)
    t0 = time.monotonic()
    res = await u.run("review", "Review this small project for bugs and security problems.", "")
    secs = time.monotonic() - t0
    fs = res["findings"]
    print("\n" + res["report"] + "\n", flush=True)

    def near(f, spot):
        return f["file"] == spot[0] and abs(f["line"] - spot[1]) <= 3

    print("planted bugs:")
    for name, spot in planted.items():
        hit = [f for f in fs if near(f, spot)]
        by = {s: sum(f["status"] == s for f in hit) for s in ("confirmed", "disputed", "rejected", "unverified")}
        print(f"  {name} ({spot[0]}:{spot[1]}): {by}")
        check(f"planted bug found and confirmed: {name}", by["confirmed"] >= 1, str(by))
    fp = [f for f in fs if f["status"] == "confirmed" and not any(near(f, s) for s in planted.values())]
    for f in fp:
        print(f"  false positive survived: [{f['severity']}] {f['title']} ({f['where']})")
    check("no false positives survive verification", not fp, f"{len(fp)} survived")
    for name, spot in planted.items():   # more than one confirmed finding on a planted spot: not counted as false, listed for a human
        extra = sorted((f for f in fs if f["status"] == "confirmed" and near(f, spot)), key=lambda f: ultra.SEVERITY[f["severity"]])[1:]
        for f in extra:
            print(f"  note: extra confirmed finding near '{name}': [{f['severity']}] {f['title']} ({f['where']})")
    stat = res["stats"]
    print(f"stats: agents={stat['agents']} secs={stat['secs']} failed={stat['failed']} peak_agents={stat['peak_agents']} "
          f"candidates={len(fs)} confirmed={sum(f['status'] == 'confirmed' for f in fs)} "
          f"disputed={sum(f['status'] == 'disputed' for f in fs)} rejected={sum(f['status'] == 'rejected' for f in fs)}", flush=True)
    check("run returns the documented shape", {"pattern", "report", "findings", "stats"} <= set(res) and isinstance(res["report"], str)
          and {"agents", "secs"} <= set(stat))
    check("review stayed within the concurrency cap", stat["peak_agents"] <= 3, str(stat["peak_agents"]))
    check("phase events were emitted", {"find", "verify", "synthesize"} <= {e["phase"] for e in events if e["event"] == "phase"})
    check("review finished within its time budget", secs < 330, f"{secs:.0f}s")



# ------------------------------------------------------------------ regressions, no model needed

def reply(content: str = "", reason: str = "stop", calls=None) -> httpx.Response:
    msg = {"role": "assistant", "content": content, **({"tool_calls": calls} if calls else {})}
    return httpx.Response(200, content=json.dumps({"message": msg, "done": True, "done_reason": reason}) + "\n")


def mock(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def tool_call(name: str, **args) -> dict:
    return {"function": {"name": name, "arguments": args}}


def mkproj(files: dict[str, str]) -> Path:
    base = Path(tempfile.mkdtemp(prefix="ultra_reg_"))
    root = base / "proj"
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


async def test_scope_boundaries():
    root = mkproj({"a.py": "x = 1\n"})
    (root.parent / "secret.txt").write_text("TOP SECRET OUTSIDE\n")
    (root.parent / "outdir").mkdir()
    (root.parent / "outdir" / "o.txt").write_text("outside dir file\n")
    os.symlink(root.parent / "secret.txt", root / "link.txt")
    os.symlink(root.parent / "outdir", root / "linkdir")
    u = Ultra(None, "m", root)
    files = await u._scope_files("")
    check("scope: a symlink to a file outside the project is not in scope", files == ["a.py"], str(files))
    check("scope: its content never reaches the worker prompt", "TOP SECRET" not in (u._source(files) or ""))
    check("scope: glob and explicit scopes refuse the symlink too",
          await u._scope_files("*.txt") == [] and await u._scope_files("link.txt") == [] and await u._scope_files("linkdir") == [])
    try:
        u._lines("link.txt")
        raised = False
    except ToolError:
        raised = True
    check("_lines goes through the project boundary", raised)
    check("scope: '../*' does not reach outside", await u._scope_files("../*") == [])
    ctx = Ctx(root)
    out = await u._call(ctx, ultra.FILE_TOOLS, {"function": {"name": "Glob", "arguments": {"pattern": "../*"}}})
    check("worker Glob refuses '..' patterns", out.startswith("Error") and "secret" not in out and "outdir" not in out, out[:80])
    out = await u._call(ctx, ultra.FILE_TOOLS, {"function": {"name": "Glob", "arguments": {"pattern": "linkdir/*"}}})
    check("worker Glob hides names behind a symlinked directory", "o.txt" not in out, out[:80])


async def test_scope_items():
    root = mkproj({".github/ci.yml": "on: push\n", "node_modules/m.js": "1\n", "app/[id]/page.tsx": "x\n", "my file.py": "y = 2\n",
                   "a.py": "x = 1\n", "skip/.hidden/h.py": "h\n", "skip/ok.py": "ok\n"})
    u = Ultra(None, "m", root)
    for s in (".github/ci.yml", "node_modules/m.js", "app/[id]/page.tsx", "my file.py"):
        u._reset()
        got = await u._scope_files(s)
        check(f"scope: exact path {s!r} is taken literally", got == [s], f"{got} {u.notes}")
    u._reset()
    got = await u._scope_files("a.py nothere.py")
    check("scope: an item that matches nothing is reported", got == ["a.py"] and any("nothere.py" in n for n in u.notes), str(u.notes))
    u._reset()
    got = await u._scope_files("typo.py, *.zzz")
    check("scope: typo and empty glob are reported", got == [] and any("typo.py" in n for n in u.notes) and any("*.zzz" in n for n in u.notes), str(u.notes))
    u._reset()
    got = await u._scope_files("skip")
    check("scope: hidden directories inside a named directory stay out", got == ["skip/ok.py"], str(got))
    u._reset()
    got = await u._scope_files("")
    check("scope: default walk skips hidden and ignored directories", got == ["a.py", "app/[id]/page.tsx", "my file.py", "skip/ok.py"], str(got))


async def test_scope_unreadable():
    if os.geteuid() == 0:
        print("SKIP  unreadable file (running as root)")
        return
    root = mkproj({"a.py": "1\n", "aa/early.py": "2\n", "zz/locked.py": "3\n", "zz/zlater.py": "4\n"})
    locked = root / "zz" / "locked.py"
    locked.chmod(0)
    try:
        u = Ultra(None, "m", root)
        files = await u._scope_files("")
    finally:
        locked.chmod(0o644)
    check("scope: one unreadable file does not drop the files sorted after it",
          files == ["a.py", "aa/early.py", "zz/zlater.py"], str(files))
    check("scope: the note names the file, not the whole item",
          any("zz/locked.py" in n for n in u.notes) and not any("item '.'" in n for n in u.notes), str(u.notes))


async def test_scope_walk():
    root = mkproj({"main.py": "x = 1\n"})
    for d in range(60):   # 60 dirs x 100 files of source: enough work for a stall to show
        sub = root / "src" / f"d{d:02d}"
        sub.mkdir(parents=True)
        for i in range(100):
            (sub / f"f{i:03d}.py").write_text("x = 1\n")
    ign = root / "node_modules" / "locked"
    ign.mkdir(parents=True)
    ign.chmod(0)
    try:
        u = Ultra(None, "m", root)
        t0 = time.monotonic()
        u._scan("")
        sync = time.monotonic() - t0
        u._reset()
        gaps, stop = [], False

        async def tick():
            last = time.monotonic()
            while not stop:
                await asyncio.sleep(0.005)
                now = time.monotonic()
                gaps.append(now - last)
                last = now

        t = asyncio.create_task(tick())
        await asyncio.sleep(0.05)
        files = await u._scope_files("")
        stop = True
        await t
    finally:
        ign.chmod(0o755)
    check("scope: the scan keeps the event loop free", sync < 0.1 or max(gaps) < sync * 0.6, f"scan {sync:.2f}s, longest stall {max(gaps):.2f}s")
    check("scope: ignored directories are pruned, not walked", not any("locked" in n for n in u.notes) and len(files) == ultra.MAX_FILES, str(u.notes[:2]))


async def test_grounding():
    root = mkproj({"inv.py": "a\nb\nc\nd\n", "my file.py": "a\nb\nc\n", "x/util.py": "a\nb\nc\n", "y/util.py": "a\nb\nc\n"})
    u = Ultra(None, "m", root)
    files = await u._scope_files("")
    mk = lambda where: {"findings": [{"title": "t", "where": where, "severity": "high", "evidence": "e", "fix": "f"}]}
    for where, want in [("inv.py:2", "inv.py:2"), (f"{root}/inv.py:2", "inv.py:2"), ("proj/inv.py:2", "inv.py:2"), ("**inv.py:2**", "inv.py:2"),
                        ("inv.py line 2", "inv.py:2"), ("File: inv.py:2", "inv.py:2"), ("inv.py#L2", "inv.py:2"), ("inv.py:L2", "inv.py:2"),
                        ("my file.py:2", "my file.py:2"), ("x/util.py:2", "x/util.py:2")]:
        u._reset()
        got = [f["where"] for f in await u._ground(mk(where), files, "correctness", "f")]
        check(f"ground: {where.replace(str(root), '<root>')!r} resolves", got == [want], f"{got} {u.notes[:1]}")
    u._reset()
    got = await u._ground(mk("util.py:2"), files, "correctness", "f")
    check("ground: an ambiguous basename says so", got == [] and "ambiguous" in u.notes[0] and "x/util.py" in u.notes[0], str(u.notes))
    u._reset()
    got = await u._ground(mk("inv.py:9"), files, "correctness", "f")
    check("ground: a line past the end gets an honest reason", got == [] and "4 lines" in u.notes[0], str(u.notes))
    u._reset()
    got = await u._ground(mk("/etc/inv.py:2"), files, "correctness", "f")
    check("ground: an absolute path outside the project is dropped", got == [] and "outside" in u.notes[0], str(u.notes))


async def test_args_and_failures():
    root = mkproj({"inv.py": "def f():\n    return 1\n", "b.py": "x = 1\n"})
    empty = lambda request: reply('{"findings": []}')
    async with mock(empty) as c:
        u = Ultra(c, "m", root, helper_model="h")
        ctx = Ctx(root)
        ctx.ultra = u.run
        for label, kw in [("list scope", {"scope": ["inv.py"]}), ("null scope", {"scope": None}), ("int scope", {"scope": 3}), ("null task", {"task": None})]:
            task = kw.pop("task", "x")
            rep = await ultra._ultra_tool(ctx, "review", task, **kw)
            check(f"tool arg {label} does not abort the run", "aborted" not in rep and "Error" not in rep, rep[:100])
        rep = await ultra._ultra_tool(ctx, "review", "x", scope=["inv.py", "b.py"])
        check("a list scope is joined", "Scope: 2 files" in rep, rep[:120])
        rep = await ultra._ultra_tool(ctx, "design", "x", scope=None)
        check("design with null scope does not abort", "aborted" not in rep and "AttributeError" not in rep, rep[:100])
        res = await u.run("audit", None, ["inv.py"])
        check("run() itself accepts a list scope and a null task", "aborted" not in res["report"] and "Task: (none given)" in res["report"], res["report"][:100])

    def gone(request):
        return httpx.Response(404, content=json.dumps({"error": "model not found"}))

    async with mock(gone) as c:
        for pat in ("review", "audit"):
            res = await Ultra(c, "nope", root, helper_model="nope").run(pat, "find bugs", "")
            st = res["stats"]
            check(f"{pat}: every worker failed -> the report says FAILED first",
                  res["report"].startswith("FAILED:") and "model not found" in res["report"] and "None survived" not in res["report"]
                  and st["failed"] == st["agents"] > 0, res["report"][:160])

    def one_bad(request):
        return httpx.Response(500, content="boom") if b"Focus: security" in request.content else reply('{"findings": []}')

    async with mock(one_bad) as c:
        res = await Ultra(c, "m", root).run("review", "find bugs", "")
        check("review: some workers failed -> warning at the top", res["report"].startswith("WARNING: 1 of 3 workers failed"), res["report"][:100])

    async with mock(empty) as c:
        res = await Ultra(c, "m", root).run("review", "find bugs", "")
        check("review: no failures, no warning", res["report"].startswith("# Review") and res["stats"]["failed"] == 0, res["report"][:60])


async def test_truncation():
    cut = lambda request: reply("Early bicycles lacked gears,", "length")
    async with mock(cut) as c:
        u = Ultra(c, "m", Path("."))
        got = await u.agent("Write a long essay.", tools=False, label="essay")
        check("a reply cut by the token cap carries a marker", isinstance(got, str) and got.endswith(ultra.CUT_MARK) and "gears," in got, str(got))
        check("and a run note", any("essay" in n and "cut off" in n for n in u.notes), str(u.notes))
        content, calls, was_cut = await u._turn_full("m", [{"role": "user", "content": "hi"}], None)
        check("_turn_full reports the cut", was_cut and not calls)
    whole = lambda request: reply("All done.")
    async with mock(whole) as c:
        u = Ultra(c, "m", Path("."))
        got = await u.agent("Say it.", tools=False)
        check("a complete reply stays unmarked", got == "All done." and not u.notes, str(got))


async def test_tool_output_clip():
    root = mkproj({"mid.txt": "".join(f"line {i:04d} " + "x" * 24 + "\n" for i in range(200)),
                   "long.txt": "".join(f"row {i:04d} " + "y" * 24 + "\n" for i in range(450))})
    u = Ultra(None, "m", root)
    ctx = Ctx(root)
    out = await u._call(ctx, ultra.FILE_TOOLS, {"function": {"name": "Read", "arguments": {"file_path": "mid.txt"}}})
    check("worker tool output over the cap keeps head and tail and says so",
          "line 0000" in out and "line 0199" in out and "truncated" in out and "offset/limit" in out, f"{len(out)} chars")
    out = await u._call(ctx, ultra.FILE_TOOLS, {"function": {"name": "Read", "arguments": {"file_path": "long.txt"}}})
    check("Read's '[showing lines ...]' note survives the worker cap", "[showing lines 1-400 of 450]" in out, out[-120:])
    out = await u._call(ctx, ultra.FILE_TOOLS, {"function": {"name": "Read", "arguments": {"file_path": "mid.txt", "limit": 10}}})
    check("short tool output is left alone", "shortened" not in out and "truncated" not in out)


def test_dedupe_distinct_defects():
    f = lambda t, line, sev, d: {"title": t, "file": "a.py", "line": line, "severity": sev, "dimensions": [d]}
    pairs = [("Shell injection via os.system with unsanitized name", "Exit status of os.system is shifted and misreported"),
             ("SQL injection in query builder", "Missing error handling for empty result"),
             ("Off-by-one skips last element", "Integer overflow on large n"),
             ("Unbounded memory growth in cache", "Password stored in plain text"),
             ("", "")]
    for a, b in pairs:
        out = ultra.dedupe([f(a, 10, "high", "security"), f(b, 10, "medium", "correctness")])
        check(f"dedupe keeps different defects apart: {a[:30]!r} / {b[:30]!r}", len(out) == 2, f"{len(out)} left")


async def regressions():
    test_dedupe_distinct_defects()
    for t in (test_scope_boundaries, test_scope_items, test_scope_unreadable, test_scope_walk, test_grounding,
              test_args_and_failures, test_truncation, test_tool_output_clip):
        await t()


async def main():
    t0 = time.monotonic()
    test_pure()
    await test_facade()
    await regressions()
    if "--offline" in sys.argv:
        print(f"\n{ok} passed, {bad} failed, {time.monotonic() - t0:.0f}s total (offline)")
        sys.exit(1 if bad else 0)
    async with httpx.AsyncClient() as client:
        await test_parallel_pipeline(client)
        await test_primitives(client)
        await test_review(client)
    print(f"\n{ok} passed, {bad} failed, {time.monotonic() - t0:.0f}s total")
    sys.exit(1 if bad else 0)


asyncio.run(main())
