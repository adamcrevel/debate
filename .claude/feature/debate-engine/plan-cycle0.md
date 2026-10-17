Status: proposed
Cycle: 0 / 3
FeatureStarted: 2026-10-17T03:57:47Z
OrchestrationTokensActual: null
OrchestrationTokensBreakdown: null
Prototype: none
BaselineTests: null
BaselineSuite: null
Issue: https://github.com/adamcrevel/debate/issues/1
IssueLastSeen: 2026-10-17T04:14:00Z

## Goal

A Python engine that runs structured, evidence-grounded debates: a user names a topic (narrow or
wide), the engine forms two 3-agent teams (FOR / AGAINST), and feeds them questions one at a time —
supplied directly or self-generated in auto mode — through a researched debate pipeline (team
huddle, openings, a budgeted rebuttal loop, closings, judge verdict). Every agent turn is a single
non-interactive call to the `omp` CLI, so the engine never talks to a model provider directly and
stays provider-agnostic by construction; `omp`'s own `web_search` tool is how agents ground claims in
real evidence. The engine is usable today as an omp skill (CLI + `SKILL.md`). A Discord bot is
explicitly out of scope for this feature — a deliberate follow-up once this engine is proven.

## Requirements

1. Starting a debate requires a topic (`debate start --topic "<text>"`); an empty or
   whitespace-only topic is rejected with a clear error, not silently accepted.
2. Starting a debate creates exactly two teams of exactly three agents: FOR and AGAINST, each built
   from three distinct in-team roles — Lead (delivers openings and closings), Researcher (produces
   the team's evidence brief), Rebuttal (argues the live rebuttal loop) — one agent instance per
   role per team, six debater agents total.
3. A user can feed a question directly: `debate ask "<question text>"` runs one full
   question-debate inside the active debate through the pipeline in Requirement 6.
4. `debate auto --count N` runs N consecutive questions without a human supplying any of them: the
   engine's own Host agent generates each question from the debate's topic, checked against every
   question already asked in this debate so it never repeats one, before that question runs through
   the same pipeline as Requirement 6.
5. `.claude/skills/debate/SKILL.md` documents a second way to drive auto mode: the orchestrating omp
   session itself composes the next question (using its own judgment, no extra agent call) and
   passes it to `debate ask`, as an alternative to delegating question choice to the Host agent in
   Requirement 4.
6. Per question, the engine runs these stages in this exact order:
   - **Huddle (private per team):** each team's Researcher agent produces an evidence brief for its
     team's stance (with `--tools=web_search` enabled); that brief is included as context in every
     later prompt to that team's Lead and Rebuttal agents for this question.
   - **Openings:** FOR's Lead speaks first, then AGAINST's Lead — one turn each.
   - **Rebuttal loop:** AGAINST's Rebuttal agent speaks first, then FOR's, alternating. The loop
     stops at whichever of two configurable limits is reached first: a maximum number of rebuttal
     turns (`--max-rebuttal-rounds`, default 2 rounds = 4 turns — reaching the 4th turn ends the
     loop after it completes, the 3rd turn does not) or a wall-clock budget for the whole loop
     (`--max-minutes`, default 10 — a turn already in flight when the clock expires is still allowed
     to finish, no new turn starts after).
   - **Closings:** AGAINST's Lead speaks first, then FOR's Lead — one turn each, so FOR holds both
     the opening and the closing word.
   - **Verdict:** if the judge is enabled (Requirement 7), one Judge turn; otherwise the question
     ends after closings.
7. A Judge agent — not on either team, `--tools=web_search` enabled — is on by default. It reviews
   the full question transcript and produces a verdict naming which side argued the question better,
   or a declared draw, with a short rationale citing specific turns by stage and side. `--no-judge`
   disables Requirement 6's verdict stage entirely for that run.
8. Every agent turn (huddle, opening, rebuttal, closing, verdict, and the Host's question
   generation) is exactly one non-interactive `omp -p` subprocess call; no module in this engine
   calls a model provider's API directly. The model used for a run is whatever `--model` resolves
   to, left unset by default so `omp`'s own configured default model answers — never a model name
   hardcoded in this engine.
9. Every agent's system prompt instructs it to answer in at most 120 words and to prefer a verified
   web search over an unverified claim when the claim is central to its argument. Independently of
   whether the model complies, the engine enforces a hard backstop: any turn's stored and displayed
   text is truncated to 200 words, and the turn is flagged `truncated: true` in storage when that
   backstop fires — the flag reports the backstop, not the model's own compliance with the 120-word
   instruction.
10. Every debate, question, and turn (speaker side, role, stage, model used, full text, citations
    extracted from URLs the turn's own text contains, start/end timestamps, the `truncated` flag) is
    persisted to a local SQLite database, so a debate survives the process exiting.
11. `debate show <debate-id>` prints the full persisted transcript for that debate, question by
    question, stages in the order they actually ran.
12. `debate list` prints every persisted debate with its topic, question count, and creation time.

## Standing checks

- The whole test suite passes. No test suite exists before this feature (`BaselineTests: null`,
  `BaselineSuite: null` above — a brand-new repo with no prior commits of its own); this feature is
  what establishes it, so the gate here is that the suite this feature adds passes, not that a count
  holds steady.
- `ruff check src/ tests/` runs clean with no violations — this feature is what adds `ruff` as the
  project's lint tool, so the check applies to everything this feature itself writes.
- Every new public function and class in `src/debate/` carries a docstring — this feature is what
  sets that convention for the project, so it applies to the modules this feature adds.
- Layering boundary this feature introduces: `src/debate/omp_client.py` is the only module allowed
  to import `subprocess`/`asyncio.create_subprocess_exec` anywhere in `src/debate/`. Checked by a
  grep/AST scan across every `.py` file under `src/debate/`, not just the modules a given task
  happens to touch — a second subsystem that shells out to `omp` on its own, bypassing
  `omp_client.py`, would defeat Requirement 8's provider-agnostic guarantee the same way a direct
  API call would.

## Tasks

| id | description | role | depends_on | status | cycle | model | expected_minutes | ui |
|---|---|---|---|---|---|---|---|---|
| T1 | Repo scaffolding: `pyproject.toml` (uv-managed, `ruff`+`pytest` configured, `debate` console-script entry point targeting `debate.cli:main`), `src/debate/config.py` (`DebateConfig` — topic, model, max_rebuttal_rounds, max_minutes, judge_enabled), `src/debate/store.py` (SQLite schema + CRUD for debates/questions/turns per Requirement 10, including the `truncated` flag and extracted citations) | builder | none | not_started | 0 | | 25 | no |
| T2 | `src/debate/omp_client.py`: async wrapper that builds and runs one `omp -p --mode text` subprocess call per Requirement 8 (system prompt, `--tools`, `--model`, timeout), and enforces the 200-word truncation backstop from Requirement 9, returning whether it fired | builder | T1 | not_started | 0 | | 20 | no |
| T3 | `src/debate/agents.py`: system-prompt templates for the six debater personas (Lead/Researcher/Rebuttal × FOR/AGAINST), the Judge persona (Requirement 7), and the Host persona (Requirement 4's question-generation, including the instruction to check against already-asked questions) | builder | T1 | not_started | 0 | | 20 | no |
| T4 | `src/debate/engine.py`: the per-question pipeline in the exact stage order and budget rules of Requirement 6, persisting every turn via T1's store and calling T2 with T3's personas; `generate_next_question()` implementing Requirement 4's Host-mode question generation against the debate's own question history from the store | builder | T1, T2, T3 | not_started | 0 | | 35 | no |
| T5 | `src/debate/cli.py`: `debate start/ask/auto/show/list` (Requirements 1, 3, 4, 11, 12) with `--model`, `--max-rebuttal-rounds`, `--max-minutes`, `--no-judge` flags; update `README.md` with install, usage for every command, the debate format, and an explicit note that Discord is future work | builder | T1, T4 | not_started | 0 | | 25 | no |
| T6 | `.claude/skills/debate/SKILL.md` documenting Requirement 5 (the orchestrating session acting as host) alongside the direct CLI commands from T5, written for an omp session reading it as a skill | builder | T5 | not_started | 0 | | 15 | no |

## Assumptions

- A1 (cycle 0): No in-flight peer features exist in this repository (`feature-issues.py list`
  returned none) — nothing to coordinate design with.
- A2 (cycle 0): Evidence grounding goes through `omp`'s own `web_search` tool, invoked by giving a
  debater/judge/host call `--tools=web_search`, rather than a dedicated search API key this engine
  manages itself — per the user's explicit answer: "abstracted through omp so other provider agents
  can search the web too." Confirmed live: `omp -p --tools=web_search` returns a real, current,
  grounded answer (tested with a live-fact query during planning).
- A3 (cycle 0): The debate's default model is left unset end-to-end (every `omp` call omits
  `--model` unless the user passes one), so the engine always defers to whatever model `omp` itself
  is configured to use — satisfies the "provider-agnostic, using omp" answer without this engine
  hardcoding any provider or model name.
- A4 (cycle 0): No CI workflow is added in this feature — a brand-new personal repo with no stated CI
  requirement; `ruff`/`pytest` run locally via the commands documented in the README is sufficient
  for this feature's own standing checks.
- A5 (cycle 0): `omp_client.py`'s tests mock the subprocess call (no automated test shells out to a
  real model); one real `omp -p --tools=web_search` call was run manually during planning as the
  live proof that the mechanism works, not as part of the permanent automated suite, since a
  permanent test making real paid API calls on every run is not something this feature should add
  silently.

## Cycle Log

### Cycle 0
Trigger: initial
UAT: not_run
