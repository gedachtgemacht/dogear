"""Minimal MCP client: stdio and Streamable HTTP transports, JSON-RPC 2.0.

Config: <repo>/mcp.json (global) and <project>/.mcp.json, same shape as Claude Code:
  {"mcpServers": {
     "files":  {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."], "env": {}},
     "remote": {"url": "http://127.0.0.1:8080/mcp", "headers": {"Authorization": "Bearer ..."}}
  }}
Tools show up to the model as mcp__<server>__<tool>.
"""
import asyncio
import json
import os
import re
import signal
from pathlib import Path

import httpx

GLOBAL_CFG = Path(__file__).resolve().parent.parent / "mcp.json"
PROTOCOL = "2025-06-18"


class MCPError(Exception):
    pass


def _safe(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", s)


class Server:
    def __init__(self, name: str, cfg: dict, cwd: Path):
        self.name, self.cfg, self.cwd = name, cfg, cwd
        self.proc = None
        self.pending: dict[int, asyncio.Future] = {}
        self.n = 0
        self.tools: list[dict] = []
        self.state, self.error, self.stderr = "starting", "", []
        self.info = {}

    async def start(self):
        if "command" not in self.cfg:
            self.state, self.error = "unsupported", "a server needs either command/args (stdio) or url (HTTP)"
            return
        env = {**os.environ, **{k: str(v) for k, v in (self.cfg.get("env") or {}).items()}}
        try:
            self.proc = await asyncio.create_subprocess_exec(
                self.cfg["command"], *[str(a) for a in self.cfg.get("args", [])], cwd=self.cwd, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True, limit=16 * 1024 * 1024)
        except OSError as e:
            self.state, self.error = "error", f"cannot start: {e}"
            return
        self._tasks = [asyncio.create_task(self._read()), asyncio.create_task(self._read_err())]
        try:
            init = await self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                                     "clientInfo": {"name": "dogear", "version": "0.2"}}, timeout=40)
            self.info = init.get("serverInfo", {})
            await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            await self._list_tools()
            self.state = "ready"
        except Exception as e:
            self.state = "error"
            self.error = (str(e) or type(e).__name__) + (" | " + self.stderr[-1] if self.stderr else "")
            await self.close()

    async def _list_tools(self):
        cursor = None
        while True:
            r = await self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=20)
            self.tools += r.get("tools", [])
            cursor = r.get("nextCursor")
            if not cursor:
                break

    async def _send(self, obj):
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
        await self.proc.stdin.drain()

    async def request(self, method, params, timeout=60):
        self.n += 1
        rid = self.n
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            raise MCPError(f"{method} timed out after {timeout}s")
        finally:
            self.pending.pop(rid, None)

    async def _read(self):
        try:
            while line := await self.proc.stdout.readline():
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if "id" in m and ("result" in m or "error" in m):
                    f = self.pending.get(m["id"])
                    if f and not f.done():
                        if "error" in m:
                            f.set_exception(MCPError(m["error"].get("message", "error")))
                        else:
                            f.set_result(m["result"])
                elif "method" in m and "id" in m:  # server → client request
                    res = {"result": {}} if m["method"] == "ping" else {"error": {"code": -32601, "message": "not supported"}}
                    await self._send({"jsonrpc": "2.0", "id": m["id"], **res})
        finally:
            for f in self.pending.values():
                if not f.done():
                    f.set_exception(MCPError("server closed the connection"))
            if self.state == "ready":
                self.state, self.error = "error", "server exited"

    async def _read_err(self):
        while line := await self.proc.stderr.readline():
            self.stderr = (self.stderr + [line.decode("utf-8", "replace").strip()])[-20:]

    async def call(self, tool: str, args: dict) -> str:
        r = await self.request("tools/call", {"name": tool, "arguments": args}, timeout=180)
        parts = []
        for c in r.get("content", []):
            if c.get("type") == "text":
                parts.append(c["text"])
            elif c.get("type") == "resource" and "text" in c.get("resource", {}):
                parts.append(c["resource"]["text"])
            else:
                parts.append(f"[{c.get('type', 'content')} omitted]")
        text = "\n".join(parts) or json.dumps(r.get("structuredContent", ""))
        if r.get("isError"):
            raise MCPError(text)
        return text

    async def close(self):
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for t in getattr(self, "_tasks", []):
            t.cancel()


class HttpServer(Server):
    """MCP over Streamable HTTP: every JSON-RPC message is a POST; the answer comes back as JSON or as an SSE stream.
    The session id the server hands out on initialize is echoed in every later request."""

    def __init__(self, name: str, cfg: dict, cwd: Path):
        super().__init__(name, cfg, cwd)
        self.url = str(cfg.get("url", ""))
        self.headers = {str(k): str(v) for k, v in (cfg.get("headers") or {}).items()}
        self.session_id = ""
        self.client: httpx.AsyncClient | None = None

    async def start(self):
        if not self.url.startswith(("http://", "https://")):
            self.state, self.error = "error", f"url must start with http:// or https://: {self.url!r}"
            return
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15))
        try:
            init = await self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                                     "clientInfo": {"name": "dogear", "version": "0.2"}}, timeout=40)
            self.info = init.get("serverInfo", {})
            await self._notify("notifications/initialized")
            await self._list_tools()
            self.state = "ready"
        except Exception as e:
            self.state, self.error = "error", str(e) or type(e).__name__
            await self.close()

    def _hdr(self) -> dict:
        h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", **self.headers}
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    async def _notify(self, method: str, params: dict | None = None):
        body = {"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})}
        r = await self.client.post(self.url, json=body, headers=self._hdr())
        if r.status_code >= 400:
            raise MCPError(f"{method}: HTTP {r.status_code}")

    async def request(self, method, params, timeout=60):
        self.n += 1
        rid = self.n
        body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        try:
            async with self.client.stream("POST", self.url, json=body, headers=self._hdr(), timeout=timeout) as r:
                if r.status_code >= 400:
                    raise MCPError(f"{method}: HTTP {r.status_code} {(await r.aread())[:200].decode('utf-8', 'replace')}")
                sid = r.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
                ctype = r.headers.get("content-type", "").split(";")[0].strip()
                if ctype == "text/event-stream":
                    msg = await self._sse_result(r, rid)
                else:
                    msg = json.loads(await r.aread())
        except httpx.TimeoutException:
            raise MCPError(f"{method} timed out after {timeout}s")
        except httpx.HTTPError as e:
            raise MCPError(f"{method}: {e}")
        if msg is None:
            raise MCPError(f"{method}: the stream ended without a response")
        if "error" in msg:
            raise MCPError(msg["error"].get("message", "error"))
        return msg.get("result", {})

    async def _sse_result(self, r, rid: int):
        """Read SSE events until the response with our id arrives. Server requests on the way (ping) are answered."""
        data: list[str] = []
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
                continue
            if line.strip() or not data:
                continue
            try:
                m = json.loads("\n".join(data))
            except ValueError:
                data = []
                continue
            data = []
            for one in (m if isinstance(m, list) else [m]):
                if isinstance(one, dict) and one.get("id") == rid and ("result" in one or "error" in one):
                    return one
                if isinstance(one, dict) and "method" in one and "id" in one:
                    res = {"result": {}} if one["method"] == "ping" else {"error": {"code": -32601, "message": "not supported"}}
                    try:
                        await self.client.post(self.url, json={"jsonrpc": "2.0", "id": one["id"], **res}, headers=self._hdr())
                    except httpx.HTTPError:
                        pass
        return None

    async def close(self):
        if self.client:
            if self.session_id:
                try:
                    await self.client.delete(self.url, headers=self._hdr(), timeout=5)
                except httpx.HTTPError:
                    pass
            await self.client.aclose()
            self.client = None


class MCP:
    def __init__(self):
        self.servers: dict[str, Server] = {}
        self.sig: dict[str, str] = {}
        self.root: Path | None = None

    @staticmethod
    def _config(root: Path) -> dict:
        out = {}
        for f in (GLOBAL_CFG, root / ".mcp.json"):
            try:
                out.update(json.loads(f.read_text()).get("mcpServers", {}))
            except (OSError, ValueError):
                pass
        return out

    async def sync(self, root: Path) -> list[dict]:
        cfg = self._config(root)
        for name in [n for n in self.servers if n not in cfg or self.sig[n] != json.dumps(cfg[n], sort_keys=True) + str(root)]:
            await self.servers.pop(name).close()
        new = [n for n in cfg if n not in self.servers]
        for n in new:
            self.servers[n] = (HttpServer if "url" in cfg[n] and "command" not in cfg[n] else Server)(n, cfg[n], root)
            self.sig[n] = json.dumps(cfg[n], sort_keys=True) + str(root)
        await asyncio.gather(*(self.servers[n].start() for n in new))
        self.root = root
        return self.status()

    def status(self) -> list[dict]:
        return [{"name": s.name, "state": s.state, "error": s.error, "tools": [t["name"] for t in s.tools],
                 "title": s.info.get("name", "")} for s in self.servers.values()]

    def specs(self) -> list[dict]:
        out = []
        for s in self.servers.values():
            if s.state != "ready":
                continue
            for t in s.tools:
                schema = t.get("inputSchema") or {"type": "object", "properties": {}}
                out.append({"type": "function", "function": {
                    "name": f"mcp__{_safe(s.name)}__{_safe(t['name'])}"[:64],
                    "description": f"[MCP: {s.name}] " + (t.get("description") or t["name"])[:900],
                    "parameters": schema}})
        return out

    def resolve(self, full: str):
        for s in self.servers.values():
            for t in s.tools:
                if f"mcp__{_safe(s.name)}__{_safe(t['name'])}"[:64] == full:
                    return s, t["name"]
        return None, None

    async def close(self):
        for s in self.servers.values():
            await s.close()
        self.servers.clear()
