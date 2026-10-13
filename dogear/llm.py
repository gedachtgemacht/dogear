"""Streaming-Client für den lokalen Ollama-Server."""
import asyncio
import json

import httpx

URL = "http://127.0.0.1:11434"
STALL_SECONDS = 150   # a stream that goes silent this long is considered dead (first token of a big prompt included)


class LLMError(Exception):
    pass


async def models(client: httpx.AsyncClient) -> list[str]:
    r = await client.get(f"{URL}/api/tags", timeout=5)
    names = [m["name"] for m in r.json().get("models", [])]
    return sorted(n for n in names if "embed" not in n)


async def stream(client, model, messages, tools, think, num_ctx):
    """Yields ('thinking'|'content'|'call'|'done', payload)."""
    body = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": think,
        "keep_alive": "30m",
        "options": {"num_ctx": num_ctx, "temperature": 0.3},
    }
    if tools:
        body["tools"] = tools
    async with client.stream("POST", f"{URL}/api/chat", json=body, timeout=None) as r:
        if r.status_code != 200:
            raise LLMError((await r.aread()).decode()[:500])
        it = r.aiter_lines().__aiter__()
        while True:
            try:
                line = await asyncio.wait_for(it.__anext__(), STALL_SECONDS)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise LLMError(f"model stalled: no output for {STALL_SECONDS} s")
            if not line:
                continue
            d = json.loads(line)
            if d.get("error"):
                raise LLMError(d["error"])
            m = d.get("message") or {}
            if m.get("thinking"):
                yield "thinking", m["thinking"]
            if m.get("content"):
                yield "content", m["content"]
            for c in m.get("tool_calls") or []:
                yield "call", c
            if d.get("done"):
                yield "done", d


_vision: dict[str, bool] = {}


async def has_vision(client: httpx.AsyncClient, model: str) -> bool:
    if model not in _vision:
        try:
            r = await client.post(f"{URL}/api/show", json={"model": model}, timeout=10)
            _vision[model] = "vision" in (r.json().get("capabilities") or [])
        except Exception:
            _vision[model] = False
    return _vision[model]
