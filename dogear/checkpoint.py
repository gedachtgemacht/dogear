"""Shadow checkpoints: every agent run can be undone.

Snapshots of the working tree are stored as commit objects under refs/dogear/* using a temporary index.
HEAD, the user's index, branches and stash are never touched, so this is safe in the user's own repos.
In a directory that is not a repo yet, one is created (with a conservative .gitignore).
"""
import os
import subprocess
from pathlib import Path

IGNORE = [".venv/", "venv/", "node_modules/", "__pycache__/", "*.pyc", ".DS_Store", "dist/", "build/", ".env", ".env.*", "*.log"]
MAX_FILES = 20000
ENV = {"GIT_AUTHOR_NAME": "dogear", "GIT_AUTHOR_EMAIL": "dogear@localhost",
       "GIT_COMMITTER_NAME": "dogear", "GIT_COMMITTER_EMAIL": "dogear@localhost"}


def _git(root: Path, *args: str, env: dict | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    e = {**os.environ, **ENV, **(env or {})}
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=e, input=stdin, timeout=60)


def available(root: Path) -> bool:
    return _git(root, "--version").returncode == 0


def ensure_repo(root: Path) -> bool:
    """True when `root` is (or now is) a git work tree we may snapshot."""
    if _git(root, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true":
        # inside a parent repo that ignores this directory: git add would refuse, so give it its own repo
        if _git(root, "check-ignore", "-q", ".").returncode != 0:
            return True
    if root == Path.home() or root == Path("/") or len(root.parts) < 3:
        return False                                  # never turn a home or system directory into a repo
    if _git(root, "init", "-q").returncode != 0:
        return False
    gi = root / ".gitignore"
    have = gi.read_text().splitlines() if gi.exists() else []
    add = [p for p in IGNORE if p not in have]
    if add:
        gi.write_text("\n".join(have + add) + "\n")
    return True


def _too_big(root: Path) -> bool:
    out = _git(root, "ls-files", "-o", "-c", "--exclude-standard").stdout
    return out.count("\n") > MAX_FILES


def checkpoint(root: Path, label: str) -> str | None:
    """Snapshot the working tree. Returns the commit sha, or None if not possible."""
    root = root.resolve()
    if not available(root) or not ensure_repo(root) or _too_big(root):
        return None
    top = Path(_git(root, "rev-parse", "--show-toplevel").stdout.strip() or root)
    gitdir = Path(_git(root, "rev-parse", "--absolute-git-dir").stdout.strip())
    idx = {"GIT_INDEX_FILE": str(gitdir / "dogear-index")}
    (gitdir / "dogear-index").unlink(missing_ok=True)
    if _git(top, "add", "-A", "--", str(root), env=idx).returncode != 0:
        return None
    tree = _git(top, "write-tree", env=idx).stdout.strip()
    (gitdir / "dogear-index").unlink(missing_ok=True)
    if not tree:
        return None
    parent = _git(top, "rev-parse", "-q", "--verify", "refs/dogear/checkpoints").stdout.strip()
    args = ["commit-tree", tree, "-m", label[:200]] + (["-p", parent] if parent else [])
    sha = _git(top, *args).stdout.strip()
    if not sha:
        return None
    _git(top, "update-ref", "refs/dogear/checkpoints", sha)
    return sha


def changed_since(root: Path, sha: str) -> list[str]:
    """Paths whose content differs between checkpoint `sha` and the working tree now."""
    now = checkpoint(root, "dogear: compare")
    if not now:
        return []
    top = Path(_git(root, "rev-parse", "--show-toplevel").stdout.strip())
    out = _git(top, "diff", "--name-status", "--no-renames", sha, now).stdout
    return [l.split("\t", 1)[1] for l in out.splitlines() if "\t" in l]


def restore(root: Path, sha: str) -> list[str]:
    """Bring the working tree back to checkpoint `sha`. Files added since are removed. Returns touched paths."""
    root = root.resolve()
    if not available(root):
        return []
    top = Path(_git(root, "rev-parse", "--show-toplevel").stdout.strip())
    before_undo = checkpoint(root, "dogear: before undo")   # so an undo can be undone
    if not before_undo:
        return []
    out = _git(top, "diff", "--name-status", "--no-renames", sha, before_undo).stdout
    touched = []
    for line in out.splitlines():
        status, _, path = line.partition("\t")
        target = top / path
        if status == "A":                              # added after the checkpoint
            target.unlink(missing_ok=True)
        else:                                          # modified or deleted: take the old version back
            _git(top, "restore", "--source", sha, "--worktree", "--", path)
        touched.append(path)
    return touched
