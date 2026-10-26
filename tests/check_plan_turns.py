"""Plan execution turns with a fake model (no Ollama): a task closed with complete_current_task stays closed even when
the quality gate and the review turn run afterwards; request_replan ends the turn; a turn without either call is
nudged and then logged as unfinished. usage: uv run python tests/check_plan_turns.py"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dogear import agent as A, checkpoint as cp, llm, memory as mem, profiles  # noqa: E402

ok_all = True


def check(name, cond, extra=""):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


tmp = Path(tempfile.mkdtemp())
A.SESSIONS = tmp / "sessions"                       # never touch data/
root = tmp / "proj"
root.mkdir()

# stubs: no model, no checkpoints, no helpers
profiles.get_profile = lambda client, model: asyncio.sleep(0, profiles.Profile(model))
profiles.note_issue = lambda *a, **k: None
cp.checkpoint = lambda *a, **k: "deadbeef"
mem.prompt_block = lambda root, text: ("", {"memory": 0, "snippets": 0})
llm.has_vision = lambda client, model: asyncio.sleep(0, False)
script: list = []          # what the fake model does, in order: ("call", name, args) | ("text", content)
TOKENS = {"prompt": 1}     # what the fake model reports as its prompt size
seen_msgs: list = []       # every message list the fake model received


async def fake_stream(client, model, msgs, tools, think, num_ctx):
    seen_msgs.append(msgs)
    step = script.pop(0) if script else ("text", "nothing more")
    if step[0] == "call":
        yield "call", {"function": {"name": step[1], "arguments": step[2]}}
    else:
        yield "content", step[1]
    yield "done", {"eval_count": 1, "prompt_eval_count": TOKENS["prompt"], "eval_duration": 1e9}


llm.stream = fake_stream


async def noop(*a, **k):
    return None


check("only similar library hits become directions", [h["id"] for h in A._similar(
    [{"id": 1, "score": 0.86}, {"id": 2, "score": 0.60}, {"id": 3, "score": 0.54}])] == [1, 2])
A.Agent.sync_mcp = noop
A.Agent._name = noop
A.Agent._present = noop
A.Agent._suggest = noop
A.Agent._auto_learn = noop
GATE = {"on": True}


async def fake_audit(self, root, changed, model="", brief=""):
    return "Page: index.html\nHIGH: something measured" if GATE["on"] else ""


A.Agent._audit_changed = fake_audit


async def run(steps, *, last=True, gate=True, mode="auto"):
    events = []

    async def send(ev):
        events.append(ev)

    GATE["on"] = gate
    ag = A.Agent(send, client=None, browser=None)
    ag.session = A.new_session(str(root))
    script[:] = list(steps)
    await ag.turn("Task 1 of 1: build the page", "m", False, mode, 8192, False, False, None,
                  _task={"i": 0, "n": 1, "content": "build the page", "last": last})
    return ag, events


async def main():
    # 1. task closed, then gate + review turn: the outcome survives
    ag, ev = await run([("call", "Write", {"file_path": "index.html", "content": "<html><body>hi</body></html>"}),
                        ("call", "complete_current_task", {"summary": "wrote index.html and opened it"}),
                        ("text", "Review done, nothing to fix.")])
    check("review turn ran after the last task", any(e["type"] == "review_start" for e in ev))
    check("the task outcome survives the review turn", (ag.last_task or {}).get("status") == "done", str(ag.last_task))
    check("the board marks the task completed", all(t["status"] == "completed" for t in ag.session["todos"]) or not ag.session["todos"])
    names = [e["name"] for e in ev if e["type"] == "tool"]
    check("complete_current_task was offered and used", "complete_current_task" in names, str(names))

    # 2. not the last task: no gate, no review
    ag, ev = await run([("call", "Write", {"file_path": "a.html", "content": "<p>x</p>"}),
                        ("call", "complete_current_task", {"summary": "wrote a.html"})], last=False)
    check("no review and no gate before the last task", not any(e["type"] == "review_start" for e in ev))
    check("outcome recorded", (ag.last_task or {}).get("summary") == "wrote a.html")

    # 3. request_replan ends the turn with the reason
    ag, ev = await run([("call", "request_replan", {"reason": "utils.py already has this function, tasks 2 and 3 are moot"})], gate=False)
    check("request_replan ends the turn", (ag.last_task or {}).get("status") == "replan")
    check("the reason is kept", "utils.py" in (ag.last_task or {}).get("reason", ""))

    # 3b. the context window fills up mid-loop: told once to close, then stopped with a report
    TOKENS["prompt"] = 7200                                   # of 8192: over the 85 % line
    ag, ev = await run([("call", "LS", {"path": "."}), ("call", "LS", {"path": "."}), ("call", "LS", {"path": "."}),
                        ("call", "LS", {"path": "."}), ("text", "report: the page is styled")], gate=False)
    warn = [m for m in ag.session["messages"] if m.get("review") and "context window is nearly full" in m.get("content", "")]
    check("a nearly full context warns the model once, naming the closing call", len(warn) == 1 and "complete_current_task" in warn[0]["content"], str(len(warn)))
    TOKENS["prompt"] = 7900                                   # over 95 % after the warning: stopped, the report is the last call
    ag, ev = await run([("call", "LS", {"path": "."}), ("call", "LS", {"path": "."}), ("text", "report: the page is styled")], gate=False)
    sm = next((m["summary"] for m in ag.session["messages"] if m.get("summary")), {})
    check("a full context stops the run with a reason and a final report", "Context window full" in (sm.get("receipt") or {}).get("reason", "") and ag.session["messages"][-1]["content"].startswith("report"), str(sm.get("receipt")))
    TOKENS["prompt"] = 1

    # 4. prose instead of a closing call: nudged, then unfinished
    ag, ev = await run([("text", "I think that is all."), ("text", "Done I guess."), ("text", "Really done.")], gate=False)
    check("a task turn without a closing call is logged as unfinished", ag.last_task is None)
    nudges = [m for m in ag.session["messages"] if m.get("review") and "complete_current_task" in m.get("content", "")]
    check("the model was nudged to close the task (twice)", len(nudges) == 2, str(len(nudges)))

    # 5. a task turn sees a briefing and its own messages, not the transcript of earlier turns
    events = []

    async def send(ev):
        events.append(ev)
    ag = A.Agent(send, client=None, browser=None)
    ag.session = A.new_session(str(root))
    ag.session["messages"] += [{"role": "user", "content": "Build the thing", "mode": "plan"},
                               {"role": "assistant", "content": "plan", "plan": {"reasoning": "r", "tasks": [{"content": "first"}, {"content": "second"}], "status": "approved"}},
                               {"role": "user", "content": "Task 1 of 2: first", "mode": "auto", "task": {"i": 0, "n": 2, "content": "first"}},
                               {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "Read", "arguments": {"file_path": "x"}}}]},
                               {"role": "tool", "tool_name": "Read", "content": "NOISE FROM TASK ONE " * 50},
                               {"role": "assistant", "content": "Done: first", "task_result": {"status": "done", "summary": "first"}}]
    seen_msgs.clear()
    script[:] = [("call", "complete_current_task", {"summary": "second done and checked"})]
    await ag.turn("Task 2 of 2: second", "m", False, "auto", 8192, False, False, None, _task={"i": 1, "n": 2, "content": "second", "last": True})
    view = seen_msgs[0]
    joined = " ".join(str(m.get("content", "")) for m in view)
    check("the task turn starts with a briefing (request + board)", "Original request" in joined and "1. first" in joined and "2. second" in joined)
    check("earlier tasks' tool noise is not in the window", "NOISE FROM TASK ONE" not in joined)
    check("the window is small", len(view) <= 5, str(len(view)))

    # 6. the last task of a plan is judged on the whole plan: the gate runs although this task changed nothing
    events = []

    async def send(ev):
        events.append(ev)
    ag = A.Agent(send, client=None, browser=None)
    ag.session = A.new_session(str(root))
    cp.changed_since = lambda r, sha: ["index.html"]      # an earlier task of the plan wrote the page
    ag._plan_cp = "planstart"
    script[:] = [("call", "complete_current_task", {"summary": "checked the page in the browser"}), ("text", "Review done.")]
    GATE["on"] = True
    await ag.turn("Task 2 of 2: verify", "m", False, "auto", 8192, False, False, None, _task={"i": 1, "n": 2, "content": "verify", "last": True})
    sm = next((e for e in events if e["type"] == "summary"), None)
    check("the last task's receipt knows the plan's files", sm and any(c["path"] == "index.html" for c in sm["changes"]), str(sm and sm["changes"]))
    check("the gate ran on the plan's page", any(e["type"] == "review_start" for e in events))
    cp.changed_since = lambda r, sha: []

    # 7. the chosen direction reaches the task briefing
    from dogear import library as L
    L.get = lambda i, full=False: {"id": i, "solution": "Palette: ink and paper. Type: a wide grotesk. Signature: oversized numerals."}
    check("'surprise' asks for a concept of its own", "distinctive look" in A.Agent._direction({"reference": "surprise"}))
    check("a chosen plan is quoted", "oversized numerals" in A.Agent._direction({"reference": 7}))
    check("no direction adds nothing", A.Agent._direction({"reference": "none"}) == "" and A.Agent._direction({}) == "")

    # 8. outside plan execution the closing tools do not exist for the model
    events = []

    async def send(ev):
        events.append(ev)
    ag = A.Agent(send, client=None, browser=None)
    ag.session = A.new_session(str(root))
    script[:] = [("call", "complete_current_task", {"summary": "sneaky"}), ("text", "ok")]
    await ag.turn("just a normal request", "m", False, "auto", 8192, False, False, None)
    res = next((e for e in events if e["type"] == "result"), None)
    check("complete_current_task outside a plan run is rejected", res is not None and not res["ok"], str(res)[:120])


asyncio.run(main())
print("ALL PASS" if ok_all else "SOME FAILED")
sys.exit(0 if ok_all else 1)
