---
name: git-workflow
description: Making clean commits and working safely with git
triggers: git, commit, commits, branch, merge, rebase, pull request, push, checkout, stash, gitignore
---
# Git workflow

- Look first: `git status`, `git diff`, `git log --oneline -10`. Never assume the state.
- Commit only what belongs together; do not commit generated files, secrets, `.venv`, `node_modules`.
- Message: imperative, specific, under 72 chars for the subject ("Fix division by zero in evaluate"), a short body explaining *why* if not obvious.
- Do not rewrite history that was shared (`push --force`, `rebase` on pushed commits), do not `reset --hard` or `clean -fd` without the user asking.
- Do not push, tag or open pull requests unless asked.
- If the working tree has the user's uncommitted changes, leave them alone and say so.
