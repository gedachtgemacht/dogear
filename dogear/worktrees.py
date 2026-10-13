"""Parallel branches: every branch run works in its own git worktree, so runs never collide on files.

A worktree is cheap (it shares the object store) and is created from a checkpoint commit, so it starts from the exact
file state of the branch point. Dependencies that git ignores (node_modules, .venv) are symlinked from the original
project. Results are brought back with adopt(), which only touches files that did not change in the project since the
branch point and reports the rest as conflicts.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import checkpoint as cp

BASE = Path(__file__).resolve().parent.parent / "data" / "worktrees"
LINK_IGNORED = (".venv", "venv", "node_modules", ".env", ".env.local", "vendor")


def _slug(s: str) -> str:
    return re.sub(r"[^\w.-]+", "-", s).strip("-")[:40] or "x"


def _git(top: Path, *args: str, check=False, text=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(top), *args], capture_output=True, text=text, check=check, timeout=120,
                          env={**os.environ, **cp.ENV})


def toplevel(root: Path) -> Path:
    out = _git(root, "rev-parse", "--show-toplevel").stdout.strip()
    if not out:
        raise RuntimeError(f"{root} is not inside a git work tree")
    return Path(out)


def create(root: Path, name: str, sha: str | None = None) -> tuple[Path, str]:
    """Create a worktree for the project at `root` from checkpoint `sha` (or the current state).
    Returns (project path inside the worktree, base sha)."""
    root = root.resolve()
    base = sha or cp.checkpoint(root, "dogear: branch base")
    if not base:
        raise RuntimeError("Could not snapshot the project (too large, or git is unavailable).")
    top = toplevel(root)
    dest = BASE / f"{_slug(top.name)}-{_slug(name)}"
    BASE.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        _git(top, "worktree", "remove", "--force", str(dest))
        shutil.rmtree(dest, ignore_errors=True)
    r = _git(top, "worktree", "add", "--detach", str(dest), base)
    if r.returncode != 0:
        raise RuntimeError(f"git worktree failed: {r.stderr.strip()[:200]}")
    rel = root.relative_to(top)
    proj = dest / rel
    proj.mkdir(parents=True, exist_ok=True)
    for n in LINK_IGNORED:                       # share ignored dependencies instead of copying them
        src, dst = root / n, proj / n
        if src.exists() and not dst.exists():
            try:
                dst.symlink_to(src, target_is_directory=src.is_dir())
            except OSError:
                pass
    return proj, base


def _blob(top: Path, rev: str, path: str) -> bytes | None:
    r = subprocess.run(["git", "-C", str(top), "cat-file", "-p", f"{rev}:{path}"], capture_output=True, timeout=30)
    return r.stdout if r.returncode == 0 else None


def changes(worktree_project: Path, base: str) -> list[tuple[str, str]]:
    """[(status, path)] of what the branch changed relative to its base (paths relative to the git top)."""
    now = cp.checkpoint(worktree_project, "dogear: branch state")
    if not now:
        return []
    top = toplevel(worktree_project)
    out = _git(top, "diff", "--name-status", "--no-renames", base, now).stdout
    res = []
    for line in out.splitlines():
        st, _, path = line.partition("\t")
        if path and not set(Path(path).parts) & set(LINK_IGNORED):     # linked dependencies are not part of the work
            res.append((st, path))
    return res


def adopt(root: Path, worktree_project: Path, base: str) -> dict:
    """Bring the branch's changes into the original project. Conflicts (changed in both places) are left alone."""
    root = root.resolve()
    top_main, top_wt = toplevel(root), toplevel(worktree_project)
    before = cp.checkpoint(root, "dogear: before adopting a branch")      # so the adoption can be undone
    applied, conflicts = [], []
    for st, path in changes(worktree_project, base):
        src, dst = top_wt / path, top_main / path
        in_base = _blob(top_main, base, path)
        current = dst.read_bytes() if dst.exists() else None
        if current != in_base:                                           # the project changed here since the branch point
            if not (st == "A" and current is None):
                conflicts.append(path)
                continue
        if st == "D":
            dst.unlink(missing_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        applied.append(path)
    return {"applied": applied, "conflicts": conflicts, "undo": {"sha": before, "root": str(root)} if before else None}


def remove(worktree_project: Path):
    try:
        top = toplevel(worktree_project)
        wt = top
        if top and BASE in wt.parents or wt == BASE:
            origin = _git(wt, "rev-parse", "--git-common-dir").stdout.strip()
            main = Path(origin).resolve().parent if origin else None
            if main:
                _git(main, "worktree", "remove", "--force", str(wt))
        shutil.rmtree(wt, ignore_errors=True)
    except Exception:
        pass
