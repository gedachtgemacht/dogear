"""Remote models: providers.json and .env are read, <provider>/<id> names are told apart from Ollama names, messages
are converted to the OpenAI shape (call ids, JSON arguments, data-URL images), a streamed answer with reasoning, text,
a tool call split over chunks and usage with cost comes back as the agent's events, a missing key is a clear error,
the profile is a full-toolbox remote profile, ultra's tuning lands in the body, and the server asks once per project.
usage: uv run python tests/check_remote.py   (no Ollama, no network: a fake provider runs on localhost)"""
import asyncio
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dogear import llm, profiles, remote, ultra  # noqa: E402

ok_all = True


def check(name, cond, extra=""):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


# ------------------------------------------------------------------ a fake OpenAI-compatible provider
SEEN: dict = {}
app = FastAPI()


@app.post("/v1/chat/completions")
async def completions(req: Request):
    SEEN["headers"] = dict(req.headers)
    SEEN["body"] = await req.json()
    if SEEN["headers"].get("authorization") != "Bearer test-key-123":
        return StreamingResponse(iter([b'{"error": {"message": "bad key"}}']), status_code=401)

    def chunk(delta, finish=None, usage=None):
        d = {"id": "x", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        if usage:
            d["usage"] = usage
        return f"data: {json.dumps(d)}\n\n"

    async def gen():
        yield ": OPENROUTER PROCESSING\n\n"
        yield chunk({"role": "assistant", "reasoning": "let me look"})
        yield chunk({"content": "I will "})
        yield chunk({"content": "read it."})
        yield chunk({"tool_calls": [{"index": 0, "id": "call_abc", "type": "function", "function": {"name": "Read", "arguments": "{\"file_"}}]})
        yield chunk({"tool_calls": [{"index": 0, "function": {"arguments": "path\": \"a.py\"}"}}]})
        yield chunk({}, finish="tool_calls")
        yield chunk({}, usage={"prompt_tokens": 120, "completion_tokens": 9, "cost": 0.00042})
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def main():
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    tmp = Path(tempfile.mkdtemp())
    remote.CONFIG, remote.ENV_FILE = tmp / "providers.json", tmp / ".env"
    remote.CONFIG.write_text(json.dumps({"fake": {"base_url": f"http://127.0.0.1:{port}/v1/", "models": [
        {"id": "acme/big-1", "ctx": 200000, "vision": True}, "acme/small"]}}))
    # config and names
    ps = remote.providers()
    check("providers.json is read, base_url without trailing slash", ps["fake"]["base_url"].endswith("/v1") and ps["fake"]["key_env"] == "FAKE_API_KEY")
    check("models get defaults", ps["fake"]["models"][1] == {"id": "acme/small", "ctx": 128000, "vision": False, "thinking": True, "tools": True})
    check("names are <provider>/<id>", remote.model_names() == ["fake/acme/big-1", "fake/acme/small"])
    check("an Ollama name is not remote", remote.split("qwen3.6:35b-a3b") is None and remote.split("hf.co/x/y") is None)
    check("a remote name splits at the provider", remote.split("fake/acme/big-1")[2] == "acme/big-1")
    check("model_info carries provider and host", remote.model_info("fake/acme/big-1")["host"] == "127.0.0.1" and remote.model_info("fake/acme/big-1")["vision"])
    # message conversion
    msgs = [{"role": "system", "content": "sys"},
            {"role": "user", "content": "look", "images": ["iVBORw0KGgo="]},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "Read", "arguments": {"file_path": "a.py"}}},
                                                                {"function": {"name": "LS", "arguments": {}}}]},
            {"role": "tool", "tool_name": "Read", "content": "print(1)"},
            {"role": "tool", "tool_name": "LS", "content": "a.py"},
            {"role": "assistant", "content": "done"}]
    w = remote.to_openai(msgs)
    check("images become data URLs in a content list", w[1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
    check("tool calls get ids and JSON-string arguments", w[2]["tool_calls"][0]["id"] == "call_1" and w[2]["tool_calls"][0]["function"]["arguments"] == '{"file_path": "a.py"}')
    check("tool results are paired to the calls in order", [m["tool_call_id"] for m in w[3:5]] == ["call_1", "call_2"] and "tool_name" not in w[3])
    check("an assistant message with calls and no text sends null content", w[2]["content"] is None and w[5]["content"] == "done")
    # the key
    async with httpx.AsyncClient() as client:
        try:
            async for _ in llm.stream(client, "fake/acme/big-1", msgs, None, False, 8192):
                pass
            check("missing key is an error", False)
        except llm.LLMError as e:
            check("missing key is an error that names the variable and .env", "FAKE_API_KEY" in str(e) and ".env" in str(e), str(e))
        remote.ENV_FILE.write_text("# keys\nFAKE_API_KEY = 'test-key-123'\n")
        remote._env_loaded = False
        os.environ.pop("FAKE_API_KEY", None)
        # a streamed answer through llm.stream
        ev = []
        async for kind, p in llm.stream(client, "fake/acme/big-1", msgs, [{"type": "function", "function": {"name": "Read", "parameters": {}}}], True, 8192):
            ev.append((kind, p))
        kinds = [k for k, _ in ev]
        check(".env key reaches the Authorization header", SEEN["headers"].get("authorization") == "Bearer test-key-123")
        check("the request is the OpenAI shape with tools and usage", SEEN["body"]["messages"][2]["tool_calls"][0]["id"] == "call_1" and SEEN["body"]["tools"] and SEEN["body"]["stream_options"]["include_usage"])
        check("reasoning, content, call, done in order", kinds == ["thinking", "content", "content", "call", "done"], str(kinds))
        call = next(p for k, p in ev if k == "call")
        check("a tool call split over chunks is assembled with parsed arguments", call["id"] == "call_abc" and call["function"] == {"name": "Read", "arguments": {"file_path": "a.py"}}, str(call))
        done = ev[-1][1]
        check("done carries Ollama's counters, cost and the provider", done["prompt_eval_count"] == 120 and done["eval_count"] == 9 and done["cost"] == 0.00042 and done["remote"] == "fake" and done["done_reason"] == "stop", str(done))
        check("has_vision reads providers.json", await llm.has_vision(client, "fake/acme/big-1") and not await llm.has_vision(client, "fake/acme/small"))
        # ultra's tuning
        t = ultra._Tuned(client, fmt={"type": "object"})
        ev2 = [k async for k, _ in llm.stream(t, "fake/acme/big-1", msgs, None, False, 8192)]
        check("ultra's temperature, token cap and JSON schema land in a remote body", SEEN["body"]["max_tokens"] == ultra.NUM_PREDICT and SEEN["body"]["response_format"]["json_schema"]["schema"] == {"type": "object"} and "done" in ev2)
        # profile
        p = await profiles.get_profile(client, "fake/acme/big-1")
        check("a remote model gets a full-toolbox large profile", p.remote == "fake" and p.toolbox == "full" and p.tier == "large" and p.vision and p.ctx_max == 200000 and "remote" in p.label)
    # the server asks once per project
    from dogear import server as S
    S.SETTINGS = tmp / "settings.json"
    sent, started = [], []

    class FakeConn:
        cfg = {**S.DEFAULTS, "model": "fake/acme/big-1", "root": str(tmp)}
        def busy(self): return False
        async def send(self, m): sent.append(m)
        def start_turn(self, text, _, imgs): started.append(text)
    c = FakeConn()
    await S.on_user(c, {"type": "user", "text": "hello", "model": "fake/acme/big-1", "root": str(tmp)})
    check("the first remote turn in a project is held with a question", [m["type"] for m in sent] == ["remote_ask", "done"] and not started and sent[0]["host"] == "127.0.0.1" and sent[0]["msg"]["text"] == "hello")
    await S.on_remote_allow(c, {"type": "remote_allow", "root": str(tmp), "msg": sent[0]["msg"]})
    check("allowing remembers the project and sends the held message", started == ["hello"] and str(tmp) in json.loads(S.SETTINGS.read_text())["remote_roots"])
    sent.clear()
    await S.on_user(c, {"type": "user", "text": "again", "model": "fake/acme/big-1", "root": str(tmp)})
    check("the second turn is not asked again", started == ["hello", "again"] and not sent)
    await S.on_user(c, {"type": "user", "text": "local", "model": "qwen3.6:35b-a3b", "root": str(tmp)})
    check("a local model is never asked", started[-1] == "local")
    server.should_exit = True
    await task


asyncio.run(main())
print("ALL PASS" if ok_all else "SOME FAILED")
sys.exit(0 if ok_all else 1)
