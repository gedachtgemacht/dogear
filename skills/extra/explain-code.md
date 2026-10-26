---
name: explain-code
description: Explaining code to a human: purpose, flow, tricky parts with line references, pitfalls, a small example
triggers: explain, how does this work, how does it work, what does this do, walk me through, walkthrough, understand, erkläre, erklär, wie funktioniert, was macht, verstehen
---
# Explaining code

1. **Read first.** Read the whole file or function with Read, then Grep the definitions of anything it calls that you need. Never explain code you have not opened, and never guess what a function does from its name.
2. **One-sentence purpose.** Start with what this code is for and who calls it: "`load_skills` picks the skill files whose trigger words appear in the user's task and returns their text for the prompt." No preamble, no "Great question".
3. **The flow.** Describe the main path in order, 3 to 7 steps, in plain words, with `file:line` references: "1. `loader.py:12` reads every `.md` in `skills/`. 2. `loader.py:18` counts trigger hits." Follow the data: what comes in, what is transformed, what goes out.
4. **The tricky parts.** Point at the lines that a reader would trip over: non-obvious conditions, regexes, side effects, concurrency, early returns, magic numbers, workarounds. Say why it is that way when the code or history shows it. Quote the line, then explain it in one or two sentences.
5. **What to watch out for.** Edge cases, hidden assumptions, things that fail silently, places where a change would ripple. Only real ones you can point to.
6. **A small example.** One concrete input and the output it produces, traced through the steps. Use real values from the code or tests, or run it if that is cheap and safe.

**Match the reader.** If the user wrote casually or says they are new, avoid jargon, define each term once, and use an analogy only if it is accurate. If they use precise terms, skip basics and go to the design decisions. When unsure, give a short answer and offer to go deeper.

**Format.** Short answer first, details after. Keep it to what fits one screen unless asked for more. Use a numbered list for flow, backticks for names, and a code block only for the few lines you discuss. Answer in the user's language.

Avoid: line-by-line paraphrase ("this line assigns x"), explaining language basics unprompted, claiming certainty about code you did not read, suggesting refactors nobody asked for, and hiding uncertainty. Say "I could not find where X is set" instead of inventing it.

Verify: check each line reference against the file, and if you ran an example, quote its real output.
