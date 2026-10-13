---
name: testing
description: How to write tests that catch real bugs and how to keep two implementations consistent
triggers: test, tests, testing, pytest, unittest, jest, tdd, coverage, regression, testen
---
# Testing

- Test **behavior from the requirement**, not what your code happens to do. Derive cases from the spec: normal, boundary (0, 1, empty, max), error paths, and the odd cases a user would try.
- Name each test after the behavior: `test_division_by_zero_raises`, not `test_3`.
- One assertion idea per test. Table-driven cases (a list of inputs and expected outputs) keep tests short and readable.
- Check the **error type and message**, not only that something raised.
- Never edit a test to make it pass unless the test itself is wrong; say so when you do.
- **Two implementations of the same logic** (e.g. Python and JavaScript): put the cases in one data file (`cases.json`) that both test suites read.
- Run the whole suite before you say you are done. Report the real counts ("41 passed"), never claim success without running.
- Fast and deterministic: no network, no real time, no random without a seed.
- Python: use `python3 -m venv .venv` in the project and install pytest there; or `uv run --with pytest pytest`. Never install into the global or tool environment.
