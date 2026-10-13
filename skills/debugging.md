---
name: debugging
description: A disciplined way to find and fix a bug instead of probing at random
triggers: bug, debug, debugging, fix, fails, failing, failure, broken, error, exception, traceback, crash, stack trace, doesn't work, geht nicht, fehler, kaputt
---
# Debugging

1. **Reproduce first.** Get one command that shows the failure. Write down expected vs actual. If you cannot reproduce it, say so instead of guessing.
2. **Read before you probe.** Read the whole function that produces the wrong result, once, slowly. Most bugs are visible: off-by-one, missing `continue`/`return`, wrong variable, shadowed name, mutated input, wrong operator precedence.
3. **Trace by hand.** Take the smallest failing input and step through the code line by line, writing the value of each variable. The line where your expectation breaks is the bug.
4. **One hypothesis, one test.** State the hypothesis ("the loop skips the char after a number"), then run ONE check that could prove it wrong. No shotgun `print`s, no rewriting large parts.
5. **Fix the cause, not the symptom.** No special-casing the failing input. Make the smallest change.
6. **Prove it.** Re-run the reproduction and the full test suite. Add a regression test for the exact case.
7. **If three probes did not move you forward**, stop. Re-read the code from the top, or bisect (halve the input or the code path) rather than adding more output.
