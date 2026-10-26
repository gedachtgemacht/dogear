# How dogear works

One Python process, one browser tab, one local model. This page follows a request through the system and then lists the moving parts.

## A turn, start to finish

`Agent.turn()` is short; the work is in named pieces: `_build_system` (the prompt), `_toolbox` (which tools the model sees), `_call_model` (one streamed call with retries), `_nudge` (when the model stops without a tool call), `_run_tool` (permissions and execution), `_guard` (stagnation and repetition), `_record` (statistics, the tool message, the UI events) and `_finish` (gate, self-check, summary, receipt). A `RunConfig` carries what the UI chose; a `TurnStats` carries what the run collected, including into the self-check pass.

1. **The UI sends `{"type": "user", "text": …}`** over the WebSocket, together with the current settings (model, mode, project root, context size, review on/off, attached images).
2. **`server.py` starts `Agent.turn()`** as a task. Only one turn runs per connection; other windows that are open see it live (mirror).
3. **`agent.py` builds the prompt.** The system prompt (`SYSTEM`) plus: project instructions (`DOGEAR.md` …), the skills whose triggers match the request, notes and snippets from memory, the current task list, library hits in plan mode, and a one-level listing of the project. The model profile (`profiles.py`) decides which tools and which prompt variant the model gets.
4. **A shadow checkpoint** of the project is taken (`checkpoint.py`): a commit under `refs/dogear/checkpoints` made with a temporary index, so the user's branches, index and working tree are never touched.
5. **The loop.** `llm.stream()` streams the model's answer from Ollama. Text tokens go to the UI as `token`; a tool call becomes a `tool` event (a card in the chat). Before a tool runs, `_needs_approval()` decides whether the UI has to confirm it (`approval` event, answered with `approve`). The tool runs (`tools.py` and friends), its result goes back to the model as a `tool` message and to the UI as `result`. File changes also emit `changed` with the diff; shell output streams as `term`.
6. **Guards along the way.** Parameter names the model got wrong are repaired (`fix_args`); tool calls written as text are rescued; a model that announces a call instead of making one is nudged; repeated errors or probe loops without an edit are cut off; the plan gate blocks the first write on large tasks until a `TodoWrite` exists; the step limit is 80, after which the model must report.
7. **After the last tool call** the final text is the answer. Then, depending on what happened: a review pass (the model checks its result against the request), the quality gate for web files (`audit.py` measures the page in the browser at desktop and phone width, `static_check` reads the source; findings start a fix pass), the copy check for new pages, auto-learning into the library when tests went green, memory suggestions from the helper model, a title for the session.
8. **`summary`** closes the turn in the UI: steps, seconds, changed files, sources, commands, the checkpoint to undo to, and the **receipt**: the tests the harness saw run (`RunTests` meta), the page it measured (audit before and after the fix pass), console errors it caught, and a status it computed (`verified`, `unverified`, `stopped`, `done`). A stopped or aborted run gets its summary too, so the UI never looks as if it were still running.

## The plan flow

1. **Plan** (mode `plan`): the same loop with read-only tools plus `kanban_create_tasks`; that call ends the phase with a `plan_proposed` event.
2. **Approval**: the board is shown as a card. The user edits, reorders, adds or removes tasks and approves with a permission mode, or rejects with feedback (`plan_reject` plans again).
3. **Execution** (`Agent.run_plan`): the harness hands the model one task per turn ("Task 2 of 5: …", with the summaries of the finished tasks). In these turns the model has two extra tools: `complete_current_task(summary)` closes the task and ends the turn, `request_replan(reason)` stops the execution and sends the plan back to the user with the reason, after which the model plans the remaining work again. A task turn that ends without either call is nudged twice and then logged as `unfinished`. A task turn does not see the whole transcript: the model gets a briefing (the original request, the approved board, the files changed so far in this plan) plus the messages of the current task, so every task starts with a fresh, small context and prompt processing stays short on a laptop; the task log records the largest prompt the model saw. The board (`todos`) is kept by the harness, the review pass and the quality gate run once after the last task, and every task leaves a log entry (`plan.log`: status, summary, steps, seconds) that the plan card shows.
4. **Direction**: for a web brief the plan phase also searches the design-plan library; the approval card shows the three closest plans as pictures (`/api/thumb/{id}`, rendered in a browser of its own and cached). The user's choice is stored on the plan and quoted in every task briefing (`Agent._direction`).

## Permission model

Every tool has a class: `read`, `write`, `shell`, `net` or `browser`. The mode decides:

| | Review (`ask`) | Edits (`edit`) | Auto | Plan |
|---|---|---|---|---|
| read tools | run | run | run | run |
| write tools | confirm | run | run | not available |
| shell | confirm | safe commands run (`ls`, `cat`, `git status` …), others confirm | run | not available |
| browser navigate | confirm for foreign hosts, localhost runs | same | run | same as Edits |
| browser click/type | confirm | run | run | n/a |
| `browser_eval`, MCP tools | confirm | confirm | run | confirm |

"Always allow" remembers a tool (or a site for `browser_navigate`) for the connection. In every mode `tools.DENY` refuses `sudo`, `rm -rf /`, `mkfs`, `dd`, fork bombs and writes to block devices, and every path is resolved inside the project root (symlinks included).

## The WebSocket protocol

Client → server (selection): `user`, `approve`, `answer` (multiple-choice form), `stop`, `new`, `open`, `fork`, `variants`, `adopt`, `discard`, `undo`, `set_todos`, `pin`, `titles`, `rate`, `compact`, `plan_approve`, `plan_reject`, `root`, `mcp_reload`, `kill` (background shell), and the browser messages `b_sub`, `b_open`, `b_nav`, `b_mouse`, `b_key`, `b_text`, `b_scrollto`, `b_viewport`, `b_back`, `b_fwd`, `b_reload`, `b_resume`.

Server → client (selection): `session`, `turn_start`, `thinking`, `token`, `tool`, `sub`, `result`, `changed`, `fs`, `term_start`, `term`, `term_end`, `approval`, `ask`, `todos`, `plan_proposed`, `plan_status`, `ultra`, `notice`, `error`, `usage`, `summary`, `present`, `done`, `forked`, `runs`, `run_status`, `run_event`, `adopted`, `undone`, `rated`, `library_saved`, `auto_saved`, `titles`, `pins`, `renamed`, `compacted`, `mcp`, `profile`, and the browser events `frame`, `b_nav`, `b_status`, `b_act`, `b_marks`, `b_log`, `b_scroll`, `b_need`.

On the server every message type has one small handler in `HANDLERS` (server.py), each taking the connection (`Conn`: its agent, settings, running task, senders) and the message. The browser messages go to `browser_msg`. What a run teaches the library, and when that is taken back, lives in `learning.py`.

Each connection has its own outbound queue and writer task; a slow window drops screencast frames first and never stalls the agent.

## The browser

`browser.py` starts Chrome headless with its own profile (`data/chrome-profile`) and speaks the DevTools protocol over a WebSocket, no Playwright. The screencast is forwarded to subscribed UI connections; user mouse and keyboard events from the UI canvas are forwarded to the page, so user and agent share one session. `browser_read` renders the page as text with element refs (`[e12]`), pierces open shadow roots, and reports consent dialogs and bot walls. Bot walls lead to `browser_handoff`: the run pauses, the UI shows "Your turn", the user solves it in the live view, and the run continues. Project files are served by a second server on port 7871, a different origin from the UI, so a page can never talk to the agent's API.

## Files on disk

```
data/
  settings.json        last used model, mode, context size, root
  sessions/<id>.json   one file per session: messages, todos, pins, titles, parent (for branches), worktree
  images/<sha>.jpg     images attached to messages
  chrome-profile/      the browser's profile (cookies, logins you did in the live view)
  library.db           the snippet library (SQLite, with embeddings)
  learned/             global memory: memory/, snippets/, skills/ as Markdown with front matter
  model_stats.json     per-model counters (text calls, malformed calls, tool errors) that feed the profiles
  profiles.json        manual profile overrides and the preferred helper model ("_helper")
  worktrees/           checkouts for parallel variants
  bench/               benchmark results
<project>/.dogear/     project memory: memory/, snippets/, skills/ (travels with the repo)
```

## The front end

Plain HTML, CSS and six classic scripts that share top-level state through the global lexical scope (load order: `core`, `sidebar`, `chat`, `workspace`, `board`, `app`). No bundler, no framework. `core.js` holds helpers, syntax highlighting, the Markdown renderer and the state object `S`; `chat.js` renders a turn as user message, status block, folded step list, answer and leftovers (changed files, sources), plus the approval and plan cards; `workspace.js` is the editor, the live browser canvas and the output panel; `board.js` is the task strip, sessions based on other sessions and the optional variants; `sidebar.js` is the drawer (sessions, files; memory and MCP from the settings); `app.js` maps every WebSocket event to one handler (`ON`), and holds the composer, slash commands and boot.

The rule for the chat: the process is folded, the answer is rendered once. While a run works, the status block shows the current step and the last three steps; a question for the user replaces the status head and changes the window title; nothing opens a panel by itself, the status block offers links instead.

The design is deliberately quiet: one accent colour, no decoration, one signature (the cut corner of every panel).

## Kept but not offered

`ultra.py` (multi-agent runs), `present.py` (answer re-rendering), the snippet-learning loop (`rate`, auto-learning, `SaveSnippet`/`SaveSkill`/`Forget`) and the generic skills in `skills/extra/` are still in the repository but hidden from the model and the UI (`CUT_TOOLS` in `agent.py`). They added surface that local models rarely used well.

## Adding a tool

1. Write the function in `dogear/tools.py` (or a module of its own) with the signature `fn(ctx, **args)`; raise `ToolError` with a message the model can act on.
2. Register it in `TOOLS` as `name: (kind, fn, spec)` where `kind` is `read | write | shell | net | browser` and `spec` is the JSON schema for the model (`_spec()` helps).
3. Add its display kind to `KIND` in `web/core.js` if it should open the workspace or show a special card.
4. If a model profile should hide it from small models, add it to the lean/standard lists in `profiles.py`.

Modules outside `tools.py` register their tools in `agent.py` (see the loop at the top of the file) to avoid circular imports.
