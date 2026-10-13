---
name: code-review
description: Checklist for reviewing a change or a code base and writing useful findings
triggers: review, code review, reviewen, prüfe den code, audit, pull request, pr, diff
---
# Code review

Read the change as the reader will. Order your findings by severity and give each one: **where** (file:line), **what is wrong**, **how it fails** (a concrete input or situation), **suggested fix**.

Check, in this order:
1. **Correctness**: does it do what was asked? Edge cases (empty, zero, null, huge, unicode, negative), off-by-one, wrong operator, error handling that swallows failures, race conditions, resource leaks.
2. **Security**: untrusted input reaching a shell, SQL, file path, HTML or URL; secrets in code; missing authorization.
3. **Tests**: do they cover the changed behavior and the failure paths? Would they fail if the code were wrong?
4. **Design**: duplicated logic, wrong abstraction level, leaky interfaces, names that lie.
5. **Style**: only what a linter would not catch and only if it hurts readability.

Rules: only report problems you can point to in the code. Do not invent issues to look thorough; "no blocking issues found" is a valid result. Do not rewrite working code to taste. Distinguish must-fix from nice-to-have.
