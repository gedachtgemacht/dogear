---
name: python-project
description: Conventions for small Python projects, scripts, CLIs and packages
triggers: python, python3, pip, venv, pyproject, cli, script, argparse, flask, fastapi, django, pandas
---
# Python projects

- Layout for small things: `name.py` + `test_name.py`. For packages: `pyproject.toml`, `src/<pkg>/` or `<pkg>/`, `tests/`.
- Environments: project-local virtualenv (`python3 -m venv .venv`) or `uv`. Do not `pip install` into the global or tool environment. Pin nothing you do not need; list real dependencies in `pyproject.toml`.
- Code: type hints on public functions, small functions, explicit exceptions (`ValueError` with a clear message), no bare `except:`, `pathlib` over string paths, f-strings.
- CLI: `argparse` (or `typer` if already used), exit code 0 on success and non-zero on error, error messages to stderr, `if __name__ == "__main__":`.
- Do not use `eval`/`exec` on input. Use `subprocess.run([...], check=True)` with a list, never a shell string with user input.
- Files: read/write with `encoding="utf-8"`; write atomically (temp file + rename) for data users care about.
- Tests: pytest, one test file per module, run them before finishing.
