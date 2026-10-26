---
name: ultracode
description: When and how to use the Task tool, and the Ultra tool if your tool list has it, for large reviews, research, design and audits
triggers: ultracode, ultra, deep review, deep audit, full audit, thorough review, multi-agent, subagent, subagents, sub-agent, sub-agents, task tool, fan out, parallel agents, whole codebase, entire codebase, gründlich, umfassend, tiefenprüfung
---
# Ultracode: Ultra and Task

Task runs one read-only sub-agent with a fresh context. Ultra, if it is in your tool list, runs a multi-step, multi-agent job and returns one report. If your tool list has no Ultra, never call it: do the same job by hand with Task (see Method). Both cost many model calls. Use them only when the work is large and splits into independent parts.

**Use Ultra (only if it is in your tool list) when:**
- review: a diff or module of more than about 300 changed lines, or several files that interact.
- research: a question that needs 3 or more independent lookups across code or the web.
- design: a choice between approaches that you want compared and attacked before committing.
- audit: a whole code base or subsystem checked for one kind of problem (security, error handling, dead code).

Without Ultra, give each independent part of such a job to its own Task call.

Name the job (review, research, design or audit) the way the Ultra tool's own description and parameters ask for it, and write a self-contained goal: what to examine (paths), what to look for, what the report must contain. The sub-agents see none of your conversation.

**Use Task** for one bounded question that would otherwise flood your context ("which files read the config, and how"). Several independent questions: call Task several times. Use fast=true only for simple lookups.

**Do not use either** for a fix in one file, a question you can answer with two Greps, a task where step 2 needs the result of step 1, or anything you can finish in under ten tool calls. Small tasks done directly are faster and more accurate.

**Method (what the tool does, and what you do by hand with Task):**
1. Decompose into parts that do not depend on each other.
2. Fan out: one job per part, each with its own complete instructions.
3. Verify adversarially: a second pass tries to refute each finding by reading the cited code. Drop what it cannot confirm.
4. Synthesize: merge duplicates, rank by severity, keep only evidence-backed items.

**Reading the report:** treat each finding as a claim, not a fact. Open the cited file and line yourself before you change anything. Act on confirmed findings in order of severity; keep a TodoWrite item per fix. Report to the user what was found, what you changed, what you rejected and why, and what remains unverified.

Avoid: launching Ultra to avoid reading the code, vague goals ("review everything"), repeating the same job, applying fixes straight from the report without checking, and ignoring findings that contradict your own view.

Verify: after fixes, run the project's tests and re-check each fixed spot.
