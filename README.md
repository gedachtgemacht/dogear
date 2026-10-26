# dogear

A coding agent that runs on your own machine, with a workspace you can watch.

dogear talks to a local model through [Ollama](https://ollama.com), gives it the tools a coding agent needs (read, write, edit, search, shell, tests, git, a real browser), and shows you what it does while it does it: files being typed, diffs, the terminal, and a live browser that you and the agent share. Nothing leaves your machine unless the agent opens a web page.

<p align="center">
  <img src="docs/screenshots/session-dark.png" width="820" alt="A session: the chat on the left with tool cards and a diff, the plan board on the right">
</p>

## What it does

- **Claude Code style tools.** `Read`, `Write`, `Edit`, `MultiEdit`, `Glob`, `Grep`, `LS`, `Bash` (with background processes), `RunTests`, `Git`, `Outline`, `FindSymbol`, `WebSearch`, `WebFetch`, `TodoWrite`, `Task` (sub-agent), `AskUser` (multiple-choice forms) and more. Names and shapes follow the Claude Code conventions, so models that learned them use them well.
- **A browser you both control.** Headless Chrome with its own profile, driven over the DevTools protocol by a small built-in client. The agent navigates, reads the page as element refs, clicks and types; you watch the screencast in the UI and can take over at any time. CAPTCHAs and logins are never bypassed: the agent hands over to you.
- **Live workspace.** New files are typed in line by line, edits are shown as diffs with the changed lines flashed, shell output streams into a terminal panel, and a preview server serves the project on a separate origin.
- **Permission modes.** Review (confirm every edit and command), Edits (edit freely, confirm commands), Auto (never ask), Plan (read-only: the model investigates and proposes a task board that you approve, edit or reject before anything runs).
- **Undo.** Every run starts with a shadow checkpoint of the project (a git commit under `refs/dogear/...`, never touching your branches). One click puts the files back.
- **Branches and parallel variants.** Branch a conversation from any turn, edit an earlier message and re-run, or start two to four variants in parallel, each in its own git worktree. Compare answers side by side, adopt the files of the one you like.
- **Plan board.** A kanban (to do / doing / done) that the agent keeps current and that you can edit and drag; the model sees your changes.
- **Quality gate for web work.** After changes to HTML/CSS/JS the harness measures the page itself (overflow, contrast, holes in grids, empty boxes, tiny targets, placeholder images, generated-UI tells) at desktop and phone width and starts a fix pass when it finds something. Optionally a copy check proofreads the visible text against the brief.
- **Memory and a library.** Notes, snippets and skills the agent learns are saved per project (`<project>/.dogear/`) or globally. Runs you rate as good teach a snippet library with embeddings that later plans draw from.
- **Skills.** Markdown skill files with triggers (`skills/*.md`, plus `<project>/.dogear/skills/`) are loaded into the prompt when the task matches: web design, debugging, testing, code review, API design, security review and more.
- **MCP.** Connect any MCP server over stdio or Streamable HTTP; its tools appear to the model as `mcp__<server>__<tool>`.
- **Model profiles.** Every model is recognised the first time it is used (size, MoE, tools, vision, reasoning) and gets a toolbox and prompt style that fits it. Small models get a lean toolbox and rescue logic for tool calls they write as text.
- **Ultra.** A deterministic multi-agent orchestrator for large reviews, research, design comparisons and audits: finders, adversarial verifiers, synthesis. Lives in the UI as a live tree.
- **Context care.** `/compact` condenses the conversation into a briefing; it happens automatically when the context window is 70 % full. Images can be attached, pasted or dropped.

## Quick start

You need Python 3.12+, [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com) with at least one tool-capable model, and Chrome or Chromium for the browser features.

```sh
ollama pull qwen3.6:35b-a3b      # the default model; any tool-capable model works
git clone https://github.com/gedachtgemacht/dogear
cd dogear
uv run python -m dogear --open   # http://127.0.0.1:7870
```

`./start.sh` does the same. `uv run python -m dogear --help` lists the options (`--port`, `--root`, `--reload`).

Point the project field in the header at a directory, pick a mode, describe a task. Type `/` in the composer for commands (`/plan`, `/compact`, `/ultra`, `/remember`, `/init` …). Shift+Tab cycles the mode, Esc stops a run.

To start dogear at login and get a launcher in the application menu (Linux with systemd):

```sh
scripts/install-desktop.sh          # scripts/install-desktop.sh --remove undoes it
```

### Models

dogear works with every Ollama model that supports tool calls. On a laptop with 30 GB of shared memory the defaults are:

| Role | Model | Why |
|---|---|---|
| main | `qwen3.6:35b-a3b` | 7/7 on the benchmark at ~70 tokens/s |
| helper (titles, suggestions, fast sub-agents) | `qwen3.5:4b` | small and quick; chosen automatically as the smallest installed tool model |
| embeddings (library) | `qwen3-embedding:0.6b` | optional; without it the library falls back to keyword search |

Models with vision get screenshots; models without are told they cannot see the attached image. `scripts/calibrate.py MODEL` measures which toolbox size a new model handles best and records it.

### Project instructions

If the project root contains a `DOGEAR.md` (also `CLAUDE.md` or `AGENTS.md`), its content goes into the system prompt. `/init` asks the agent to write one.

### MCP servers

`mcp.json` in the dogear directory (global) or `.mcp.json` in the project, the same shape Claude Code uses:

```json
{"mcpServers": {
  "files":  {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]},
  "remote": {"url": "http://127.0.0.1:8080/mcp", "headers": {"Authorization": "Bearer …"}}
}}
```

MCP tools always ask for permission outside Auto mode.

## How it is built

No build step, no framework on the front end, few dependencies on the back end.

```
dogear/          the Python package
  server.py      FastAPI: HTTP API, WebSocket, the preview server on a second port
  agent.py       the agent loop: prompt, model → tool calls → permissions → results → model, review pass, quality gate
  tools.py       built-in tools and the browser tools; permission classes (read / write / shell / net / browser)
  browser.py     Chrome over the DevTools protocol: screencast, input, reading the page, consent dialogs, hand-over
  devtools_*.py  MultiEdit, Outline, FindSymbol, RunTests, Git
  planning.py    the plan phase and the approval board
  checkpoint.py  shadow checkpoints and undo
  worktrees.py   parallel variants in git worktrees
  memory.py      notes, snippets and learned skills
  library.py     the snippet library with embeddings
  profiles.py    model detection, toolbox and prompt selection, issue statistics
  audit.py       the measured visual audit and the static source checks
  copycheck.py   proofreading of page copy against the brief
  present.py     turns a finished answer into display blocks
  ultra.py       the multi-agent orchestrator
  mcp.py         MCP client, stdio and Streamable HTTP
  llm.py         streaming client for Ollama
web/             the UI: index.html, style.css and six plain scripts (core, sidebar, chat, workspace, board, app)
skills/          built-in skills
scripts/         benchmark, calibration, design benchmark, screenshots, run a task from the shell
tests/           pytest entry (test_checks.py), the check scripts, live end-to-end scripts, fixtures
data/            runtime state (sessions, images, Chrome profile, library, learned skills); not in git
projects/        default workspace for new sessions; not in git
```

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) describes the agent loop, the WebSocket protocol, the permission model and the data on disk in more detail.

### Safety model

- The server binds to `127.0.0.1` only, and the WebSocket accepts connections only from the page it served (Origin check), so no other web page can drive the agent.
- Project files are served from a second origin (port 7871); pages the agent writes or visits can never reach the agent's API.
- Tools stay inside the project directory. `sudo`, `rm -rf /` and similar are refused in every mode.
- The shell runs with a cleaned environment, so the agent cannot install into dogear's own virtualenv.
- The browser never solves CAPTCHAs, logins or 2FA; it hands over to you. Cookie banners are dismissed with the most restrictive option.
- Secrets (keys, tokens, passwords) are refused by the memory and library tools.

## Tests

```sh
uv run pytest                              # the check scripts that run on this machine (browser, model and dataset checks skip when missing)
uv run python tests/check_skills.py        # any check on its own
uv run python tests/live/smoke.py          # end-to-end scripts: need the server on 7870 and the models
uv run python scripts/bench.py             # benchmark all installed models on small coding tasks
```

## Status

dogear is a personal tool, built in a few weeks, in daily use with local models. It is complete enough to be useful and small enough to read in an afternoon. Things that are known to be rough: visual judgement of the models themselves is weak (that is why the audit measures instead of asking), small models vary a lot between runs, and parallel variants share one browser.

## License

MIT. Built by [gedachtgemacht](https://gedachtgemacht.app).
