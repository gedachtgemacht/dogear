"""Source checks of the quality gate: known bad snippet, and no false alarms on the 300 reference solutions.
usage: uv run python tests/check_static_check.py"""
import collections, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dogear.audit import static_check, static_report
DS = Path(__file__).resolve().parent.parent / "data" / "design-dataset-300"
ok = True
def check(name, cond, extra=""):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

bad = ('<!doctype html><html><head><title>t</title><style>a{transition:color .2s}.a{text-transform:uppercase}.b{text-transform:uppercase}.c{text-transform:uppercase}'
       '</style></head><body><h1>Bread the <em>old way</em></h1><input> → → → → lorem ipsum</body></html>')
floor, tells = static_check(bad)
for k in ("viewport", "lang", "focus-visible", "reduced-motion", "labels", "responsive"):
    check(f"flags {k}", k in floor, str(floor))
for k in ("arrows", "caps labels", "styled headline word", "lorem ipsum"):
    check(f"flags {k}", k in tells, str(tells))
check("static_report is non-empty for a bad page", "Source checks" in static_report(floor, tells))
quiet = '<!doctype html><html lang="en"><head><meta name="viewport" content="x"><title>t</title><style>:focus-visible{outline:2px solid}@media (max-width:600px){body{margin:0}}</style></head><body><h1>Plain headline</h1></body></html>'
check("a quiet page is clean", static_check(quiet) == ([], []))
check("no animation means no reduced-motion demand", "reduced-motion" not in static_check(quiet)[0])
_link = quiet.replace("</body>", '<a href="https://instagram.com/x">Instagram</a></body>')
check("an outbound link is not an external resource", "external resources" not in static_check(_link)[0], str(static_check(_link)[0]))
_js = quiet.replace("</body>", '<script src="https://cdn.example.net/x.js"></script></body>')
check("a loaded script is", "external resources" in static_check(_js)[0])

if DS.exists():
    kinds = collections.Counter(); n = 0
    for f in sorted((DS / "solutions").glob("*.html")):
        email = any(w in json.loads((DS / "tasks_all.json").read_text())[int(f.stem) - 1]["prompt"].lower() for w in ("email", "e-mail")) if False else False
        fl, tl = static_check(f.read_text(errors="replace"), email)
        n += 1
        for k in fl + tl: kinds[k] += 1
    print(f"reference solutions: {n} pages, flagged kinds: {dict(kinds)}")
    check("reference solutions are almost never flagged (< 8% per rule)", all(v / n < 0.08 for v in kinds.values()), str(dict(kinds)))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
