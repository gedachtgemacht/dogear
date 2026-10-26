---
name: shell-scripting
description: Writing safe bash and sh scripts and knowing when to use Python instead
triggers: bash, shell, sh, shellscript, shellcheck, zsh, pipefail, heredoc, xargs, one-liner, cron job, shellskript
---
# Shell scripting

1. **Header.** `#!/usr/bin/env bash`, then `set -euo pipefail` and `IFS=$'\n\t'` for scripts of more than a few lines. Say in a comment what the script does and how to call it. Exit non-zero on error, print errors to stderr (`echo "error: ..." >&2`).
2. **Quote every expansion.** `"$var"`, `"${arr[@]}"`, `"$(command)"`. Unquoted variables split on spaces and expand globs. Use `[[ ... ]]` in bash, `=` not `==` in plain sh.
3. **Never parse `ls`.** Use globs (`for f in ./*.txt`), `find ... -print0 | while IFS= read -r -d '' f`, or `find -exec`. Guard the empty-glob case with `[ -e "$f" ] || continue`. Prefix paths with `./` or use `--` so names starting with `-` are not options.
4. **Check arguments and inputs.** `: "${1:?usage: script.sh FILE}"`. Test that files exist before use. Use `local` in functions. Defaults with `${VAR:-default}`.
5. **Temp files and cleanup.** `tmp=$(mktemp -d)` and `trap 'rm -rf "$tmp"' EXIT`. Never write fixed names in `/tmp`. Before `rm -rf "$dir/..."` check that `$dir` is non-empty; `set -u` helps but is not enough.
6. **Commands.** `command -v tool >/dev/null || { echo "tool missing" >&2; exit 1; }`. Use `$(...)` not backticks. Read lines with `while IFS= read -r line`. Prefer `printf` over `echo` for data. Use arrays for argument lists instead of building strings.
7. **shellcheck rules to follow by hand** (run `shellcheck` if installed): quote variables (SC2086), no `cd` without `|| exit` (SC2164), no useless `cat` (SC2002), no `for x in $(cmd)` (SC2013), `read -r` always (SC2162).
8. **Portability.** `#!/bin/sh` means POSIX only: no arrays, no `[[`, no `local` guarantees, no `<(...)`. Differences: GNU versus BSD `sed -i`, `date`, `readlink -f`. If you need arrays, associative maps or `<(...)`, say bash.

**Use Python instead** when the script needs JSON or CSV parsing, more than about 50 lines of logic, nested data, real error handling, arithmetic with decimals, or tests. Keep shell for gluing commands together.

Avoid: `eval`, `curl | sh`, `rm -rf` on a variable path, `cd` side effects in the caller, sudo inside scripts, secrets on the command line (they show in `ps`).

Verify: run it with `bash -n script.sh` and `shellcheck` if available, run it once with a filename containing a space, once with empty input, and confirm the exit code with `echo $?`.
