"""Regression tests for skill trigger matching and the skill files. usage: uv run python tests/check_skills.py"""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dogear import tools
from dogear.agent import SKILLS_DIR, load_skills

ROOT = Path("/tmp")   # no project skills under /tmp/.dogear
NEW = ["planning", "asking-questions", "ultracode", "javascript-frontend", "api-design", "sql-database", "shell-scripting", "performance", "explain-code"]
results = []


def check(name: str, ok: bool, detail: str = ""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail and not ok else ""))


def parse(name: str) -> tuple[list[str], str]:
    m = re.match(r"---\n(.*?)\n---\n(.*)", (SKILLS_DIR / f"{name}.md").read_text(), re.S)
    meta = dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l)
    return [t.strip().lower() for t in meta["triggers"].split(",") if t.strip()], m.group(2)


def hits(name: str, text: str) -> int:
    """Count triggers the same way load_skills does."""
    return sum(1 for t in parse(name)[0] if re.search(r"(?<![a-zäöü])" + re.escape(t) + r"(?![a-zäöü])", text.lower()))


def names(text: str) -> list[str]:
    return load_skills(text, ROOT)[1]


# issue 1: generic single words must not select a skill
for text, absent in [
    ("Fix the rest of the failing tests in the login form", "api-design"),
    ("git fetch and rebase onto main", "javascript-frontend"),
    ("Make a multiple choice quiz game with 10 questions", "asking-questions"),
    ("Run the pytest suite in parallel with xdist", "ultracode"),
    ("Add config options to the settings dialog", "asking-questions"),
    ("Implement the settings page with a feature flag", "planning"),
    ("Open the db file and print the first row", "sql-database"),
    ("Why does the slow loop print twice", "performance"),
    ("List the api keys in the env file", "api-design"),
]:
    got = names(text)
    check(f"no {absent} for: {text}", absent not in got, str(got))
check("web-design still selected for 'form' next to rest/tests", "web-design" in names("Fix the rest of the failing tests in the login form"))
check("git-workflow selected for git fetch", names("git fetch and rebase onto main")[:1] == ["git-workflow"])
# the specific phrases still select their skill
for text, want in [
    ("Design a REST API for the inventory", "api-design"),
    ("The page is too slow, speed up the render", "performance"),
    ("Use the fetch API to load the list", "javascript-frontend"),
    ("Ask me which option I prefer, use AskUser", "asking-questions"),
    ("Review the entire codebase with parallel agents", "ultracode"),
    ("Make a plan for the new feature", "planning"),
]:
    check(f"{want} selected for: {text}", want in names(text), str(names(text)))

# issue 2: one phrase is one hit, no trigger is contained in another trigger of the same file
for n in NEW:
    trig = parse(n)[0]
    over = [(a, b) for a in trig for b in trig if a != b and re.search(r"(?<![a-zäöü])" + re.escape(a) + r"(?![a-zäöü])", b)]
    check(f"{n}: no overlapping triggers", not over, str(over))
    check(f"{n}: no duplicate triggers", len(trig) == len(set(trig)))
for text, name, want in [("Implement the new feature and fix the failing test in the form", "planning", 1),
                         ("Fix the bug in the new feature form test", "planning", 1),
                         ("Make a plan first", "planning", 1),
                         ("Explain this code", "explain-code", 1),
                         ("Explain the code", "explain-code", 1),
                         ("Write a shell script", "shell-scripting", 1),
                         ("Write a bash script", "shell-scripting", 1),
                         ("Create a sqlite3 file", "sql-database", 1),    # was sqlite + sqlite3
                         ("Use vanilla javascript", "javascript-frontend", 1),
                         ("Use vanilla js", "javascript-frontend", 1),
                         ("Run ultra on the whole codebase", "ultracode", 2)]:
    n = hits(name, text)
    check(f"{name}: {n} hits (max {want}) for: {text}", n <= want, f"hits={n}")

# issue 3: the skill must not send the model to a tool that is not registered
body = parse("ultracode")[1]
if "Ultra" not in tools.TOOLS:
    check("ultracode: Ultra is conditional on the tool list", "no Ultra" in body and "tool list" in body)
    check("ultracode: no unconditional 'Use Ultra when'", "Use Ultra when" not in body)
    check("ultracode: no invented 'pattern' parameter", "pattern" not in body.lower())
check("ultracode: Task is still documented and exists", "Task" in tools.TOOLS and "**Use Task**" in body)
check("ultracode: no invented parameter names", not re.search(r"\b(pattern|mode|depth|agents)\s*=", body))

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
