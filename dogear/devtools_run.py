"""Developer tools: RunTests (compact test summary) and Git (restricted git wrapper)."""
import asyncio
import heapq
import json
import os
import re
import shlex
import shutil
import signal
from pathlib import Path

from .tools import DENY, Bash, SKIP_DIRS, ToolError, _clip, clean_env, make_diff

TEST_TIMEOUT = 180
TAIL_LINES = 40
GIT_TIMEOUT = 30
DIFF_LINES = 300
SCAN_DEPTH = 8
SCAN_CAP = 3000
SCAN_WORK = 30000
MAX_GLOB = 1000
READ_ACTIONS = {"status", "diff", "log", "show", "branch", "blame"}
WRITE_ACTIONS = {"add", "commit", "restore"}
ALLOWED = ("status", "diff", "log", "show", "branch", "blame", "add", "commit", "restore")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


# ------------------------------------------------------------------ RunTests: output parsing

_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")


def _result(runner, passed=0, failed=0, errors=0, skipped=0, failures=None):
    return {"runner": runner, "passed": passed, "failed": failed, "errors": errors,
            "skipped": skipped, "failures": failures or []}


_PYTEST_SUMMARY = re.compile(r"^(?:no tests ran|\d+ [a-z]+(?:, \d+ [a-z]+)*) in \d+(?:\.\d+)?s(?: \(\d+:\d+:\d+\))?$")


def _parse_pytest(lines):
    n, found = {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}, False
    for ln in lines:  # every summary line counts: a custom command may run pytest several times
        s = ln.strip("= ").strip()
        if not _PYTEST_SUMMARY.match(s) or not (s.startswith("no tests ran") or _COUNT.search(s)):
            continue
        found = True
        for num, word in _COUNT.findall(s):
            key = "error" if word.startswith("error") else word
            if key in n:
                n[key] += int(num)
    if not found:
        return None
    return _result("pytest", n["passed"] + n["xpassed"], n["failed"], n["error"], n["skipped"] + n["xfailed"],
                   _pytest_failures(lines))


def _pytest_failures(lines):
    reasons, cur = {}, None
    for ln in lines:
        m = re.match(r"^_{2,} (.+?) _{2,}$", ln)
        if m:
            cur = m.group(1)
        elif cur and ln.startswith("E  ") and cur not in reasons:
            reasons[cur] = ln[1:].strip()
    start = next((i for i, ln in enumerate(lines) if "short test summary info" in ln), -1) + 1
    found = []
    for ln in lines[start:]:
        m = re.match(r"^(FAILED|ERROR) (.+)$", ln.rstrip())
        if not m:
            continue
        name, _, why = m.group(2).partition(" - ")
        if not why:
            last = name.split("::")[-1]
            why = next((v for k, v in reasons.items() if k == last or k.endswith("." + last) or k.endswith(" " + name)), "")
        found.append((m.group(1), name.strip(), why.strip()))
    return found


def _parse_unittest(lines):
    tot, found = [0, 0, 0, 0], False
    for i, ln in enumerate(lines):
        m = re.match(r"^Ran (\d+) tests? in ", ln)
        if not m:
            continue
        found = True
        verdict = next((x for x in lines[i + 1:i + 6] if re.match(r"^(OK|FAILED|NO TESTS RAN)\b", x)), "")
        kv = {k.strip(): int(v) for k, v in re.findall(r"([a-z ]+)=(\d+)", verdict)}
        f, e, sk = kv.get("failures", 0), kv.get("errors", 0), kv.get("skipped", 0)
        for j, v in enumerate((max(int(m.group(1)) - f - e - sk, 0), f, e, sk)):
            tot[j] += v
    return _result("unittest", *tot, _unittest_failures(lines)) if found else None


def _unittest_failures(lines):
    out, i = [], 0
    while i < len(lines):
        m = re.match(r"^(FAIL|ERROR): (\S+) \((.+)\)$", lines[i])
        i += 1
        if not m:
            continue
        block = []
        if i < len(lines) and re.match(r"^-{20,}$", lines[i]):
            i += 1
        while i < len(lines) and not re.match(r"^(={20,}|-{20,}|Ran \d+ tests?)", lines[i]):
            block.append(lines[i])
            i += 1
        body = [b.strip() for b in block if b.strip()]
        why = next((b for b in reversed(body) if re.match(r"^[A-Za-z_][\w.]*(Error|Exception|Failure|Warning)\b", b)),
                   body[-1] if body else "")
        out.append(("FAILED" if m.group(1) == "FAIL" else "ERROR", m.group(3), why))
    return out


def _parse_node(lines):
    n = {}
    for ln in lines:
        m = re.match(r"^(?:ℹ|#)\s+(tests|pass|fail|cancelled|skipped|todo)\s+(\d+)\s*$", ln)
        if m:
            n[m.group(1)] = n.get(m.group(1), 0) + int(m.group(2))
    if "tests" not in n:
        return None
    return _result("node", n.get("pass", 0), n.get("fail", 0), n.get("cancelled", 0), n.get("skipped", 0), _node_failures(lines))


def _node_failures(lines):
    out = []
    head = next((i for i, ln in enumerate(lines) if re.match(r"^✖ failing tests:", ln)), -1)
    if head >= 0:
        i = head + 1
        while i < len(lines):
            m = re.match(r"^\s*✖ (.+?) \(\d+(?:\.\d+)?m?s\)\s*$", lines[i])
            i += 1
            if not m:
                continue
            why = []
            while i < len(lines) and len(why) < 2 and not re.match(r"^\s*(test at |✖ )", lines[i]):
                t = lines[i].strip()
                if t and not t.startswith(("at ", "{", "}")):
                    why.append(t)
                elif t.startswith("at "):
                    break
                i += 1
            out.append(("FAILED", m.group(1), " ".join(why)))
        return out
    for i, ln in enumerate(lines):  # TAP reporter
        m = re.match(r"^\s*not ok \d+ - (.+?)(?: # .*)?$", ln)
        if not m:
            continue
        why = ""
        for j in range(i + 1, min(i + 40, len(lines))):
            if re.match(r"^\s*(not )?ok \d+", lines[j]):
                break
            e = re.match(r"^\s*error: (.*)$", lines[j])
            if e:
                why = e.group(1).strip("'\" ")
                if why.startswith("|"):
                    why = next((x.strip() for x in lines[j + 1:j + 6] if x.strip()), "")
                break
        out.append(("FAILED", m.group(1), why))
    return out


def _sum_counts(lines, pattern, words):
    n, found = dict.fromkeys(words, 0), False
    for ln in lines:
        m = re.match(pattern, ln)
        if m:
            found = True
            for c, w in re.findall(r"(\d+) (" + "|".join(words) + ")", m.group(1)):
                n[w] += int(c)
    return n if found else None


def _parse_jest(lines):
    n = _sum_counts(lines, r"^\s*Tests:\s+(.*\btotal)\s*$", ("failed", "passed", "skipped"))
    if n is None:
        return None
    names = list(dict.fromkeys(x.group(1).strip() for l in lines if (x := re.match(r"^\s*●\s+(.+?)\s*$", l)) and "Console" not in l))
    return _result("jest", n["passed"], n["failed"], 0, n["skipped"], [("FAILED", s, "") for s in names])


def _parse_vitest(lines):
    n = _sum_counts(lines, r"^\s*Tests\s+(.*)\(\d+\)\s*$", ("failed", "passed", "skipped"))
    if n is None:
        return None
    return _result("vitest", n["passed"], n["failed"], 0, n["skipped"], _vitest_failures(lines))


def _vitest_failures(lines):
    """Names from ' FAIL file > name' lines (file included), reasons from the '× name' / '→ reason' pair."""
    why = {}
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*×\s+(.+?)(?:\s+\d+(?:\.\d+)?m?s)?\s*$", ln)
        if m:
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            why.setdefault(m.group(1), nxt[1:].strip() if nxt.startswith("→") else "")
    names = list(dict.fromkeys(x.group(1) for l in lines if (x := re.match(r"^\s*FAIL\s+(.+?)\s*$", l))))
    if not names:
        return [("FAILED", k, v) for k, v in why.items()]
    out = []
    for name in names:
        reason = next((v for k, v in why.items() if name == k or name.endswith(" > " + k)), "")
        out.append(("FAILED", name, reason))
    return out


_PARSERS = (_parse_pytest, _parse_unittest, _parse_node, _parse_jest, _parse_vitest)


def parse_output(text: str):
    """Parse a test runner's output into counts and failures. None when no known summary is found.
    Several summaries (one command running a runner twice, or two runners) are added up."""
    lines = _ANSI.sub("", text).replace("\r", "\n").splitlines()
    found = [r for fn in _PARSERS if (r := fn(lines))]
    if len(found) < 2:
        return found[0] if found else None
    total = _result("+".join(r["runner"] for r in found))
    for r in found:
        for k in ("passed", "failed", "errors", "skipped"):
            total[k] += r[k]
        total["failures"] += r["failures"]
    return total


def summary_line(r: dict) -> str:
    skipped = f", {r['skipped']} skipped" if r["skipped"] else ""
    return f"TESTS: {r['passed']} passed, {r['failed']} failed, {r['errors']} errors{skipped} ({r['runner']})"


# ------------------------------------------------------------------ RunTests: detection

_CODE_EXT = (".py", ".js", ".mjs", ".cjs")
_TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs"}


def _scan(root: Path, depth=None, cap=None, work=None) -> tuple[list[str], bool]:
    """Code files under root (relative paths) and whether a limit cut the scan short.
    Test directories are visited first, then shallow before deep, so a limit rarely hides tests."""
    depth, cap, work = depth or SCAN_DEPTH, cap or SCAN_CAP, work or SCAN_WORK
    out, cut, seen = [], False, 0
    heap = [(0, 0, "", root)]
    while heap:
        _, n, _, d = heapq.heappop(heap)
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        seen += len(entries)
        for e in entries:
            if e.is_dir():
                if e.name in SKIP_DIRS or e.name.startswith("."):
                    continue
                if n + 1 >= depth:
                    cut = True
                else:
                    heapq.heappush(heap, (int(e.name not in _TEST_DIRS), n + 1, e.name, e))
            elif e.name.endswith(_CODE_EXT):
                if len(out) >= cap:
                    return out, True
                out.append(e.relative_to(root).as_posix())
        if seen >= work and heap:
            return out, True
    return out, cut


def _head(root: Path, rel: str, n=8000) -> str:
    try:
        with open(root / rel, encoding="utf-8", errors="replace") as f:
            return f.read(n)
    except OSError:
        return ""


def _py_test_files(files):
    return [f for f in files if f.endswith(".py") and re.fullmatch(r"test\w*\.py|\w+_test\.py", Path(f).name)]


def _pytest_config(root: Path) -> str:
    for name, needle in (("pytest.ini", ""), ("conftest.py", ""), ("pyproject.toml", "[tool.pytest"),
                         ("tox.ini", "[pytest]"), ("setup.cfg", "[tool:pytest]")):
        f = root / name
        if f.is_file() and needle in _head(root, name, 200_000):
            return name
    return ""


def _node_test_files(files):
    pat = (r".*[.\-_]test\.[cm]?js", r"test-.*\.[cm]?js", r"test\.[cm]?js")
    return [f for f in files if any(re.fullmatch(p, Path(f).name) for p in pat)
            or (f.endswith((".js", ".mjs", ".cjs")) and "test" in Path(f).parts[:-1])]


def _npm_test_script(root: Path) -> str:
    try:
        s = json.loads((root / "package.json").read_text()).get("scripts", {}).get("test", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return "" if not isinstance(s, str) or "no test specified" in s else s


def _venv_pythons(*dirs: Path) -> list[str]:
    seen, out = set(), []
    for d in dirs:
        for sub in (".venv", "venv"):
            p = d / sub / "bin" / "python"
            if p.exists() and str(p) not in seen:
                seen.add(str(p))
                out.append(str(p))
    return out


def _kill(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def _has_pytest(python: str) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            python, "-c", "import pytest", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.DEVNULL, env=clean_env(), start_new_session=True)
    except OSError:
        return False
    try:
        return await asyncio.wait_for(proc.wait(), 20) == 0
    except asyncio.TimeoutError:
        _kill(proc)
        return False
    except asyncio.CancelledError:
        _kill(proc)
        await proc.wait()
        raise


def _py_style(root: Path, tests: list[str]) -> str:
    """'pytest' when the project clearly wants pytest, else 'unittest'."""
    if _pytest_config(root):
        return "pytest"
    heads = [_head(root, f) for f in tests[:50]]
    if any(re.search(r"^\s*(import pytest|from pytest)", h, re.M) for h in heads):
        return "pytest"
    plain = [h for h in heads if "unittest" not in h and re.search(r"^def test_", h, re.M)]
    return "pytest" if plain else "unittest"


def _covered(d: str, runs: list[str], root: Path) -> bool:
    """True when discovery started at one of runs already reaches d (every directory below it is a package)."""
    for r in runs:
        if r != "." and not d.startswith(r + "/"):
            continue
        cur, ok = Path(r), True
        for part in (Path(d).parts if r == "." else Path(d).relative_to(r).parts):
            cur = cur / part
            ok = ok and (root / cur / "__init__.py").exists()
        if ok:
            return True
    return False


def _unittest_cmd(root: Path, py: str, tests: list[str]) -> str:
    """One discover run per directory that holds test files: discover does not enter directories without __init__.py."""
    groups = sorted({(Path(f).parent.as_posix(), "*_test.py" if f.endswith("_test.py") else "test*.py") for f in tests},
                    key=lambda k: (k[0].count("/") if k[0] != "." else -1, k))
    cmds, done = [], {}
    for d, pat in groups:
        if _covered(d, done.setdefault(pat, []), root):
            continue
        done[pat].append(d)
        start = "" if d == "." else f" -s {shlex.quote(d)}" + (" -t ." if (root / d / "__init__.py").exists() else "")
        cmds.append(f"{py} -m unittest discover{start}" + ("" if pat == "test*.py" else f" -p {shlex.quote(pat)}"))
    if not cmds:
        return f"{py} -m unittest discover"
    if len(cmds) == 1:
        return cmds[0]
    return "rc=0\n" + "".join(f"{c} || rc=$?\n" for c in cmds) + "exit $rc"


PYTEST_FLAGS = "-q --tb=short -rfE -p no:cacheprovider"
PYTEST_MISSING = "pytest-missing"


async def _detect_python(ctx, root: Path, files):
    tests = _py_test_files(files)
    cfg = _pytest_config(root)
    if not tests and not cfg:
        return "", ""
    venvs = _venv_pythons(root, ctx.root)
    system = shutil.which("python3", path=clean_env().get("PATH", ""))
    cands = venvs + ([system] if system else [])
    for py in cands:
        if await _has_pytest(py):
            return f"COLUMNS=140 {shlex.quote(py)} -m pytest {PYTEST_FLAGS}", "pytest"
    style = _py_style(root, tests)
    if style == "pytest" and shutil.which("uv"):  # --no-project: do not write .venv or uv.lock into the project
        return f"COLUMNS=140 uv run --no-project --with pytest python -m pytest {PYTEST_FLAGS}", "pytest"
    if style == "pytest" and not any("unittest" in _head(root, f) for f in tests[:50]):
        return "", PYTEST_MISSING
    py = shlex.quote(venvs[0]) if venvs else "python3"
    return _unittest_cmd(root, py, tests), "unittest"


async def _detect(ctx, root: Path):
    """Return (command, label, nothing_found_text). command is '' when nothing was found."""
    files, cut = _scan(root)
    cmd, label = await _detect_python(ctx, root, files)
    if cmd:
        return cmd, label, ""
    node_files, script = _node_test_files(files), _npm_test_script(root)
    uses_node_test = any("node:test" in _head(root, f, 4000) for f in node_files[:20])
    if node_files and (uses_node_test or not script) and shutil.which("node"):
        return "node --test", "node", ""
    if script and shutil.which("npm"):
        return "npm test", "npm test", ""
    if label == PYTEST_MISSING:
        raise ToolError("These Python tests are written for pytest (plain test_ functions or a pytest config), but pytest is "
                        "not installed for python3 and uv is not on PATH. Install pytest (python3 -m pip install pytest) "
                        "or uv, or pass command=\"...\" to run them another way.")
    looked = (f"Looked in {root} ({SCAN_DEPTH} levels, skipping .git, node_modules, .venv) for: "
              "pytest config (pytest.ini, conftest.py, [tool.pytest] in pyproject.toml, [pytest] in tox.ini, [tool:pytest] in setup.cfg); "
              "Python test files (test_*.py, *_test.py, tests.py) for pytest or python3 -m unittest discover; "
              "Node test files (*.test.js, *-test.js, test-*.js, test/**/*.js) for node --test; "
              "a scripts.test entry in package.json for npm test. ")
    if node_files or script:
        found = f"Found Node test files or an npm test script, but {'node' if node_files else 'npm'} is not on PATH."
    elif cut:
        found = (f"Found: none in the part that was scanned, but the scan limit was reached ({SCAN_CAP} code files, "
                 f"{SCAN_DEPTH} levels), so tests may exist deeper. Pass path=\"<subdirectory>\" or command=\"...\".")
    else:
        found = "Found: none of these."
    return "", "", f"TESTS: nothing to run.\n{looked}{found}\nPass command=\"...\" to run a specific test command."


# ------------------------------------------------------------------ RunTests: tool

# A custom command may only be a test run: the agent skips the approval prompt for RunTests in edit mode.
_TESTISH = re.compile(r"test|spec|check|e2e|jest|vitest|mocha|pytest", re.I)
_RUNNERS = {"pytest", "py.test", "tox", "nox", "jest", "vitest", "mocha", "ava", "rspec", "phpunit", "nose2", "ctest",
            "playwright"}
_FILTERS = {"tail", "head", "grep", "wc", "cat", "sort", "uniq", "cut", "tr"}
_SIMPLE = {"true", "false", ":", "exit", "echo", "set", "unset", "export"}
_BUILD = {"npm", "pnpm", "yarn", "bun", "deno", "cargo", "go", "make", "mvn", "mvnw", "gradle", "gradlew", "dotnet",
          "mix", "swift", "dart", "flutter", "rake", "composer"}
_BAD_ENV = {"PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "BASH_ENV", "ENV", "IFS", "SHELL"}
_PY_MODULES = {"pytest", "unittest", "nose2", "coverage", "doctest", "tox"}
_UV_VALUED = {"--with", "--python", "-p", "--with-requirements", "--extra", "--group", "--directory", "--project",
              "--env-file", "--with-editable", "--index", "-w", "--package", "--from"}
_OK_REDIRECT = re.compile(r"\s*(?:&>>?|\d?>>?)\s*/dev/null|\s*\d?>&\d")
_PUNCT = re.compile(r"^[();<>|&]+$")
_JOINERS = {";", "&&", "||", "|"}


def _after_opts(words: list[str], valued=frozenset()) -> list[str]:
    i = 0
    while i < len(words) and words[i].startswith("-"):
        i += 2 if words[i] in valued else 1
    return words[i:]


def _python_ok(args: list[str]) -> bool:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-m":
            return i + 1 < len(args) and args[i + 1] in _PY_MODULES
        if args[i].startswith("-c") or args[i] == "-":
            return False
        i += 2 if args[i] in ("-W", "-X") else 1
    return i < len(args) and args[i].endswith(".py")


def _build_ok(prog: str, args: list[str]) -> bool:
    a = _after_opts(args)
    if not a:
        return False
    if prog in ("npm", "pnpm", "yarn", "bun") and a[0] in ("run", "run-script", "exec", "dlx", "x"):
        rest = _after_opts(a[1:])
        if a[0] in ("run", "run-script"):
            return bool(rest) and bool(_TESTISH.search(rest[0]))
        return _cmd_ok(rest)
    if prog in ("yarn", "pnpm") and not _TESTISH.search(a[0]):
        return _cmd_ok(a)  # yarn jest, pnpm vitest
    return bool(_TESTISH.search(a[0])) or a[0] in ("verify", "vet", "clippy")


def _cmd_ok(w: list[str], cwd: Path | None = None, root: Path | None = None) -> bool:
    while w and re.match(r"^[A-Za-z_]\w*=", w[0]):
        if w[0].split("=")[0] in _BAD_ENV:
            return False
        w = w[1:]
    if not w:
        return True
    prog, args = os.path.basename(w[0]), w[1:]
    if prog in _RUNNERS or prog in _FILTERS or prog in _SIMPLE:
        return True
    if prog == "cd":
        return cwd is None or (len(args) == 1 and (cwd / args[0]).resolve().is_relative_to(root))
    if prog in ("source", "."):
        return len(args) == 1 and os.path.basename(args[0]) == "activate"
    if prog == "time":
        return _cmd_ok(args)
    if prog == "timeout":
        return len(args) > 1 and _cmd_ok(args[1:])
    if prog == "uv":
        return args[:1] == ["run"] and _cmd_ok(_after_opts(args[1:], _UV_VALUED))
    if prog in ("uvx", "npx", "pnpx", "bunx"):
        return _cmd_ok(_after_opts(args, _UV_VALUED))
    if prog in ("bundle", "bundler"):
        return args[:1] == ["exec"] and _cmd_ok(args[1:])
    if re.fullmatch(r"python[\d.]*", prog):
        return _python_ok(args)
    if prog == "node":
        return not {"-e", "--eval", "-p", "--print"} & set(args) and (
            "--test" in args or any(a.endswith((".js", ".mjs", ".cjs")) for a in args))
    if prog in ("sh", "bash", "zsh"):
        a = _after_opts(args)
        return "-c" not in args and bool(a) and bool(_TESTISH.search(os.path.basename(a[0])))
    if prog in _BUILD:
        return _build_ok(prog, args)
    return bool(_TESTISH.search(prog)) and "/" in w[0] and not os.path.isabs(w[0])  # ./run_tests.sh, scripts/test.sh


def _check_command(cwd: Path, root: Path, cmd: str) -> None:
    """Refuse anything that is not a test run: this tool never asks the user in edit mode."""
    if DENY.search(cmd):
        raise ToolError("This command is blocked.")
    plain = _OK_REDIRECT.sub(" ", cmd)
    why = ""
    if re.search(r"`|\$\(|<\(|[<>]", plain):
        why = "Redirections, command substitution and backticks are not allowed."
    else:
        try:
            lex = shlex.shlex(plain.replace("\n", " ; "), posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            toks = list(lex)
        except ValueError as e:
            raise ToolError(f"Could not parse the command: {e}")
        seg: list[str] = []
        for t in toks + [";"]:
            if _PUNCT.match(t) and t not in _JOINERS:
                why = f"{t!r} is not allowed."
            elif t in _JOINERS:
                if seg and not _cmd_ok(seg, cwd, root):
                    why = f"{os.path.basename(seg[0])!r} is not a test runner."
                seg = []
            else:
                seg.append(t)
            if why:
                break
    if why:
        raise ToolError(
            f"RunTests only runs test commands: {why} Allowed: pytest, python -m pytest/unittest, uv run ..., node --test, "
            "npm/pnpm/yarn test, jest, vitest, mocha, go test, cargo test, make test, ./run_tests.sh, joined with ; && or |. "
            "Use Bash for anything else.")


MAX_COLLECT = 4_000_000


async def _run(ctx, cwd: Path, cmd: str):
    """Run cmd in cwd. Returns (full output, exit code); the output is collected from the terminal events, unclipped."""
    shell = f"cd {shlex.quote(str(cwd))} && (\n{cmd}\n)"
    saved, chunks, size = ctx.emit, [], 0

    async def tap(event):
        nonlocal size
        if event.get("type") == "term" and size < MAX_COLLECT:
            chunks.append(event.get("text", ""))
            size += len(chunks[-1])
        if saved:
            await saved(event)

    ctx.emit = tap
    try:
        text = await Bash(ctx, shell, timeout=TEST_TIMEOUT)
    except ToolError:
        partial = _tail("".join(chunks), TAIL_LINES)
        raise ToolError(f"Tests timed out after {TEST_TIMEOUT} s and were killed. Run a smaller set with "
                        f"command=\"...\" (one test file or one test name)." + (f"\nOutput so far:\n{partial}" if partial else ""))
    finally:
        ctx.emit = saved
    m = re.search(r"\n?\[exit code (-?\d+)\]\s*$", text)
    return ("".join(chunks) if chunks else (text[:m.start()] if m else text)), int(m.group(1)) if m else 0


def _tail(text: str, n: int) -> str:
    return "\n".join(_ANSI.sub("", text).replace("\r", "\n").rstrip().splitlines()[-n:])


def _report(out: str, code: int, label: str) -> str:
    r = parse_output(out)
    if not r:
        head = f"TESTS: finished with exit code {code}, no test summary recognised ({label})"
        return head + "\n" + _tail(out, TAIL_LINES if code else 10)
    lines = [summary_line(r)]
    bad = r["failed"] or r["errors"] or code
    if r["passed"] + r["failed"] + r["errors"] + r["skipped"] == 0:
        lines.append("No tests were collected. Check that the test files are in the directory that was run, "
                     "or pass command=\"...\" to run a specific file.")
    elif code and not (r["failed"] or r["errors"]):
        lines.append(f"The run exited with code {code} although no failures were counted.")
    for kind, name, why in r["failures"][:20]:
        lines.append(f"{kind} {name}" + (f": {why[:200]}" if why else ""))
    more = max(len(r["failures"]), r["failed"] + r["errors"]) - min(len(r["failures"]), 20)
    if more > 0:
        lines.append(f"... and {more} more" + (" (names not found in the output)" if len(r["failures"]) < r["failed"] + r["errors"] else ""))
    if bad:
        lines.append(f"--- last {TAIL_LINES} lines of output ---")
        lines.append(_tail(out, TAIL_LINES))
    return "\n".join(lines)


async def RunTests(ctx, command="", path="."):
    root = ctx.path(path or ".")
    if not root.is_dir():
        raise ToolError(f"{path} is not a directory inside the project.")
    command = (command or "").strip()
    if command:
        _check_command(root, ctx.root, command)
        cmd, label = command, "custom command"
    else:
        cmd, label, nothing = await _detect(ctx, root)
        if not cmd:
            return nothing
    out, code = await _run(ctx, root, cmd)
    r = parse_output(out)
    ctx.meta = {"exit": code, "command": cmd[:200]}
    if r:
        ctx.meta["tests"] = {k: r[k] for k in ("runner", "passed", "failed", "errors", "skipped")}
    return _report(out, code, label)


# ------------------------------------------------------------------ Git

REFUSED_NOTE = {
    "push": "it sends commits to a remote", "pull": "it talks to a remote and changes the working tree",
    "fetch": "it talks to a remote", "reset": "it can discard work or rewrite history",
    "clean": "it deletes untracked files", "checkout": "it can overwrite working-tree files",
    "switch": "it changes the working tree", "rebase": "it rewrites history", "merge": "it changes history and the working tree",
    "stash": "it hides or discards working-tree changes", "tag": "it changes repository references",
}
FORCE_FLAGS = re.compile(r"^(-f|-[a-zA-Z]*f[a-zA-Z]*|--force\S*|--hard|--no-verify|--amend)$")


def _split(args: str) -> list[str]:
    try:
        return shlex.split(args or "")
    except ValueError:
        return (args or "").split()


def _no_flags(toks: list[str]):
    for t in toks:
        if t.startswith("-"):
            why = "force and unsafe flags are refused" if FORCE_FLAGS.match(t) else "options are not accepted"
            raise ToolError(f"Refused: {t!r}: {why}. Pass only paths or the plain value this action takes.")


def _has_glob(ctx, t: str) -> bool:
    """A token is a glob only when it has glob characters and is not itself an existing path (pages/[id].tsx)."""
    return any(c in t for c in "*?[") and not os.path.isabs(t) and not os.path.lexists(ctx.root / t)


def _paths(ctx, toks: list[str]) -> list[str]:
    _no_flags(toks)
    out = []
    for t in toks:
        if _has_glob(ctx, t):
            hits = [ctx.rel(p) for p in (q.resolve() for q in sorted(ctx.root.glob(t)))
                    if p.is_relative_to(ctx.root) and ".git" not in p.relative_to(ctx.root).parts]
            if not hits:
                raise ToolError(f"No file matches {t!r}.")
            if len(hits) > MAX_GLOB:
                raise ToolError(f"{t!r} matches {len(hits)} files (limit {MAX_GLOB}). Use a narrower pattern.")
            out += hits
        else:
            out.append(ctx.rel(ctx.path(t)))
    return out


async def _git(ctx, *argv, timeout=None):
    timeout = timeout or GIT_TIMEOUT
    env = {**clean_env(), "GIT_PAGER": "cat", "GIT_EDITOR": "true", "GIT_TERMINAL_PROMPT": "0",
           "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "--no-pager", "-c", "core.quotepath=off", "--literal-pathspecs", *argv, cwd=ctx.root,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL,
            env=env, start_new_session=True)
    except FileNotFoundError:
        raise ToolError("git is not installed or not on PATH.")
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        _kill(proc)
        await proc.wait()
        raise ToolError(f"git {argv[0]} timed out after {timeout} s and was killed.")
    except asyncio.CancelledError:
        _kill(proc)  # the child (and hooks it started) must not outlive the cancelled call
        await proc.wait()
        raise
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _need(rc: int, out: str, err: str):
    if rc:
        raise ToolError(_clip((err.strip() or out.strip() or f"git failed with exit code {rc}"), 3000))


def _cap(text: str, n: int, hint: str) -> str:
    lines = text.rstrip("\n").splitlines()
    if len(lines) <= n:
        return "\n".join(lines)
    return "\n".join(lines[:n]) + f"\n... {len(lines) - n} more lines not shown. {hint}"


async def _toplevel(ctx) -> str:
    rc, out, err = await _git(ctx, "rev-parse", "--show-toplevel")
    if rc:
        if "not a git repository" in err:
            raise ToolError(f"{ctx.root} is not a git repository, so nothing was done. "
                            "Do not guess commands; ask the user whether they want one here (git init).")
        raise ToolError(_clip(err.strip(), 1000))
    return out.strip()


async def _status(ctx, toks):
    rc, out, err = await _git(ctx, "status", "--short", "--branch")
    _need(rc, out, err)
    text = out.rstrip()
    return text + ("\nWorking tree clean." if "\n" not in text else "")


async def _is_rev(ctx, tok: str) -> bool:
    sides = [x or "HEAD" for x in re.split(r"\.{2,3}", tok)] if ".." in tok else [tok]
    for side in sides:
        rc, _, _ = await _git(ctx, "rev-parse", "--verify", "--quiet", f"{side}^{{commit}}")
        if rc:
            return False
    return True


async def _revs_paths(ctx, toks: list[str]) -> tuple[list[str], list[str]]:
    """Split tokens into revisions and project paths. A token that is neither is an error, not a silent pathspec."""
    _no_flags(toks)
    revs, paths = [], []
    for t in toks:
        here = ctx.path(t)  # refuses paths outside the project
        if _has_glob(ctx, t) or os.path.lexists(here):
            paths += _paths(ctx, [t])
        elif await _is_rev(ctx, t):
            revs.append(t)
        else:
            rc, out, _ = await _git(ctx, "log", "--all", "-n1", "--format=%h", "--", t)
            if rc or not out.strip():
                raise ToolError(f"{t!r} is not a file in the project and not a known git revision. "
                                "Check the spelling; use status or log to see what exists.")
            paths.append(ctx.rel(ctx.path(t)))  # a file that only exists in history
    return revs, paths


async def _diff(ctx, toks):
    revs, paths = await _revs_paths(ctx, toks)
    if len(paths) > 1:
        raise ToolError("diff takes at most one path.")
    if len(revs) > 2:
        raise ToolError("diff takes at most two revisions, e.g. args='HEAD~1' or args='main feature'.")
    sep = ["--", *paths] if paths else []
    if revs:
        title = f"Changes since {revs[0]} (working tree)" if len(revs) == 1 else f"Changes {revs[0]} to {revs[1]}"
        sections = [(title, revs)]
    else:
        sections = [("Unstaged changes", []), ("Staged changes", ["--cached"])]
    budget, parts = DIFF_LINES, []
    for title, flag in sections:
        rc, stat, err = await _git(ctx, "diff", *flag, "--stat=100", *sep)
        _need(rc, stat, err)
        if not stat.strip():
            continue
        rc, body, err = await _git(ctx, "diff", *flag, "--no-color", *sep)
        _need(rc, body, err)
        lines = body.splitlines()
        shown = lines[:max(budget, 0)]
        budget -= len(shown)
        text = f"{title}:\n{stat.rstrip()}\n\n" + "\n".join(shown)
        if len(lines) > len(shown):
            text += f"\n... {len(lines) - len(shown)} more diff lines not shown. Pass one file path to see just that file."
        parts.append(text.rstrip())
    if parts:
        return "\n\n".join(parts)
    if revs:
        return f"No changes between {' and '.join(revs) if len(revs) == 2 else revs[0] + ' and the working tree'}."
    return "No changes. (Untracked files do not appear in a diff; use status.)"


async def _log(ctx, toks):
    n = 15
    if toks and toks[0].isdigit():
        n = min(max(int(toks[0]), 1), 200)
        toks = toks[1:]
    revs, paths = await _revs_paths(ctx, toks)
    rc, out, err = await _git(ctx, "log", f"-n{n}", "--date=short", "--format=%h %ad %s", *revs,
                              *(["--", *paths] if paths else []))
    if rc and "does not have any commits" in err:
        return "No commits yet."
    _need(rc, out, err)
    if out.strip():
        return out.rstrip()
    return f"No commits touch {', '.join(paths)}." if paths else "No commits."


async def _show(ctx, toks):
    _no_flags(toks)
    if len(toks) > 2:
        raise ToolError("show takes a revision and at most one path, e.g. args='HEAD~1' or args='abc123 src/app.py'.")
    rev = toks[0] if toks else "HEAD"
    paths = _paths(ctx, toks[1:])
    sep = ["--", *paths] if paths else []
    if ":" in rev:  # blob: rev:path
        rc, out, err = await _git(ctx, "show", "--no-color", rev)
        _need(rc, out, err)
        return _cap(out, DIFF_LINES, "Use Read for the full file.")
    rc, head, err = await _git(ctx, "show", "--stat=100", "--format=medium", "--no-color", rev, *sep)
    _need(rc, head, err)
    rc, body, err = await _git(ctx, "show", "--format=", "--no-color", rev, *sep)
    _need(rc, body, err)
    return head.rstrip() + "\n\n" + _cap(body, DIFF_LINES, "Pass a path after the revision to see one file.")


async def _branch(ctx, toks):
    flag = []
    if toks:
        if [t.lower() for t in toks] in (["-a"], ["all"], ["--all"]):
            flag = ["--all"]
        else:
            raise ToolError("Refused: branch only lists branches (optionally args='all'). Creating, deleting or "
                            "switching branches is not available.")
    rc, out, err = await _git(ctx, "branch", "--list", "-vv", "--no-color", *flag)
    _need(rc, out, err)
    return out.rstrip() or "No branches yet (no commits)."


async def _blame(ctx, toks):
    rng = []
    if len(toks) == 2 and re.fullmatch(r"\d+[,-]\d+", toks[1]):
        rng = ["-L", toks[1].replace("-", ",")]
        toks = toks[:1]
    paths = _paths(ctx, toks)
    if len(paths) != 1:
        raise ToolError("blame needs exactly one file path, optionally followed by a line range: args='src/app.py 10-40'.")
    rc, out, err = await _git(ctx, "blame", "--date=short", *rng, "--", paths[0])
    _need(rc, out, err)
    return _cap(out, DIFF_LINES, "Add a line range, e.g. args='src/app.py 10-40'.")


async def _add(ctx, toks):
    paths = _paths(ctx, toks)
    if not paths:
        raise ToolError("add needs paths, e.g. args='src/app.py README.md', or args='.' for everything under the project.")
    rc, out, err = await _git(ctx, "add", "--", *paths)
    _need(rc, out, err)
    shown = ", ".join(paths[:30]) + (f", ... and {len(paths) - 30} more ({len(paths)} paths)" if len(paths) > 30 else "")
    return "Staged: " + shown + "\n" + await _status(ctx, [])


async def _commit(ctx, message: str):
    msg = message.strip()
    if len(msg) >= 2 and msg[0] == msg[-1] and msg[0] in "\"'":
        msg = msg[1:-1].strip()
    if not msg:
        raise ToolError("Refused: empty commit message. Pass the message as args, e.g. args='Fix login redirect'.")
    if msg.startswith("-"):
        raise ToolError("Refused: args must be only the commit message text. Options such as -m, -a, --amend and "
                        "--no-verify are not allowed.")
    rc, _, _ = await _git(ctx, "diff", "--cached", "--quiet")
    if rc == 0:
        st = await _status(ctx, [])
        raise ToolError("Nothing is staged, so there is nothing to commit. Stage files first with "
                        "Git(action='add', args='<paths>').\n" + st)
    rc, out, err = await _git(ctx, "commit", "-m", msg)
    if rc:
        text = (out + "\n" + err).strip()
        hint = ("\nGit has no author identity configured. Ask the user to run git config user.name / user.email."
                if re.search(r"tell me who you are|empty ident|unable to auto-detect", text) else "")
        raise ToolError(_clip(text, 3000) + hint)
    return out.strip()


def _read_text(p: Path):
    try:
        return p.read_text() if p.exists() else ""
    except (OSError, UnicodeDecodeError):
        return None


async def _restore(ctx, toks):
    _no_flags(toks)
    if len(toks) != 1:
        raise ToolError("Refused: restore takes exactly one file path, e.g. args='src/app.py'. It discards that file's unstaged edits.")
    p = ctx.path(toks[0])
    if p == ctx.root or p.is_dir():
        raise ToolError("Refused: restore works on a single file, not a directory or '.'.")
    rel = ctx.rel(p)
    rc, out, err = await _git(ctx, "ls-files", "--error-unmatch", "--", rel)
    if rc:
        raise ToolError(f"{rel} is not tracked by git, so there is nothing to restore it from.")
    rc, out, err = await _git(ctx, "diff", "--quiet", "--", rel)
    if rc == 0:
        return f"{rel} has no unstaged changes. Nothing to restore."
    old = _read_text(p)
    rc, out, err = await _git(ctx, "restore", "--worktree", "--", rel)
    _need(rc, out, err)
    new = _read_text(p)
    if old is not None and new is not None:
        d = make_diff(old, new)
        ctx.meta = {"path": rel, "diff": d, "new_text": new}
        return f"Restored {rel} to the staged/committed version ({d['added']} lines added back, {d['removed']} removed)."
    return f"Restored {rel} to the staged/committed version."


HANDLERS = {"status": _status, "diff": _diff, "log": _log, "show": _show, "branch": _branch, "blame": _blame,
            "add": _add, "restore": _restore}


async def Git(ctx, action, args=""):
    parts = str(action or "").strip().split(None, 1)
    if parts and parts[0].lower() == "git" and len(parts) > 1:
        parts = parts[1].split(None, 1)
    act = parts[0].lower() if parts else ""
    args = str(args or "")
    if len(parts) > 1 and not args.strip():
        args = parts[1]
    if act not in ALLOWED:
        allowed = ", ".join(ALLOWED)
        if act in REFUSED_NOTE:
            raise ToolError(f"Refused: git {act} is not available here ({REFUSED_NOTE[act]}). Allowed actions: {allowed}. "
                            "Ask the user to run it themselves if it is really needed.")
        raise ToolError(f"Refused: {act or 'empty action'!r} is not an allowed git action. Allowed actions: {allowed}.")
    top = await _toplevel(ctx)
    if act == "commit":
        res = await _commit(ctx, args)
    else:
        res = await HANDLERS[act](ctx, _split(args))
    if act in READ_ACTIONS and Path(top) != ctx.root:
        res = f"(repository root: {top})\n" + res
    return _clip(res, 12000)


# ------------------------------------------------------------------ registry

def _spec(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


_S = {"type": "string"}

TOOLS = {
    "RunTests": ("shell", RunTests, _spec("RunTests",
        "Run the project's tests and get a short summary: counts, the names of failing tests with one-line reasons, "
        "and the last lines of output when something failed. Detects pytest, unittest, node --test or npm test by itself. "
        "Use this after changing code instead of running tests through Bash.",
        {"command": {**_S, "description": "optional test command (a test runner only); leave empty to auto-detect, e.g. 'pytest tests/test_x.py -k login'"},
         "path": {**_S, "description": "project subdirectory to test, default ."}}, [])),
    "Git": ("shell", Git, _spec("Git",
        "Safe git. Read: status, diff (args: optional path), log (args: optional count and path), show (args: revision, default HEAD), "
        "branch (lists), blame (args: path). Change: add (args: paths), commit (args: message text only), restore (args: one file; "
        "discards its unstaged edits). Push, pull, reset, checkout, stash, rebase, merge, clean and force flags are refused. "
        "Use this instead of Bash for git.",
        {"action": {**_S, "enum": list(ALLOWED), "description": "git action"},
         "args": {**_S, "description": "paths, revision or commit message, depending on the action"}}, ["action"])),
}
