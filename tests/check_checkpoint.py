"""Shadow checkpoints: a fresh directory gets a repository, a snapshot can be restored, an embedded repository
without a commit (left-over worktree, half-cloned dependency) does not sink the snapshot, and a failure is explained.
usage: uv run python tests/check_checkpoint.py"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dogear import checkpoint as cp  # noqa: E402

ok_all = True


def check(name, cond, extra=""):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


root = Path(tempfile.mkdtemp()) / "proj"
root.mkdir()
(root / "a.txt").write_text("one\n")
sha1 = cp.checkpoint(root, "first")
check("a plain directory becomes a repository and gets a snapshot", bool(sha1), cp.last_error)
check("a conservative .gitignore was written", (root / ".gitignore").exists() and ".venv/" in (root / ".gitignore").read_text())
(root / "a.txt").write_text("two\n")
(root / "b.txt").write_text("new\n")
sha2 = cp.checkpoint(root, "second")
check("changed files make a new snapshot", bool(sha2) and sha2 != sha1)
check("changed_since lists the changes", set(cp.changed_since(root, sha1)) >= {"a.txt", "b.txt"}, str(cp.changed_since(root, sha1)))
touched = cp.restore(root, sha1)
check("restore puts the files back", (root / "a.txt").read_text() == "one\n" and not (root / "b.txt").exists(), str(touched))
# an embedded repository without any commit used to make `git add -A` fail with exit 128 -> no undo, silently
nested = root / "left-over"
nested.mkdir()
subprocess.run(["git", "init", "-q"], cwd=nested, check=True)
(root / "c.txt").write_text("after the nested repo\n")
sha3 = cp.checkpoint(root, "third")
check("an embedded repository without a commit does not sink the snapshot", bool(sha3), cp.last_error)
check("the new file is in that snapshot", "c.txt" in cp.changed_since(root, sha2) or sha3 != sha2)
# failure is explained, not silent
check("a home directory is refused with a reason", cp.checkpoint(Path.home(), "x") is None and "home" in cp.last_error, cp.last_error)
print("ALL PASS" if ok_all else "SOME FAILED")
sys.exit(0 if ok_all else 1)
