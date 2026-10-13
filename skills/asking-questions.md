---
name: asking-questions
description: How to use the AskUser tool well: only for the user's decisions, with a few concrete options
triggers: askuser, ask user, ask the user, ask me, which option, clarify, clarification, unclear, not sure, frag mich, nachfragen, rückfrage, was soll ich
---
# Asking questions

AskUser interrupts the user. Each question must be worth that.

**Ask only when all three hold:**
1. The decision belongs to the user: product behavior, scope, taste, a trade-off between valid options, anything irreversible or costly (deleting data, new paid service, public API change).
2. You cannot read the answer from the project: you already checked the README, config, existing code, tests and git history.
3. A wrong guess would cost real rework, more than one or two minutes.

**Never ask** what a file can tell you (which framework, which test runner, where config lives), what has a sensible default (port, file name, indentation: copy the project's convention), or whether you may proceed with the task you were given. Decide, state the assumption in one sentence, continue.

**Shape of a good question:**
1. One clear question, answerable without reading your mind. Put the needed context in the question itself, in one or two sentences.
2. Offer 2 to 4 options. Put the one you recommend first and mark it ("recommended"). Do not pad with fake options; 2 real ones beat 4.
3. Each option is a short label plus a one-line consequence: what it means for the user, not how you would implement it. Example: "SQLite file (recommended): no server, one file to back up" versus "Postgres: needed only if several machines write at once".
4. If the answer may be free text (a name, a number), ask for it directly and give your default in the question.

**Batch related questions.** Collect everything you need to know for the next phase, ask them back to back in one turn, then work. Do not ask one question, work for a minute, and come back with another one. If a later question depends on an earlier answer, ask only the first, then continue.

**After the answer:** do not ask the same thing again, do not ask for confirmation of what was just chosen. Record the decision in the plan or todo list and proceed.

**If the tool is unavailable or no answer arrives:** take the recommended option, say clearly that you assumed it, and keep the change easy to adjust.

Verify before asking: reread the question as the user would. If it can be answered "whatever you think is best", you should have decided.
