"""Independent check of the calculator project: values, errors, and Python/JS parity.
usage: python3 tools/calc_eval.py PROJECT_DIR"""
import json, subprocess, sys
root = sys.argv[1]; sys.path.insert(0, root)
import calc
VALUES = [("2+3*4",14),("(2+3)*4",20),("2^3^2",512),("-2^2",-4),("2^-1",0.5),("--3",3),("10/4",2.5),("1.5+2.25",3.75),
          ("sqrt(16)",4),("min(3,1)+max(2,9)",10),("2^3^2 + sqrt(16)",516),("  7 - 2 - 1 ",4),("2*(3+(4-1))",12),("-(2+3)",-5),
          ("max(1,2)*min(5,4)",8),("sqrt(2)*sqrt(2)",2),("3-(-2)",5),(".5+.5",1),("100/10/5",2),("2*-3",-6)]
ERRORS = [("",ValueError),("(2+3",ValueError),("2+*3",ValueError),("2 $ 3",ValueError),("foo(3)",ValueError),("1/0",ZeroDivisionError),
          ("2+",ValueError),("()",ValueError),("max(1)",ValueError),("sqrt(-1)",ValueError),("min()",ValueError),("sqrt(1,2)",ValueError)]
bad = []
for e, v in VALUES:
    try:
        r = calc.evaluate(e)
        if abs(r - v) > 1e-9: bad.append((e, v, r))
    except Exception as x: bad.append((e, v, repr(x)))
ebad = []
for e, exc in ERRORS:
    try: ebad.append((e, "no error", calc.evaluate(e)))
    except exc: pass
    except Exception as x: ebad.append((e, exc.__name__, repr(x)))
print(f"values {len(VALUES)-len(bad)}/{len(VALUES)}", bad or "")
print(f"errors {len(ERRORS)-len(ebad)}/{len(ERRORS)}", ebad or "")
exprs = [e for e, _ in VALUES] + [e for e, _ in ERRORS] + ["0.1+0.2", "1e3", "5%2", "2 3"]
js = f"""const c=require({json.dumps(root + '/calc.js')});const o={{}};
for(const e of {json.dumps(exprs)}){{try{{o[e]=Number(c.evaluate(e))}}catch(x){{o[e]="ERR"}}}}
console.log(JSON.stringify(o))"""
jv = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True).stdout)
diff = []
for e in exprs:
    try: pv = float(calc.evaluate(e))
    except Exception: pv = "ERR"
    j = jv[e]
    if not ((pv == "ERR" and j == "ERR") or (pv != "ERR" and j != "ERR" and abs(pv - j) < 1e-9)): diff.append((e, pv, j))
print(f"python/js parity {len(exprs)-len(diff)}/{len(exprs)}", diff or "")
