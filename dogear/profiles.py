"""Model profiles: every model is recognized the first time it is used and gets the toolbox and prompt style that fit it.

Detection comes from Ollama itself (/api/show: parameter count, capabilities, context length, MoE experts), not from
a list of model names, so a new model works immediately. The profile can be overridden per model in
data/profiles.json, and it adapts: observed problems per model (tool calls written as text, no-tool answers,
failing calls) are recorded in data/model_stats.json and downgrade a model that struggles with a big toolbox.
"""
import ast
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from .llm import URL

DATA = Path(__file__).resolve().parent.parent / "data"
STATS_FILE = DATA / "model_stats.json"
OVERRIDES_FILE = DATA / "profiles.json"

# ordered from leanest to fullest; a toolbox is a set of tool names, "*" means everything registered
TOOLBOXES = {
    "lean": ("Read", "Write", "Edit", "MultiEdit", "LS", "Glob", "Grep", "Bash", "RunTests", "Recall", "WebSearch", "WebFetch",
             "browser_navigate", "browser_read", "browser_click", "browser_type", "browser_key", "browser_screenshot", "browser_console"),
    "standard": ("Read", "Write", "Edit", "MultiEdit", "LS", "Glob", "Grep", "Bash", "BashOutput", "KillBash", "RunTests", "Git",
                 "Outline", "FindSymbol", "TodoWrite", "AskUser", "Skill", "Remember", "Recall", "SaveSnippet", "ViewImage", "WebSearch", "WebFetch",
                 "browser_navigate", "browser_read", "browser_click", "browser_type", "browser_key", "browser_scroll", "browser_screenshot",
                 "browser_console", "browser_audit", "browser_resize", "browser_wait"),
    "full": ("*",),
}
ORDER = ["lean", "standard", "full"]


@dataclass
class Profile:
    model: str
    params_b: float | None = None        # total parameters in billions
    active_b: float | None = None        # active parameters for MoE (estimate), else None
    moe: bool = False
    ctx_max: int | None = None
    family: str = ""
    quant: str = ""
    tools: bool = True                   # model advertises tool calling
    vision: bool = False
    thinking: bool = False
    embedding: bool = False
    tier: str = "medium"                 # small | medium | large
    toolbox: str = "full"                # lean | standard | full
    prompt: str = "full"                 # lean | full
    planning: bool = True                # mandate TodoWrite for multi-step work
    skills_index: bool = True
    review: bool = True                  # default for the automatic review pass
    notes: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        size = f"{self.params_b:.0f}B" if self.params_b and self.params_b >= 10 else (f"{self.params_b:.1f}B" if self.params_b else "?")
        return f"{size}{' MoE' if self.moe else ''} · {self.toolbox}"

    def summary(self) -> dict:
        d = asdict(self)
        d["label"] = self.label
        return d

    def tool_names(self, available: list[str]) -> list[str]:
        allow = TOOLBOXES[self.toolbox]
        return list(available) if "*" in allow else [n for n in available if n in allow]


# ------------------------------------------------------------------ detection

def _size_from_name(name: str) -> float | None:
    m = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*([bm])\b", name.lower())
    if not m:
        return None
    v = float(m.group(1))
    return v / 1000 if m.group(2) == "m" else v


def _active_from_name(name: str) -> float | None:
    m = re.search(r"-a(\d+(?:\.\d+)?)b\b", name.lower())
    return float(m.group(1)) if m else None


def classify(params_b: float | None, moe: bool, active_b: float | None) -> tuple[str, str, str]:
    """(tier, toolbox, prompt) from the model's size. Unknown size is treated as medium."""
    if params_b is None:
        return "medium", "standard", "full"
    if moe and params_b >= 20:
        # Sparse models of this size handled the whole toolbox in benchmarks (qwen3.6 35B-A3B: 7/7), so they are not
        # sized by their active parameters. Calibrate (tools/calibrate.py) to confirm for a new model.
        return ("large" if params_b >= 60 else "medium"), "full", "full"
    if moe:
        params_b *= 0.6                              # a small sparse model is weaker than its parameter count suggests
    if params_b <= 8:
        # measured on qwen3.5:4b: standard 6/7, full 4.5/7, lean 4/7. Small models get the standard toolbox with a short prompt.
        return "small", "standard", "lean"
    if params_b <= 16:
        return "medium", "standard", "full"
    return ("large" if params_b >= 60 else "medium"), "full", "full"


_cache: dict[str, tuple[float, Profile]] = {}


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _from_show(model: str, d: dict) -> Profile:
    mi, det = d.get("model_info", {}) or {}, d.get("details", {}) or {}
    caps = d.get("capabilities") or []
    params = mi.get("general.parameter_count")
    params_b = params / 1e9 if isinstance(params, (int, float)) and params else None
    if params_b is None:
        ps = str(det.get("parameter_size", ""))
        m = re.match(r"([\d.]+)\s*([BM])", ps, re.I)
        params_b = (float(m.group(1)) / (1000 if m.group(2).upper() == "M" else 1)) if m else _size_from_name(model)
    experts = [v for k, v in mi.items() if k.endswith("expert_count") and isinstance(v, int)]
    used = [v for k, v in mi.items() if k.endswith("expert_used_count") and isinstance(v, int)]
    moe = bool(experts and experts[0] > 1)
    active = _active_from_name(model)
    if moe and active is None and params_b and experts and used:
        active = params_b * used[0] / experts[0] * 1.35      # experts dominate; shared layers add a margin
    ctx = next((v for k, v in mi.items() if k.endswith(".context_length") and isinstance(v, int)), None)
    p = Profile(model=model, params_b=params_b, active_b=active, moe=moe, ctx_max=ctx, family=det.get("family", ""),
                quant=det.get("quantization_level", ""), tools="tools" in caps, vision="vision" in caps,
                thinking="thinking" in caps, embedding="embedding" in caps)
    p.tier, p.toolbox, p.prompt = classify(params_b, moe, active)
    if not p.tools:
        p.notes.append("model does not advertise tool calling: running as plain chat")
    if p.embedding:
        p.notes.append("embedding model, not usable for chat")
    p.planning = p.tier != "small"
    p.skills_index = p.tier != "small"
    p.review = p.tier != "small"
    return p


def _apply_overrides_and_stats(p: Profile) -> Profile:
    ov = _load_json(OVERRIDES_FILE).get(p.model, {})
    for k, v in ov.items():
        if hasattr(p, k):
            setattr(p, k, v)
    if ov:
        p.notes.append("settings overridden in data/profiles.json")
    st = _load_json(STATS_FILE).get(p.model)
    if st and "toolbox" not in ov and st.get("runs", 0) >= 3:
        bad = (st.get("text_calls", 0) + st.get("announced", 0) + st.get("malformed", 0)) / st["runs"]
        errs = st.get("tool_errors", 0) / max(st.get("steps", 1), 1)
        i = ORDER.index(p.toolbox)
        if (bad >= 0.5 or errs >= 0.4) and i > 0:
            p.toolbox = ORDER[i - 1]
            p.prompt = "lean"
            p.notes.append(f"toolbox reduced to '{p.toolbox}' after observed problems ({st['runs']} runs)")
    return p


async def get_profile(client: httpx.AsyncClient, model: str, ttl: float = 300) -> Profile:
    hit = _cache.get(model)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        r = await client.post(f"{URL}/api/show", json={"model": model}, timeout=10)
        r.raise_for_status()
        p = _from_show(model, r.json())
    except Exception:
        p = Profile(model=model, params_b=_size_from_name(model))
        p.tier, p.toolbox, p.prompt = classify(p.params_b, False, None)
        p.notes.append("could not read model details from Ollama; sized by name")
    p = _apply_overrides_and_stats(p)
    _cache[model] = (time.time(), p)
    return p


def invalidate(model: str | None = None):
    if model:
        _cache.pop(model, None)
    else:
        _cache.clear()


async def list_profiles(client: httpx.AsyncClient) -> list[Profile]:
    r = await client.get(f"{URL}/api/tags", timeout=5)
    out = []
    for m in r.json().get("models", []):
        p = await get_profile(client, m["name"])
        if not p.embedding:
            out.append(p)
    return sorted(out, key=lambda p: p.model)


PREFERRED_HELPER = "qwen3.5:4b"


async def pick_helper(client: httpx.AsyncClient, avoid: str = "") -> str | None:
    """The model for small side jobs (titles, structure, suggestions, sub-agents).
    The preferred helper (data/profiles.json key "_helper", default qwen3.5:4b) wins when it is installed and not the
    model already in use; otherwise the smallest installed tool-capable chat model of at least 2.5B."""
    ps = [p for p in await list_profiles(client) if p.tools]
    pref = _load_json(OVERRIDES_FILE).get("_helper") or PREFERRED_HELPER
    if any(p.model == pref for p in ps) and pref != avoid:
        return pref
    cands = sorted((p for p in ps if p.model != avoid and p.params_b and p.params_b >= 2.5), key=lambda p: p.params_b)
    return cands[0].model if cands else None


# ------------------------------------------------------------------ learning

def note_issue(model: str, kind: str, n: int = 1):
    """kind: run | text_calls | announced | malformed | tool_errors | steps"""
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        st = _load_json(STATS_FILE)
        m = st.setdefault(model, {})
        m[kind] = m.get(kind, 0) + n
        STATS_FILE.write_text(json.dumps(st, indent=1))
        _cache.pop(model, None)
    except OSError:
        pass


# ------------------------------------------------------------------ rescue: tool calls that were written as text

def salvage_text_calls(content: str, known: set[str]) -> list[dict]:
    """Some models write a tool call into the answer instead of using the function channel.
    Understand the common shapes: JSON {"name":..,"arguments":..} (also fenced), Name(arg=value, ...), Name {json}.
    Returns Ollama-style tool_calls, or [] when the text is a normal answer."""
    text = content.strip()
    if not text or len(text) > 2500:
        return []
    text = re.sub(r"^```(?:json|python|tool_call)?\s*|\s*```$", "", text, flags=re.I).strip()
    calls = []

    def add(name, args):
        if name in known and isinstance(args, dict):
            calls.append({"function": {"name": name, "arguments": args}})

    try:                                                   # JSON object or array of calls
        j = json.loads(text)
        for item in (j if isinstance(j, list) else [j]):
            if isinstance(item, dict):
                name = item.get("name") or item.get("tool") or item.get("function")
                if isinstance(name, dict):
                    name, item = name.get("name"), name
                add(name, item.get("arguments") or item.get("args") or item.get("parameters") or {})
        if calls:
            return calls
    except ValueError:
        pass
    for line in text.splitlines():                         # Name(key="value", ...) or Name {json}
        line = line.strip()
        m = re.match(r"^([A-Za-z_][\w]*)\s*\((.*)\)\s*$", line)
        if m and m.group(1) in known:
            try:
                call = ast.parse(f"f({m.group(2)})", mode="eval").body
                add(m.group(1), {k.arg: ast.literal_eval(k.value) for k in call.keywords if k.arg})
            except (SyntaxError, ValueError):
                pass
            continue
        m = re.match(r"^([A-Za-z_][\w]*)\s*(\{.*\})\s*$", line)
        if m and m.group(1) in known:
            try:
                add(m.group(1), json.loads(m.group(2)))
            except ValueError:
                pass
    return calls
