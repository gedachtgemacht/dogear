---
name: refactor
description: Safe refactoring and simplification without changing behavior
triggers: refactor, refactoring, clean up, cleanup, simplify, restructure, rename, aufräumen, vereinfachen, umbenennen
---
# Refactoring

1. **Pin behavior first.** Run the tests (or write characterization tests for the current outputs) before touching anything. No tests and no way to check: say so and keep changes tiny.
2. **Small, mechanical steps**, each one verified: rename, extract function, inline, move. Run the tests after every step.
3. **Rename across the whole project.** Use `Grep` for every usage (code, tests, docs, config, strings) before and after; the old name must have zero hits afterwards.
4. **Do not mix** refactoring with behavior changes or new features.
5. Remove dead code and duplication only when you have verified it is unused (grep, tests).
6. Prefer deleting code to adding abstraction. Three similar lines are better than a premature framework.
7. Finish by showing the diff summary: what moved, what was renamed, test results before and after.
