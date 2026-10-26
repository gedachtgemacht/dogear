"""Plan flow, offline parts: the three board tools validate their input, close the phase or the task, keep the board;
the tool registry exposes them; the execution tools are hidden outside plan execution. usage: uv run python tests/check_planning.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dogear import agent, planning, tools  # noqa: E402  (importing agent registers the tool modules)
from dogear.tools import Ctx, ToolError  # noqa: E402

ok_all = True


def check(name, cond, extra=""):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return False
    except ToolError:
        return True


ctx = Ctx(Path("."), None, None, None)
check("execution tools are registered", all(n in tools.TOOLS for n in planning.EXEC_TOOLS))
check("execution tools are read-class (no approval dialog)", all(tools.TOOLS[n][0] == "read" for n in planning.EXEC_TOOLS))
check("kanban_create_tasks needs reasoning", raises(planning.kanban_create_tasks, ctx, "", ["a task here", "another task"]))
check("kanban_create_tasks needs tasks", raises(planning.kanban_create_tasks, ctx, "because of reasons", []))
planning.kanban_create_tasks(ctx, "found nothing, build it from scratch", ["Write slug.py", {"content": "Write tests", "detail": "pytest"}, "x"])
check("board built from strings and dicts, short junk dropped", [t["content"] for t in ctx.plan["tasks"]] == ["Write slug.py", "Write tests"], str(ctx.plan))
check("todos mirror the board, all pending", [t["status"] for t in ctx.todos] == ["pending", "pending"])

ctx2 = Ctx(Path("."), None, None, None)
ctx2.todos = [{"content": "a", "status": "completed"}, {"content": "b", "status": "in_progress"}, {"content": "c", "status": "pending"}]
check("complete_current_task needs a summary", raises(planning.complete_current_task, ctx2, "ok"))
check("… and leaves the board alone when it fails", ctx2.task_done is None and ctx2.todos[1]["status"] == "in_progress")
out = planning.complete_current_task(ctx2, "  wrote slug.py and\n ran the tests ")
check("complete_current_task records a normalised summary", ctx2.task_done == {"status": "done", "summary": "wrote slug.py and ran the tests"}, str(ctx2.task_done))
check("… marks the running task completed, others untouched", [t["status"] for t in ctx2.todos] == ["completed", "completed", "pending"])
check("… tells the model what happens next", "next task" in out)

ctx3 = Ctx(Path("."), None, None, None)
check("request_replan needs a reason", raises(planning.request_replan, ctx3, "no"))
planning.request_replan(ctx3, "the project already has a slugify in utils.py, task 2 and 3 make no sense")
check("request_replan records the reason", ctx3.task_done["status"] == "replan" and "utils.py" in ctx3.task_done["reason"])

# visibility: outside plan execution the execution tools are hidden, in plan mode only PLAN_TOOLS exist
check("execution tools are not in the planning toolbox", not any(n in planning.PLAN_TOOLS for n in planning.EXEC_TOOLS))
check("the execution prompt tells the model how a task turn ends", "complete_current_task" in planning.EXEC_PROMPT and "request_replan" in planning.EXEC_PROMPT)
check("Agent.run_plan exists", callable(getattr(agent.Agent, "run_plan", None)))
_plan = {"references": [{"id": 298, "label": "Clay"}]}
_tasks = [{"content": "Verify the page", "detail": ""}]
check("a picked look adds a closing look pass", [t["content"] for t in planning.with_look_pass(_tasks, _plan, 298)] == ["Verify the page", "Look pass: make every page of this plan visibly Clay; restyle what is not"])
check("surprise, none or an unknown id add nothing", all(planning.with_look_pass(_tasks, _plan, r) == _tasks for r in ("surprise", "none", None, 5)))


print("ALL PASS" if ok_all else "SOME FAILED")
sys.exit(0 if ok_all else 1)
