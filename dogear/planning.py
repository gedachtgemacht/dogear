"""Planning phase: the model may only read, think and fill the board.

In plan mode the harness shows the model read-only tools plus kanban_create_tasks. Calling it ends the phase: the board
goes to the user for approval (and edits) before anything is executed.
"""
from .tools import ToolError, _spec

MAX_TASKS = 12

# tools visible in the planning phase
PLAN_TOOLS = ("Read", "LS", "Glob", "Grep", "Outline", "FindSymbol", "WebSearch", "WebFetch", "Skill", "Recall",
              "Task", "ViewImage", "AskUser", "browser_navigate", "browser_read", "browser_screenshot", "browser_console",
              "kanban_create_tasks")

PLAN_PROMPT = (
    "\nPLANNING PHASE. You cannot change files or run commands in this phase; you can read, search and think.\n"
    "1. Investigate what the request needs: read the relevant files, look things up, check what already exists.\n"
    "2. Then call kanban_create_tasks ONCE. Put your reasoning in `reasoning` (what you found, the approach, risks), then the tasks.\n"
    "Tasks: 3 to 8 concrete steps in execution order, each one a unit of work that can be finished and checked on its own. "
    "Name files and commands where you know them. The last task verifies the result (run it, run the tests, open the page). "
    "Do not write the plan as prose; the user approves the board, not your text. "
    "If the request is ambiguous in a way that changes the plan, ask with AskUser before you create the board.\n")


def kanban_create_tasks(ctx, reasoning="", tasks=None):
    reasoning = str(reasoning or "").strip()
    if isinstance(tasks, str):
        tasks = [t.strip(" -*\t") for t in tasks.splitlines() if t.strip()]
    if not isinstance(tasks, list) or not tasks:
        raise ToolError("`tasks` must be a non-empty list. Call kanban_create_tasks again with reasoning and 3-8 tasks.")
    out = []
    for t in tasks[:MAX_TASKS]:
        if isinstance(t, str):
            t = {"content": t}
        if not isinstance(t, dict):
            continue
        content = " ".join(str(t.get("content") or t.get("task") or t.get("title") or "").split())
        if len(content) < 4:
            continue
        out.append({"content": content[:300], "detail": " ".join(str(t.get("detail") or t.get("details") or "").split())[:600]})
    if not out:
        raise ToolError("No usable task: every task needs a `content` text of at least a few words.")
    if len(reasoning) < 12:
        raise ToolError("Give your `reasoning` first: what you found and why this plan. Then call the tool again.")
    ctx.plan = {"reasoning": reasoning[:4000], "tasks": out, "status": "proposed"}
    ctx.todos = [{"content": t["content"], "status": "pending"} for t in out]
    return f"Board created with {len(out)} tasks. The planning phase is over; the user now reviews the board."


TOOLS = {
    "kanban_create_tasks": ("read", kanban_create_tasks, _spec(
        "kanban_create_tasks",
        "End the planning phase: submit your reasoning and the task board for the user's approval. Call it once, after you have investigated.",
        {"reasoning": {"type": "string", "description": "what you found, the approach and the risks (write this first)"},
         "tasks": {"type": "array", "description": "3-8 tasks in execution order; the last one verifies the result",
                   "items": {"type": "object", "properties": {
                       "content": {"type": "string", "description": "one concrete step, one sentence"},
                       "detail": {"type": "string", "description": "optional: files, commands, how to check it is done"}},
                       "required": ["content"]}}},
        ["reasoning", "tasks"])),
}
