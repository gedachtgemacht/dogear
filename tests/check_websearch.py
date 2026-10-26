"""WebSearch provider chain: Brave first, Marginalia, then Wikipedia. Offline parts are simulated; --live also hits the network."""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dogear import tools  # noqa: E402

ok = True


def check(name, cond):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name)


async def run(brave=None, marg=None, wiki=None, query="q"):
    async def mk(v):
        async def f(c, q, n):
            if isinstance(v, Exception):
                raise v
            return v
        return f
    tools._SEARCH_CACHE.clear()
    orig = (tools._search_brave, tools._search_marginalia, tools._search_wikipedia)
    tools._search_brave, tools._search_marginalia, tools._search_wikipedia = await mk(brave), await mk(marg), await mk(wiki)
    ctx = types.SimpleNamespace()
    try:
        return await tools.WebSearch(ctx, query), ctx
    except tools.ToolError as e:
        return "ERR " + str(e), ctx
    finally:
        tools._search_brave, tools._search_marginalia, tools._search_wikipedia = orig


async def main():
    r = [("https://a.test", "A", "alpha")]
    out, ctx = await run(brave=r)
    check("brave used, no provider note", "a.test" in out and " via " not in out.splitlines()[0] and ctx.meta["provider"] == "Brave")
    out, ctx = await run(brave=tools.ToolError("Brave answered 429"), marg=r)
    check("429 falls back to Marginalia", "via Marginalia" in out and ctx.meta["provider"] == "Marginalia")
    out, ctx = await run(brave=[], marg=[], wiki=r)
    check("empty results fall back to Wikipedia", "via Wikipedia" in out)
    out, ctx = await run(brave=tools.ToolError("x"), marg=tools.ToolError("y"), wiki=[])
    check("all fail -> one error naming the providers", out.startswith("ERR") and "Brave: x" in out and "Marginalia: y" in out)
    if "--live" in sys.argv:
        tools._SEARCH_CACHE.clear()
        for fn in (tools._search_brave, tools._search_marginalia, tools._search_wikipedia):
            import httpx
            async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/154.0"}) as c:
                try:
                    res = await fn(c, "python asyncio gather", 3)
                except Exception as e:
                    res = f"{type(e).__name__}: {e}"
            check(f"live {fn.__name__}: {res[0][1] if isinstance(res, list) and res else res}", isinstance(res, list) and len(res) >= 1)
    sys.exit(0 if ok else 1)

asyncio.run(main())
