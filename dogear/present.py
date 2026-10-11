"""Turns a finished answer into display blocks.

Text is NEVER rewritten. The answer is split into units deterministically (paragraphs, list items,
tables, code); a small fast model only classifies them: which unit is the headline, which are
warnings/notes, what kind of answer this is, and what the user might ask next. Anything the model
does not mention is shown as plain prose, in original order, so nothing can be lost or changed.
"""
import json
import re

import httpx

from .llm import URL

MODEL = "qwen3.5:4b"
KINDS = ["fact", "how-to", "code-change", "debugging", "comparison", "explanation", "status", "other"]

SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": KINDS},
        "headline": {"type": "integer"},
        "callouts": {"type": "array", "items": {"type": "object", "properties": {
            "unit": {"type": "integer"}, "tone": {"type": "string", "enum": ["note", "warning", "success"]}},
            "required": ["unit", "tone"]}},
        "followups": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "headline", "callouts", "followups"],
}

PROMPT = """You classify the parts of an assistant's finished answer so a UI can lay it out. You do not rewrite anything.

You get the user's question and the answer split into numbered units like [3] text.
Return JSON:
- kind: what the answer is: fact (a direct factual answer), how-to (steps/instructions), code-change (something was edited/fixed/built), debugging (diagnosis of a problem), comparison, explanation, status (progress or result report), other.
- headline: the number of the ONE unit that states the direct answer or the key result. 0 if there is no single such unit.
- callouts: units that are a warning, caveat, risk or important note (tone warning or note), or an explicit success/result confirmation (tone success). Usually 0 to 2.
- followups: up to 3 short things the USER might say next, in the answer's language, max 50 characters each. If the answer asks the user a question or offers a choice, these must be possible replies to it (e.g. "Yes, replace it", "Make a new page"), never questions back to the user. No facts that are not in the answer.
Output JSON only."""

CODE_RE = re.compile(r"```([^\n]*)\n(.*?)```", re.S)
BULLET = re.compile(r"^\s*(?:[-*•▪–]\s+|\d+[.)]\s+)")
NUMBERED = re.compile(r"^\s*\d+[.)]\s+")
KV = re.compile(r"^\s*(?:[-*•▪–]\s+)?([^:|]{1,36}?)\s*:\s+(\S.*)$")
BOLD = re.compile(r"\*\*|__")
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9\"„(])")


ABBR = re.compile(r"(?:\b[A-Za-zÄÖÜäöü]{1,2}\.|\b(?:ca|bzw|Nr|Dr|Prof|usw|vgl|etc|inkl|ggf|Std|Mio|Mrd|Abb|Tel|St)\.)$")


def _sentences(p: str) -> list[str]:
    p = p.strip()
    if p.startswith("**") and p.endswith("**") and p.count("**") == 2:
        return [p]                                   # a bold label line is one unit
    out = []
    for part in (x.strip() for x in SENT.split(p) if x.strip()):
        if out and ABBR.search(out[-1]):             # "e. V." / "z. B." / "ca." are not sentence ends
            out[-1] += " " + part
        else:
            out.append(part)
    return out


def split_units(masked: str) -> list[dict]:
    """Deterministic segmentation. Kinds: text, item, code, table, heading."""
    units, buf, para = [], [], [0]

    def flush():
        if not buf:
            return
        kv = [bool(KV.match(BOLD.sub("", l))) for l in buf]
        if len(buf) >= 2 and sum(kv) >= 2:           # lines like "Name: Sampson" form a fact list
            units.extend({"kind": "item", "text": BOLD.sub("", BULLET.sub("", l)).strip(), "num": False} for l in buf)
        else:
            para[0] += 1
            for s in _sentences(" ".join(l.strip() for l in buf)):
                units.append({"kind": "text", "text": s, "p": para[0]})
        buf.clear()

    lines, i = masked.split("\n"), 0
    while i < len(lines):
        l, st = lines[i], lines[i].strip()
        if not st:
            flush()
        elif re.fullmatch(r"\[\[CODE \d+\]\]", st):
            flush()
            units.append({"kind": "code", "ref": int(re.search(r"\d+", st).group())})
        elif st.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            units.append({"kind": "table", "rows": rows})
            continue
        elif re.match(r"^#{1,4}\s", st):
            flush()
            units.append({"kind": "heading", "text": st.lstrip("# ").strip()})
        elif re.match(r"^\s{2,}\S", l) and units and units[-1]["kind"] == "item" and not buf:
            # indented continuation of the previous item ("1. Step\n   – detail")
            units[-1]["text"] += " – " + BULLET.sub("", st).lstrip("–-— ").strip()
        elif BULLET.match(l):
            flush()
            units.append({"kind": "item", "text": BULLET.sub("", l).strip(), "num": bool(NUMBERED.match(l)),
                          "dash": bool(re.match(r"^\s*[–—]\s", l))})
        else:
            buf.append(l)
        i += 1
    flush()
    return units


def _table(rows: list[str]) -> dict | None:
    cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows if not re.fullmatch(r"\|?[\s:\-|]+\|?", r)]
    if len(cells) < 2 or len(cells[0]) < 2:
        return None
    cols = cells[0]
    return {"type": "table", "columns": cols, "rows": [r[:len(cols)] + [""] * (len(cols) - len(r)) for r in cells[1:]]}


def _is_term(t: str) -> bool:
    """A short label line: bold-wrapped (may end in an abbreviation dot) or plain without sentence punctuation."""
    t = t.strip()
    if t.startswith("**") and t.endswith("**"):
        return True
    return not re.search(r"[.!?:]$", t)


def build(units: list[dict], headline: int, callouts: dict[int, str]) -> tuple[str | None, list[dict]]:
    """Group units into blocks. Model output only selects headline and callouts by unit number."""
    texts = [u for u in units if u["kind"] == "text"]
    num = {id(u): n for n, u in enumerate(units, 1)}
    head = None
    blocks, i = [], 0
    pending_title = ""
    while i < len(units):
        u, n = units[i], i + 1
        if u["kind"] == "text":
            t = u["text"]
            nxt = units[i + 1] if i + 1 < len(units) else None
            term = BOLD.sub("", t).strip()
            if (nxt and nxt["kind"] == "item" and nxt.get("dash") and len(term) <= 110 and not term.endswith(":")
                    and (_is_term(t)) and n != headline):
                pairs = []
                while (i + 1 < len(units) and units[i]["kind"] == "text" and units[i + 1]["kind"] == "item"
                       and units[i + 1].get("dash") and len(BOLD.sub("", units[i]["text"])) <= 110 and _is_term(units[i]["text"])):
                    pairs.append({"label": BOLD.sub("", units[i]["text"]).strip(), "value": units[i + 1]["text"]})
                    i += 2
                blocks.append({"type": "defs", "title": pending_title, "pairs": pairs})
                pending_title = ""
                continue
            if n == headline and head is None:
                head = t
            elif BOLD.sub("", t).endswith(":") and nxt and nxt["kind"] in ("item", "table") and len(t) < 90:
                pending_title = BOLD.sub("", t).rstrip(":")
            elif n in callouts:
                blocks.append({"type": "callout", "tone": callouts[n], "text": t})
            elif blocks and blocks[-1]["type"] == "prose" and blocks[-1].get("p") == u.get("p"):
                blocks[-1]["text"] += " " + t
            elif blocks and blocks[-1]["type"] == "prose" and len(blocks[-1]["text"]) + len(t) < 420:
                blocks[-1]["text"] += "\n\n" + t; blocks[-1]["p"] = u.get("p")
            else:
                blocks.append({"type": "prose", "text": t, "p": u.get("p")})
        elif u["kind"] == "heading":
            pending_title = u["text"]
        elif u["kind"] == "code":
            blocks.append({"type": "code", "ref": u["ref"], "title": pending_title})
            pending_title = ""
        elif u["kind"] == "table":
            tb = _table(u["rows"])
            if tb:
                tb["title"] = pending_title
                blocks.append(tb)
            else:
                blocks.append({"type": "prose", "text": "\n".join(u["rows"])})
            pending_title = ""
        else:  # run of items
            run = []
            while i < len(units) and units[i]["kind"] == "item":
                run.append(units[i])
                i += 1
            kv = [KV.match(BOLD.sub("", r["text"])) for r in run]
            if len(run) >= 2 and all(kv):
                blocks.append({"type": "facts", "title": pending_title,
                               "pairs": [{"label": m.group(1).strip(), "value": m.group(2).strip()} for m in kv]})
            else:
                blocks.append({"type": "steps" if all(r.get("num") for r in run) and len(run) > 1 else "list",
                               "title": pending_title, "items": [r["text"] for r in run]})
            pending_title = ""
            continue
        i += 1
    return head, blocks


async def present(client: httpx.AsyncClient, question: str, answer: str, hints: str = "", model: str = MODEL) -> dict | None:
    """Returns {kind, headline, blocks, followups, code} or None when plain text is the better display."""
    plain = answer.strip()
    if len(plain) < 240 and plain.count("\n") < 3:
        return None
    codes = [{"lang": m.group(1).strip(), "code": m.group(2).rstrip("\n")} for m in CODE_RE.finditer(answer)]
    masked = answer
    for n, m in enumerate(CODE_RE.finditer(answer), 1):
        masked = masked.replace(m.group(0), f"\n[[CODE {n}]]\n", 1)
    units = split_units(masked)
    if not units:
        return None
    listing = "\n".join(f"[{n}] {u['text'][:260]}" if u["kind"] in ("text", "item", "heading") else f"[{n}] ({u['kind']})"
                        for n, u in enumerate(units, 1))
    body = {"model": model, "stream": False, "think": False, "format": SCHEMA, "keep_alive": "30m",
            "options": {"temperature": 0.0, "num_ctx": 6144},
            "messages": [{"role": "system", "content": PROMPT},
                         {"role": "user", "content": f"Question:\n{question[:500]}\n\nContext: {hints}\n\nAnswer units:\n{listing[:5500]}"}]}
    kind, headline, callouts, fups = "other", 0, {}, []
    try:
        r = await client.post(f"{URL}/api/chat", json=body, timeout=60)
        r.raise_for_status()
        raw = json.loads(r.json()["message"]["content"])
        kind = raw.get("kind") if raw.get("kind") in KINDS else "other"
        h = raw.get("headline")
        headline = h if isinstance(h, int) and 1 <= h <= len(units) and units[h - 1]["kind"] == "text" else 0
        for c in raw.get("callouts", [])[:3]:
            u = c.get("unit")
            if isinstance(u, int) and 1 <= u <= len(units) and units[u - 1]["kind"] == "text" and u != headline:
                callouts[u] = c.get("tone", "note")
        nums = set(re.findall(r"\d[\d.,]*", answer))
        for f in raw.get("followups", [])[:3]:
            if isinstance(f, str) and 3 < len(f.strip()) <= 70 and set(re.findall(r"\d[\d.,]*", f)) <= nums:
                fups.append(f.strip())
    except Exception:
        pass                                          # classification is optional; structure still applies
    head, blocks = build(units, headline, callouts)
    for b in blocks:
        b.pop("p", None)
    if head and len(head) > 220:                       # a long sentence is not a headline
        blocks.insert(0, {"type": "prose", "text": head})
        head = None
    structured = any(b["type"] != "prose" for b in blocks) or head or fups
    if not structured and len(blocks) <= 2:
        return None
    return {"kind": kind, "headline": head, "blocks": blocks, "followups": fups, "code": codes}
