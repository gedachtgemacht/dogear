"""Open approvals and questions are remembered while they wait, so a window that joins later can answer them;
switching the mode while a turn runs applies at once, and "Don't ask" grants what is waiting.
usage: uv run python tests/check_approvals.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402

from dogear import agent as A  # noqa: E402

ok_all = True


def check(name, cond, extra=""):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


async def main():
    sent = []

    async def send(m):
        sent.append(m)

    ag = A.Agent(send, httpx.AsyncClient())
    t = asyncio.create_task(ag._ask("c1", "Bash", {"command": "pytest -q"}))
    await asyncio.sleep(0.05)
    check("the approval event is sent", sent and sent[-1]["type"] == "approval" and sent[-1]["id"] == "c1")
    check("the open approval is remembered for late windows", ag.pending_info.get("c1") == sent[-1])
    ag.answer("c1", True, always=True, key="Bash")
    check("the answer resolves the wait", await t is True)
    check("remembered state is cleared after the answer", "c1" not in ag.pending_info and "c1" not in ag.pending)
    check("'always' is kept", "Bash" in ag.always)
    t2 = asyncio.create_task(ag._ask_user("q1", [{"question": "Which?", "header": "Choice", "options": []}]))
    await asyncio.sleep(0.05)
    check("open questions are remembered too", ag.pending_info.get("q1", {}).get("type") == "ask")
    ag.answer_ask("q1", [{"selected": ["A"], "other": ""}])
    check("the question's answer comes back as text", "Choice: A" in await t2)
    check("cleared afterwards", not ag.pending_info)
    # switching to "auto" while a question is open grants it and tells every window
    sent.clear()
    t3 = asyncio.create_task(ag._ask("c2", "Bash", {"command": "pytest"}))
    await asyncio.sleep(0.05)
    ag.set_mode("auto")
    check("'Don't ask' during a run grants the open approval", await t3 is True)
    await asyncio.sleep(0.05)
    check("every window is told the question is gone", any(m["type"] == "approval_done" and m["id"] == "c2" for m in sent))
    check("the live mode is auto from now on", ag.mode == "auto")
    ag.set_mode("plan")
    check("plan is not a mode you can switch to mid-run", ag.mode == "auto")


asyncio.run(main())
print("ALL PASS" if ok_all else "SOME FAILED")
sys.exit(0 if ok_all else 1)
