"""A real Chrome (headless, own profile) driven over the DevTools protocol by our own small client.

The agent and the user share it: frames are screencast to the UI, user input is forwarded,
and the agent acts through the same session (so everything is visible live).
"""
import asyncio
import json
import os
import re
import shutil
import signal
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

from websockets.asyncio.client import connect

PREVIEW_PORT = 7871
PREVIEW_ROOTS: dict[str, str] = {}      # session id -> project directory served at /@<id>/


class BrowserError(Exception):
    pass


class CDP:
    def __init__(self):
        self.n = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.handlers: dict[str, list] = {}
        self.ws = None
        self.closed = True

    async def open(self, url: str):
        self.ws = await connect(url, max_size=None, ping_interval=None)
        self.closed = False
        self.task = asyncio.create_task(self._loop())

    async def _loop(self):
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                if "id" in m:
                    f = self.pending.pop(m["id"], None)
                    if f and not f.done():
                        if "error" in m:
                            f.set_exception(BrowserError(m["error"].get("message", "CDP error")))
                        else:
                            f.set_result(m.get("result", {}))
                else:
                    for h in self.handlers.get(m.get("method", ""), []):
                        asyncio.create_task(h(m.get("params", {}), m.get("sessionId")))
        except Exception:
            pass
        finally:
            self.closed = True
            for f in self.pending.values():
                if not f.done():
                    f.set_exception(BrowserError("browser connection closed"))

    async def call(self, method, params=None, session=None, timeout=30):
        if self.closed:
            raise BrowserError("browser is not running")
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.n] = fut
        msg = {"id": self.n, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        await self.ws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, timeout)

    def on(self, method, fn):
        self.handlers.setdefault(method, []).append(fn)

    async def close(self):
        self.closed = True
        try:
            await self.ws.close()
        except Exception:
            pass


KEYS = {  # name: (windowsVirtualKeyCode, code, text)
    "Enter": (13, "Enter", "\r"), "Tab": (9, "Tab", ""), "Escape": (27, "Escape", ""), "Backspace": (8, "Backspace", ""),
    "Delete": (46, "Delete", ""), "ArrowUp": (38, "ArrowUp", ""), "ArrowDown": (40, "ArrowDown", ""),
    "ArrowLeft": (37, "ArrowLeft", ""), "ArrowRight": (39, "ArrowRight", ""), "PageUp": (33, "PageUp", ""),
    "PageDown": (34, "PageDown", ""), "Home": (36, "Home", ""), "End": (35, "End", ""), "Space": (32, "Space", " "),
}
MOD = {"Alt": 1, "Control": 2, "Ctrl": 2, "Meta": 4, "Cmd": 4, "Shift": 8}

INIT_JS = """
(() => {
  window.open = (u) => { if (u) location.href = u; return window; };
  document.addEventListener('click', e => { const a = e.target.closest && e.target.closest('a[target]'); if (a) a.target = '_self'; }, true);
})();
"""

BLOCK_JS = r"""
(() => {
  const shown = e => { const r = e.getBoundingClientRect(), c = getComputedStyle(e);
    return r.width > 40 && r.height > 40 && c.visibility !== "hidden" && c.display !== "none" && r.bottom > 0 && r.top < innerHeight; };
  const t = ((document.body && document.body.innerText) || "").slice(0, 3000).toLowerCase();
  if (/unusual traffic|are you a robot|verify (that )?you are (a )?human|not a robot|checking your browser|just a moment|ungewöhnlichen datenverkehr|kein roboter|bist du ein roboter|sind sie ein roboter|captcha/.test(t)) return "text";
  if (/\/sorry\/|captcha|\/challenge/.test(location.href)) return "url";
  for (const f of document.querySelectorAll('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare"],.g-recaptcha,.cf-turnstile'))
    if (shown(f)) return "widget";
  return "";
})()
"""

READ_JS = r"""
(all) => {
  const K = window.__dogear = window.__dogear || { n: 0, els: new Map(), ids: new WeakMap() };
  const ref = el => { let id = K.ids.get(el); if (!id) { id = "e" + (++K.n); K.ids.set(el, id); K.els.set(id, new WeakRef(el)); } return id; };
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "HEAD", "META", "LINK", "SVG", "PATH"]);
  const INTER = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],[role=tab],[role=menuitem],[role=checkbox],[role=switch],[role=option],[onclick],[contenteditable=""],[contenteditable=true]';
  const vw = innerWidth, vh = innerHeight, lines = [], rects = [];
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const inView = r => r.bottom > 0 && r.right > 0 && r.top < vh && r.left < vw;
  const label = el => clean(el.getAttribute("aria-label")) || clean(el.innerText) || clean(el.value) || clean(el.placeholder) || clean(el.title) || clean(el.alt) || clean(el.name);
  const emit = s => { if (lines.length < 500) lines.push(s); };
  const seen = new Set();
  function walk(el) {
    if (lines.length >= 500 || SKIP.has(el.tagName.toUpperCase()) || seen.has(el)) return;
    seen.add(el);
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return;
    const r = el.getBoundingClientRect(), tag = el.tagName.toLowerCase();
    if (el.matches(INTER) && r.width > 0 && r.height > 0) {
      const id = ref(el), role = el.getAttribute("role") || (tag === "a" ? "link" : tag === "input" ? (el.type || "text") : tag);
      let extra = "";
      if (tag === "a") extra = " href=" + (el.getAttribute("href") || "").slice(0, 80);
      if (tag === "input" || tag === "textarea") {
        if (el.type === "checkbox" || el.type === "radio") extra += el.checked ? " checked" : "";
        else extra += ` value="${clean(el.value).slice(0, 60)}"`;
      }
      if (tag === "select") extra += ` value="${clean(el.options[el.selectedIndex] && el.options[el.selectedIndex].text)}"`;
      if (el.disabled) extra += " disabled";
      const on = inView(r), lab = label(el).slice(0, 80);
      emit(`[${id}] ${role} "${lab}"${extra}${on ? "" : " (offscreen)"}`);
      if (on) rects.push({ ref: id, x: r.x, y: r.y, w: r.width, h: r.height });
      return;
    }
    if (/^h[1-6]$/.test(tag)) { const t = clean(el.innerText); if (t) emit(`heading${tag[1]} "${t.slice(0, 100)}"`); return; }
    if (tag === "img") { const a = clean(el.alt); if (a) emit(`image "${a.slice(0, 60)}"`); return; }
    for (const c of el.childNodes) {
      if (c.nodeType === 3) { const t = clean(c.textContent); if (t.length > 1) emit(`text "${t.slice(0, 160)}"`); }
      else if (c.nodeType === 1) walk(c);
    }
    if (el.shadowRoot) {                                  // open shadow roots (consent managers, web components)
      for (const c of el.shadowRoot.childNodes) {
        if (c.nodeType === 3) { const t = clean(c.textContent); if (t.length > 1) emit(`text "${t.slice(0, 160)}"`); }
        else if (c.nodeType === 1) walk(c);
      }
    }
  }
  // dialogs and consent managers first: they sit at the end of the document and would be cut off by the line cap
  for (const p of document.querySelectorAll('#usercentrics-root,#onetrust-consent-sdk,#onetrust-banner-sdk,#CybotCookiebotDialog,#cmpbox,[role=dialog],[aria-modal=true],[id*="consent" i],[id*="cookie" i]')) walk(p);
  walk(document.body || document.documentElement);
  // A consent dialog that locks the page: scrolling is disabled and the dialog's buttons are what the user must press.
  const locked = [document.body, document.documentElement].some(e => e && /hidden|clip/.test(getComputedStyle(e).overflowY));
  const CONSENT = /akzeptier|zustimm|ablehn|einverstanden|nur (technisch|notwendig|erforderlich)|alle erlauben|accept|reject|decline|agree|necessary only|only necessary|essential only|allow all|deny/i;
  const consent = [];
  for (const l of lines) {
    const m = l.match(/^\[(e\d+)\] (?:button|link|a) "([^"]*)"/);
    if (m && CONSENT.test(m[2])) consent.push({ ref: m[1], label: m[2] });
  }
  return { url: location.href, title: document.title, scrollY: Math.round(scrollY), scrollH: document.documentElement.scrollHeight, vw, vh, lines, rects, locked, consent: locked ? consent.slice(0, 6) : [] };
}
"""

REF_JS = r"""
(ref) => {
  const el = window.__dogear && window.__dogear.els.get(ref) && window.__dogear.els.get(ref).deref();
  if (!el || !el.isConnected) return null;
  el.scrollIntoView({ block: "center", inline: "center" });
  const r = el.getBoundingClientRect();
  return { x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height, tag: el.tagName.toLowerCase(),
           label: (el.innerText || el.value || el.placeholder || "").slice(0, 40) };
}
"""


RESTRICTIVE = re.compile(r"nur (technisch|notwendig|erforderlich|essenziell)|ablehn|reject|decline|\bdeny\b|necessary only|only necessary|essential only", re.I)
CONSENT_PENDING_JS = ("!!document.querySelector('#usercentrics-root,#onetrust-consent-sdk,#onetrust-banner-sdk,#CybotCookiebotDialog,#cmpbox,"
                      "[id*=\"cookie\" i],[class*=\"cookie\" i],[id*=\"consent\" i],[class*=\"consent\" i],[aria-modal=true]')")

CMP_SCRIPT_JS = ("!!document.querySelector('script[src*=\"usercentrics\"],script[src*=\"onetrust\"],script[src*=\"cookiebot\"],"
                 "script[src*=\"cookielaw\"],script[src*=\"consentmanager\"],script[src*=\"sourcepoint\"],script[src*=\"didomi\"]')")

BOT_NOTE = ("[This page looks like a CAPTCHA or bot check. Do not try to solve or bypass it. "
            "Call browser_handoff so the user can complete it, then continue.]")


class Browser:
    def __init__(self, profile: Path):
        self.profile = profile
        self.proc = None
        self.cdp: CDP | None = None
        self.sess = None
        self.subs: set = set()
        self.url, self.title = "", ""
        self.vw, self.vh = 1280, 800
        self.console: deque = deque(maxlen=300)
        self.net: deque = deque(maxlen=100)
        self.reqs: dict[str, str] = {}
        self.waiters: list[asyncio.Future] = []
        self.lock = asyncio.Lock()
        self.last_frame = None
        self._sent_at, self._flush = 0.0, None
        self.state = "stopped"
        self.errors_seen = 0
        self.handoff: asyncio.Future | None = None
        self.overlay_locked = False
        self._metrics_at = 0.0
        self.cmp_hosts: set[str] = set()
        self.owner, self.owner_ts = "", 0.0      # which branch run currently drives the shared browser

    # ------------------------------------------------------------ lifecycle
    @property
    def alive(self):
        return bool(self.cdp and not self.cdp.closed and self.proc and self.proc.returncode is None)

    async def ensure(self):
        async with self.lock:
            if self.alive:
                return
            await self._launch()

    async def _launch(self):
        chrome = next((p for p in (shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")) if p), None)
        if not chrome:
            raise BrowserError("Chrome or Chromium not found")
        await self._broadcast({"type": "b_status", "state": "starting"})
        self.profile.mkdir(parents=True, exist_ok=True)
        (self.profile / "DevToolsActivePort").unlink(missing_ok=True)
        self.proc = await asyncio.create_subprocess_exec(
            chrome, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={self.profile}", "--no-first-run",
            "--disable-blink-features=AutomationControlled", "--no-default-browser-check", "--hide-scrollbars", "--mute-audio", "--disable-features=Translate",
            f"--window-size={self.vw},{self.vh}", "about:blank",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
        port_file = self.profile / "DevToolsActivePort"
        for _ in range(150):
            if port_file.exists() and len(port_file.read_text().split("\n")) >= 2:
                break
            await asyncio.sleep(0.1)
        else:
            raise BrowserError("Chrome did not start")
        port, path = port_file.read_text().split("\n")[:2]
        self.cdp = CDP()
        await self.cdp.open(f"ws://127.0.0.1:{port}{path}")
        infos = (await self.cdp.call("Target.getTargets"))["targetInfos"]
        page = next((t for t in infos if t["type"] == "page"), None)
        tid = page["targetId"] if page else (await self.cdp.call("Target.createTarget", {"url": "about:blank"}))["targetId"]
        self.sess = (await self.cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]
        self._register()
        for d in ("Page", "Runtime", "Network", "Log"):
            await self.cdp.call(f"{d}.enable", session=self.sess)
        await self.cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": INIT_JS}, session=self.sess)
        await self._identify()
        await self.set_viewport(self.vw, self.vh)
        self.state = "ready"
        await self._broadcast({"type": "b_status", "state": "ready"})

    async def _identify(self):
        """Report as the regular Chrome this is: headless mode only changes the UA token."""
        v = await self.cdp.call("Browser.getVersion")
        ua = v["userAgent"].replace("HeadlessChrome", "Chrome")
        major = re.search(r"Chrome/(\d+)", ua).group(1)
        full = re.search(r"Chrome/([\d.]+)", ua).group(1)
        await self.cdp.call("Emulation.setUserAgentOverride", {
            "userAgent": ua, "acceptLanguage": "de-DE,de,en-US,en", "platform": "Linux x86_64",
            "userAgentMetadata": {"brands": [{"brand": "Chromium", "version": major}, {"brand": "Google Chrome", "version": major},
                                             {"brand": "Not.A/Brand", "version": "24"}],
                                  "fullVersion": full, "platform": "Linux", "platformVersion": "", "architecture": "x86",
                                  "model": "", "mobile": False}}, session=self.sess)

    async def settle(self, timeout=9.0):
        """Wait until the page stopped navigating (e.g. after the user solved a check and the site redirects)."""
        end, last, stable = time.time() + timeout, None, 0
        while time.time() < end:
            await asyncio.sleep(0.5)
            try:
                ready = await self.eval("document.readyState", timeout=3) == "complete"
            except Exception:
                ready = False
            stable = stable + 1 if (ready and self.url == last) else 0
            last = self.url
            if stable >= 2 and not await self.blocked():
                return
        await self._title()

    async def blocked(self) -> bool:
        """Does the page look like a CAPTCHA or bot check (which only the user should solve)?"""
        try:
            return bool(await self.eval(BLOCK_JS, timeout=5))
        except Exception:
            return False

    def _register(self):
        c, s = self.cdp, self.sess
        guard = lambda fn: (lambda p, sid: fn(p) if sid == s else asyncio.sleep(0))
        c.on("Page.screencastFrame", guard(self._on_frame))
        c.on("Page.frameNavigated", guard(self._on_nav))
        c.on("Page.navigatedWithinDocument", guard(self._on_nav_doc))
        c.on("Page.loadEventFired", guard(self._on_load))
        c.on("Page.javascriptDialogOpening", guard(self._on_dialog))
        c.on("Runtime.consoleAPICalled", guard(self._on_console))
        c.on("Runtime.exceptionThrown", guard(self._on_exception))
        c.on("Log.entryAdded", guard(self._on_log))
        c.on("Network.requestWillBeSent", guard(self._on_req))
        c.on("Network.responseReceived", guard(self._on_resp))
        c.on("Network.loadingFailed", guard(self._on_failed))

    async def close(self):
        self.state = "stopped"
        if self.cdp:
            await self.cdp.close()
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    # ------------------------------------------------------------ events
    async def _broadcast(self, msg):
        for send in list(self.subs):
            await send(msg)

    async def _on_frame(self, p):
        try:
            await self.cdp.call("Page.screencastFrameAck", {"sessionId": p["sessionId"]}, session=self.sess)
        except BrowserError:
            return                                   # the browser is shutting down
        self.last_frame = {"type": "frame", "d": p["data"], "w": int(p["metadata"].get("deviceWidth", self.vw)),
                           "h": int(p["metadata"].get("deviceHeight", self.vh))}
        now = time.time()
        if now - self._metrics_at >= 0.25:
            self._metrics_at = now
            asyncio.create_task(self._send_metrics())
        if now - self._sent_at >= 0.06:
            self._sent_at = now
            await self._broadcast(self.last_frame)
        elif not self._flush or self._flush.done():
            self._flush = asyncio.create_task(self._flush_frame())

    async def _metrics(self):
        """Scroll position and content size, so the live view can draw real scrollbars (the headless page hides its own)."""
        try:
            m = await self.cdp.call("Page.getLayoutMetrics", session=self.sess)
            c, v = m.get("cssContentSize") or m["contentSize"], m.get("cssVisualViewport") or m["visualViewport"]
            return {"type": "b_scroll", "x": round(v.get("pageX", 0)), "y": round(v.get("pageY", 0)),
                    "w": round(c["width"]), "h": round(c["height"]),
                    "vw": round(v.get("clientWidth", self.vw)), "vh": round(v.get("clientHeight", self.vh))}
        except Exception:
            return None

    async def _send_metrics(self):
        msg = await self._metrics()
        if msg:
            await self._broadcast(msg)

    async def scroll_to(self, x=None, y=None, dx=0, dy=0):
        """Absolute (x, y) or relative (dx, dy) page scroll, used by the live view's scrollbars and keys."""
        def num(v):
            return max(-1e7, min(1e7, float(v)))
        if x is not None or y is not None:
            await self.eval(f"window.scrollTo({num(x) if x is not None else 'scrollX'}, {num(y) if y is not None else 'scrollY'})")
        else:
            await self.eval(f"window.scrollBy({num(dx)}, {num(dy)})")
        self._metrics_at = 0
        await self._send_metrics()

    async def _flush_frame(self):
        await asyncio.sleep(0.09)
        self._sent_at = time.time()
        if self.last_frame:
            await self._broadcast(self.last_frame)

    async def _title(self):
        try:
            r = await self.eval("document.title")
            self.title = str(r or "")
        except Exception:
            pass

    async def _on_nav(self, p):
        fr = p.get("frame", {})
        if not fr.get("parentId"):
            self.url = fr.get("url", self.url)
            await self._broadcast({"type": "b_nav", "url": self.url, "title": self.title})

    async def _on_nav_doc(self, p):
        self.url = p.get("url", self.url)
        await self._broadcast({"type": "b_nav", "url": self.url, "title": self.title})

    async def _on_load(self, p):
        asyncio.create_task(self._send_metrics())
        await self._title()
        await self._broadcast({"type": "b_nav", "url": self.url, "title": self.title})
        for w in self.waiters:
            if not w.done():
                w.set_result(True)
        self.waiters.clear()

    async def _on_dialog(self, p):
        self._log("warning", f"Dialog ({p.get('type')}): {p.get('message', '')}")
        await self.cdp.call("Page.handleJavaScriptDialog", {"accept": True, "promptText": p.get("defaultPrompt", "")}, session=self.sess)

    def _log(self, level, text):
        self.console.append({"level": level, "text": text[:600], "t": time.time()})
        if level == "error":
            self.errors_seen += 1
        asyncio.create_task(self._broadcast({"type": "b_log", "level": level, "text": text[:600]}))

    async def _on_console(self, p):
        parts = []
        for a in p.get("args", []):
            parts.append(str(a["value"]) if "value" in a else (a.get("description") or a.get("type", "")))
        lvl = {"error": "error", "warning": "warning", "assert": "error"}.get(p.get("type"), "log")
        self._log(lvl, " ".join(parts))

    async def _on_exception(self, p):
        d = p.get("exceptionDetails", {})
        desc = (d.get("exception", {}).get("description") or d.get("text", "")).split("\n")[0]
        self._log("error", f"{desc}  ({d.get('url', '')}:{d.get('lineNumber', 0) + 1})")

    async def _on_log(self, p):
        e = p.get("entry", {})
        if e.get("level") in ("error", "warning") and e.get("source") != "network":
            self._log(e["level"], f"{e.get('text', '')} {e.get('url', '')}".strip())

    async def _on_req(self, p):
        if len(self.reqs) > 500:
            self.reqs.clear()
        self.reqs[p["requestId"]] = p.get("request", {}).get("url", "")

    async def _on_resp(self, p):
        r = p.get("response", {})
        if r.get("status", 200) >= 400:
            t = f"HTTP {r['status']} {r.get('url', '')}"
            self.net.append(t)
            self._log("error", t)

    async def _on_failed(self, p):
        if p.get("errorText") == "net::ERR_ABORTED" or p.get("canceled"):
            return
        t = f"{p.get('errorText')} {self.reqs.get(p['requestId'], '')}"
        self.net.append(t)
        self._log("error", t)

    # ------------------------------------------------------------ viewport and screencast
    async def set_viewport(self, w, h):
        self.vw, self.vh = int(w), int(h)
        await self.cdp.call("Emulation.setDeviceMetricsOverride",
                            {"width": self.vw, "height": self.vh, "deviceScaleFactor": 1, "mobile": False}, session=self.sess)
        try:
            await self.cdp.call("Page.stopScreencast", session=self.sess)
        except BrowserError:
            pass
        await self.cdp.call("Page.startScreencast", {"format": "jpeg", "quality": 72, "maxWidth": self.vw, "maxHeight": self.vh,
                                                     "everyNthFrame": 1}, session=self.sess)

    async def snapshot(self):
        """Send the current state to a newly attached viewer."""
        out = [{"type": "b_status", "state": self.state}, {"type": "b_nav", "url": self.url, "title": self.title}] + \
              ([self.last_frame] if self.last_frame else [])
        if self.alive:
            sc = await self._metrics()
            if sc:
                out.append(sc)
        return out

    # ------------------------------------------------------------ actions
    async def eval(self, expr, timeout=20):
        r = await self.cdp.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True},
                                session=self.sess, timeout=timeout)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise BrowserError((d.get("exception", {}).get("description") or d.get("text", "script error")).split("\n")[0])
        return r.get("result", {}).get("value")

    async def navigate(self, url):
        await self.ensure()
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
            url = ("http://" if re.match(r"^(localhost|127\.0\.0\.1)", url) else "https://") + url
        fut = asyncio.get_running_loop().create_future()
        self.waiters.append(fut)
        r = await self.cdp.call("Page.navigate", {"url": url}, session=self.sess)
        if r.get("errorText"):
            raise BrowserError(f"{r['errorText']} while loading {url}")
        try:
            await asyncio.wait_for(fut, 20)
        except asyncio.TimeoutError:
            pass
        await asyncio.sleep(0.25)

    async def history(self, delta):
        h = await self.cdp.call("Page.getNavigationHistory", session=self.sess)
        i = h["currentIndex"] + delta
        if 0 <= i < len(h["entries"]):
            await self.cdp.call("Page.navigateToHistoryEntry", {"entryId": h["entries"][i]["id"]}, session=self.sess)

    async def reload(self):
        await self.cdp.call("Page.reload", {"ignoreCache": True}, session=self.sess)

    async def read(self, all_=False):
        await self.ensure()
        try:
            if await self.eval("document.readyState", timeout=3) != "complete":
                await self.settle(4)
        except Exception:
            pass
        d = await self.overlay_state(all_)
        dismissed = ""
        if d.get("consent"):
            dismissed = await self.dismiss_consent(d)
            if dismissed:
                d = await self.overlay_state(all_)
        await self._broadcast({"type": "b_marks", "rects": d["rects"], "vw": d["vw"], "vh": d["vh"]})
        head = f"Page: {d['title'] or '(untitled)'}\nURL: {d['url']}\nViewport {d['vw']}x{d['vh']}, scrolled {d['scrollY']} of {d['scrollH']}px\n"
        if await self.blocked():
            head += BOT_NOTE + "\n"
        self.overlay_locked = bool(d.get("locked"))
        if dismissed:
            head += f'[A cookie dialog was open; dismissed it by choosing "{dismissed}", the most restrictive option.]\n'
        if d.get("consent"):
            opts = "; ".join(f'[{c["ref"]}] "{c["label"]}"' for c in d["consent"])
            head += ("[A cookie/consent dialog is open and locks scrolling. Dismiss it first with browser_click. Prefer the most "
                     f"restrictive choice (reject or necessary-only) over accepting everything. Options: {opts}]\n")
        return head + "\n".join(d["lines"])

    async def overlay_state(self, all_=False):
        """READ_JS result. Consent managers appear a moment after load, so wait briefly while one is present but not yet shown."""
        d = await self.eval(f"({READ_JS})({json.dumps(bool(all_))})")
        host = urlparse(d.get("url", "")).netloc
        for _ in range(7):
            if d.get("consent"):
                break
            pending = await self.eval(CONSENT_PENDING_JS)
            if not pending and host not in self.cmp_hosts:       # a consent-manager script is loaded but has not drawn yet
                pending = await self.eval(CMP_SCRIPT_JS)
            if not pending:
                break
            await asyncio.sleep(0.6)
            d = await self.eval(f"({READ_JS})({json.dumps(bool(all_))})")
        self.cmp_hosts.add(host)
        return d

    async def dismiss_consent(self, d=None):
        """Click a restrictive consent option (reject / necessary only) when the page offers one. Never 'accept all'.
        Returns the label that was clicked, or ''."""
        d = d or await self.overlay_state()
        for c in d.get("consent") or []:
            if RESTRICTIVE.search(c["label"]):
                try:
                    r = await self.locate(c["ref"])
                    await self.click(r["x"], r["y"], False, c["label"])
                    await asyncio.sleep(0.9)
                    return c["label"]
                except BrowserError:
                    return ""
        return ""

    async def locate(self, ref):
        r = await self.eval(f"({REF_JS})({json.dumps(ref)})")
        if not r:
            raise BrowserError(f"Unknown or stale ref {ref}. Call browser_read again for fresh refs.")
        await asyncio.sleep(0.05)
        return r

    async def _mouse(self, kind, x, y, button="left", clicks=1, **kw):
        await self.cdp.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": button, "clickCount": clicks, **kw}, session=self.sess)

    async def click(self, x, y, double=False, label=""):
        await self._broadcast({"type": "b_act", "kind": "click", "x": x, "y": y, "label": label})
        await asyncio.sleep(0.35)
        await self._mouse("mouseMoved", x, y)
        for n in (1, 2) if double else (1,):
            await self._mouse("mousePressed", x, y, clicks=n)
            await self._mouse("mouseReleased", x, y, clicks=n)
        await asyncio.sleep(0.35)

    async def insert(self, text):
        await self.cdp.call("Input.insertText", {"text": text}, session=self.sess)

    async def key(self, spec):
        parts = spec.split("+")
        name, mods = parts[-1], sum(MOD.get(m, 0) for m in parts[:-1])
        if name in KEYS:
            vk, code, text = KEYS[name]
        elif len(name) == 1:
            vk, code, text = ord(name.upper()), (f"Key{name.upper()}" if name.isalpha() else f"Digit{name}"), name
        else:
            raise BrowserError(f"Unknown key {spec}. Use e.g. Enter, Tab, Escape, ArrowDown, Control+a")
        if mods & ~8:
            text = ""
        ev = {"key": name, "code": code, "windowsVirtualKeyCode": vk, "modifiers": mods}
        if mods & 2 and name.lower() == "a":
            ev["commands"] = ["selectAll"]
        await self.cdp.call("Input.dispatchKeyEvent", {**ev, "type": "keyDown", **({"text": text} if text else {})}, session=self.sess)
        await self.cdp.call("Input.dispatchKeyEvent", {**ev, "type": "keyUp"}, session=self.sess)

    async def scroll(self, dy, x=None, y=None):
        x = self.vw / 2 if x is None else x
        y = self.vh / 2 if y is None else y
        await self._broadcast({"type": "b_act", "kind": "scroll", "x": x, "y": y})
        await self._mouse("mouseWheel", x, y, deltaX=0, deltaY=dy)
        await asyncio.sleep(0.3)

    async def screenshot(self):
        await self.ensure()
        r = await self.cdp.call("Page.captureScreenshot", {"format": "jpeg", "quality": 70}, session=self.sess)
        return r["data"]

    # ------------------------------------------------------------ user input (forwarded from the UI)
    async def user_mouse(self, m):
        if not self.alive:
            return
        t = {"move": "mouseMoved", "down": "mousePressed", "up": "mouseReleased", "wheel": "mouseWheel"}[m["kind"]]
        extra = {"deltaX": m.get("dx", 0), "deltaY": m.get("dy", 0)} if t == "mouseWheel" else {}
        await self._mouse(t, m["x"], m["y"], m.get("button", "left") if t != "mouseMoved" else "none", m.get("clicks", 1),
                          modifiers=m.get("mods", 0), **extra)

    async def user_key(self, m):
        if not self.alive:
            return
        # Page-scroll keys scroll the page unless a text field has focus (headless Chrome does not do this by itself).
        step = {"PageDown": 0.9, "PageUp": -0.9, "ArrowDown": 0.1, "ArrowUp": -0.1, " ": 0.9, "Home": -1e5, "End": 1e5}.get(m["key"])
        if step is not None and not m.get("mods", 0) & 0b1110:
            editable = await self.eval("(()=>{const a=document.activeElement;return !!a&&(a.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName))})()")
            if not editable:
                if m["kind"] == "down":
                    if abs(step) > 1:
                        await self.scroll_to(y=0 if step < 0 else 10 ** 7)
                    else:
                        await self.scroll_to(dy=step * self.vh)
                return
        ev = {"type": "keyDown" if m["kind"] == "down" else "keyUp", "key": m["key"], "code": m.get("code", ""),
              "windowsVirtualKeyCode": m.get("vk", 0), "modifiers": m.get("mods", 0)}
        if m["kind"] == "down" and m.get("text"):
            ev["text"] = m["text"]
        await self.cdp.call("Input.dispatchKeyEvent", ev, session=self.sess)
