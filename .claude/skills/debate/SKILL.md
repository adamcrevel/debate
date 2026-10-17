---
name: debate
description: Run a structured, evidence-grounded multi-agent debate via the `debate` CLI. Trigger whenever the user wants two sides (FOR/AGAINST) to argue a topic or question through a huddle -> openings -> rebuttal -> closings -> verdict pipeline, wants to continue an existing debate with a new question, or wants a sequence of questions run automatically. Covers both ways to drive multi-question ("auto") runs: delegating question choice to the engine's own Host agent, or composing each next question yourself and calling `debate ask` directly.
user-invocable: true
---

# debate — drive the structured debate CLI

Wraps the `debate` console script (`uv run debate ...`, run from the project root).
Two 3-agent teams (FOR, AGAINST) argue one question through: huddle (evidence
briefs, web-search-backed) -> openings (FOR, then AGAINST) -> rebuttal loop
(AGAINST first, alternating) -> closings (AGAINST, then FOR) -> verdict (Judge,
unless disabled). Every turn persists to SQLite (`~/.debate/debate.db` by
default; override with the global `--db-path PATH` placed before the
subcommand).

## Commands

### `debate start` — create a debate, get its id
```sh
uv run debate start --topic "Should cities ban private cars downtown?"
```
- `--topic TEXT` (required): rejected if blank/whitespace-only.
- `--model NAME` (default: unset -> omp's own default).
- `--max-rebuttal-rounds N` (default: `2`): rounds = turns per side.
- `--max-minutes M` (default: `10`): wall-clock budget for the rebuttal loop.
- `--no-judge`: disable the verdict stage for this debate (default: judge on).

These become the debate's stored defaults. Prints:
```
Created debate 1: Should cities ban private cars downtown?
```
**Capture that id (`1` here) immediately — you need it for every later call.**

### `debate ask "<question>"` — run one question on a debate
```sh
uv run debate ask "What would it do to small businesses?" --debate-id 1
```
- Positional `question` (required).
- `--debate-id N`: target debate. **Always pass this explicitly** (see below).
- `--model`, `--max-rebuttal-rounds`, `--max-minutes`, `--no-judge`: override
  the debate's stored defaults **for this one question only**; the debate row
  itself is never changed. `--no-judge` can only force the verdict off for
  this question, never re-enable a debate-level disabled judge.

### `debate auto --count N` — run N Host-generated questions, no human input
```sh
uv run debate auto --count 3 --debate-id 1
```
- `--count N` (required): how many questions to generate and run.
- `--debate-id`, `--model`, `--max-rebuttal-rounds`, `--max-minutes`,
  `--no-judge`: same meaning and override semantics as `debate ask`.
- The engine's own Host agent writes each question (checked against every
  question already asked in this debate, including ones it generated earlier
  in the same run, so it never repeats one) and runs it through the full
  pipeline, printing each question and result as it completes.

### `debate show <debate_id>` — print a transcript
```sh
uv run debate show 1
```
Prints the topic, then each question in ask order, then every turn in actual
pipeline order (huddle, openings, rebuttal turns, closings, verdict), labeled
by stage/side/role, with `[truncated]` on any turn whose 200-word backstop
fired. Use this to see what's already been asked before composing a new
question.

### `debate list` — list every debate
```sh
uv run debate list
```
Prints id, topic, question count, creation time for every persisted debate.

## Active-debate rule: always pass `--debate-id`

A `debate` invocation is a new process each time — nothing is remembered
between calls except what's in the database. `debate ask`/`debate auto`
default to the **most recently created debate** when `--debate-id` is
omitted. That fallback is only safe immediately after a `debate start` in
the same turn, and becomes wrong the moment any other debate might exist
(including one started by a different session). **Capture the id `debate
start` prints and pass `--debate-id` explicitly on every subsequent `ask`/
`auto` call in this session — never rely on the fallback.**

## Two ways to drive multiple questions

### A — Delegated: let the engine pick questions
```sh
uv run debate auto --count 3 --debate-id 1
```
One `debate auto` invocation makes one extra `omp` call per question (to the
engine's own Host agent), which composes each question and checks it against
history itself. Use this when you just want N more questions run and don't
need to control what they are.

### B — Self-composed: you pick each question (no extra agent call)
Instead of delegating to the Host agent, reason about the topic yourself —
using what's already been asked (from `debate show` or your own memory of
this session's prior calls) — and call `debate ask` directly with the
question you composed. This skips the Host agent's extra `omp` call entirely
because you (the orchestrating session) are already an LLM making the
judgment call.

Worked example, asking two follow-up questions after the opening one:
```sh
# 1. Start the debate, capture the id from the printed line.
uv run debate start --topic "Should cities ban private cars downtown?"
# -> Created debate 1: Should cities ban private cars downtown?

# 2. (If resuming an existing debate instead of one you just started,
#    read back what's already been asked first.)
uv run debate show 1

# 3. Compose the next question yourself, reasoning about the topic and
#    what's already been covered, then ask it on the captured id.
uv run debate ask "What would it do to small businesses that depend on street parking?" --debate-id 1

# 4. Compose another, now also aware of turn 3's content (from its output
#    or a fresh `debate show 1`), and ask it the same way.
uv run debate ask "How would emergency and accessibility vehicle access be handled?" --debate-id 1

# Repeat: compose -> ask --debate-id <id> -> (optionally show to re-ground) -> compose again.
```
Prefer this path whenever you want to steer the debate toward specific
angles; prefer `debate auto` whenever you just want more coverage and don't
care which angles are picked.

## Out of scope

No Discord (or any chat-platform) integration exists or is planned as part
of this skill — it is a deliberate future follow-up tracked separately. Only
the `debate` CLI is available here.
