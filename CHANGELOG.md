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
- The chat shows the process folded and the answer once: one status block per turn (working, waiting for you, checking, done, stopped), the last three steps while it runs, everything else behind "Show steps"; questions and permissions appear in the status block and in the window title; panels never open by themselves.
- The receipt: tests, page audit before and after the fix pass, console errors, and a status the harness computed (Verified / Unverified / Stopped).
- Modes renamed by what they ask (Ask all, Ask commands, Don't ask); "Plan first" is a toggle on the composer, not a mode. The kanban column is a one-line task strip above the chat.
- Quieter: sans for what the UI says, mono only for machine data; dots carry state, no second accent colour; diffs no longer wrap and are capped; drawer with a scrim; settings grouped.
- Cut from the UI and the model's toolbox (code kept): Ultra, rating and snippet learning, outline and pins, answer re-rendering, twelve generic skills (now in `skills/extra`). Parallel variants are a setting.
- Open approvals and questions reach windows that join later. Switching the mode applies at once, also to the running turn; "Don't ask" grants whatever is waiting, and every window drops the question.
- Checkpoints survive an embedded repository without a commit (a left-over worktree); when a checkpoint is impossible, the run says why instead of silently offering no Undo.
- Answers render Markdown tables, numbered lists and rules; the prompt asks for plain words instead of emoji markers.
- Code: `Agent.turn()` split into named pieces with `RunConfig` and `TurnStats`; the WebSocket handler is a table of small functions on a `Conn` object; library learning moved to `learning.py`; silent exceptions now log; one shared `rel_paths`.
- Plan execution: every task turn gets a fresh, small context (briefing with request, board and changed files, plus the task's own messages) instead of the whole transcript; the task log shows the context size.
- README, architecture notes, MIT license.

## Before 0.2.0

Built between 2026-10-11 and 2026-10-15 as a personal tool: agent loop with Claude Code style tools, live workspace (editor, browser, terminal), permission modes, shadow checkpoints and undo, branches and parallel variants in worktrees, plan mode with an approval board, kanban, memory and a snippet library, skills, model profiles, the measured visual audit and copy check, Ultra multi-agent runs, MCP over stdio, compaction, image input.
