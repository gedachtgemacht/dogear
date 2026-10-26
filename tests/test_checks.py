"""Runs the self-contained check scripts in this folder under pytest.

Each `check_*.py` prints PASS/FAIL lines and exits non-zero on failure; it can also be run on its own
(`uv run python tests/check_skills.py`). Checks that need a browser, a local model or the design dataset
are skipped automatically when that is not available, so `uv run pytest` works on a bare checkout.
"""
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# script -> (extra args, needs)
CHECKS = {
    "check_skills.py": ([], set()),
    "check_profiles.py": ([], set()),
    "check_websearch.py": ([], set()),
    "check_memory.py": ([], set()),
    "check_autosave.py": ([], set()),
    "check_devtools_run.py": ([], set()),
    "check_devtools_code.py": ([], set()),
    "check_mcp_http.py": ([], set()),
    "check_planning.py": ([], set()),
    "check_approvals.py": ([], set()),
    "check_plan_turns.py": ([], set()),
    "check_ultra.py": (["--offline"], set()),
    "check_library.py": ([], {"ollama"}),
    "check_audit.py": ([], {"chrome"}),
    "check_copycheck.py": ([], {"chrome", "ollama"}),
    "check_static_check.py": ([], {"dataset"}),
}


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


AVAILABLE = {
    "chrome": any(shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")),
    "ollama": _port_open(11434),
    "dataset": (REPO / "data" / "design-dataset-300").is_dir(),
}


@pytest.mark.parametrize("script", sorted(CHECKS))
def test_check(script):
    args, needs = CHECKS[script]
    missing = [n for n in needs if not AVAILABLE[n]]
    if missing:
        pytest.skip(f"needs {', '.join(missing)}")
    r = subprocess.run([sys.executable, str(HERE / script), *args], cwd=REPO, capture_output=True, text=True, timeout=900)
    fails = [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
    assert r.returncode == 0 and not fails, f"{script} exit {r.returncode}\n" + "\n".join(fails) + "\n" + r.stdout[-3000:] + r.stderr[-2000:]
