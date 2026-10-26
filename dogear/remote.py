"""Remote models through an OpenAI-compatible API (OpenRouter, MiniMax, Groq, Together, ...), opt-in.

dogear stays local first: Ollama is the default, the helper model and the embeddings stay local, and a remote model
is only ever used when the user picks it. Everything the agent reads in a project (files, tool output, screenshots)
is sent to the provider then, so the server asks once per project before the first remote turn (`remote_roots` in
settings.json).

Config: <repo>/providers.json (gitignored; providers.example.json shows the shape):
    {"openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY",
                    "models": [{"id": "minimax/minimax-m3.1-flash", "ctx": 1000000, "vision": true, "thinking": true}]}}
A model is named <provider>/<id>, e.g. openrouter/minimax/minimax-m3.1-flash. The key comes from the environment or
from <repo>/.env (gitignored, KEY=VALUE lines); it is never written anywhere else.
"""
import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "providers.json"
ENV_FILE = ROOT / ".env"
STALL_SECONDS = 150


class RemoteError(Exception):
    pass


# ------------------------------------------------------------------ config

_env_loaded = False


def load_env():
    """KEY=VALUE lines from <repo>/.env into the environment, once, without overriding what is already set."""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v
    except OSError:
        pass


def providers() -> dict[str, dict]:
    """name -> {base_url, key_env, models: [ {id, ctx, vision, thinking, tools, params_b, moe} ]}"""
    try:
        raw = json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    for name, p in (raw.get("providers") or raw).items():
        if not isinstance(p, dict) or not p.get("base_url") or "/" in name:
            continue
        models = []
        for m in p.get("models") or []:
            m = {"id": m} if isinstance(m, str) else dict(m)
            if m.get("id"):
                models.append({"ctx": 128000, "vision": False, "thinking": True, "tools": True, **m})
        out[name] = {"base_url": p["base_url"].rstrip("/"), "key_env": p.get("key_env") or f"{name.upper()}_API_KEY",
                     "models": models, "host": urlparse(p["base_url"]).hostname or p["base_url"]}
    return out


def split(model: str) -> tuple[str, dict, str] | None:
    """(provider name, provider, model id) for a remote model name, None for an Ollama model."""
    if "/" not in (model or ""):
        return None
    name, rest = model.split("/", 1)
    p = providers().get(name)
    return (name, p, rest) if p and rest else None


def model_names() -> list[str]:
    return [f"{name}/{m['id']}" for name, p in providers().items() for m in p["models"]]


def model_info(model: str) -> dict | None:
    """The configured entry for a remote model, with the provider name and host added."""
    sp = split(model)
    if not sp:
        return None
    name, p, mid = sp
    m = next((m for m in p["models"] if m["id"] == mid), {"id": mid, "ctx": 128000, "vision": False, "thinking": True, "tools": True})
    return {**m, "provider": name, "host": p["host"]}


def api_key(name: str, p: dict) -> str:
    load_env()
    key = os.environ.get(p["key_env"], "")
    if not key:
        raise RemoteError(f"no API key for {name}: set {p['key_env']} in {ENV_FILE.name} or the environment")
    return key


# ------------------------------------------------------------------ messages: Ollama shape -> OpenAI shape

def _image_url(b64: str) -> str:
    mime = "image/jpeg" if b64.startswith("/9j/") else "image/webp" if b64.startswith("UklGR") else "image/png"
    return f"data:{mime};base64,{b64}"


def to_openai(messages: list[dict]) -> list[dict]:
    """The agent keeps messages in Ollama's shape (tool calls without ids, tool results by name, images as base64 lists).
    OpenAI-style APIs need call ids, arguments as JSON strings and images as data URLs."""
    out, pending, n = [], [], 0
    for m in messages:
        role = m.get("role")
        if role == "assistant":
            calls = []
            for c in m.get("tool_calls") or []:
                fn = c.get("function") or {}
                args = fn.get("arguments")
                n += 1
                cid = c.get("id") or f"call_{n}"
                calls.append({"id": cid, "type": "function", "function": {
                    "name": fn.get("name", ""), "arguments": args if isinstance(args, str) else json.dumps(args or {})}})
            pending = [c["id"] for c in calls]
            w = {"role": "assistant", "content": m.get("content") or ("" if not calls else None)}
            if calls:
                w["tool_calls"] = calls
            out.append(w)
        elif role == "tool":
            n += 1
            cid = pending.pop(0) if pending else f"call_{n}"
            out.append({"role": "tool", "tool_call_id": cid, "content": str(m.get("content") or "")})
        else:
            imgs = m.get("images") or []
            if imgs:
                content = [{"type": "text", "text": m.get("content") or ""}] + \
                          [{"type": "image_url", "image_url": {"url": _image_url(b)}} for b in imgs]
            else:
                content = m.get("content") or ""
            out.append({"role": role, "content": content})
    return out


# ------------------------------------------------------------------ streaming

class _open:
    """The POST as a context manager; a 400 that objects to the `reasoning` parameter is retried once without it."""

    def __init__(self, client, p, body, headers):
        self.client, self.p, self.body, self.headers, self.cm = client, p, body, headers, None

    async def __aenter__(self):
        for attempt in range(2):
            self.cm = self.client.stream("POST", f"{self.p['base_url']}/chat/completions", json=self.body, headers=self.headers, timeout=None)
            r = await self.cm.__aenter__()
            if r.status_code == 200:
                return r
            text = (await r.aread()).decode()[:500]
            await self.cm.__aexit__(None, None, None)
            if attempt == 0 and r.status_code == 400 and "reasoning" in text.lower() and "reasoning" in self.body:
                self.body.pop("reasoning")
                continue
            raise RemoteError(f"answered {r.status_code}: {text}")
        raise RemoteError("request failed")

    async def __aexit__(self, *a):
        return await self.cm.__aexit__(*a)

async def stream(client, name: str, p: dict, model_id: str, messages, tools, think, tuned=None):
    """Yields ('thinking'|'content'|'call'|'done', payload) in the same shape as llm.stream, so the agent does not
    know which kind of model answers. `done` carries Ollama's counters plus `cost` (OpenRouter) and `remote`."""
    key = api_key(name, p)
    body = {"model": model_id, "messages": to_openai(messages), "stream": True, "temperature": 0.3,
            "stream_options": {"include_usage": True}}
    if tools:
        body["tools"] = tools
    openrouter = "openrouter" in p["host"]
    if openrouter:
        body["usage"] = {"include": True}
        if think:                       # asked for; when not asked, the model keeps its own default (some cannot switch it off)
            body["reasoning"] = {"enabled": True}
    if tuned:
        tuned(body)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if openrouter:
        headers["X-Title"] = "dogear"
    t0, first, out_tokens, calls = time.time(), None, 0, {}
    usage, finish = {}, None
    async with _open(client, p, body, headers) as r:
        it = r.aiter_lines().__aiter__()
        while True:
            try:
                line = await asyncio.wait_for(it.__anext__(), STALL_SECONDS)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise RemoteError(f"model stalled: no output for {STALL_SECONDS} s")
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if line == "[DONE]":
                break
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("error"):
                e = d["error"]
                raise RemoteError(e.get("message") if isinstance(e, dict) else str(e))
            if d.get("usage"):
                usage = d["usage"]
            for ch in d.get("choices") or []:
                delta = ch.get("delta") or {}
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
                r_text = delta.get("reasoning") or delta.get("reasoning_content")
                if r_text:
                    first = first or time.time()
                    yield "thinking", r_text
                if delta.get("content"):
                    first = first or time.time()
                    out_tokens += 1
                    yield "content", delta["content"]
                for tc in delta.get("tool_calls") or []:
                    i = tc.get("index", len(calls))
                    slot = calls.setdefault(i, {"id": "", "name": "", "args": ""})
                    slot["id"] = tc.get("id") or slot["id"]
                    fn = tc.get("function") or {}
                    slot["name"] = fn.get("name") or slot["name"]
                    slot["args"] += fn.get("arguments") or ""
    for i in sorted(calls):
        c = calls[i]
        try:
            args = json.loads(c["args"] or "{}")
        except ValueError:
            raise RemoteError(f"tool call {c['name']}: arguments are not valid JSON (parse)")
        yield "call", {"id": c["id"], "function": {"name": c["name"], "arguments": args if isinstance(args, dict) else {}}}
    gen_ns = int(max(time.time() - (first or t0), 0.001) * 1e9)
    done = {"done": True, "done_reason": "length" if finish in ("length", "max_tokens") else "stop",
            "prompt_eval_count": int(usage.get("prompt_tokens") or 0),
            "eval_count": int(usage.get("completion_tokens") or out_tokens),
            "eval_duration": gen_ns, "remote": name}
    if usage.get("cost") is not None:
        done["cost"] = float(usage["cost"])
    yield "done", done
