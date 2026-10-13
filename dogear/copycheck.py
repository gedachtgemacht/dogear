"""Copy check: proofreads the visible text of a page against the client's brief.

Two kinds of findings, both checked mechanically before they are reported:
  language  a definite spelling/grammar/agreement error (the quoted words must occur in the page text)
  claim     a concrete factual assertion that is neither in the brief nor derivable from it (invented numbers,
            origins, promises, certifications ...)
The model only nominates; a finding whose quote is not found verbatim in the block is dropped.
"""
import json
import re

TEXT_JS = r"""
(() => {
  const skip = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "SVG", "CODE", "PRE", "TEMPLATE"]);
  const out = [], seen = new Set();
  const vis = e => { const s = getComputedStyle(e); return s.display !== "none" && s.visibility !== "hidden" && e.getClientRects().length; };
  const walk = e => {
    if (skip.has(e.tagName.toUpperCase()) || !vis(e)) return;
    const kids = [...e.children].filter(c => !skip.has(c.tagName.toUpperCase()));
    const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(" ").replace(/\s+/g, " ").trim();
    const inline = kids.length && kids.every(c => /^(A|B|I|EM|STRONG|SPAN|SMALL|BR|MARK|ABBR|SUB|SUP|TIME)$/i.test(c.tagName));
    if (own && (!kids.length || inline)) {
      const t = e.innerText.replace(/\s+/g, " ").trim();
      if (t.length >= 2 && !seen.has(t)) { seen.add(t); out.push(t.slice(0, 400)); }
      return;
    }
    if (own && own.length > 3 && !seen.has(own)) { seen.add(own); out.push(own.slice(0, 400)); }
    kids.forEach(walk);
  };
  walk(document.body);
  const title = document.title && document.title.trim();
  return (title ? [title] : []).concat(out).slice(0, 150);
})()
"""

LANG_SYSTEM = (
    "You are a meticulous proofreader. You receive the numbered text blocks of a web page. Go through EVERY block one by one and look for "
    "definite errors in the language the block is written in: wrong word forms, number/case/gender agreement (for German: article, adjective and noun "
    "endings, singular vs plural, e.g. 'jede zweite Woche' not 'jedes zweite Wochen'), compounds that do not exist or have the wrong gender "
    "('die Abo-Bindung', not 'Abo-Bindlichkeit'), spelling, punctuation. For each error quote the faulty words exactly as written and give the corrected phrase. "
    "Do not report style preferences, brand names, product names, deliberate fragments or words that are merely unusual. "
    "Return one entry per block; use an empty list for blocks without errors.")

CLAIM_SYSTEM = (
    "You fact-check website copy against the client's brief, which is the ONLY source of facts. You receive the brief and the numbered text blocks "
    "of the page. Go through EVERY block one by one. A claim is a concrete, checkable assertion that is not in the brief and cannot be derived from it: "
    "numbers, durations, dates, years, quantities, origins, suppliers, certifications, awards, guarantees, delivery or shipping promises, ingredients, "
    "people, history, statistics. Facts that are in the brief (names, prices, hours, address, products and their taste notes, subscription terms) are fine. "
    "General tone and benefit wording without a checkable fact is not a claim. Quote the asserting words exactly as written. "
    "Return one entry per block; use an empty list for blocks without claims.")

LANG_SCHEMA = {"type": "object", "required": ["blocks"], "properties": {"blocks": {"type": "array", "items": {
    "type": "object", "required": ["block", "errors"], "properties": {"block": {"type": "integer"}, "errors": {"type": "array", "items": {
        "type": "object", "required": ["quote", "fix"], "properties": {"quote": {"type": "string"}, "fix": {"type": "string"}, "problem": {"type": "string"}}}}}}}}}

CLAIM_SCHEMA = {"type": "object", "required": ["blocks"], "properties": {"blocks": {"type": "array", "items": {
    "type": "object", "required": ["block", "claims"], "properties": {"block": {"type": "integer"}, "claims": {"type": "array", "items": {
        "type": "object", "required": ["quote", "problem"], "properties": {"quote": {"type": "string"}, "problem": {"type": "string"}}}}}}}}}


VERIFY_SYSTEM = (
    "You judge candidate claims from website copy against the client's brief. For each numbered claim decide:\n"
    "supported: everything concrete in the claim is in the brief or is a plain rewording of it (same numbers, same terms; hours, prices, address, "
    "product notes and subscription terms that match; a place named more loosely, such as Altona for Hamburg-Altona), or the claim contains no concrete "
    "detail at all, only ordinary descriptive or marketing words (fresh, small, careful, roasted here, local) or what such a business obviously does.\n"
    "unsupported: the claim asserts a concrete detail that the brief does not contain: a number or time span that the brief does not attach to this "
    "thing (a shipping or delivery time, a quantity, a percentage), a year or date, an origin or supplier, a certification or award, a guarantee, "
    "a founding story, a statistic. A number that occurs in the brief for something else does not support it.\n"
    "Check the claim word by word against the brief before you answer.")

VERIFY_SCHEMA = {"type": "object", "required": ["verdicts"], "properties": {"verdicts": {"type": "array", "items": {
    "type": "object", "required": ["id", "reason", "verdict"], "properties": {
        "id": {"type": "integer"}, "reason": {"type": "string"}, "verdict": {"type": "string", "enum": ["supported", "unsupported"]}}}}}}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _digits(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", s))


async def _ask(client, url, model, system, schema, user):
    body = {"model": model, "stream": False, "think": False, "format": schema, "keep_alive": "30m",
            "options": {"temperature": 0, "num_ctx": 16384},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    r = await client.post(f"{url}/api/chat", json=body, timeout=240)
    return json.loads(r.json()["message"]["content"]).get("blocks", [])


async def check(client, url: str, model: str, brief: str, blocks: list[str]) -> list[dict]:
    """Returns validated findings: [{kind, quote, problem, fix, block}]."""
    import asyncio
    blocks = [b for b in blocks if b.strip()][:150]
    if not blocks or not brief.strip():
        return []
    listing = "\n".join(f"[{i}] {b}" for i, b in enumerate(blocks))
    lang, claim = await asyncio.gather(
        _ask(client, url, model, LANG_SYSTEM, LANG_SCHEMA, "Page text blocks:\n" + listing),
        _ask(client, url, model, CLAIM_SYSTEM, CLAIM_SCHEMA, "Client brief:\n" + brief.strip()[:3000] + "\n\nPage text blocks:\n" + listing),
        return_exceptions=True)
    brief_n, brief_digits = _norm(brief), _digits(brief)
    out, seen = [], set()

    def add(kind, i, quote, problem, fix=""):
        quote, fix = str(quote or "").strip(), str(fix or "").strip()
        if not isinstance(i, int) or not (0 <= i < len(blocks)) or len(quote) < 3 or _norm(quote) not in _norm(blocks[i]):
            return                                          # not literally on the page: the model made it up
        if kind == "language" and (not fix or _norm(fix) == _norm(quote)):
            return                                          # no concrete correction, or nothing changes
        if kind == "claim":
            nums = _digits(quote)
            if _norm(quote) in brief_n or (nums and nums <= brief_digits and len(_norm(quote)) < 24):
                return                                      # it is in the brief
        key = (kind, _norm(quote))
        if key in seen:
            return
        seen.add(key)
        out.append({"kind": kind, "quote": quote, "problem": str(problem or "")[:200], "fix": fix[:200], "block": blocks[i][:160]})

    for kind, res, key in (("language", lang, "errors"), ("claim", claim, "claims")):
        if isinstance(res, Exception):
            continue
        for entry in res[:200]:
            try:
                for it in (entry.get(key) or [])[:6]:
                    add(kind, entry.get("block"), it.get("quote"), it.get("problem"), it.get("fix"))
            except (AttributeError, TypeError):
                continue
    claims = [f for f in out if f["kind"] == "claim"]
    if claims:                                              # a second, stricter look at each claim removes the pedantic ones
        user = "Client brief:\n" + brief.strip()[:3000] + "\n\nClaims:\n" + "\n".join(
            f"[{i}] {c['quote']}   (in the sentence: {c['block']})" for i, c in enumerate(claims))
        try:
            body = {"model": model, "stream": False, "think": True, "format": VERIFY_SCHEMA, "options": {"temperature": 0, "num_ctx": 16384},
                    "messages": [{"role": "system", "content": VERIFY_SYSTEM}, {"role": "user", "content": user}]}
            r = await client.post(f"{url}/api/chat", json=body, timeout=240)
            verdict = {v["id"]: v.get("verdict") for v in json.loads(r.json()["message"]["content"]).get("verdicts", []) if isinstance(v.get("id"), int)}
            drop = {id(c) for i, c in enumerate(claims) if verdict.get(i) == "supported"}
            out = [f for f in out if id(f) not in drop]
        except Exception:
            pass
    return out[:20]


def format_report(findings: list[dict]) -> str:
    if not findings:
        return "== Copy check: no findings"
    lines = [f"== Copy check: {len(findings)} finding(s)"]
    for f in findings:
        if f["kind"] == "language":
            lines.append(f"  MEDIUM language: \"{f['quote']}\" -> \"{f['fix']}\" ({f['problem']})")
        else:
            lines.append(f"  MEDIUM claim: \"{f['quote']}\" is not in the client's brief ({f['problem']}). Remove it or rewrite without the invented fact.")
    return "\n".join(lines)
