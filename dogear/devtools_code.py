"""Code tools: MultiEdit (atomic multi-replace), Outline (symbol map of a file), FindSymbol (definitions and usages)."""
import ast
import asyncio
import base64
import bisect
import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .tools import SKIP_DIRS, ToolError     # tools.py does not import this module; dogear.agent registers TOOLS, so import order is free

# ------------------------------------------------------------------ MultiEdit


def _edit_list(edits) -> list[dict]:
    if isinstance(edits, str):
        try:
            edits = json.loads(edits)
        except ValueError:
            raise ToolError("edits must be a list of objects {old_string, new_string, replace_all?}, not text.")
    if isinstance(edits, dict):
        edits = [edits]
    if not isinstance(edits, list) or not edits:
        raise ToolError("edits must be a non-empty list of objects {old_string, new_string, replace_all?}.")
    out = []
    for i, e in enumerate(edits):
        if not isinstance(e, dict) or not isinstance(e.get("old_string"), str) or not isinstance(e.get("new_string"), str):
            raise ToolError(f"edits[{i}] (edit #{i + 1}) must be an object with string fields old_string and new_string.")
        ra = e.get("replace_all", False)
        ra = ra.strip().lower() in ("true", "1", "yes") if isinstance(ra, str) else bool(ra)
        out.append({"old": e["old_string"], "new": e["new_string"], "all": ra})
    return out


def _miss_hint(old: str, text: str, orig: str, shifted: bool = False) -> str:
    if old in orig:
        return " The text exists in the original file, but an earlier edit in this call changed it; order the edits so each old_string still exists at its turn."
    first = next((l.strip() for l in old.splitlines() if l.strip()), "")
    if first and first in text:
        ln = text.count("\n", 0, text.index(first)) + 1
        of = " (counted after the previous edits in this call)" if shifted else ""
        return f" Its first line does appear at line {ln}{of}, but the full text differs (check whitespace, indentation and line breaks)."
    if re.sub(r"\s+", " ", old).strip() in re.sub(r"\s+", " ", text):
        return " It matches only when whitespace is ignored; copy the exact whitespace from the file."
    return " Re-read the file and copy the text exactly."


def _apply_edits(text: str, edits: list[dict]) -> str:
    orig, n = text, len(edits)
    for i, e in enumerate(edits):
        old, new, where = e["old"], e["new"], f"edits[{i}] (edit #{i + 1} of {n})"
        tail = " No edits were applied; the file is unchanged."
        shifted = text != orig      # line numbers below refer to the text after the earlier edits, not to the file on disk
        if not old:
            raise ToolError(f"{where} failed: old_string is empty." + tail)
        if old == new:
            raise ToolError(f"{where} failed: old_string and new_string are identical." + tail)
        cnt = text.count(old)
        if cnt == 0:
            raise ToolError(f"{where} failed: old_string not found." + _miss_hint(old, text, orig, shifted) + tail)
        if cnt > 1 and not e["all"]:
            lines, pos = [], text.find(old)
            while pos >= 0 and len(lines) < 6:
                lines.append(text.count("\n", 0, pos) + 1)
                pos = text.find(old, pos + 1)
            at = ", ".join(map(str, lines)) + (", ..." if cnt > len(lines) else "")
            of = " (counted after the previous edits in this call)" if shifted else ""
            raise ToolError(f"{where} failed: old_string occurs {cnt} times (lines {at}{of}). "
                            f"Add surrounding context to make it unique or set replace_all=true." + tail)
        text = text.replace(old, new) if e["all"] else text.replace(old, new, 1)
    return text


def _atomic_write(p: Path, data: bytes) -> None:
    """Replace the file through a temp file; write in place when that is impossible (hard link, read-only directory)."""
    if p.stat().st_nlink > 1:
        p.write_bytes(data)                 # os.replace would break the hard link
        return
    try:
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".me-", suffix=".tmp")   # short name: the file name may already be near the limit
    except OSError:
        p.write_bytes(data)
        return
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        shutil.copymode(p, tmp)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


DIFF_WORK = 4_000_000   # lines(old) * lines(new) up to which the diff is exact; beyond it the counts are approximate


def _anchors(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    """Longest in-order chain of lines that occur exactly once in both lists, as (index in a, index in b)."""
    ca, cb = Counter(a), Counter(b)
    pos = {l: i for i, l in enumerate(a) if ca[l] == 1 and cb[l] == 1}
    pairs = [(pos[l], j) for j, l in enumerate(b) if l in pos]
    tails: list[int] = []           # pairs[tails[k]] ends the best chain of length k + 1
    heads: list[int] = []           # its index in a, kept sorted for bisect
    prev = [-1] * len(pairs)
    for k, (i, _) in enumerate(pairs):
        at = bisect.bisect_left(heads, i)
        prev[k] = tails[at - 1] if at else -1
        if at == len(tails):
            tails.append(k)
            heads.append(i)
        else:
            tails[at], heads[at] = k, i
    out, k = [], tails[-1] if tails else -1
    while k >= 0:
        out.append(pairs[k])
        k = prev[k]
    return out[::-1]


def _opcodes(a: list[str], b: list[str], depth: int = 0) -> list[tuple]:
    """Opcodes (tag, i1, i2, j1, j2) turning a into b. Exact for small inputs; larger ones are split at lines that are
    unique in both texts, and what is still too big is compared line by line (counts are then approximate)."""
    if len(a) * len(b) <= DIFF_WORK:
        return difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    anchors = _anchors(a, b) if depth < 4 else []
    if not anchors:
        if len(a) != len(b):
            return [("replace", 0, len(a), 0, len(b))]
        ops, i = [], 0
        while i < len(a):
            j, same = i, a[i] == b[i]
            while j < len(a) and (a[j] == b[j]) == same:
                j += 1
            ops.append(("equal" if same else "replace", i, j, i, j))
            i = j
        return ops
    ops, pi, pj = [], 0, 0
    for i, j in anchors + [(len(a), len(b))]:
        if i > pi or j > pj:
            ops += [(t, i1 + pi, i2 + pi, j1 + pj, j2 + pj) for t, i1, i2, j1, j2 in _opcodes(a[pi:i], b[pj:j], depth + 1)]
        if i < len(a):
            ops.append(("equal", i, i + 1, j, j + 1))
        pi, pj = i + 1, j + 1
    merged: list[tuple] = []
    for op in ops:
        if merged and op[0] == "equal" == merged[-1][0] and merged[-1][2] == op[1]:
            merged[-1] = ("equal", merged[-1][1], op[2], merged[-1][3], op[4])
        else:
            merged.append(op)
    return merged


def _diff(old: str, new: str, cap: int = 160) -> dict:
    """Same shape as tools.make_diff, but trims the common head and tail first and bounds the work on huge inputs."""
    a, b = old.splitlines(), new.splitlines()
    head = 0
    while head < min(len(a), len(b)) and a[head] == b[head]:
        head += 1
    tail = 0
    while tail < min(len(a), len(b)) - head and a[-1 - tail] == b[-1 - tail]:
        tail += 1
    am, bm = a[head:len(a) - tail], b[head:len(b) - tail]
    mid = [(t, i1 + head, i2 + head, j1 + head, j2 + head) for t, i1, i2, j1, j2 in _opcodes(am, bm)]
    ops = ([("equal", 0, head, 0, head)] if head else []) + mid + \
          ([("equal", len(a) - tail, len(a), len(b) - tail, len(b))] if tail else [])

    class _Ops(difflib.SequenceMatcher):
        def get_opcodes(self):
            return ops
    hunks, add, rem, shown = [], 0, 0, 0
    for group in _Ops().get_grouped_opcodes(2):
        lines = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                lines += [[" ", j1 + k + 1, a[i1 + k]] for k in range(i2 - i1)]
                continue
            lines += [["-", k + 1, a[k]] for k in range(i1, i2)]
            lines += [["+", k + 1, b[k]] for k in range(j1, j2)]
            rem += i2 - i1
            add += j2 - j1
        if shown < cap:
            hunks.append(lines[: cap - shown])
            shown += len(lines)
    return {"added": add, "removed": rem, "hunks": hunks}


def multi_edit(ctx, file_path, edits):
    p = ctx.path(file_path)
    if not p.is_file():
        raise ToolError(f"{file_path} does not exist")
    if not os.access(p, os.W_OK):
        raise ToolError(f"{file_path} is read-only (no write permission). Nothing was changed.")
    todo = _edit_list(edits)
    raw = p.read_bytes()
    if b"\0" in raw[:4096]:
        raise ToolError(f"{file_path} is binary")
    try:
        old_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"{file_path} is not valid UTF-8 text")
    crlf = "\r\n" in old_text and old_text.count("\n") == old_text.count("\r\n")
    work = old_text.replace("\r\n", "\n") if crlf else old_text
    if crlf:
        for e in todo:
            e["old"], e["new"] = e["old"].replace("\r\n", "\n"), e["new"].replace("\r\n", "\n")
    new_work = _apply_edits(work, todo)
    new_text = new_work.replace("\n", "\r\n") if crlf else new_work
    _atomic_write(p, new_text.encode("utf-8"))
    d = _diff(old_text, new_text)
    ctx.meta = {"path": file_path, "diff": d, "new_text": new_text}
    return f"Updated {file_path} ({len(todo)} edits, +{d['added']} -{d['removed']})"


async def MultiEdit(ctx, file_path, edits):
    return await asyncio.to_thread(multi_edit, ctx, file_path, edits)


# ------------------------------------------------------------------ Outline

CAP_LINES = 200
_KINDS = {".py": "py", ".pyi": "py", ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".ts": "js", ".tsx": "js", ".mts": "js",
          ".md": "md", ".markdown": "md", ".html": "html", ".htm": "html", ".json": "json", ".css": "css", ".scss": "css", ".less": "css"}
_Row = tuple[int, int, int, str]   # start line, end line, depth, text


def _clipl(s: str, n: int = 170) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _fmt(r: _Row) -> str:
    rng = f"{r[0]}-{r[1]}" if r[1] > r[0] else f"{r[0]}"
    return f"{rng:<9} " + "  " * r[2] + _clipl(r[3])


def _first(lines: list[str], n: int = 40) -> list[str]:
    out: list[str] = []
    for i, l in enumerate(lines, 1):
        if l.strip():
            out.append(f"{i:<9} {_clipl(l.strip())}")
            if len(out) >= n:
                break
    return out


# --- python

def _unparse(n) -> str:
    try:
        return ast.unparse(n)
    except (RecursionError, ValueError, MemoryError):    # e.g. a chain of hundreds of `+`
        return "..."


def _py_sig(n) -> str:
    ret = f" -> {_unparse(n.returns)}" if n.returns else ""
    return f"({_unparse(n.args)}){ret}"


def _py_doc(n) -> str:
    d = ast.get_docstring(n)
    return f"  # {d.strip().splitlines()[0][:70]}" if d and d.strip() else ""


def _sub_bodies(n) -> list[list]:
    if not isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, getattr(ast, "TryStar", ast.Try))):
        return []
    subs = [getattr(n, k, []) for k in ("body", "orelse", "finalbody")]
    return subs + [h.body for h in getattr(n, "handlers", [])]


def _py_assign(n, scope: str) -> str | None:
    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
    names = [t.id for t in targets if isinstance(t, ast.Name)]
    if not names or (scope == "class" and not all(x.isupper() for x in names)):
        return None
    val = _unparse(n.value)[:50] if n.value is not None else "..."
    ann = f": {_unparse(n.annotation)}" if isinstance(n, ast.AnnAssign) else ""
    return f"{', '.join(names)}{ann} = {val}"


def _py_rows(body: list, depth: int, scope: str, rows: list[_Row]) -> None:
    for n in body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kw = "async def" if isinstance(n, ast.AsyncFunctionDef) else "def"
            decos = "".join(f"@{_unparse(d)} " for d in n.decorator_list)
            start = min([n.lineno] + [d.lineno for d in n.decorator_list])
            rows.append((start, n.end_lineno, depth, f"{decos}{kw} {n.name}{_py_sig(n)}{_py_doc(n)}"))
            if depth < 3:
                _py_rows(n.body, depth + 1, "func", rows)
        elif isinstance(n, ast.ClassDef):
            decos = "".join(f"@{_unparse(d)} " for d in n.decorator_list)
            start = min([n.lineno] + [d.lineno for d in n.decorator_list])
            bases = ", ".join([_unparse(b) for b in n.bases] + [f"{k.arg}={_unparse(k.value)}" for k in n.keywords])
            rows.append((start, n.end_lineno, depth, f"{decos}class {n.name}({bases}){_py_doc(n)}" if bases else f"{decos}class {n.name}{_py_doc(n)}"))
            _py_rows(n.body, depth + 1, "class", rows)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)) and scope in ("module", "class"):
            t = _py_assign(n, scope)
            if t:
                rows.append((n.lineno, n.end_lineno, depth, t))
        elif isinstance(n, ast.If) and "__name__" in _unparse(n.test):
            rows.append((n.lineno, n.end_lineno, depth, f"if {_unparse(n.test)}"))
            _py_rows(n.body, depth + 1, "func", rows)
        else:
            for sub in _sub_bodies(n):
                _py_rows(sub, depth, scope, rows)


def _py_regex(lines: list[str], why: str) -> list[str]:
    rx = re.compile(r"^(\s*)((?:async\s+)?def|class)\s+(\w+)(.*)$")
    out = [f"({why}; regex fallback, line ends unknown)"]
    for i, l in enumerate(lines, 1):
        m = rx.match(l)
        if m:
            out.append(_fmt((i, i, len(m.group(1).expandtabs(4)) // 4, f"{m.group(2)} {m.group(3)}{m.group(4).rstrip(': ')}")))
    return out


def _outline_py(text: str, lines: list[str]) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return _py_regex(lines, f"syntax error at line {e.lineno}: {e.msg}" if e.lineno else f"syntax error: {e.msg}")
    except (RecursionError, ValueError, MemoryError) as e:
        return _py_regex(lines, f"could not parse: {type(e).__name__}")
    rows: list[_Row] = []
    try:
        _py_rows(tree.body, 0, "module", rows)
    except RecursionError:
        return _py_regex(lines, "file is nested too deeply to outline")
    out = []
    doc = ast.get_docstring(tree)
    if doc and doc.strip():
        out.append(f"module: {_clipl(doc.strip().splitlines()[0], 140)}")
    return out + [_fmt(r) for r in rows]


# --- js / ts

_ID = r"[\w$]+"
_JS_FUNC = re.compile(rf"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?function\b")
_JS_CLASS = re.compile(rf"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?class\s+{_ID}")
_JS_TYPE = re.compile(rf"^\s*(?:export\s+)?(?:declare\s+)?(?:const\s+)?(?:interface|type|enum|namespace)\s+{_ID}")
_JS_VAR = re.compile(rf"^\s*(?:export\s+)?(?:const|let|var)\s+({_ID})\s*(?::[^=]+)?=\s*(.*)$")
_JS_FNVAL = re.compile(rf"^(?:async\s*)?(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|{_ID}\s*=>|\([^)]*$)")
_JS_METHOD = re.compile(rf"^\s*(?:(?:static|async|public|private|protected|readonly|override|abstract|get|set)\s+)*\*?\s*(#?{_ID})\s*(?:<[^>]*>)?\s*"
                        rf"\((?:[^()]*|[^()]*\([^()]*\)[^()]*)\)\s*(?::\s*[^{{;=]+)?\{{\s*$")
_JS_PROP = re.compile(rf"^\s*(?:(?:static|readonly|public|private|protected)\s+)*(#?{_ID})\s*=\s*(?:async\s+)?(?:\([^)]*\)|{_ID})\s*(?::[^=]+)?=>")
_JS_EXPORT = re.compile(r"^\s*(?:export\s+default\b|export\s*\{|export\s+\*|module\.exports\s*=|exports\.[\w$]+\s*=)")
_JS_ROUTE = re.compile(r"^\s*(?:app|router|server)\.(?:get|post|put|patch|delete|use|all)\(\s*['\"`][^'\"`]+['\"`]")
_CONTROL = {"if", "for", "while", "switch", "catch", "function", "return", "else", "do", "with", "try", "await", "new", "typeof", "super"}


def _indent(l: str) -> int:
    return len(l[: len(l) - len(l.lstrip())].replace("\t", "  "))


def _block_end(lines: list[str], i: int) -> int:
    """Rough end of the block starting at index i, from indentation: the closing line at the same indent, or the last deeper line."""
    base, last = _indent(lines[i]), i
    for j in range(i + 1, len(lines)):
        l = lines[j]
        if not l.strip():
            continue
        if _indent(l) > base:
            last = j
            continue
        if _indent(l) == base and l.lstrip()[0] in "})]":
            last = j
        break
    return last


def _js_head(l: str) -> str:
    s = l.strip()
    s = s[: s.index("=>") + 2] if "=>" in s else s.rstrip("{").rstrip()
    return s.rstrip(";")


def _js_rows(lines: list[str], base: int = 0, max_indent: int = 4) -> list[_Row]:
    rows: list[_Row] = []
    stack: list[tuple[int, bool]] = []     # (indent, is_class) of enclosing recorded rows
    for i, l in enumerate(lines):
        if not l.strip() or l.lstrip().startswith(("//", "*", "/*")):
            continue
        ind = _indent(l)
        while stack and ind <= stack[-1][0]:
            stack.pop()
        in_class = any(c for _, c in stack)
        text, is_class = None, False
        if _JS_CLASS.match(l):
            text, is_class = l.strip().rstrip("{").rstrip(), True
        elif _JS_FUNC.match(l) or _JS_TYPE.match(l):
            text = l.strip().rstrip("{").rstrip()
        elif (m := _JS_VAR.match(l)) is not None:
            if _JS_FNVAL.match(m.group(2)) and ind <= max_indent and (not stack or in_class):
                text = _clipl(_js_head(l), 120)
            elif ind == 0:
                text = _clipl(l.strip().rstrip(";"), 100)
        elif in_class and (m := _JS_METHOD.match(l)) and m.group(1) not in _CONTROL:
            text = l.strip().rstrip("{").rstrip()
        elif in_class and _JS_PROP.match(l):
            text = _js_head(l)
        elif _JS_EXPORT.match(l) and ind <= max_indent:
            text = _clipl(l.strip().rstrip("{").rstrip(), 100)
        elif _JS_ROUTE.match(l) and ind <= max_indent:
            text = re.match(r"^\s*([\w.]+\(\s*['\"`][^'\"`]+['\"`])", l).group(1) + ")"
        if text is None or (ind > max_indent and not in_class):
            continue
        end = _block_end(lines, i)
        rows.append((i + 1 + base, end + 1 + base, len(stack), text))
        stack.append((ind, is_class))
    return rows


def _dedent(lines: list[str]) -> list[str]:
    ind = min((_indent(l) for l in lines if l.strip()), default=0)
    return [l.expandtabs(2)[ind:] if l.strip() else "" for l in lines]


_JS_SPECIAL = re.compile(r"[/'\"`]")
_JS_BODY = {"'": re.compile(r"(?:\\.|[^'\\\n])*"), '"': re.compile(r'(?:\\.|[^"\\\n])*'), "`": re.compile(r"(?:\\.|[^`\\])*", re.S)}
_JS_REGEX = re.compile(r"/(?:\\.|\[(?:\\.|[^\]\\\n])*\]|[^/\\\n\[])+/")
_RX_AFTER = set("(,=:[!&|?{};+-*%<>~^")


def _blank(s: str) -> str:
    return re.sub(r"[^\n]", " ", s)


def _newlines(s: str) -> str:
    return "\n" * s.count("\n")


def _js_blank(src: str) -> str:
    """Drop block comments and template-literal text (newlines kept, so line numbers hold) so the line scan only sees code."""
    out, pos, last, n = [], 0, 0, len(src)
    while (m := _JS_SPECIAL.search(src, pos)):
        i, c = m.start(), m.group()
        if c == "/":
            nxt = src[i + 1:i + 2]
            if nxt == "/":
                j = src.find("\n", i)
                pos = n if j < 0 else j
            elif nxt == "*":
                j = src.find("*/", i + 2)
                end = n if j < 0 else j + 2
                out += [src[last:i], _newlines(src[i:end])]
                last = pos = end
            else:   # a regex literal after an operator or bracket, otherwise a division sign
                k = i - 1
                while k >= 0 and src[k] in " \t":
                    k -= 1
                if k >= 0 and src[k] != "\n" and src[k] not in _RX_AFTER:
                    pos = i + 1
                    continue
                r = _JS_REGEX.match(src, i)
                pos = r.end() if r else i + 1
        else:
            j = _JS_BODY[c].match(src, i + 1).end()
            closed = j < n and src[j] == c
            if c == "`" and closed:
                out += [src[last:i + 1], _newlines(src[i + 1:j])]
                last = j
            pos = j + 1 if closed or c != "`" else i + 1   # an unclosed backtick is a stray character, not a template
    out.append(src[last:])
    return "".join(out)


def _outline_js(text: str, lines: list[str]) -> list[str]:
    return [_fmt(r) for r in _js_rows(_js_blank(text).split("\n"))]


# --- markdown

_FM_KEY = re.compile(r"""^["']?[\w .-]+["']?\s*:(?:\s|$)""")
_FM_MORE = re.compile(r"^\s+\S|^\s*-\s")


def _front_matter_end(lines: list[str]) -> int:
    """Index of the closing line of YAML front matter, or 0 when the leading '---' is just a rule."""
    if not lines or lines[0].strip() != "---":
        return 0
    body: list[str] = []
    for j in range(1, min(len(lines), 60)):
        if lines[j].strip() in ("---", "..."):
            return j if body and _FM_KEY.match(body[0]) else 0
        if lines[j].strip():
            if not (_FM_KEY.match(lines[j]) or _FM_MORE.match(lines[j])):
                return 0
            body.append(lines[j])
    return 0


def _outline_md(text: str, lines: list[str]) -> list[str]:
    heads: list[tuple[int, int, str]] = []
    n, fence, start = len(lines), None, 0
    front = ""
    close = _front_matter_end(lines)
    if close:
        front, start = f"{'1-' + str(close + 1):<9} front matter", close + 1
    for i in range(start, n):
        l = lines[i]
        m = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", l)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            if fence is None:
                fence = (m.group(1)[0], len(m.group(1)))
            elif m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] and not m.group(2).strip():
                fence = None
            continue
        if fence:
            continue
        m = re.match(r"^ {0,3}(#{1,6})[ \t]+(.*)$", l)
        if m:
            title = re.sub(r"(?:^|[ \t]+)#+[ \t]*$", "", m.group(2).strip()).strip()   # a closing run of # needs a space before it
            heads.append((i + 1, len(m.group(1)), title))
        elif i + 1 < n and l.strip() and re.match(r"^(=+|-+)\s*$", lines[i + 1]) and not re.match(r"^\s*([-*+]|\d+\.)\s", l):
            heads.append((i + 1, 1 if lines[i + 1].startswith("=") else 2, l.strip()))
    ends = [0] * len(heads)       # next heading of the same or a higher level, found with a stack in one pass
    stack: list[tuple[int, int]] = []
    for k in range(len(heads) - 1, -1, -1):
        ln, lv = heads[k][0], heads[k][1]
        while stack and stack[-1][1] > lv:
            stack.pop()
        ends[k] = stack[-1][0] if stack else n + 1
        stack.append((ln, lv))
    out = [front] if front else []
    for (ln, lv, title), nxt in zip(heads, ends):
        end = nxt - 1
        while end > ln and not lines[end - 1].strip():
            end -= 1
        out.append(_fmt((ln, end, lv - 1, f"{'#' * lv} {title}")))
    return out


# --- html

_TAG_NOISE = {"html", "head", "meta", "link", "script", "style", "title", "br", "span", "i", "b", "em", "strong", "li", "td", "tr", "th", "p", "label", "option"}


_HTML_OPEN = re.compile(r"<!--|<(script|style)\b([^>]{0,500})>", re.I)
_CLOSERS: dict[str, re.Pattern] = {}


def _closer(tag: str) -> re.Pattern:
    if tag not in _CLOSERS:
        _CLOSERS[tag] = re.compile(rf"</{tag}\s*>", re.I)
    return _CLOSERS[tag]


def _html_split(text: str) -> tuple[str, list[tuple[str, str, int, int, int, int]]]:
    """Blank comments and script/style bodies (same length, newlines kept) and list the script/style blocks
    as (tag, attrs, open_start, body_start, body_end, end). One left-to-right pass, so it stays linear."""
    out, blocks, pos, last = [], [], 0, 0
    while (m := _HTML_OPEN.search(text, pos)):
        if m.group().startswith("<!--"):
            j = text.find("-->", m.end())
            end = len(text) if j < 0 else j + 3
            out += [text[last:m.start()], _blank(text[m.start():end])]
            last = pos = end
            continue
        tag = m.group(1).lower()
        c = _closer(tag).search(text, m.end())
        body_end, end = (c.start(), c.end()) if c else (len(text), len(text))
        blocks.append((tag, m.group(2), m.start(), m.end(), body_end, end))
        out += [text[last:m.end()], _blank(text[m.end():body_end])]
        last, pos = body_end, end
    out.append(text[last:])
    return "".join(out), blocks


def _outline_html(text: str, lines: list[str]) -> list[str]:
    starts = [0]
    for m in re.finditer("\n", text):
        starts.append(m.end())
    ln = lambda pos: bisect.bisect_right(starts, pos)
    clean, blocks = _html_split(text)
    rows: list[_Row] = []
    for m in re.finditer(r"<title\b[^>]{0,500}>", clean, re.I):
        c = _closer("title").search(clean, m.end(), m.end() + 1000)
        if c:
            rows.append((ln(m.start()), ln(c.end()), 0, "title: " + _clipl(re.sub(r"\s+", " ", clean[m.end():c.start()]).strip(), 100)))
    for m in re.finditer(r"<h([1-6])\b([^>]{0,500})>", clean, re.I):
        c = _closer("h" + m.group(1)).search(clean, m.end(), m.end() + 4000)
        if not c:
            continue
        label = _clipl(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", clean[m.end():c.start()])).strip(), 80)
        idm = re.search(r"\bid\s*=\s*[\"']([^\"']+)", m.group(2))
        rows.append((ln(m.start()), ln(c.end()), int(m.group(1)) - 1, f"h{m.group(1)}: {label}" + (f"  #{idm.group(1)}" if idm else "")))
    ids = 0
    for m in re.finditer(r"<([a-zA-Z][\w-]*)\b[^>]{0,500}?\bid\s*=\s*[\"']([^\"']+)[\"']", clean):
        tag = m.group(1).lower()
        if tag in _TAG_NOISE or re.fullmatch(r"h[1-6]", tag):
            continue
        ids += 1
        if ids <= 60:
            rows.append((ln(m.start()), ln(m.start()), 0, f"<{tag} id=\"{m.group(2)}\">"))
    for tag, attrs, o_start, b_start, b_end, end in blocks:
        a, b = ln(o_start), ln(max(end - 1, o_start))
        src = re.search(r"\bsrc\s*=\s*[\"']([^\"']+)", attrs)
        typ = re.search(r"\btype\s*=\s*[\"']([^\"']+)", attrs)
        if src:
            rows.append((a, b, 0, f"<script src=\"{src.group(1)}\">"))
            continue
        body = text[b_start:b_end]
        label = f"<{tag}{' type=' + typ.group(1) if typ else ''}> inline, {b - a + 1} lines"
        rows.append((a, b, 0, label))
        if not body.strip() or (typ and "javascript" not in typ.group(1) and "module" not in typ.group(1)):
            continue
        base = ln(b_start) - 1
        sub = _js_rows(_dedent(_js_blank(body).split("\n")), base) if tag == "script" else _css_rows(body, base, 40)
        rows += [(r[0], r[1], r[2] + 1, r[3]) for r in sub[:60]]
    rows.sort(key=lambda r: (r[0], r[2]))
    out = [_fmt(r) for r in rows]
    if ids > 60:
        out.append(f"... {ids - 60} more elements with ids not shown")
    return out


# --- json

def _json_key_lines(text: str) -> dict[str, int]:
    out, depth, i, line, n = {}, 0, 0, 1, len(text)
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            if depth == 1:
                k = j + 1
                while k < n and text[k] in " \t\r\n":
                    k += 1
                if text[k:k + 1] == ":":
                    try:
                        out.setdefault(json.loads(text[i:j + 1]), line)
                    except ValueError:
                        pass
            i = j
        i += 1
    return out


def _json_desc(v) -> str:
    if isinstance(v, dict):
        keys = list(v)
        return f"object ({len(keys)} keys)" + (": " + ", ".join(map(str, keys[:8])) + (", ..." if len(keys) > 8 else "") if keys else "")
    if isinstance(v, list):
        return f"array ({len(v)} items)"
    if isinstance(v, str):
        return f"string {json.dumps(v[:40], ensure_ascii=False)}" + ("..." if len(v) > 40 else "")
    return json.dumps(v)


def _outline_json(text: str, lines: list[str]) -> list[str] | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, dict):
        at = _json_key_lines(text)
        return [f"{at.get(k, 1):<9} {_clipl(json.dumps(k, ensure_ascii=False) + ': ' + _json_desc(v))}" for k, v in data.items()]
    if isinstance(data, list):
        first = data[0] if data else None
        return [f"1         array of {len(data)} items" + (f", first item: {_json_desc(first)}" if first is not None else "")]
    return [f"1         {_json_desc(data)}"]


# --- css

def _css_rows(text: str, base: int = 0, cap: int = 400) -> list[_Row]:
    clean = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), text, flags=re.S)
    starts = [0] + [m.end() for m in re.finditer("\n", clean)]
    ln = lambda pos: bisect.bisect_right(starts, pos) + base
    rows: list[_Row] = []
    stack: list[tuple[int | None, bool]] = []   # (row index or None, opens a block whose children are not listed)
    seg, i, n, quote, hidden = 0, 0, len(clean), "", 0
    while i < n:
        c = clean[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == ";":
            seg = i + 1
        elif c == "{":
            raw = clean[seg:i]
            head = re.sub(r"\s+", " ", raw).strip()
            at = seg + (len(raw) - len(raw.lstrip()))
            leaf = head.startswith(("@keyframes", "@-webkit-keyframes", "@font-face"))
            if not head or hidden > 0 or len(rows) >= cap:
                stack.append((None, False))
            else:
                rows.append((ln(at), ln(at), len(stack), head))
                stack.append((len(rows) - 1, leaf))
                hidden += leaf
            seg = i + 1
        elif c == "}":
            if stack:
                top, leaf = stack.pop()
                hidden -= leaf
                if top is not None:
                    r = rows[top]
                    rows[top] = (r[0], ln(i), r[2], r[3])
            seg = i + 1
        i += 1
    return rows


def _outline_css(text: str, lines: list[str]) -> list[str]:
    rows = _css_rows(text)
    return [_fmt(r) for r in rows]


_BUILDERS = {"py": _outline_py, "js": _outline_js, "md": _outline_md, "html": _outline_html, "json": _outline_json, "css": _outline_css}


OUTLINE_MAX = 2_000_000     # bytes; larger files get the first lines only


def outline(ctx, file_path):
    p = ctx.path(file_path)
    if not p.is_file():
        raise ToolError(f"{file_path} is not a file")
    raw = p.read_bytes()
    if b"\0" in raw[:4096]:
        raise ToolError(f"{file_path} is binary ({len(raw)} bytes)")
    lines = raw.decode("utf-8", "replace").splitlines()      # the same line numbering as Read
    kind = _KINDS.get(p.suffix.lower())
    if kind and len(raw) > OUTLINE_MAX:
        body = [f"file is {len(raw) // 1000} KB, over the {OUTLINE_MAX // 1_000_000} MB outline limit; use Grep or Read with a line range. First non-empty lines:"] + _first(lines)
    else:
        body = _BUILDERS[kind]("\n".join(lines), lines) if kind else None
    head = f"{file_path}: {kind or 'text'}, {len(lines)} lines"
    if not body:
        note = f"could not parse as {kind}; first non-empty lines:" if body is None and kind else \
            "no symbols found; first non-empty lines:" if kind else "unknown file type; first non-empty lines:"
        body = [note] + _first(lines)
    more = len(body) - CAP_LINES
    if more > 0:
        body = body[:CAP_LINES] + [f"... {more} more entries not shown. Read a line range or use Grep for specifics."]
    ctx.meta = {"entries": min(len(body), CAP_LINES), "total": len(lines)}
    return "\n".join([head] + body)


async def Outline(ctx, file_path):
    return await asyncio.to_thread(outline, ctx, file_path)


# ------------------------------------------------------------------ FindSymbol

MAX_RESULTS = 60
SCAN_LIMIT = 20000      # usages collected; definitions are always kept
SCAN_HARD = 200000      # matches examined before the scan gives up
MAX_FILE = 1_000_000
_PROSE = {".md", ".markdown", ".txt", ".rst", ".adoc"}
_CSS = {".css", ".scss", ".less", ".sass"}
_CLIKE = {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".java", ".cs", ".m", ".mm", ".kt", ".swift", ".php", ".scala", ".dart"}
_FIELD = {".py", ".pyi", ".ts", ".tsx", ".rs", ".kt", ".swift", ".scala", ".dart"}
_COMMENT = ("#", "//", "/*", "*", "--", ";", "<!--")
_NOT_TYPE = r"(?!(?:return|else|new|throw|delete|await|yield|case|goto|typeof|sizeof|in|of|not|and|or|is)\b)"
_MOD = (r"(?:(?:export|default|declare|pub(?:\([^)]*\))?|public|private|protected|internal|static|final|abstract|async|open|override|unsafe|"
        r"extern|inline|virtual|const|readonly|local|sealed|partial|suspend|data)\s+)*")
_FN_RHS = re.compile(r"^\s*(?:async\s*)?(?:lambda\b|function\b|\([^)]*\)\s*(?::[^=]+)?=>|[\w$]+\s*=>)")
KINDS = ("any", "definition", "usage", "function", "class", "type", "variable")


def _word_rx(name: str) -> re.Pattern:
    return re.compile(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])")


class _Pats(list):
    quick: re.Pattern


def _def_patterns(name: str, ext: str) -> list[tuple[str, re.Pattern]]:
    n = re.escape(name)
    end = r"(?![\w$])"
    pats = [
        ("macro", rf"^\s*#\s*define\s+{n}{end}"),
        ("id", rf"\bid\s*=\s*[\"']{n}[\"']"),
    ]
    if ext in _CSS:
        pats += [("selector", rf"^\s*(?:[^{{}}]*[\s,>+~])?[.#]{n}(?![\w-])[^{{;]*(?:[{{,]\s*$|\{{[^{{}}]*\}}\s*$)"), ("cssvar", rf"^\s*--{n}\s*:")]
    pats += [
        ("function", rf"^\s*{_MOD}(?:async\s+)?(?:def|fn|func|fun|function|sub|proc|defn|defun|procedure)\s*\*?\s*(?:\([^)]*\)\s*)?(?:[A-Za-z_][\w$]*\.)?{n}{end}"),
        ("class", rf"^\s*{_MOD}(?:class|struct|trait|object|protocol|module|record|actor)\s+{n}{end}"),
        ("type", rf"^\s*{_MOD}(?:type|interface|enum|union|typedef|namespace|typealias)\s+{n}{end}"),
        ("variable", rf"^\s*{_MOD}(?:const|let|var|val|static|mut|final)\s+(?:mut\s+)?{n}{end}"),
        ("assign", rf"^\s*(?:(?:this|self)\.)?#?{n}\s*(?::\s*[^=]+?)?\s*=(?![=>])"),
        ("assign", rf"^\s*(?:(?:module\.)?exports|[\w$]+\.prototype)\.{n}\s*=(?![=>])"),
        ("function", rf"^\s*{n}\s*:\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*=>|[\w$]+\s*=>)"),
    ]
    if name not in _CONTROL and ext not in _PROSE:
        pats.append(("function", rf"^\s*(?:(?:static|async|public|private|protected|readonly|override|abstract|get|set)\s+)*\*?\s*#?{n}\s*(?:<[^>]*>)?\s*"
                                 rf"\((?:[^()]*|[^()]*\([^()]*\)[^()]*)\)\s*(?::\s*[^{{;=]+)?\{{\s*$"))
    if ext == ".rs":
        pats.append(("impl", rf"^\s*(?:unsafe\s+)?impl(?:<[^>]*>)?\s+(?:[\w:<>, ]+\s+for\s+)?{n}{end}"))
    if ext in _CLIKE:
        pats.append(("function", rf"^\s*{_MOD}{_NOT_TYPE}[\w:<>,\[\]*&]+(?:\s+|\s*[*&]+\s*){n}\s*\([^;]*$"))
        pats.append(("variable", rf"^\s*{_MOD}{_NOT_TYPE}[\w:<>,\[\]*&]+(?:\s+|\s*[*&]+\s*){n}(?=\s*(?:=(?![=>])|;|\[))"))
    if ext in _FIELD:
        pats.append(("field", rf"^\s*(?:pub\s+)?{n}\s*\??\s*:\s*(?P<ty>[A-Za-z_][\w\[\], .|\"'<>?&*]*?)\s*[,;]?\s*$"))
    out = _Pats((c, re.compile(p)) for c, p in pats)
    out.quick = re.compile("|".join(f"(?:{p})" for _, p in pats))      # one scan rejects most usage lines
    return out


def _rhs(rest: str) -> str:
    m = re.match(r"\s*(?::[^=]+)?=(?![=>])(.*)$", rest)
    return m.group(1) if m else rest


_PRIM = {"int", "str", "float", "bool", "bytes", "list", "dict", "set", "tuple", "string", "number", "boolean", "any", "unknown", "void",
         "never", "object", "null", "undefined", "bigint", "symbol", "char", "double", "long", "short", "byte", "self"}
_PRIM_RS = re.compile(r"[iu](?:8|16|32|64|128|size)|f32|f64")


def _is_type(ty: str) -> bool:
    """Whether the text after `name:` looks like a type (a field declaration) and not a value (an object literal)."""
    t = ty.strip()
    return t in _PRIM or bool(_PRIM_RS.fullmatch(t)) or t.split(".")[-1][:1].isupper() or bool(re.search(r"[\[\]<>|&*?]", t))


def _classify(line: str, name: str, ext: str, pats=None) -> str | None:
    """Category of a definition ('function', 'class', 'type', 'variable', 'macro', 'selector', 'id', 'impl') or None for a usage."""
    if ext in _PROSE or not line.strip():
        return None
    pats = pats or _def_patterns(name, ext)
    if hasattr(pats, "quick") and not pats.quick.search(line):
        return None
    comment = line.lstrip().startswith(_COMMENT)
    for cat, rx in pats:
        if comment and cat not in ("macro", "id", "selector", "cssvar"):
            continue
        m = rx.search(line)
        if not m:
            continue
        if cat == "assign" and (line.rstrip().endswith(",") or line.count(")") > line.count("(")):
            continue                                    # keyword argument or tuple item, not an assignment
        if cat == "field":
            if not _is_type(m.group("ty")):
                continue                                # `name: value,` in an object literal
            return "variable"
        if cat == "cssvar":
            return "variable"
        if cat in ("assign", "variable"):
            return "function" if _FN_RHS.match(_rhs(line[m.end():])) else "variable"
        return cat
    return None


def _glob_re(p: str) -> str:
    """Regex for one gitignore pattern (no leading or trailing slash), matched against a path relative to the .gitignore."""
    i, n, out = 0, len(p), []
    while i < n:
        c = p[i]
        if c == "*":
            if p[i:i + 2] == "**":
                j = i + 2
                at_start = i == 0 or p[i - 1] == "/"
                if at_start and p[j:j + 1] == "/":
                    out.append("(?:.*/)?")
                    i = j + 1
                    continue
                if at_start and j >= n:
                    out.append(".*")
                    i = j
                    continue
                i = j
            else:
                i += 1
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and p[j] in "!^":
                j += 1
            if j < n and p[j] == "]":
                j += 1
            while j < n and p[j] != "]":
                j += 1
            if j >= n:
                out.append(r"\[")
                i += 1
            else:
                cls = p[i + 1:j].replace("\\", "\\\\").replace("[", r"\[")
                out.append("[" + ("^" + cls[1:] if cls[:1] == "!" else cls) + "]")
                i = j + 1
        elif c == "\\" and i + 1 < n:
            out.append(re.escape(p[i + 1]))
            i += 2
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def _gitignore_rules(d: Path) -> list[tuple[int, re.Pattern, bool, bool]]:
    """Rules of d/.gitignore as (depth of d, regex, negated, dir_only), in file order."""
    try:
        text = (d / ".gitignore").read_text("utf-8", "replace")
    except OSError:
        return []
    rules = []
    for l in text.splitlines():
        while l.endswith(" ") and not l.endswith("\\ "):
            l = l[:-1]
        if not l or l.startswith("#"):
            continue
        neg = l.startswith("!")
        l = l[1:] if neg else l
        dir_only = l.endswith("/")
        l = l.rstrip("/")
        anchored = "/" in l
        l = l.lstrip("/")
        if not l:
            continue
        try:
            rx = re.compile(_glob_re(l) if anchored else "(?:.*/)?" + _glob_re(l), re.S)
        except re.error:
            continue
        rules.append((len(d.parts), rx, neg, dir_only))
    return rules


def _ignored(parts: tuple[str, ...], is_dir: bool, rules) -> bool:
    """Last matching rule wins, like git. `parts` is the absolute path split into components."""
    res = False
    for depth, rx, neg, dir_only in rules:
        if (not dir_only or is_dir) and rx.fullmatch("/".join(parts[depth:])):
            res = not neg
    return res


def _skip_name(name: str) -> bool:
    return name.endswith(".map") or ".min." in name or name.endswith((".lock", "-lock.json"))


def _py_files(root: Path) -> list[str]:
    """Files under root in sorted order. Ignore rules follow ripgrep with --no-require-git: the .gitignore of every
    ancestor and every directory on the way, negation and `**` included. Symlinks are never followed."""
    inherited = []
    for a in reversed(root.parents):
        inherited += _gitignore_rules(a)
    out: list[str] = []

    def walk(d: str, parts: tuple[str, ...], up: list) -> None:
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            return
        rules = up + _gitignore_rules(Path(d)) if any(e.name == ".gitignore" for e in entries) else up
        subdirs = []
        for e in entries:
            name = e.name
            if name.startswith(".") or e.is_symlink():
                continue
            try:
                is_dir, is_file = e.is_dir(follow_symlinks=False), e.is_file(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if name not in SKIP_DIRS and not _ignored(parts + (name,), True, rules):
                    subdirs.append((e.path, parts + (name,)))
            elif is_file and not _skip_name(name) and not _ignored(parts + (name,), False, rules):
                out.append(e.path)
        for q, qparts in subdirs:
            walk(q, qparts, rules)

    walk(str(root), root.parts, inherited)
    return out


def _safe(s: str) -> str:
    return s.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


class _Sink:
    """Collects scan hits. Usages stop at SCAN_LIMIT, but anything `is_def` accepts is always kept, so a definition in a
    late file is not lost behind thousands of usages. `cut` is "" (complete), "usages" or "all"."""

    def __init__(self, is_def=None):
        self.hits: list[tuple[str, int, str]] = []
        self.is_def, self.n_use, self.seen, self.cut = is_def, 0, 0, ""

    def add(self, rel: str, no: int, text: str) -> bool:
        """False when the scan should stop."""
        self.seen += 1
        if self.is_def and self.is_def(rel, no, text):
            self.hits.append((rel, no, text))
        elif self.n_use < SCAN_LIMIT:
            self.n_use += 1
            self.hits.append((rel, no, text))
        else:
            self.cut = "usages"
            if not self.is_def:
                return False
        if self.seen >= SCAN_HARD:
            self.cut = "all"
            return False
        return True


def _scan_py(root: Path, name: str, project: Path, is_def=None) -> tuple[list[tuple[str, int, str]], str]:
    rx, sink = _word_rx(name), _Sink(is_def)
    prefix, needle = str(project) + os.sep, name.encode()
    for f in [str(root)] if root.is_file() else _py_files(root):
        try:
            with open(f, "rb") as fh:
                raw = fh.read(MAX_FILE + 1)
        except OSError:
            continue
        if len(raw) > MAX_FILE or b"\0" in raw[:4096] or needle not in raw:
            continue
        rel = _safe(f[len(prefix):] if f.startswith(prefix) else str(Path(f).relative_to(project)))
        for i, l in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
            if rx.search(l) and not sink.add(rel, i, l):
                return sink.hits, sink.cut
    return sink.hits, sink.cut


def _rg_text(d: dict) -> str:
    """Text of a ripgrep JSON field: {"text": ...} or, for bytes that are not UTF-8, {"bytes": base64}."""
    if "text" in d:
        return d["text"]
    return base64.b64decode(d["bytes"]).decode("utf-8", "replace")


def _scan_rg(root: Path, name: str, project: Path, is_def=None) -> tuple[list[tuple[str, int, str]], str] | None:
    cmd = ["rg", "--json", "-w", "-F", "--no-config", "--no-require-git", "--no-ignore-global", "--no-ignore-exclude", "--no-ignore-dot",
           "--max-filesize", "1M", "-g", "!*.map", "-g", "!*.min.*", "-g", "!*.lock", "-g", "!*-lock.json"]
    for d in sorted(SKIP_DIRS):
        cmd += ["-g", f"!{d}"]
    cmd += ["--", name, str(root)]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", cwd=project)
    except OSError:
        return None
    rx, sink, prefix = _word_rx(name), _Sink(is_def), str(project) + os.sep
    try:
        for raw in proc.stdout:
            if '"type":"match"' not in raw[:20]:
                continue
            try:
                d = json.loads(raw)["data"]
                pd = d["path"]
                path = pd["text"] if "text" in pd else os.fsdecode(base64.b64decode(pd["bytes"]))
                text, no = _rg_text(d["lines"]).rstrip("\r\n"), d["line_number"]
            except (ValueError, KeyError):
                continue
            if not rx.search(text):
                continue
            if path.startswith(prefix):
                rel = path[len(prefix):]
            else:
                try:
                    rel = str(Path(path).resolve().relative_to(project))
                except ValueError:
                    rel = path
            if not sink.add(_safe(rel), no, text):
                break
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
        proc.wait()
    if proc.returncode not in (0, 1, -9) and not sink.hits:
        return None
    return sink.hits, sink.cut


_ASSIGN_SHAPE = re.compile(r"^\s*[\w$.#]+\s*(?::[^=]+)?=(?![=>])")
_CONTEXT_MAX = 2000


def _continued(project: Path, defs: list) -> set[tuple[str, int]]:
    """(file, line) of assignment-shaped definitions that sit inside an open call or list, i.e. the previous code line
    ends with '(' or ','. They are keyword arguments or default values, not definitions."""
    cand = [d for d in defs if d[3] in ("variable", "function") and _ASSIGN_SHAPE.match(d[2]) and not d[2].rstrip().endswith(";")]
    if not cand or len(cand) > _CONTEXT_MAX:
        return set()
    drop, cur, lines = set(), "", []
    for rel, no, text, _ in sorted(cand, key=lambda d: (d[0], d[1])):
        if rel != cur:
            cur = rel
            try:
                lines = (project / rel).read_bytes().decode("utf-8", "replace").splitlines()
            except OSError:
                lines = []
        prev = next((l.strip() for l in reversed(lines[:no - 1]) if l.strip()), "")
        if prev.endswith(("(", ",")):
            drop.add((rel, no))
    return drop


def _find(ctx, name: str, path: str, kind: str, use_rg: bool | None = None) -> str:
    name = (name or "").strip()
    if not name or re.search(r"\s", name):
        raise ToolError("name must be a single identifier, e.g. 'parse_config' or 'Ctx'. Use Grep to search for other text.")
    kind = (kind or "any").strip().lower()
    kind = {"def": "definition", "definitions": "definition", "use": "usage", "usages": "usage", "def_only": "definition"}.get(kind, kind)
    if kind not in KINDS:
        raise ToolError(f"kind must be one of: {', '.join(KINDS)}")
    root = ctx.path(path or ".")
    if not root.exists():
        raise ToolError(f"{path} does not exist")
    pats_by_ext: dict[str, list] = {}

    def category(rel: str, text: str) -> str | None:
        ext = os.path.splitext(rel)[1].lower()
        if ext not in pats_by_ext:
            pats_by_ext[ext] = _def_patterns(name, ext)
        return _classify(text, name, ext, pats_by_ext[ext])

    is_def = lambda rel, no, text: category(rel, text) is not None
    res = None
    if use_rg is not False and shutil.which("rg"):
        res = _scan_rg(root, name, ctx.root, is_def)
    if res is None:
        res = _scan_py(root, name, ctx.root, is_def)
    hits, cut = res
    hits = sorted(set(hits), key=lambda h: (h[0], h[1]))
    defs, uses = [], []
    for rel, no, text in hits:
        cat = category(rel, text)
        (defs if cat else uses).append((rel, no, text, cat))
    demoted = _continued(ctx.root, defs)
    if demoted:
        uses = sorted(uses + [(r, n, t, None) for r, n, t, _ in defs if (r, n) in demoted], key=lambda h: (h[0], h[1]))
        defs = [d for d in defs if (d[0], d[1]) not in demoted]
    all_defs, all_uses = defs, uses
    if kind in ("function", "class", "type", "variable"):
        defs, uses = [d for d in defs if d[3] == kind], []
    elif kind == "definition":
        uses = []
    elif kind == "usage":
        defs = []
    ctx.meta = {"definitions": len(defs), "usages": len(uses), "files": len({h[0] for h in defs + uses})}
    note = {"usages": f"scan stopped collecting usages after {SCAN_LIMIT} matches; all definitions were kept",
            "all": f"scan stopped after {SCAN_HARD} matches; the rest of the project was not searched"}.get(cut, "")
    where = path if path not in ("", ".") else "the project"
    if not defs and not uses:
        if all_defs or all_uses:
            cats = ", ".join(f"{k}: {c}" for k, c in Counter(d[3] for d in all_defs).most_common())
            msg = (f"'{name}' occurs in {where} but none of it is kind={kind}: {len(all_defs)} definitions" + (f" ({cats})" if cats else "") +
                   f" and {len(all_uses)} usages. Use kind=any, definition or usage to see them.")
        else:
            msg = f"No whole-word matches for '{name}' in {where}" + (f" with kind={kind}" if kind != "any" else "") + \
                  ". Matching is case-sensitive; use Grep for partial matches."
        return msg + (f" ({note})" if note else "")
    shown_d, shown_u = defs[:MAX_RESULTS], uses[: max(0, MAX_RESULTS - len(defs[:MAX_RESULTS]))]
    out = [f"'{name}': {len(defs)} definitions, {len(uses)} usages in {len({h[0] for h in defs + uses})} files" + (f" ({note})" if note else "")]
    if shown_d:
        out.append("Definitions:")
        out += [f"  {rel}:{no}  [{cat}]  {_clipl(text.strip(), 140)}" for rel, no, text, cat in shown_d]
    if shown_u:
        per_file = Counter(u[0] for u in uses)
        out.append("Usages:")
        cur = ""
        for rel, no, text, _ in shown_u:
            if rel != cur:
                cur = rel
                out.append(f"  {rel} ({per_file[rel]})")
            out.append(f"    {no}: {_clipl(text.strip(), 140)}")
    cut_d, cut_u = len(defs) - len(shown_d), len(uses) - len(shown_u)
    if cut_d or cut_u:
        parts = ([f"{cut_d} definitions"] if cut_d else []) + ([f"{cut_u} usages"] if cut_u else [])
        out.append(f"... {' and '.join(parts)} not shown. Narrow with path=<directory or file> or kind=definition.")
    return "\n".join(out)


async def FindSymbol(ctx, name, path=".", kind="any"):
    return await asyncio.to_thread(_find, ctx, name, path, kind)


# ------------------------------------------------------------------ registry

def _spec(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


S, B = {"type": "string"}, {"type": "boolean"}
_p = lambda t, d: {**t, "description": d}

TOOLS = {
    "MultiEdit": ("write", MultiEdit, _spec("MultiEdit",
        "Make several exact-text replacements in ONE file in a single call. Edits run in order; if any edit fails, nothing is written. "
        "Each old_string must be unique in the file unless replace_all is true. Use it instead of repeated Edit calls on the same file.",
        {"file_path": _p(S, "path of the file"),
         "edits": {"type": "array", "description": "list of edits, applied in order",
                   "items": {"type": "object", "properties": {
                       "old_string": _p(S, "existing text, exact"), "new_string": _p(S, "replacement"),
                       "replace_all": _p(B, "replace every occurrence")}, "required": ["old_string", "new_string"]}}},
        ["file_path", "edits"])),
    "Outline": ("read", Outline, _spec("Outline",
        "List the symbols of a file with line numbers (classes, functions, methods, headings, element ids, keys, selectors) without reading it. "
        "Use it first on a big file, then Read only the line range you need. Works for Python, JS/TS, Markdown, HTML, JSON, CSS.",
        {"file_path": _p(S, "path of the file")}, ["file_path"])),
    "FindSymbol": ("read", FindSymbol, _spec("FindSymbol",
        "Find where a function, class or variable is DEFINED and where it is USED in the project (whole word, case-sensitive). "
        "Definitions come first, then usages by file. Use it before changing or renaming something.",
        {"name": _p(S, "the identifier, e.g. parse_config"), "path": _p(S, "directory or file to search, default ."),
         "kind": {"type": "string", "enum": list(KINDS), "description": "any (default), definition, usage, or a definition type"}},
        ["name"])),
}
