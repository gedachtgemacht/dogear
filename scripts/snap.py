"""Screenshots of a URL at desktop and phone width, dark and light.
usage: uv run python scripts/snap.py URL OUTDIR"""
import asyncio, base64, sys, tempfile
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
from pathlib import Path
from dogear.browser import Browser

async def main():
    url, out = sys.argv[1], Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    b = Browser(Path(tempfile.mkdtemp())); await b.ensure()
    for scheme in ("light", "dark"):
        await b.cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]}, session=b.sess)
        for name, w, h in (("desktop", 1280, 800), ("mobile", 390, 844)):
            await b.set_viewport(w, h); await b.navigate(url); await asyncio.sleep(0.6)
            (out / f"{scheme}-{name}.jpg").write_bytes(base64.b64decode(await b.screenshot()))
    await b.close()

asyncio.run(main())
