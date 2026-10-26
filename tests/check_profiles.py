"""Model profile detection with synthetic /api/show payloads, plus rescue of text-written tool calls.
usage: uv run python tests/check_profiles.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dogear import profiles as P

def show(name, params, caps=("completion", "tools"), experts=None, used=None, ctx=32768, size=None):
    mi = {"general.parameter_count": params, "x.context_length": ctx}
    if experts: mi["x.expert_count"], mi["x.expert_used_count"] = experts, used
    return {"model_info": mi, "details": {"family": "x", "parameter_size": size or "", "quantization_level": "Q4_K_M"}, "capabilities": list(caps)}

CASES = [  # name, payload, expected tier/toolbox/prompt
    ("tiny:1b", show("tiny:1b", 1.2e9), ("small", "standard", "lean")),
    ("phi:3.8b", show("phi", 3.8e9), ("small", "standard", "lean")),
    ("qwen3.5:4b", show("q", 4.66e9, ("completion", "vision", "tools", "thinking")), ("small", "standard", "lean")),
    ("llama:8b", show("l", 8.0e9), ("small", "standard", "lean")),
    ("mid:14b", show("m", 14.8e9), ("medium", "standard", "full")),
    ("dense:27b", show("d", 27.3e9), ("medium", "full", "full")),
    ("dense:32b", show("d", 32.8e9), ("medium", "full", "full")),
    ("big:70b", show("b", 70.6e9), ("large", "full", "full")),
    ("moe:30b-a3b", show("m", 30.5e9, experts=128, used=8), ("medium", "full", "full")),
    ("moe:35b-a3b", show("m", 35.5e9, experts=256, used=8), ("medium", "full", "full")),
    ("moe:8b-a1b", show("m", 8.3e9, experts=64, used=4), ("small", "standard", "lean")),
    ("huge:480b-a35b", show("h", 480e9, experts=160, used=8), ("large", "full", "full")),
    ("weird:latest", {"model_info": {}, "details": {}, "capabilities": ["completion", "tools"]}, ("medium", "standard", "full")),  # unknown size
    ("sized-by-name:7b", {"model_info": {}, "details": {"parameter_size": "7B"}, "capabilities": ["tools"]}, ("small", "standard", "lean")),
]
ok = bad = 0
for name, payload, want in CASES:
    p = P._from_show(name, payload)
    got = (p.tier, p.toolbox, p.prompt)
    flag = "PASS" if got == want else "FAIL"; ok += got == want; bad += got != want
    print(f"{flag}  {name:<18} -> {got}  params={p.params_b and round(p.params_b,1)}B moe={p.moe} active={p.active_b and round(p.active_b,1)}")
p = P._from_show("nocalls:7b", show("n", 7e9, caps=("completion",)))
print("PASS" if not p.tools and any("tool" in n for n in p.notes) else "FAIL", " model without tool support is flagged")
ok += (not p.tools); bad += p.tools
p = P._from_show("emb", show("e", 0.6e9, caps=("embedding",)))
print("PASS" if p.embedding else "FAIL", " embedding model detected"); ok += p.embedding; bad += not p.embedding

known = {"Read", "Write", "TodoWrite", "Bash"}
T = [
  ('{"name": "Read", "arguments": {"file_path": "a.py"}}', [("Read", {"file_path": "a.py"})]),
  ('```json\n{"name":"Write","arguments":{"file_path":"x","content":"hi"}}\n```', [("Write", {"file_path": "x", "content": "hi"})]),
  ('[{"name":"Read","arguments":{"file_path":"a"}},{"name":"Bash","arguments":{"command":"ls"}}]', [("Read", {"file_path": "a"}), ("Bash", {"command": "ls"})]),
  ('Read(file_path="stats.py", offset=3)', [("Read", {"file_path": "stats.py", "offset": 3})]),
  ('Bash {"command": "python3 t.py"}', [("Bash", {"command": "python3 t.py"})]),
  ('{"tool":"Bash","args":{"command":"pwd"}}', [("Bash", {"command": "pwd"})]),
  ('TodoWrite in_progress: Fix stats.py', []),                       # prose that merely names a tool is not a call
  ('Here is the code:\n```python\nprint(1)\n```', []),
  ('The Read tool reads files.', []),
  ('{"name": "Nope", "arguments": {}}', []),                          # unknown tool
]
for text, want in T:
    got = [(c["function"]["name"], c["function"]["arguments"]) for c in P.salvage_text_calls(text, known)]
    good = got == want; ok += good; bad += not good
    print(f"{'PASS' if good else 'FAIL'}  salvage {text[:56]!r:<60} -> {got}")
print(f"\n{ok} passed, {bad} failed"); sys.exit(1 if bad else 0)
