"""Flows: a sequence of clicks, typing and navigation that the user demonstrated in the shared browser, replayed later.

Local models are poor at exploring a page but reliable at repeating a demonstrated sequence. The recorder listens to the
input the UI forwards to the browser (user_mouse, user_key, insert, navigate) and turns it into steps with locators that
survive a reload: id, name, aria-label, visible text, then a CSS path. Flows live in <project>/.dogear/flows/<name>.json.
A flow marked `check` is replayed by the quality gate after runs that touch web files and feeds the receipt.
"""
import asyncio
import json
import re
import time
from pathlib import Path

DESCRIBE_JS = r"""
(x, y) => {
  let el = document.elementFromPoint(x, y);
  if (!el) return null;
  const INTER = 'a[href],button,input,select,textarea,summary,label,[role=button],[role=link],[role=tab],[role=menuitem],[role=checkbox],[role=option],[onclick]';
  const hit = el.closest(INTER) || el;
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const path = e => { const parts = []; for (let n = e; n && n.nodeType === 1 && parts.length < 6; n = n.parentElement) {
      let s = n.tagName.toLowerCase(); if (n.id) { parts.unshift(s + "#" + CSS.escape(n.id)); break; }
      const sib = n.parentElement ? [...n.parentElement.children].filter(c => c.tagName === n.tagName) : [n];
      if (sib.length > 1) s += `:nth-of-type(${sib.indexOf(n) + 1})`; parts.unshift(s); } return parts.join(" > "); };
  const r = hit.getBoundingClientRect();
  return { tag: hit.tagName.toLowerCase(), id: hit.id || "", name: hit.getAttribute("name") || "", aria: clean(hit.getAttribute("aria-label")),
           text: clean(hit.innerText || hit.value || hit.placeholder).slice(0, 80), href: hit.getAttribute("href") || "", css: path(hit),
           editable: hit.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(hit.tagName), x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}
"""

FIND_JS = r"""
(loc) => {
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const cands = [];
  if (loc.id) cands.push(document.getElementById(loc.id));
  if (loc.name) cands.push(...document.getElementsByName(loc.name));
  if (loc.aria) cands.push(...document.querySelectorAll(`[aria-label="${CSS.escape(loc.aria)}"]`));
  if (loc.text) for (const e of document.querySelectorAll(loc.tag || "*")) if (clean(e.innerText || e.value || e.placeholder).slice(0, 80) === loc.text) cands.push(e);
  if (loc.css) { try { cands.push(document.querySelector(loc.css)); } catch {} }
  const el = cands.find(e => e && vis(e));
  if (!el) return null;
  el.scrollIntoView({ block: "center", inline: "center" });
  const r = el.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), tag: el.tagName.toLowerCase() };
}
"""


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60] or "flow"


def folder(root: Path) -> Path:
    return Path(root) / ".dogear" / "flows"


def list_flows(root: Path) -> list[dict]:
    out = []
    for f in sorted(folder(root).glob("*.json")):
        try:
            d = json.loads(f.read_text())
            out.append({"name": d.get("name", f.stem), "file": f.stem, "steps": len(d.get("steps", [])), "check": bool(d.get("check")),
                        "url": d.get("url", "")})
        except (OSError, ValueError):
            pass
    return out


def load(root: Path, name: str) -> dict | None:
    f = folder(root) / f"{slug(name)}.json"
    if not f.exists():
        f = next((p for p in folder(root).glob("*.json") if json.loads(p.read_text()).get("name") == name), None)
    if not f:
        return None
    d = json.loads(f.read_text())
    d["file"] = f.stem
    return d


def save(root: Path, name: str, steps: list[dict], url: str, check: bool = False) -> Path:
    folder(root).mkdir(parents=True, exist_ok=True)
    f = folder(root) / f"{slug(name)}.json"
    f.write_text(json.dumps({"name": name, "url": url, "created": time.time(), "check": check, "steps": steps}, indent=1, ensure_ascii=False))
    return f


def set_check(root: Path, name: str, check: bool) -> bool:
    d = load(root, name)
    if not d:
        return False
    f = folder(root) / f"{d['file']}.json"
    d.pop("file", None)
    d["check"] = check
    f.write_text(json.dumps(d, indent=1, ensure_ascii=False))
    return True


def describe_step(s: dict) -> str:
    loc = s.get("target") or {}
    what = loc.get("aria") or loc.get("text") or loc.get("id") or loc.get("name") or loc.get("css") or "?"
    if s["action"] == "navigate":
        return f"open {s['url']}"
    if s["action"] == "click":
        return f"click {loc.get('tag', '')} \"{what[:40]}\""
    if s["action"] == "type":
        return f"type \"{s['text'][:40]}\" into {loc.get('tag', '')} \"{what[:30]}\""
    if s["action"] == "key":
        return f"press {s['key']}"
    return s["action"]


class Recorder:
    """Turns the input the UI forwards into steps. Typing is buffered per field and flushed by a click, Enter or stop."""

    def __init__(self, url: str):
        self.start_url = url
        self.steps: list[dict] = []
        self.typing: dict | None = None            # {"target": loc, "text": str}

    def flush(self):
        if self.typing and self.typing["text"]:
            self.steps.append({"action": "type", "target": self.typing["target"], "text": self.typing["text"]})
        self.typing = None

    def navigate(self, url: str):
        self.flush()
        self.steps.append({"action": "navigate", "url": url})

    def click(self, loc: dict | None, x: float, y: float):
        self.flush()
        self.steps.append({"action": "click", "target": loc or {}, "x": round(x), "y": round(y)})
        if loc and loc.get("editable"):
            self.typing = {"target": loc, "text": ""}

    def text(self, text: str, loc: dict | None):
        if self.typing is None:
            self.typing = {"target": loc or {}, "text": ""}
        self.typing["text"] += text

    def key(self, key: str):
        if key == "Backspace" and self.typing and self.typing["text"]:
            self.typing["text"] = self.typing["text"][:-1]
            return
        if key in ("Enter", "Tab", "Escape"):
            self.flush()
            self.steps.append({"action": "key", "key": key})


async def replay(b, flow: dict, pause: float = 0.6) -> dict:
    """Carry out a recorded flow in the browser. Returns {ok, done, failed, errors, steps}: which step failed and why,
    and the console errors that appeared on the way."""
    steps = flow.get("steps", [])
    report = {"ok": True, "done": 0, "failed": None, "errors": 0, "steps": len(steps), "detail": ""}
    await b.ensure()
    err0 = getattr(b, "errors_seen", 0)
    if flow.get("url") and not any(s["action"] == "navigate" for s in steps[:1]):
        await b.navigate(flow["url"])
        await asyncio.sleep(pause)
    for i, s in enumerate(steps):
        try:
            if s["action"] == "navigate":
                await b.navigate(s["url"])
            elif s["action"] in ("click", "type"):
                loc = s.get("target") or {}
                pos = await b.eval(f"({FIND_JS})({json.dumps(loc)})") if loc else None
                if not pos and s["action"] == "click" and "x" in s:
                    pos = {"x": s["x"], "y": s["y"]}
                if not pos:
                    raise RuntimeError(f"element not found: {describe_step(s)}")
                await b.click(pos["x"], pos["y"], label=describe_step(s))
                if s["action"] == "type":
                    await b.eval("(()=>{const a=document.activeElement; if(a && 'value' in a) a.value='';})()")
                    await b.insert(s["text"])
            elif s["action"] == "key":
                await b.key(s["key"])
            await asyncio.sleep(pause)
            report["done"] = i + 1
        except Exception as e:
            report.update(ok=False, failed=i, detail=f"step {i + 1} ({describe_step(s)}): {e}")
            break
    try:
        await b.settle(4)
    except Exception:
        pass
    report["errors"] = max(0, getattr(b, "errors_seen", 0) - err0)
    if report["errors"]:
        report["ok"] = False
    return report


def format_report(flow: dict, r: dict) -> str:
    head = f"Flow \"{flow.get('name')}\": {r['done']}/{r['steps']} steps" + (" ok" if r["ok"] else " FAILED")
    lines = [head]
    if r["detail"]:
        lines.append(r["detail"])
    if r["errors"]:
        lines.append(f"{r['errors']} console error(s) during the flow (browser_console shows them)")
    return "\n".join(lines)
