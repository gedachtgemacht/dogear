# Changelog

## 0.2.0 (2026-10-26), first public release

- Repository reorganised for readers: `dogear/` (package), `web/` (UI), `skills/`, `scripts/` (benchmark, calibration, screenshots, run a task), `tests/` (pytest entry, check scripts, live end-to-end scripts, fixtures). Benchmark results moved out of the tree into `data/bench/`.
- `python -m dogear` (and the `dogear` script): `--port`, `--root`, `--open`, `--reload`; `DOGEAR_ROOT` and `DOGEAR_PORT` as environment variables.
- `scripts/install-desktop.sh`: run dogear as a user service that starts at login, plus an application-menu launcher.
- MCP over Streamable HTTP (`{"url": …, "headers": …}` in `mcp.json`), next to stdio. Session id, SSE answers and server pings are handled.
- The empty session shows the modes, four starting points and the recent sessions instead of a blank page.
- The UI script is split into six files by concern (core, sidebar, chat, workspace, board, app); no behaviour change.
- `uv run pytest` runs every check that can run on the machine and skips the ones that need a browser, a model or the design dataset.
- `/init` writes `DOGEAR.md` (it still said `KERF.md`).
- Plan flow phase 3: after approval the harness runs the board one task per turn; `complete_current_task` and `request_replan` close a task or send the plan back; task log on the plan card; review and quality gate once after the last task.
- README, architecture notes, MIT license.

## Before 0.2.0

Built between 2026-10-11 and 2026-10-15 as a personal tool: agent loop with Claude Code style tools, live workspace (editor, browser, terminal), permission modes, shadow checkpoints and undo, branches and parallel variants in worktrees, plan mode with an approval board, kanban, memory and a snippet library, skills, model profiles, the measured visual audit and copy check, Ultra multi-agent runs, MCP over stdio, compaction, image input.
