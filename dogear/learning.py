"""What a finished run may teach, and when that must be taken back.

The snippet library learns from runs the user rated as good, from runs that ended with green tests (auto entries)
and from variants the user adopted. An undone run, a discarded variant or a "not good" rating takes the auto entries
back. The request handlers in server.py call these; nothing here talks to a socket.
"""
import asyncio
import logging
import time
from pathlib import Path

from . import agent as A, library, llm, profiles, tools

log = logging.getLogger("dogear")


def summary_message(session: dict, turn: int) -> dict | None:
    """The assistant message that carries the summary of turn `turn`, or None if that turn has no finished run."""
    pos = A.user_positions(session["messages"])
    if not (0 <= turn < len(pos)):
        return None
    end = pos[turn + 1] if turn + 1 < len(pos) else len(session["messages"])
    return next((x for x in reversed(session["messages"][pos[turn]:end]) if x.get("summary")), None)


def rate(session: dict, turn: int, value: int, note: str) -> tuple[dict, dict, int] | None:
    """Record the user's verdict on a run. Returns (rating, the summary message, auto entries removed) or None.
    "Not good" removes what the run taught by itself; "good" confirms it."""
    sm_msg = summary_message(session, turn)
    if not sm_msg:
        return None
    prev = sm_msg.get("rating") or {}
    rating = {"value": 1 if value > 0 else -1, "note": note[:500], "at": time.time(), "extracted": bool(prev.get("extracted"))}
    auto = (sm_msg["summary"].get("auto_library") or {}).get("entries", [])
    removed = 0
    if auto and rating["value"] < 0:
        removed = library.delete_many([e["id"] for e in auto], True)
        sm_msg["summary"].pop("auto_library", None)
    elif auto and rating["value"] > 0 and not rating["extracted"]:
        library.confirm([e["id"] for e in auto])
        rating["extracted"], rating["saved"] = True, auto
    sm_msg["rating"] = rating
    sm_msg["summary"]["rating"] = rating
    A.save(session)
    return rating, sm_msg, removed


async def learn_from_rating(client, session: dict, turn: int, sm_msg: dict, model: str) -> list[dict]:
    """A good run: let the model nominate reusable code and store it in the library."""
    rating = sm_msg["rating"]
    rating["extracted"] = True
    A.save(session)
    request = session["messages"][A.user_positions(session["messages"])[turn]]["content"]
    changed = [c["path"] for c in sm_msg["summary"].get("changes", [])]
    items = await library.extract(client, llm.URL, model, Path(session["root"]), request, sm_msg.get("content", ""), changed)
    saved = []
    for it in items:
        r = await library.add(client, llm.URL, it)
        saved.append({"id": r["id"], "problem": it["problem"], "language": it["language"], "replaced": r["replaced"]})
    rating["saved"] = saved
    A.save(session)
    return saved


def forget_undone(session: dict, checkpoint_sha: str) -> int:
    """The run that started at this checkpoint was undone: what it taught by itself is wrong by definition."""
    gone = 0
    for x in session["messages"]:
        sm = x.get("summary") or {}
        if (sm.get("checkpoint") or {}).get("before") == checkpoint_sha and sm.get("auto_library"):
            gone += library.delete_many([e["id"] for e in sm["auto_library"].get("entries", [])], True)
            sm.pop("auto_library", None)
    if gone:
        A.save(session)
    return gone


def forget_session(session: dict) -> int:
    """A discarded variant must not teach."""
    ids = [e["id"] for x in session["messages"] for e in ((x.get("summary") or {}).get("auto_library") or {}).get("entries", [])]
    return library.delete_many(ids, True) if ids else 0


async def learn_adopted(client, session: dict, worktree: dict) -> None:
    """Taking a variant over is a weak "good": learn from its last turn, once, unless it was rated or learned from already."""
    sm = next((x for x in reversed(session["messages"]) if x.get("summary")), None)
    if not sm or sm["summary"].get("auto_library") or (sm.get("rating") or {}).get("extracted") or not sm["summary"].get("changes"):
        return
    wp = Path(worktree["path"]).resolve()
    request = next((x["content"] for x in reversed(session["messages"]) if x["role"] == "user" and isinstance(x.get("content"), str)
                    and not x.get("review")), "")
    rels = tools.rel_paths(wp, [c["path"] for c in sm["summary"]["changes"]])
    try:
        helper = await profiles.pick_helper(client) or A.HELPER_MODEL
        saved = await library.learn(client, llm.URL, helper, Path(worktree["origin"]), request, sm.get("content", ""), rels, auto=True)
        sm["summary"]["auto_library"] = {"entries": saved}
        A.save(session)
    except Exception as e:
        log.warning("learning from the adopted variant failed: %s", e)


def learn_adopted_later(client, session: dict, worktree: dict) -> None:
    asyncio.create_task(learn_adopted(client, session, worktree))
