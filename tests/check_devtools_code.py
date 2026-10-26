"""Tests for dogear/devtools_code.py (MultiEdit, Outline, FindSymbol). usage: uv run python tests/check_devtools_code.py"""
import asyncio
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# dogear.tools must not import devtools_code (the agent registers it), so either import order works.
from dogear import devtools_code as dc
from dogear.tools import Ctx, ToolError, Read

REPO = Path(__file__).resolve().parent.parent
RESULTS: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {detail}"))


def raises(fn, *a, **kw) -> str | None:
    try:
        fn(*a, **kw)
    except ToolError as e:
        return str(e)
    return None


def lineno(text: str, needle: str) -> int:
    for i, l in enumerate(text.splitlines(), 1):
        if needle in l:
            return i
    raise AssertionError(f"{needle!r} not in text")


def row(out: str, needle: str) -> str:
    return next((l for l in out.splitlines() if needle in l), "")


def start_of(out: str, needle: str) -> int:
    m = re.match(r"\s*(\d+)", row(out, needle))
    return int(m.group(1)) if m else -1


def depth_of(out: str, needle: str) -> int:
    r = row(out, needle)
    body = r[10:]
    return (len(body) - len(body.lstrip())) // 2


def mk(root: Path, rel: str, content: str | bytes) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return p


# ------------------------------------------------------------------ MultiEdit

def test_multiedit(root: Path) -> None:
    ctx = Ctx(root)
    src = "alpha = 1\nbeta = 2\ndef f():\n    return alpha + beta\n\nprint(alpha)\nprint(alpha)\n"
    p = mk(root, "m.py", src)
    out = dc.multi_edit(ctx, "m.py", [
        {"old_string": "alpha = 1", "new_string": "alpha = 10"},
        {"old_string": "return alpha + beta", "new_string": "return alpha * beta"},
        {"old_string": "print(alpha)", "new_string": "print(alpha, beta)", "replace_all": True},
        {"old_string": "alpha = 10", "new_string": "alpha = 11"},                 # depends on edit 0
    ])
    want = "alpha = 11\nbeta = 2\ndef f():\n    return alpha * beta\n\nprint(alpha, beta)\nprint(alpha, beta)\n"
    check("multiedit applies all edits in order", p.read_text() == want, repr(p.read_text()))
    check("multiedit result string", re.fullmatch(r"Updated m\.py \(4 edits, \+\d+ -\d+\)", out) is not None, out)
    check("multiedit fills ctx.meta", set(ctx.meta) >= {"path", "diff", "new_text"} and ctx.meta["new_text"] == want
          and ctx.meta["path"] == "m.py" and ctx.meta["diff"]["added"] >= 1 and isinstance(ctx.meta["diff"]["hunks"], list), str(ctx.meta)[:200])
    check("multiedit leaves no temp files", [f.name for f in root.iterdir() if f.name.endswith(".tmp")] == [])


def test_multiedit_failure(root: Path) -> None:
    ctx = Ctx(root)
    src = "one\ntwo\nthree\ntwo\n"
    p = mk(root, "f.txt", src)
    before = p.read_bytes()
    err = raises(dc.multi_edit, ctx, "f.txt", [
        {"old_string": "one", "new_string": "1"},
        {"old_string": "three", "new_string": "3"},
        {"old_string": "does not exist", "new_string": "x"},
    ])
    check("partial failure: error names the edit index", err is not None and "edits[2]" in err and "not found" in err, str(err))
    check("partial failure: file untouched", p.read_bytes() == before)
    check("partial failure: no temp files", [f.name for f in root.iterdir() if f.name.endswith(".tmp")] == [])

    err = raises(dc.multi_edit, ctx, "f.txt", [{"old_string": "two", "new_string": "2"}])
    check("ambiguous old_string needs replace_all", err is not None and "edits[0]" in err and "2 times" in err and "lines 2, 4" in err, str(err))
    check("ambiguous failure leaves file untouched", p.read_bytes() == before)

    err = raises(dc.multi_edit, ctx, "f.txt", [{"old_string": "one", "new_string": "1"}, {"old_string": "1", "new_string": "uno"},
                                               {"old_string": "one", "new_string": "x"}])
    check("edit consumed by an earlier edit gives a hint", err is not None and "edits[2]" in err and "earlier edit" in err, str(err))

    err = raises(dc.multi_edit, ctx, "f.txt", [{"old_string": "", "new_string": "x"}])
    check("empty old_string rejected", err is not None and "edits[0]" in err and "empty" in err, str(err))
    err = raises(dc.multi_edit, ctx, "f.txt", [{"old_string": "one", "new_string": "one"}])
    check("identical old/new rejected", err is not None and "identical" in err, str(err))
    err = raises(dc.multi_edit, ctx, "f.txt", [])
    check("empty edit list rejected", err is not None and "non-empty" in err, str(err))
    err = raises(dc.multi_edit, ctx, "f.txt", [{"old_string": "one"}])
    check("missing new_string rejected", err is not None and "edits[0]" in err, str(err))
    err = raises(dc.multi_edit, ctx, "nope.txt", [{"old_string": "a", "new_string": "b"}])
    check("missing file rejected", err is not None and "does not exist" in err, str(err))
    err = raises(dc.multi_edit, ctx, "/etc/hostname", [{"old_string": "a", "new_string": "b"}])
    check("path outside project rejected", err is not None, str(err))
    out = dc.multi_edit(ctx, "f.txt", '[{"old_string": "one", "new_string": "1"}]')
    check("edits given as a JSON string are accepted", out.startswith("Updated f.txt (1 edits") and p.read_text().startswith("1\n"), out)
    err = raises(dc.multi_edit, ctx, "f.txt", [{"old_string": "t  w  o", "new_string": "x"}])
    check("whitespace-only mismatch is reported", err is not None and "not found" in err, str(err))
    mk(root, "bin.dat", b"\x00\x01\x02binary")
    err = raises(dc.multi_edit, ctx, "bin.dat", [{"old_string": "a", "new_string": "b"}])
    check("binary file rejected", err is not None and "binary" in err, str(err))
    mk(root, "latin.txt", "caf\xe9\n".encode("latin-1"))
    err = raises(dc.multi_edit, ctx, "latin.txt", [{"old_string": "a", "new_string": "b"}])
    check("non-UTF-8 file rejected", err is not None and "UTF-8" in err, str(err))


def test_multiedit_unicode(root: Path) -> None:
    ctx = Ctx(root)
    src = "# Grüße aus Köln\nname = 'Zoë'\nemoji = '🎉'\ncjk = '日本語のテキスト'\n"
    p = mk(root, "u.py", src)
    out = dc.multi_edit(ctx, "u.py", [
        {"old_string": "Zoë", "new_string": "Zoé 🌍"},
        {"old_string": "日本語のテキスト", "new_string": "中文文本 — ok"},
        {"old_string": "Grüße", "new_string": "Straße"},
    ])
    want = "# Straße aus Köln\nname = 'Zoé 🌍'\nemoji = '🎉'\ncjk = '中文文本 — ok'\n"
    check("unicode content round-trips", p.read_bytes() == want.encode("utf-8"), p.read_text())
    check("unicode result line", out.startswith("Updated u.py (3 edits"), out)
    bom = mk(root, "bom.txt", "﻿hello wörld\n")
    dc.multi_edit(ctx, "bom.txt", [{"old_string": "hello", "new_string": "hi"}])
    check("UTF-8 BOM is preserved", bom.read_bytes() == "﻿hi wörld\n".encode("utf-8"), repr(bom.read_bytes()))


def test_multiedit_eol(root: Path) -> None:
    ctx = Ctx(root)
    p = mk(root, "w.txt", b"line one\r\nline two\r\nline three\r\n")
    out = dc.multi_edit(ctx, "w.txt", [
        {"old_string": "line one\nline two", "new_string": "first\nsecond\ninserted"},      # model writes plain \n
        {"old_string": "three", "new_string": "3"},
    ])
    want = b"first\r\nsecond\r\ninserted\r\nline 3\r\n"
    check("CRLF file keeps CRLF line endings", p.read_bytes() == want, repr(p.read_bytes()))
    check("CRLF edit counted", "(2 edits" in out, out)
    q = mk(root, "lf.txt", "a\nb\nc")
    dc.multi_edit(ctx, "lf.txt", [{"old_string": "b\nc", "new_string": "B\nC"}])
    check("LF file without trailing newline stays as is", q.read_bytes() == b"a\nB\nC", repr(q.read_bytes()))
    r = mk(root, "mixed.txt", b"a\r\nb\nc\r\n")
    dc.multi_edit(ctx, "mixed.txt", [{"old_string": "b", "new_string": "B"}])
    check("mixed line endings are not rewritten", r.read_bytes() == b"a\r\nB\nc\r\n", repr(r.read_bytes()))


def test_multiedit_mode(root: Path) -> None:
    ctx = Ctx(root)
    p = mk(root, "run.sh", "#!/bin/sh\necho hi\n")
    p.chmod(0o755)
    dc.multi_edit(ctx, "run.sh", [{"old_string": "hi", "new_string": "there"}])
    check("file mode is preserved", stat.S_IMODE(p.stat().st_mode) == 0o755 and "there" in p.read_text(), oct(p.stat().st_mode))


# ------------------------------------------------------------------ Outline

PY_SRC = '''"""Sample module for the outline test."""
import os
from dataclasses import dataclass

VERSION = "1.2.3"
LIMITS: dict[str, int] = {"a": 1}


def helper(a, b=2, *args, **kw) -> int:
    """Add things up."""
    def inner(x):
        return x
    return a + b


@dataclass
class Config:
    """Settings."""
    DEFAULT = 5
    name: str = "x"

    def load(self, path: str) -> "Config":
        return self

    @staticmethod
    def make() -> "Config":
        return Config()

    class Nested:
        LEVEL = 2

        async def deep(self, n: int):
            return n

        class Deeper:
            def leaf(self):
                pass


class Base(Config, metaclass=type):
    @property
    def size(self):
        return 1

    @app.get("/items/{id}")
    async def handler(self, id: int, q: str = "") -> dict:
        return {}


async def main():
    pass


if __name__ == "__main__":
    result = main()
'''


def test_outline_python(root: Path) -> None:
    ctx = Ctx(root)
    mk(root, "sample.py", PY_SRC)
    out = dc.outline(ctx, "sample.py")
    check("py: header", out.startswith("sample.py: py, ") and "Sample module" in out, out[:120])
    check("py: top-level function with signature and return", "def helper(a, b=2, *args, **kw) -> int" in row(out, "def helper"), row(out, "def helper"))
    check("py: function line range", re.match(rf"\s*{lineno(PY_SRC, 'def helper')}-{lineno(PY_SRC, 'return a + b')}\s", row(out, "def helper")) is not None, row(out, "def helper"))
    check("py: nested function is shown deeper", row(out, "def inner").index("def") > row(out, "def helper").index("def"), row(out, "def inner"))
    check("py: decorated class starts at decorator line", start_of(out, "class Config") == lineno(PY_SRC, "@dataclass") and "@dataclass" in row(out, "class Config"),
          row(out, "class Config"))
    check("py: class bases and keywords", "class Base(Config, metaclass=type)" in out, out)
    check("py: method signature", "def load(self, path: str) -> 'Config'" in out, row(out, "def load"))
    check("py: staticmethod decorator", "@staticmethod def make() -> 'Config'" in row(out, "def make"), row(out, "def make"))
    check("py: nested class and deeper nesting",
          [depth_of(out, n) for n in ("class Config", "class Nested", "class Deeper", "def leaf")] == [0, 1, 2, 3], out)
    check("py: async method", "async def deep(self, n: int)" in out and start_of(out, "async def deep") == lineno(PY_SRC, "async def deep"), row(out, "deep"))
    check("py: decorated async method with route decorator",
          '@app.get(\'/items/{id}\') async def handler(self, id: int, q: str=\'\') -> dict' in row(out, "handler") and
          start_of(out, "async def handler") == lineno(PY_SRC, '@app.get'), row(out, "handler"))
    check("py: property decorator", "@property def size(self)" in row(out, "def size"), row(out, "def size"))
    check("py: top-level async function", re.match(r"\s*\d+-\d+\s+async def main\(\)", row(out, "async def main")) is not None, row(out, "async def main"))
    check("py: top-level constants", "VERSION = '1.2.3'" in out and "LIMITS: dict[str, int] =" in out, out)
    check("py: class-level constant but not instance-like fields", "DEFAULT = 5" in out and "LEVEL = 2" in out and "name: str" not in out, out)
    check("py: __main__ block", "if __name__ == '__main__'" in out and "result =" not in out, out)
    check("py: docstring first line", "# Add things up." in row(out, "def helper"), row(out, "def helper"))
    check("py: imports are not listed", "import os" not in out, out)
    broken = mk(root, "broken.py", "def ok(a):\n    return a\n\nclass Half(:\n    def m(self): pass\n")
    out = dc.outline(ctx, "broken.py")
    check("py: syntax error falls back to regex", "syntax error" in out and "def ok" in out and "def m" in out, out)


def test_outline_real_python(root: Path) -> None:
    ctx = Ctx(REPO)
    text = (REPO / "dogear" / "tools.py").read_text()
    out = dc.outline(ctx, "dogear/tools.py")
    ok = all(start_of(out, needle) == lineno(text, needle) for needle in
             ("def make_diff(", "class Ctx", "class Procs", "def Read(", "def Edit(", "async def Bash("))
    check("real py: top-level symbols have the right line numbers", ok, "\n".join(row(out, n) for n in ("make_diff", "class Ctx", "def Read(", "def Edit(")))
    check("real py: methods nested under their class", row(out, "def path(self").index("def") > row(out, "class Ctx").index("class")
          and start_of(out, "def path(self") > start_of(out, "class Ctx"), row(out, "def path(self"))
    check("real py: async function marked", "async def Grep(ctx, pattern, path='.', glob='')" in out, row(out, "Grep"))
    check("real py: at most 200 entries", len(out.splitlines()) <= 202, str(len(out.splitlines())))


def test_outline_js(root: Path) -> None:
    ctx = Ctx(root)
    src = '''// helpers
import { x } from "./x.js";
export const API = "/api";
const PI = 3.14;

export function greet(name) {
  if (name) {
    return "hi " + name;
  }
  return "hi";
}

async function load(url, opts = {}) {
  const res = await fetch(url);
  return res.json();
}

const add = (a, b) => a + b;
export const handler = async (req, res) => {
  const inner = () => 1;
  res.send("ok");
};

class Widget extends Base {
  constructor(el) {
    super();
    this.el = el;
  }

  async render(props) {
    for (const p of props) {
      console.log(p);
    }
  }

  static create() {
    return new Widget();
  }

  onClick = (e) => {
    e.stop();
  };
}

interface User { id: number }
export type Id = string | number;

app.get("/users/:id", (req, res) => {
  res.json({});
});

module.exports = { greet, load };
export default Widget;
'''
    mk(root, "app.js", src)
    out = dc.outline(ctx, "app.js")
    check("js: header", out.startswith("app.js: js, "), out[:60])
    check("js: function with range", re.match(r"\s*6-11\s+export function greet\(name\)", row(out, "function greet")) is not None, row(out, "function greet"))
    check("js: async function", "async function load(url, opts = {})" in out and start_of(out, "async function load") == lineno(src, "async function load"), row(out, "load"))
    check("js: const arrow", "const add = (a, b) =>" in out and start_of(out, "const add") == lineno(src, "const add"), row(out, "const add"))
    check("js: exported async arrow", "export const handler = async (req, res) =>" in out, row(out, "handler"))
    check("js: class", start_of(out, "class Widget extends Base") == lineno(src, "class Widget"), row(out, "class Widget"))
    check("js: class methods nested under class", all(row(out, m).index(m) > row(out, "class Widget").index("class") for m in
                                                    ("constructor(el)", "async render(props)", "static create()")), out)
    check("js: method line number", start_of(out, "async render") == lineno(src, "async render"), row(out, "render"))
    check("js: arrow class property", "onClick = (e) =>" in out, out)
    check("js: control flow is not a symbol", "if (name)" not in out and "for (const p" not in out, out)
    check("js: nested arrow inside function not listed", "const inner" not in out, out)
    check("js: interface and type", "interface User" in out and "export type Id" in out, out)
    check("js: express route", 'app.get("/users/:id"' in out, out)
    check("js: exports", "module.exports" in out and "export default Widget" in out, out)
    check("js: top-level constants", 'export const API = "/api"' in out and "const PI = 3.14" in out, out)
    ts = mk(root, "svc.ts", "export class Svc<T> {\n  private items: T[] = [];\n  public async get(id: number): Promise<T | undefined> {\n    return this.items[id];\n  }\n}\n"
                            "export enum Mode { A, B }\nexport const run = (n: number): number => n * 2;\n")
    out = dc.outline(ctx, "svc.ts")
    check("ts: generics, typed methods, enum, typed arrow",
          "export class Svc<T>" in out and "public async get(id: number): Promise<T | undefined>" in out and "export enum Mode" in out
          and "export const run = (n: number): number =>" in out, out)


def test_outline_markdown(root: Path) -> None:
    ctx = Ctx(root)
    src = '''# Project

Intro text.

## Install

```bash
# not a heading
npm install
```

## Usage
### CLI
text

### API
more

Setext Title
============

- list item
'''
    mk(root, "README.md", src)
    out = dc.outline(ctx, "README.md")
    check("md: headings with line numbers", start_of(out, "# Project") == 1 and start_of(out, "## Install") == lineno(src, "## Install")
          and start_of(out, "### CLI") == lineno(src, "### CLI"), out)
    check("md: code fence content is ignored", "not a heading" not in out, out)
    check("md: section ranges", re.match(r"\s*1-\d+\s+# Project", row(out, "# Project")) is not None
          and re.match(rf"\s*{lineno(src, '## Usage')}-{lineno(src, 'more')}\s", row(out, "## Usage")) is not None, out)
    check("md: setext heading", "# Setext Title" in out, out)
    check("md: nesting indent", row(out, "### CLI").index("###") > row(out, "## Usage").index("##") > row(out, "# Project").index("#"), out)
    fm = mk(root, "post.md", "---\ntitle: Hello\ntags: [a]\n---\n# Body\ntext\n")
    out = dc.outline(ctx, "post.md")
    check("md: front matter is not a heading", "front matter" in out and "# Body" in out and "title: Hello" not in out, out)


def test_outline_html(root: Path) -> None:
    ctx = Ctx(root)
    src = '''<!doctype html>
<html>
<head>
  <title>Todo App</title>
  <style>
    body { margin: 0; }
    .card { padding: 8px; }
    @media (max-width: 600px) {
      .card { padding: 4px; }
    }
  </style>
</head>
<body>
  <header id="top"><h1>My Todos</h1></header>
  <main id="app">
    <h2 id="list-title">Open items</h2>
    <button id="add-btn">Add</button>
  </main>
  <script src="vendor.js"></script>
  <script>
    function addTodo(text) {
      items.push(text);
    }
    const render = () => {
      document.getElementById("app");
    };
  </script>
</body>
</html>
'''
    mk(root, "index.html", src)
    out = dc.outline(ctx, "index.html")
    check("html: title", "title: Todo App" in out and start_of(out, "title:") == 4, out)
    check("html: headings", "h1: My Todos" in out and "h2: Open items" in out, out)
    check("html: ids of major elements", '<header id="top">' in out and '<main id="app">' in out and '<button id="add-btn">' in out, out)
    check("html: inline script block range", re.match(rf"\s*{lineno(src, '<script>')}-{len(src.splitlines()) - 2}\s+<script> inline", row(out, "<script> inline")) is not None,
          row(out, "inline"))
    check("html: external script", '<script src="vendor.js">' in out, out)
    check("html: style block range", re.match(rf"\s*{lineno(src, '<style>')}-{lineno(src, '</style>')}\s+<style> inline", row(out, "<style> inline")) is not None, row(out, "<style>"))
    check("html: functions inside the inline script with absolute line numbers",
          start_of(out, "function addTodo") == lineno(src, "function addTodo") and start_of(out, "const render") == lineno(src, "const render"), out)
    check("html: css selectors inside style with absolute line numbers", start_of(out, ".card { padding: 8px; }") == -1
          and start_of(out, "body") == lineno(src, "body { margin") and start_of(out, "@media") == lineno(src, "@media"), out)


def test_outline_json_css_other(root: Path) -> None:
    ctx = Ctx(root)
    pkg = '{\n  "name": "demo",\n  "version": "1.0.0",\n  "scripts": {\n    "build": "x",\n    "test": "y"\n  },\n  "dependencies": {},\n  "files": ["a", "b"],\n  "private": true\n}\n'
    mk(root, "package.json", pkg)
    out = dc.outline(ctx, "package.json")
    check("json: top-level keys with line numbers", start_of(out, '"name"') == 2 and start_of(out, '"scripts"') == 4 and start_of(out, '"private"') == 10, out)
    check("json: value summaries", 'object (2 keys): build, test' in out and "array (2 items)" in out and 'string "demo"' in out and "true" in out, out)
    mk(root, "bad.json", '{"a": 1,,}\n')
    out = dc.outline(ctx, "bad.json")
    check("json: invalid file falls back to first lines", "could not parse" in out and '{"a": 1,,}' in out, out)
    mk(root, "arr.json", "[{\"id\": 1}, {\"id\": 2}]")
    check("json: array root", "array of 2 items" in dc.outline(ctx, "arr.json"))

    css = '''/* theme */
:root {
  --bg: #fff;
}

.btn, .btn-primary {
  color: red;
}

@media (max-width: 600px) {
  .btn {
    padding: 0;
  }
}

@keyframes spin {
  from { transform: none; }
  to { transform: rotate(1turn); }
}
'''
    mk(root, "site.css", css)
    out = dc.outline(ctx, "site.css")
    check("css: selectors with line numbers", start_of(out, ":root") == 2 and start_of(out, ".btn, .btn-primary") == 6 and start_of(out, "@media") == 10, out)
    check("css: ranges and nesting", re.match(r"\s*6-8\s", row(out, ".btn, .btn-primary")) is not None
          and start_of(out, ".btn") > 0 and [l for l in out.splitlines() if l.rstrip().endswith(".btn")][0].index(".btn") > row(out, "@media").index("@media"), out)
    check("css: keyframes steps are skipped", "@keyframes spin" in out and "from" not in out and "rotate" not in out, out)

    txt = "\n\n".join(f"line {i}" for i in range(1, 100))
    mk(root, "notes.txt", txt)
    out = dc.outline(ctx, "notes.txt")
    body = out.splitlines()
    check("unknown type: first 40 non-empty lines", out.startswith("notes.txt: text, ") and sum(1 for l in body if re.search(r"line \d+$", l)) == 40 and "line 41" not in out, out[:200])

    big = "\n".join(f"def fn_{i}():\n    pass\n" for i in range(300))
    mk(root, "big.py", big)
    out = dc.outline(ctx, "big.py")
    check("cap: output limited to 200 entries with a note", len(out.splitlines()) == 1 + 200 + 1 and "100 more entries not shown" in out, f"{len(out.splitlines())} lines; tail={out.splitlines()[-1]!r}")

    mk(root, "blob.bin", b"\x00\x01\x02" * 10)
    err = raises(dc.outline, ctx, "blob.bin")
    check("outline: binary file rejected", err is not None and "binary" in err, str(err))
    err = raises(dc.outline, ctx, ".")
    check("outline: directory rejected", err is not None and "not a file" in err, str(err))
    mk(root, "empty.py", "")
    check("outline: empty python file does not crash", "empty.py: py, 0 lines" in dc.outline(ctx, "empty.py"))


# ------------------------------------------------------------------ FindSymbol

def find(ctx, name, path=".", kind="any") -> str:
    return asyncio.run(dc.FindSymbol(ctx, name, path, kind))


def test_classify() -> None:
    cases = [
        ("def foo(x):", "foo", ".py", "function"), ("async def foo(x):", "foo", ".py", "function"), ("    def foo(self):", "foo", ".py", "function"),
        ("class Foo(Base):", "Foo", ".py", "class"), ("foo = 3", "foo", ".py", "variable"), ("    foo: int = 3", "foo", ".py", "variable"),
        ("foo = lambda x: x", "foo", ".py", "function"), ("    foo: int", "foo", ".py", "variable"),
        ("x = foo(1)", "foo", ".py", None), ("print(foo)", "foo", ".py", None), ("from m import foo", "foo", ".py", None),
        ("# def foo(x):", "foo", ".py", None), ("if foo == 3:", "foo", ".py", None), ("bar(foo=1,", "foo", ".py", None), ("    foo=1,", "foo", ".py", None),
        ("function foo(a) {", "foo", ".js", "function"), ("export async function foo() {", "foo", ".js", "function"),
        ("const foo = () => 1;", "foo", ".js", "function"), ("let foo = 5;", "foo", ".js", "variable"), ("var foo;", "foo", ".js", "variable"),
        ("const foo = function() {", "foo", ".js", "function"), ("export const foo: Foo = (a) => a;", "foo", ".ts", "function"),
        ("class Foo extends Bar {", "Foo", ".js", "class"), ("  foo(a, b) {", "foo", ".js", "function"), ("  async foo() {", "foo", ".js", "function"),
        ("  foo: function() {", "foo", ".js", "function"), ("foo();", "foo", ".js", None), ("new Foo()", "Foo", ".js", None),
        ("interface Foo {", "Foo", ".ts", "type"), ("export type Foo = string;", "Foo", ".ts", "type"), ("enum Foo { A }", "Foo", ".ts", "type"),
        ("if (foo) {", "foo", ".js", None), ("while (foo(x)) {", "foo", ".js", None),
        ("func foo(a int) int {", "foo", ".go", "function"), ("func (s *Server) Foo() error {", "Foo", ".go", "function"),
        ("type Foo struct {", "Foo", ".go", "type"), ("foo := 3", "foo", ".go", None),
        ("fn foo(x: i32) -> i32 {", "foo", ".rs", "function"), ("pub fn foo() {", "foo", ".rs", "function"), ("pub struct Foo {", "Foo", ".rs", "class"),
        ("let mut foo = 1;", "foo", ".rs", "variable"), ("    foo: String,", "foo", ".rs", "variable"), ("trait Foo {", "Foo", ".rs", "class"),
        ("int foo(int a) {", "foo", ".c", "function"), ("static void foo(void)", "foo", ".c", "function"), ("    return foo(3);", "foo", ".c", None),
        ("    x = foo(3);", "foo", ".c", None), ("#define FOO 1", "FOO", ".h", "macro"), ("struct foo {", "foo", ".c", "class"),
        ("public static void foo(String a) {", "foo", ".java", "function"), ("    else foo(1)", "foo", ".java", None),
        (".card {", "card", ".css", "selector"), ("  .nav .card:hover, ", "card", ".css", "selector"), ("--card: 3px;", "card", ".css", "variable"),
        ('<div id="card">', "card", ".html", "id"), ("document.getElementById('card')", "card", ".js", None),
        ("def foo", "foo", ".rb", "function"), ("Use def foo(x) to define it.", "foo", ".md", None),
        (".card { color: red; }", "card", ".css", "selector"), ("#hero { }", "hero", ".css", "selector"), ("  color: #fff;", "fff", ".css", None),
        ("a { color: #fff }", "fff", ".css", None),
        ("int name = 5;", "name", ".c", "variable"), ('String name = "x";', "name", ".java", "variable"), ("auto name = 5;", "name", ".cpp", "variable"),
        ("    return name;", "name", ".c", None), ("    x = a * name;", "name", ".c", None), ("  else name = 3;", "name", ".c", None),
        ("  def self.name(x)", "name", ".rb", "function"), ("def Klass.name(x)", "name", ".rb", "function"),
        ("impl Name {", "Name", ".rs", "impl"), ("impl<T> Trait for Name<T> {", "Name", ".rs", "impl"), ("let x = Name::new();", "Name", ".rs", None),
        ("Foo.prototype.name = function() {", "name", ".js", "function"), ("exports.name = function(a) {", "name", ".js", "function"),
        ("module.exports.name = 5;", "name", ".js", "variable"),
        ("    check=True)", "check", ".py", None), ("    name: value,", "name", ".ts", None), ("  name: string;", "name", ".ts", "variable"),
        ("  name?: Foo[];", "name", ".ts", "variable"), ("    name: this.value,", "name", ".ts", None),
    ]
    bad = []
    for line, name, ext, want in cases:
        got = dc._classify(line, name, ext)
        if got != want:
            bad.append(f"{line!r} ({ext}) -> {got}, want {want}")
    check(f"classify: {len(cases)} definition/usage lines", not bad, "; ".join(bad))


SYMBOL_FILES = {
    "src/a.py": "def foo(x):\n    return x\n\n\nclass Foo:\n    pass\n\n\nfoobar = 2\nmy_foo = foo(1)\nprint(foo)\n# foo is great\nresult = foo(2) + foobar\nfoo2 = 5\n",
    "src/b.js": "function foo() {}\nconst foo2 = 1;\nconst bar = () => foo();\nlet $foo = 0;\nclass Holder {\n  foo(a) {\n    return a;\n  }\n}\n",
    "node_modules/pkg/index.js": "function foo() {}\nfoo();\n",
    "ignored/c.py": "def foo(): pass\n",
    ".gitignore": "ignored/\n*.log\n",
    "app.log": "foo foo foo\n",
    "README.md": "Call `foo` to start. def foo(x) is documented here.\n",
    "docs/notes.txt": "foo and foobar\n",
    "static/bundle.min.js": "function foo(){}foo();\n",
}


def test_findsymbol(root: Path) -> None:
    ctx = Ctx(root)
    for rel, content in SYMBOL_FILES.items():
        mk(root, rel, content)
    out = find(ctx, "foo")
    defs = out.split("Usages:")[0]
    uses = out.split("Usages:")[1] if "Usages:" in out else ""
    check("find: definitions listed first", out.index("Definitions:") < out.index("Usages:"), out)
    check("find: python function definition", "src/a.py:1  [function]" in defs, defs)
    check("find: js function definition", "src/b.js:1  [function]" in defs, defs)
    check("find: js method definition", "src/b.js:6  [function]" in defs, defs)
    check("find: usages are not in the definition block", "src/a.py:10" not in defs and "src/a.py:11" not in defs, defs)
    check("find: usages grouped by file with line numbers", "  src/a.py (" in uses and re.search(r"^\s+10: .*foo\(1\)", uses, re.M) is not None
          and re.search(r"^\s+11: print\(foo\)", uses, re.M) is not None and re.search(r"^\s+3: .*foo\(\)", uses, re.M) is not None, uses)
    check("find: comment mention is a usage", re.search(r"^\s+12: # foo is great", uses, re.M) is not None, uses)
    check("find: no substring matches (foobar, my_foo, foo2, $foo, Foo)",
          not re.search(r"^\s+9: ", uses, re.M) and "foo2 = 5" not in out and "const foo2" not in out and "let $foo" not in out
          and "class Foo" not in out and "my_foo =" not in uses.replace("my_foo = foo(1)", ""), out)
    check("find: line with foobar only on a mixed line is matched for foo", "result = foo(2) + foobar" in uses, uses)
    check("find: skips node_modules, .gitignore entries and minified files",
          "node_modules" not in out and "ignored/c.py" not in out and "app.log" not in out and "bundle.min.js" not in out, out)
    check("find: markdown prose is never a definition", "README.md" in uses and "README.md" not in defs, out)
    check("find: summary line counts", re.match(r"'foo': 3 definitions, \d+ usages in 4 files", out) is not None, out.splitlines()[0])

    out = find(ctx, "Foo")
    check("find: case-sensitive class definition", "src/a.py:5  [class]" in out and "foo" not in out.split("Definitions:")[1].split("Usages")[0], out)
    out = find(ctx, "foo", kind="definition")
    check("find: kind=definition has no usages", "Definitions:" in out and "Usages:" not in out, out)
    out = find(ctx, "foo", kind="usage")
    check("find: kind=usage has no definitions", "Usages:" in out and "Definitions:" not in out, out)
    out = find(ctx, "foo", kind="class")
    check("find: kind=class matches nothing for foo and says what exists",
          "none of it is kind=class" in out and "3 definitions (function: 3)" in out and "kind=any" in out, out)
    out = find(ctx, "foo", path="src/a.py")
    check("find: path can be a single file", "src/b.js" not in out and "src/a.py" in out, out)
    out = find(ctx, "foo", path="docs")
    check("find: path can be a directory", "docs/notes.txt" in out and "src/a.py" not in out, out)
    out = find(ctx, "nonexistent_symbol")
    check("find: no match message", out.startswith("No whole-word matches for 'nonexistent_symbol'"), out)
    err = raises(lambda: find(ctx, "two words"))
    check("find: multi-word name rejected", err is not None and "single identifier" in err, str(err))
    err = raises(lambda: find(ctx, "foo", kind="banana"))
    check("find: bad kind rejected", err is not None and "kind must be" in err, str(err))
    err = raises(lambda: find(ctx, "foo", path="missing_dir"))
    check("find: missing path rejected", err is not None and "does not exist" in err, str(err))
    find(ctx, "foo")
    check("find: ctx.meta filled", ctx.meta.get("definitions") == 3 and ctx.meta.get("usages", 0) > 0 and ctx.meta.get("files") == 4, str(ctx.meta))


def test_findsymbol_backends(root: Path) -> None:
    ctx = Ctx(root)
    for rel, content in SYMBOL_FILES.items():
        mk(root, rel, content)
    py_hits, _ = dc._scan_py(root, "foo", root)
    py = sorted(set(py_hits))
    if not dc.shutil.which("rg"):
        check("backends: ripgrep not installed, python fallback only", bool(py))
        return
    rg_res = dc._scan_rg(root, "foo", root)
    rg = sorted(set(rg_res[0])) if rg_res else None
    check("backends: ripgrep and python scan return identical hits", rg == py, f"rg={rg}\npy={py}")
    out_rg = dc._find(ctx, "foo", ".", "any", use_rg=True)
    out_py = dc._find(ctx, "foo", ".", "any", use_rg=False)
    check("backends: identical rendered output", out_rg == out_py, out_rg + "\n---\n" + out_py)
    mk(root, "sub/.gitignore", "secret.py\n")
    mk(root, "sub/secret.py", "def foo(): pass\n")
    mk(root, "sub/open.py", "def foo(): pass\n")
    a, b = dc._find(ctx, "foo", "sub", "any", use_rg=True), dc._find(ctx, "foo", "sub", "any", use_rg=False)
    check("backends: nested .gitignore respected by both", "secret.py" not in a and "open.py" in a and "secret.py" not in b and "open.py" in b, a + "\n---\n" + b)


def test_findsymbol_cap(root: Path) -> None:
    ctx = Ctx(root)
    mk(root, "def.py", "def target():\n    pass\n")
    for i in range(5):
        mk(root, f"use{i}.py", "".join(f"target()  # call {j}\n" for j in range(30)))
    out = find(ctx, "target")
    shown = len(re.findall(r"^\s+\d+: ", out, re.M)) + len(re.findall(r"\[function\]", out))
    check("cap: at most 60 results shown", shown == 60, f"shown={shown}")
    check("cap: reports what was cut", "91 usages not shown" in out and "1 definitions, 150 usages in 6 files" in out, out.splitlines()[0] + " ... " + out.splitlines()[-1])
    check("cap: definition still first", out.index("def.py:1") < out.index("use0.py"), out[:200])
    for i in range(70):
        mk(root, f"many/m{i:02d}.py", "def dup():\n    pass\n")
    out = find(ctx, "dup", path="many")
    check("cap: definitions are capped too", len(re.findall(r"\[function\]", out)) == 60 and "10 definitions not shown" in out, out[-200:])


# ------------------------------------------------------------------ regressions

def read_line_of(ctx, rel: str, needle: str) -> int:
    for l in Read(ctx, rel).splitlines():
        if needle in l:
            return int(l.split("\t")[0])
    raise AssertionError(f"{needle!r} not in Read output")


def test_import_order(root: Path) -> None:
    for code in ("from dogear import devtools_code", "import dogear.devtools_code as d; assert d.TOOLS",
                 "import dogear.tools; import dogear.devtools_code"):
        r = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True)
        check(f"import works standalone: {code[:45]}", r.returncode == 0, r.stderr[-200:])
    check("Outline, MultiEdit and FindSymbol are coroutine functions (they run off the event loop)",
          all(asyncio.iscoroutinefunction(dc.TOOLS[n][1]) for n in ("Outline", "MultiEdit", "FindSymbol")))


def test_find_definition_beyond_scan_limit(root: Path) -> None:
    ctx = Ctx(root)
    for i in range(30):
        for j in range(5):
            mk(root, f"d{i:02}/f{j}.py", "def run(x):\n    return helper(x)\n")
    mk(root, "zzz/defs.py", "def helper(x):\n    return x\n")
    old = dc.SCAN_LIMIT
    dc.SCAN_LIMIT = 40
    try:
        for rg in ([True, False] if dc.shutil.which("rg") else [False]):
            tag = "rg" if rg else "py"
            any_ = dc._find(ctx, "helper", ".", "any", use_rg=rg)
            check(f"{tag}: definition behind a cut usage list is found", "1 definitions" in any_ and "zzz/defs.py:1" in any_ and "scan stopped" in any_, any_[:300])
            only = dc._find(ctx, "helper", ".", "definition", use_rg=rg)
            check(f"{tag}: kind=definition finds it too", "zzz/defs.py:1  [function]" in only and "No whole-word" not in only, only[:300])
            none = dc._find(ctx, "helper", ".", "class", use_rg=rg)
            check(f"{tag}: the no-match message carries the scan-stopped notice", "scan stopped" in none and "kind=class" in none, none)
    finally:
        dc.SCAN_LIMIT = old


def test_find_kind_messages_and_context(root: Path) -> None:
    ctx = Ctx(root)
    mk(root, "m.py", "def only_def():\n    pass\nclass K: pass\n")
    out = find(ctx, "only_def", kind="usage")
    check("kind=usage on a symbol with only a definition says it exists", "1 definitions (function: 1)" in out and "kind=usage" in out and not out.startswith("No whole-word"), out)
    out = find(ctx, "K", kind="function")
    check("kind=function on a class says what it is", "(class: 1)" in out and "kind=function" in out, out)
    out = find(ctx, "nothing_here", kind="usage")
    check("a real miss still says no matches", out.startswith("No whole-word matches for 'nothing_here'") and "kind=usage" in out, out)
    mk(root, "call.py", "run(\n    cwd=root,\n    check=True)\n")
    out = find(ctx, "check")
    check("keyword argument on a closing line is not a definition", "0 definitions" in out and "Definitions:" not in out, out)
    mk(root, "sig.py", "def f(\n    a,\n    name=None\n):\n    pass\n\nname = 5\n")
    out = find(ctx, "name", kind="definition")
    check("default value of the last parameter is not a definition, a later assignment is", "sig.py:7" in out and "sig.py:3" not in out and "1 definitions" in out, out)
    mk(root, "obj.ts", "const o = {\n    id: value,\n};\ninterface P {\n  id: string;\n}\n")
    out = find(ctx, "id", kind="definition")
    check("object literal property is not a definition, an interface field is", "obj.ts:5" in out and "obj.ts:2" not in out, out)
    mk(root, "decl.js", "const a = 1,\n    b = 2;\n")
    out = find(ctx, "b", kind="definition")
    check("second name of a comma declaration ending in ';' stays a definition", "decl.js:2" in out, out)


def test_find_backends_edge_cases(root: Path) -> None:
    ctx = Ctx(root)
    mk(root, "latin.py", b"def target(): # caf\xe9\n")
    mk(root, "utf.py", "def target(): # café\n")
    if dc.shutil.which("rg"):
        res = dc._scan_rg(root, "target", root)
        check("rg backend itself returns the non-UTF-8 line", res is not None and {h[0] for h in res[0]} == {"latin.py", "utf.py"}, str(res))
    for rg in ([True, False] if dc.shutil.which("rg") else [False]):
        out = dc._find(ctx, "target", ".", "any", use_rg=rg)
        check(f"{'rg' if rg else 'py'}: a line with non-UTF-8 bytes is found", "latin.py:1" in out and "utf.py:1" in out and "2 definitions" in out, out)
    outside = Path(tempfile.mkdtemp()).resolve()
    try:
        (outside / "secret.txt").write_text("hunter2 secretword\n")
        os.symlink(outside / "secret.txt", root / "link.txt")
        os.symlink(outside, root / "outlink")
        mk(root, "inside.txt", "secretword in the project\n")
        for rg in ([True, False] if dc.shutil.which("rg") else [False]):
            out = dc._find(ctx, "secretword", ".", "any", use_rg=rg)
            check(f"{'rg' if rg else 'py'}: symlinks are not followed out of the project",
                  "inside.txt" in out and "link.txt" not in out and "outlink" not in out and "hunter2" not in out, out)
    finally:
        for n in ("link.txt", "outlink"):
            try:
                os.unlink(root / n)
            except OSError:
                pass
        import shutil as _sh
        _sh.rmtree(outside, ignore_errors=True)


def test_find_ignore_parity(root: Path) -> None:
    proj = root / "proj"
    mk(proj, ".gitignore", "*.log\n!keep.log\n**/temp\n/top_only.py\nbuild_*/\ndocs/**/gen\n")
    mk(proj, "pkg/.gitignore", "local.py\n!/inner/local.py\n")
    mk(root, ".gitignore", "*.generated.py\n")                  # a parent of the project
    body = "def target(): pass\n"
    shown = ["keep.log", "src/a.py", "pkg/inner/local.py", "other/top_only.py", "docs/a/b.py", "x/build.py"]
    hidden = ["drop.log", "temp/x.py", "a/temp/x.py", "pkg/local.py", "pkg/sub/local.py", "top_only.py", "build_x/y.py",
              "docs/a/gen/z.py", "src/b.generated.py"]
    for rel in shown + hidden:
        mk(proj, rel, body)
    ctx = Ctx(proj)
    res = {}
    for rg in ([True, False] if dc.shutil.which("rg") else [False]):
        out = dc._find(ctx, "target", ".", "any", use_rg=rg)
        res[rg] = out
        files = set(re.findall(r"^  (\S+):\d+  \[", out, re.M))
        check(f"{'rg' if rg else 'py'}: gitignore negation, ** , anchors, nested files and parent files",
              files == set(shown), f"extra={sorted(files - set(shown))} missing={sorted(set(shown) - files)}")
    if len(res) == 2:
        check("rg and python backends give identical output with a complex .gitignore", res[True] == res[False], res[True] + "\n---\n" + res[False])
        sub_rg, sub_py = dc._find(ctx, "target", "pkg", "any", use_rg=True), dc._find(ctx, "target", "pkg", "any", use_rg=False)
        check("backends agree when searching a subdirectory", sub_rg == sub_py and "pkg/inner/local.py" in sub_py and "pkg/local.py" not in sub_py, sub_rg + "\n---\n" + sub_py)


def test_multiedit_filesystem(root: Path) -> None:
    ctx = Ctx(root)
    edit = lambda f: dc.multi_edit(ctx, f, [{"old_string": "old", "new_string": "new"}])
    if os.geteuid() != 0:
        ro = mk(root, "r.txt", "old\n")
        ro.chmod(0o444)
        err = raises(edit, "r.txt")
        check("read-only file: clear error, file untouched", err is not None and "read-only" in err and ro.read_text() == "old\n", str(err))
        d = root / "rodir"
        mk(d, "f.txt", "old\n")
        d.chmod(0o555)
        try:
            out = edit("rodir/f.txt")
            check("file in a read-only directory is edited in place", out.startswith("Updated") and (d / "f.txt").read_text() == "new\n", out)
        finally:
            d.chmod(0o755)
    long = mk(root, "n" * 250 + ".txt", "old\n")
    out = edit(long.name)
    check("250-character file name", out.startswith("Updated") and long.read_text() == "new\n", out)
    a = mk(root, "hard_a.txt", "old\n")
    os.link(a, root / "hard_b.txt")
    edit("hard_a.txt")
    check("hard link is kept: both names see the edit", (root / "hard_b.txt").read_text() == "new\n" and a.read_text() == "new\n")
    check("no temp files left", [f.name for f in root.iterdir() if f.name.endswith(".tmp")] == [])


def test_multiedit_line_numbers(root: Path) -> None:
    ctx = Ctx(root)
    mk(root, "a.txt", "a\nb\nx\nc\nx\n")
    err = raises(dc.multi_edit, ctx, "a.txt", [{"old_string": "a", "new_string": "a1\na2\na3\na4\na5"}, {"old_string": "x", "new_string": "y"}])
    check("ambiguity after an earlier edit says the lines are shifted", err is not None and "lines 7, 9" in err and "after the previous edits" in err, str(err))
    err = raises(dc.multi_edit, ctx, "a.txt", [{"old_string": "x", "new_string": "y"}])
    check("ambiguity in the first edit has plain line numbers", err is not None and "lines 3, 5)" in err and "previous edits" not in err, str(err))
    err = raises(dc.multi_edit, ctx, "a.txt", [{"old_string": "a", "new_string": "a1\na2\na3"}, {"old_string": "x\nzzz", "new_string": "y"}])
    check("miss hint after an earlier edit says the line is shifted", err is not None and "previous edits" in err, str(err))


def test_multiedit_diff_is_bounded(root: Path) -> None:
    ctx = Ctx(root)
    text = "".join(f"line {i}\n\n" if i % 2 else f"line {i}\n" for i in range(16000))
    mk(root, "big.txt", text)
    t = time.time()
    dc.multi_edit(ctx, "big.txt", [{"old_string": "line 8000\n", "new_string": "changed\n"}])
    check("one edit in a 16000-line file with many blank lines is fast", time.time() - t < 3 and ctx.meta["diff"]["added"] == 1 and ctx.meta["diff"]["removed"] == 1,
          f"{time.time() - t:.1f}s {ctx.meta['diff']['added']}/{ctx.meta['diff']['removed']}")
    mk(root, "same.txt", "same\n" * 5000 + "x\n" + "same\n" * 5000)
    t = time.time()
    dc.multi_edit(ctx, "same.txt", [{"old_string": "x\n", "new_string": "y\n"}])
    check("one edit among 10000 identical lines is fast", time.time() - t < 3 and ctx.meta["diff"]["added"] == 1, f"{time.time() - t:.1f}s")
    mk(root, "many.txt", "".join(f"row {i}\nkeep\n" for i in range(6000)))
    t = time.time()
    dc.multi_edit(ctx, "many.txt", [{"old_string": "keep\n", "new_string": "kept\n", "replace_all": True}])
    d = ctx.meta["diff"]
    check("replace_all across a large file stays fast and counts correctly", time.time() - t < 5 and d["added"] == 6000 and d["removed"] == 6000, f"{time.time() - t:.1f}s {d['added']}/{d['removed']}")
    text = "".join(f"line {i}\n\n" if i % 2 else f"line {i}\n" for i in range(16000))
    mk(root, "two.txt", text)
    t = time.time()
    dc.multi_edit(ctx, "two.txt", [{"old_string": "line 100\n", "new_string": "line 100\nnew a\nnew b\n"}, {"old_string": "line 15000\n", "new_string": ""}])
    d = ctx.meta["diff"]
    check("two far-apart edits that change the line count give exact counts quickly", time.time() - t < 3 and (d["added"], d["removed"]) == (2, 1),
          f"{time.time() - t:.1f}s {d['added']}/{d['removed']}")
    check("hunks stay small", sum(len(h) for h in d["hunks"]) < 30, str(sum(len(h) for h in d["hunks"])))
    d = dc._diff("a\nb\nc\nd\ne\n", "a\nB\nc\nd\nE\n")
    check("diff shape: added/removed and new line numbers", d["added"] == 2 and d["removed"] == 2 and d["hunks"][0][0] == [" ", 1, "a"]
          and ["-", 2, "b"] in d["hunks"][0] and ["+", 2, "B"] in d["hunks"][0], str(d))


def test_outline_line_numbers_match_read(root: Path) -> None:
    ctx = Ctx(root)
    mk(root, "a.py", "import os\n\x0c\ndef foo():\n    pass\n")
    out = dc.outline(ctx, "a.py")
    check("py with form feed: outline line equals Read line", start_of(out, "def foo") == read_line_of(ctx, "a.py", "def foo") == 4, out)
    mk(root, "p.html", "<p>x</p>\x0c\n<h1>T</h1>")
    out = dc.outline(ctx, "p.html")
    check("html with form feed: outline line equals Read line", start_of(out, "h1: T") == read_line_of(ctx, "p.html", "<h1>") == 3, out)
    mk(root, "s.css", "a { }\x0c\n.b { }\n")
    out = dc.outline(ctx, "s.css")
    check("css with form feed: outline line equals Read line", start_of(out, ".b") == read_line_of(ctx, "s.css", ".b") == 3, out)
    mk(root, "k.json", '{\n\x0c"a": 1}\n')
    out = dc.outline(ctx, "k.json")
    check("json with form feed: outline line equals Read line", start_of(out, '"a"') == read_line_of(ctx, "k.json", '"a"'), out)
    mk(root, "u.py", "x = 1\u2028def bar():\n    pass\n")
    out = dc.outline(ctx, "u.py")
    check("py with U+2028: outline line equals Read line", start_of(out, "def bar") == read_line_of(ctx, "u.py", "def bar"), out)


def test_outline_python_robust(root: Path) -> None:
    ctx = Ctx(root)
    src = "HELP = (" + " +\n    ".join('"line %d\\n"' % i for i in range(400)) + ")\ndef after(): pass\n"
    mk(root, "chain.py", src)
    out = dc.outline(ctx, "chain.py")
    check("py: 400-term chained expression does not crash", "HELP" in out and "def after" in out, out[:300])
    mk(root, "nul.py", "def a():\n    pass\n" + "#" * 5000 + "\x00\n" + "def b(): pass\n")
    out = dc.outline(ctx, "nul.py")
    check("py: NUL after byte 4096 gives a readable fallback", "line None" not in out and "def a" in out and "def b" in out, out[:300])


def test_outline_limits(root: Path) -> None:
    ctx = Ctx(root)
    mk(root, "huge.py", "x = 1\n" * 500_000)
    t = time.time()
    out = dc.outline(ctx, "huge.py")
    check("outline: file over the size limit gets a note and the first lines", time.time() - t < 3 and "outline limit" in out and "500000 lines" in out, f"{time.time() - t:.1f}s {out[:200]}")
    mk(root, "many.md", "".join(f"## h{i}\n" for i in range(100_000)))
    t = time.time()
    out = dc.outline(ctx, "many.md")
    check("markdown with 100000 headings is linear", time.time() - t < 5 and "## h0" in out, f"{time.time() - t:.1f}s")
    mk(root, "h2.html", "<h2>x\n" * 20000)
    t = time.time()
    dc.outline(ctx, "h2.html")
    check("html with 20000 unclosed <h2> is fast", time.time() - t < 5, f"{time.time() - t:.1f}s")
    for tag in ("script", "title", "style"):
        mk(root, f"{tag}.html", f"<{tag}>x\n" * 5000)
        t = time.time()
        dc.outline(ctx, f"{tag}.html")
        check(f"html with 5000 unclosed <{tag}> is fast", time.time() - t < 3, f"{time.time() - t:.1f}s")
    mk(root, "ok.md", "# T\n\n## Two\ntext\n")
    out = asyncio.run(dc.Outline(ctx, "ok.md"))
    check("async Outline returns the same text", out == dc.outline(ctx, "ok.md") and "## Two" in out, out)


def test_outline_non_structural(root: Path) -> None:
    ctx = Ctx(root)
    mk(root, "fence.md", "# Top\n````md\n```py\n# in\n```\n````\n## After\n")
    out = dc.outline(ctx, "fence.md")
    check("md: a 4-backtick fence is not closed by a 3-backtick line", "# in" not in out and start_of(out, "## After") == 7 and start_of(out, "# Top") == 1, out)
    mk(root, "tilde.md", "# A\n~~~\n```\n# x\n~~~\n# B\n")
    out = dc.outline(ctx, "tilde.md")
    check("md: a tilde fence is closed only by tildes", "# x" not in out and "# B" in out, out)
    mk(root, "csharp.md", "# Learning C#\n## Closed ##\n### Mixed ## x\n")
    out = dc.outline(ctx, "csharp.md")
    check("md: '#' without a space before it stays in the title", "# Learning C#" in out and "## Closed" in out and "## Closed #" not in out and "Mixed ## x" in out, out)
    mk(root, "rule.md", "---\n\n# One\n\ntext\n\n## Two\n\n---\n\nmore\n")
    out = dc.outline(ctx, "rule.md")
    check("md: a leading rule is not front matter", "front matter" not in out and "# One" in out and "## Two" in out, out)
    mk(root, "fm.md", "---\ntitle: x\ntags:\n  - a\n---\n# Body\n")
    out = dc.outline(ctx, "fm.md")
    check("md: real front matter with a list is recognised", "1-5" in row(out, "front matter") and "# Body" in out, out)
    mk(root, "x.html", '<h1>Real</h1>\n<script>el.innerHTML = \'<h2 id="fake">Fake</h2><div id="ghost"></div>\';</script>\n'
                       '<!-- <h3>old</h3><div id="gone"></div> -->\n<div id="real"></div>\n')
    out = dc.outline(ctx, "x.html")
    check("html: headings and ids inside script strings and comments are ignored",
          "Fake" not in out and "ghost" not in out and "old" not in out and "gone" not in out and "h1: Real" in out and 'id="real"' in out and "<script> inline" in out, out)
    mk(root, "c.js", "/*\nfunction hidden() {\n}\n  class Ghost {\n  }\n*/\nconst t = `\nfunction inTemplate() {\n}\n`;\n"
                     "const g = 'src/**/*.js';\nfunction real() {\n  return 1;\n}\n/* after */ class Shown {\n}\n")
    out = dc.outline(ctx, "c.js")
    check("js: functions in block comments and template literals are not listed", "hidden" not in out and "Ghost" not in out and "inTemplate" not in out, out)
    check("js: code after a '/*' inside a string is still listed", "function real" in out and "class Shown" in out and start_of(out, "function real") == 12, out)


def main() -> int:
    for fn in (test_multiedit, test_multiedit_failure, test_multiedit_unicode, test_multiedit_eol, test_multiedit_mode,
               test_outline_python, test_outline_js, test_outline_markdown, test_outline_html, test_outline_json_css_other,
               test_findsymbol, test_findsymbol_backends, test_findsymbol_cap,
               test_import_order, test_find_definition_beyond_scan_limit, test_find_kind_messages_and_context, test_find_backends_edge_cases,
               test_find_ignore_parity, test_multiedit_filesystem, test_multiedit_line_numbers, test_multiedit_diff_is_bounded,
               test_outline_line_numbers_match_read, test_outline_python_robust, test_outline_limits, test_outline_non_structural):
        with tempfile.TemporaryDirectory() as d:
            try:
                fn(Path(d).resolve())
            except Exception as e:      # a crashing test counts as one failure and the run continues
                import traceback
                traceback.print_exc()
                check(f"{fn.__name__} crashed", False, f"{type(e).__name__}: {e}")
    test_classify()
    try:
        test_outline_real_python(REPO)
    except Exception as e:
        check("real python outline crashed", False, f"{type(e).__name__}: {e}")
    n, ok = len(RESULTS), sum(RESULTS)
    print(f"\n{ok}/{n} checks passed" + ("" if ok == n else f", {n - ok} FAILED"))
    return 0 if ok == n else 1


if __name__ == "__main__":
    sys.exit(main())
