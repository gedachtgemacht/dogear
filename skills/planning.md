---
name: planning
description: How to plan a multi-step change before writing code, and when to ask the user versus decide
triggers: plan, planning, break down, step by step, architecture, roadmap, new feature, build a, planen, plane, vorgehen, umsetzung, umsetzen, konzept
---
# Planning

Plan when the task touches more than one file or has more than three steps. For a one-line fix, skip this and just do it.

1. **Restate the goal** in one or two sentences: what changes for the user, and what must keep working. If you cannot say it plainly, you are missing information; go to step 6.
2. **Look before you plan.** Use LS, Glob and Grep to find the files involved; Read the ones you will change. Do not plan against files you have not seen.
3. **List the files** you will create or edit, one line each with the reason. More than about 8 files means the task is too big: split it and finish the first slice completely.
4. **Order the steps** so that each one leaves the project working: data and types first, then logic, then interface, then tests. Prefer the smallest slice that runs end to end over layers that cannot be tested yet.
5. **Define done** as checks you can run: a command and its expected output, a test that passes, a page that renders without console errors. Write them into the plan.
6. **Name the risks**: things you could break, assumptions you cannot verify (library version, file format, existing behavior), and anything destructive such as deleting or overwriting files.

Keep the plan short: a list in TodoWrite, 3 to 8 items, each a concrete action ("Add parse_date() in utils.py"), not a topic ("Dates"). Exactly one item is in_progress. Mark an item completed the moment it is verified, not later. If you discover the plan is wrong, update the list first, then continue; do not silently drift.

**Decide yourself** when the choice is technical and reversible: names, file layout, library already used in the project, error message wording, which tests to write. State the choice in one sentence and move on.

**Ask the user** (AskUser, with options) only when the choice is theirs and costly to undo: product behavior with several valid readings, data deletion, a new dependency or service, changing a public interface, spending money. Ask before starting that step, not after.

Avoid: a plan longer than the code, planning without reading the project, re-planning after every step, starting to code while the done criteria are still vague.

Verify: at the end, walk the done checks from step 5 and report each one with its real result.
