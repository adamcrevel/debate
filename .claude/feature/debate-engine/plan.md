Status: done
Cycle: 1 / 3
FeatureCompletedAt: 2026-10-17T08:51:50Z
FeatureStarted: 2026-10-17T03:57:47Z
OrchestrationTokensActual: null
OrchestrationTokensBreakdown: null
Prototype: none
BaselineTests: null
BaselineSuite: null
Issue: https://github.com/adamcrevel/debate/issues/1
IssueLastSeen: 2026-10-17T04:14:00Z
Walkthrough: local://debate-engine-walkthrough.html

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

| id | description | role | depends_on | status | cycle | model | expected_minutes | estimated_start | ui | started_at | completed_at | files_touched | estimated_tokens | actual_tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1 | Repo scaffolding: `pyproject.toml` (uv-managed, `ruff`+`pytest` configured, `debate` console-script entry point targeting `debate.cli:main`), `src/debate/config.py` (`DebateConfig` — topic, model, max_rebuttal_rounds, max_minutes, judge_enabled), `src/debate/store.py` (SQLite schema + CRUD for debates/questions/turns per Requirement 10, including the `truncated` flag and extracted citations) | builder | none | complete | 0 | | 25 | 2026-10-17T07:49:34Z | no | 2026-10-17T07:55:55Z | 2026-10-17T07:58:28Z | pyproject.toml; src/debate/__init__.py; src/debate/config.py; src/debate/store.py; tests/test_config.py; tests/test_store.py | 20900 | null |
| T2 | `src/debate/omp_client.py`: async wrapper that builds and runs one `omp -p --mode text` subprocess call per Requirement 8 (system prompt, `--tools`, `--model`, timeout), and enforces the 200-word truncation backstop from Requirement 9, returning whether it fired | builder | T1 | complete | 0 | | 20 | 2026-10-17T08:14:34Z | no | 2026-10-17T07:58:28Z | 2026-10-17T08:01:39Z | src/debate/omp_client.py; tests/test_omp_client.py | 10900 | null |
| T3 | `src/debate/agents.py`: system-prompt templates for the six debater personas (Lead/Researcher/Rebuttal × FOR/AGAINST), the Judge persona (Requirement 7), and the Host persona (Requirement 4's question-generation, including the instruction to check against already-asked questions) | builder | T1 | complete | 0 | | 20 | 2026-10-17T08:34:34Z | no | 2026-10-17T07:58:28Z | 2026-10-17T08:01:39Z | src/debate/agents.py; tests/test_agents.py | 13700 | null |
| T4 | `src/debate/engine.py`: the per-question pipeline in the exact stage order and budget rules of Requirement 6, persisting every turn via T1's store and calling T2 with T3's personas; `generate_next_question()` implementing Requirement 4's Host-mode question generation against the debate's own question history from the store | builder | T1, T2, T3 | complete | 0 | | 35 | 2026-10-17T08:54:34Z | no | 2026-10-17T08:01:39Z | 2026-10-17T08:07:19Z | src/debate/engine.py; tests/test_engine.py | null | null |
| T5 | `src/debate/cli.py`: `debate start/ask/auto/show/list` (Requirements 1, 3, 4, 11, 12) with `--model`, `--max-rebuttal-rounds`, `--max-minutes`, `--no-judge` flags; update `README.md` with install, usage for every command, the debate format, and an explicit note that Discord is future work | builder | T1, T4 | complete | 0 | | 25 | 2026-10-17T09:29:34Z | no | 2026-10-17T08:07:19Z | 2026-10-17T08:12:06Z | src/debate/cli.py; tests/test_cli.py; README.md | null | null |
| T6 | `.claude/skills/debate/SKILL.md` documenting Requirement 5 (the orchestrating session acting as host) alongside the direct CLI commands from T5, written for an omp session reading it as a skill | builder | T5 | complete | 0 | | 15 | 2026-10-17T09:54:34Z | no | 2026-10-17T08:12:06Z | 2026-10-17T08:13:46Z | .claude/skills/debate/SKILL.md | null | null |
| T7 | Fix T1 test-coverage gaps (`tests/test_store.py`): (1) `test_create_turn_auto_extracts_citations` never asserts `turn.role`, `turn.text`, `turn.model_used`, `turn.started_at`, `turn.ended_at` round-trip through `Store.create_turn`/`list_turns` against the literals passed in (Requirement 10) — add those assertions. (2) `DebateSummary.created_at` (rendered by `debate list`, Requirement 12) is never asserted by value anywhere, only a truthiness check on the unrelated singular `Debate.created_at` — assert each summary's `created_at` by value in `test_list_debates_ordering_and_counts`. | builder | T1 | complete | 1 | | 12 | 2026-10-17T08:30:56Z | no | 2026-10-17T08:35:00Z | 2026-10-17T08:39:34Z | tests/test_store.py | 12000 | null |
| T8 | Fix T2 test-coverage gap (`tests/test_omp_client.py::test_builds_argv_without_model_or_tools`): the call's return value is discarded, so nothing asserts `result.model_used is None` on the default (no `--model`) path (Requirement 8's "never a model name hardcoded" / Requirement 10's model-used persistence) — capture the result and add that assertion. | builder | T2 | complete | 1 | | 10 | 2026-10-17T08:42:56Z | no | 2026-10-17T08:35:00Z | 2026-10-17T08:39:34Z | tests/test_omp_client.py | 10000 | null |
| T9 | Fix T3 production bug and test gap (`src/debate/agents.py`, `tests/test_agents.py`): (1) `build_host_system_prompt` never appends the 120-word-cap / prefer-verified-search instruction that `build_debater_system_prompt` and `build_judge_system_prompt` both carry, though Requirement 9 names "every agent's system prompt" including the Host's question generation — append the same instruction text used by the other two builders. (2) No Judge test asserts the 120-word-cap / verified-search sentences appear in the Judge's prompt, unlike the debater prompts' dedicated parametrized tests — add a matching assertion for `build_judge_system_prompt`. | builder | T3 | complete | 1 | | 12 | 2026-10-17T08:52:56Z | no | 2026-10-17T08:35:00Z | 2026-10-17T08:39:34Z | src/debate/agents.py; tests/test_agents.py | 12000 | null |
| T10 | Fix T4 test-coverage gaps (`src/debate/engine.py`, `tests/test_engine.py`): (1) `config.max_rebuttal_rounds` is only ever exercised at its default (2) in every binding test, so `max_rebuttal_turns = config.max_rebuttal_rounds * 2` could be hardcoded to `4` undetected — add a round-limit test parameterized both directions (rounds=1 -> 2 turns, rounds=3 -> 6 turns) with an instant mock and a large `max_minutes` so only the round limit binds. (2) No test asserts prior turns' text actually reaches later prompts via `_render_transcript` — passing `""` at the rebuttal, closing, and AGAINST-opening call sites would leave the suite green — extend the sentinel-based test to assert each later prompt contains every prior debated turn's sentinel text it should see. (3) `question_index = len(store.list_questions(debate_id))` is never observed at a value other than 0 since no test runs `run_question` twice against the same debate — add a two-question-same-debate test asserting indices 0 and 1. Before adding new tests, re-run the suite and check whether the tester's own concurrent edits during review already closed any of these three (worktree saw concurrent edits from multiple review agents on this file). | builder | T4 | complete | 1 | | 18 | 2026-10-17T09:04:56Z | no | 2026-10-17T08:35:00Z | 2026-10-17T08:39:34Z | tests/test_engine.py | 18000 | null |
| T11 | Fix T5 test-coverage gaps (`src/debate/cli.py`, `tests/test_cli.py`): (1) the one assertion touching `--max-rebuttal-rounds`/`--max-minutes` overrides uses values indistinguishable from the stored-fallback, the config dataclass default, and the CLI parser's own default at once — test an override with values differing from all three (e.g. 5 / 0.5), and separately re-pin the fallback path with stored values that also differ from all defaults. (2) `debate show`'s test only ever persists one question, so truncating to `questions[:1]` would leave the suite green — persist two questions with distinct text and assert both appear in order. (3) The show test's stage-order assertion (`huddle < opening < verdict`) is also satisfied by plain alphabetical sort, since the fixture omits 'closing' and 'rebuttal' (whose alphabetical position differs from run order) — include all five stages in the fixture so alphabetical-vs-run-order can't coincide. Before adding new tests, re-run the suite and check whether the tester's own concurrent edits during review already closed any of these three. | builder | T5 | complete | 1 | | 18 | 2026-10-17T09:22:56Z | no | 2026-10-17T08:35:00Z | 2026-10-17T08:39:34Z | tests/test_cli.py | 18000 | null |
| R7 | Independent review of T7's fix (tests/test_store.py) | reviewer | T7 | complete | 1 | | 5 | 2026-10-17T08:39:34Z | no | 2026-10-17T08:39:34Z | 2026-10-17T08:46:00Z | tests/test_store.py | | null |
| TE7 | Independent mutation-proof of T7's fix | tester | T7 | complete | 1 | | 5 | 2026-10-17T08:39:34Z | no | 2026-10-17T08:39:34Z | 2026-10-17T08:46:00Z | tests/test_store.py | | null |
| R8 | Independent review of T8's fix (tests/test_omp_client.py) | reviewer | T8 | complete | 1 | | 5 | 2026-10-17T08:39:34Z | no | 2026-10-17T08:39:34Z | 2026-10-17T08:46:00Z | tests/test_omp_client.py | | null |
| TE8 | Independent mutation-proof of T8's fix | tester | T8 | complete | 1 | | 5 | 2026-10-17T08:39:34Z | no | 2026-10-17T08:39:34Z | 2026-10-17T08:46:00Z | tests/test_omp_client.py | | null |
| R9 | Independent review of T9's production fix + tests (src/debate/agents.py) | reviewer | T9 | complete | 1 | | 5 | 2026-10-17T08:39:34Z | no | 2026-10-17T08:39:34Z | 2026-10-17T08:46:00Z | src/debate/agents.py; tests/test_agents.py | | null |
| TE9 | Independent mutation-proof of T9's fix | tester | T9 | complete | 1 | | 5 | 2026-10-17T08:39:34Z | no | 2026-10-17T08:39:34Z | 2026-10-17T08:46:00Z | src/debate/agents.py; tests/test_agents.py | | null |
| R10 | Independent review of T10's fix (src/debate/engine.py, tests/test_engine.py) | reviewer | T10 | complete | 1 | | 5 | 2026-10-17T08:39:34Z | no | 2026-10-17T08:39:34Z | 2026-10-17T08:46:00Z | tests/test_engine.py | | null |
| TE10 | Independent mutation-proof of T10's fix | tester | T10 | complete | 1 | | 5 | 2026-10-17T08:39:34Z | no | 2026-10-17T08:39:34Z | 2026-10-17T08:46:00Z | tests/test_engine.py | | null |
| R11 | Independent review of T11's fix (src/debate/cli.py, tests/test_cli.py) | reviewer | T11 | complete | 1 | | 5 | 2026-10-17T08:39:34Z | no | 2026-10-17T08:39:34Z | 2026-10-17T08:46:00Z | tests/test_cli.py | | null |
| TE11 | Independent mutation-proof of T11's fix | tester | T11 | complete | 1 | | 5 | 2026-10-17T08:39:34Z | no | 2026-10-17T08:39:34Z | 2026-10-17T08:46:00Z | tests/test_cli.py | | null |
| U1 | Run the whole debate-engine feature end to end as a real user would: `debate start`, `debate ask`, `debate auto`, `debate show`, `debate list`, exercising the full pipeline (huddle/openings/rebuttal loop/closings/judge) against the real `omp` CLI, not mocks | uat | T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11 | complete | 1 | | 20 | 2026-10-17T08:45:14Z | no | 2026-10-17T08:45:14Z | 2026-10-17T08:51:27Z | | | null |

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
- A6 (cycle 0): T1 — `hatchling` as the uv build backend; `DEFAULT_DB_PATH = ~/.debate/debate.db`;
  citations are always auto-derived from a turn's own text in `Store.create_turn`, no caller-supplied
  override.
- A7 (cycle 0): T2 — system + user prompt combined into one string passed to `omp -p` (it takes a
  single prompt argument, no separate system/user flags); a non-zero `omp` exit raises a generic
  `RuntimeError`.
- A8 (cycle 0): T4 — the rebuttal loop's wall-clock deadline is computed once when the loop starts
  (right after openings) and checked only before starting a new turn, never aborting a turn already
  in flight — matches Requirement 6's "a turn already in flight is still allowed to finish" exactly.
- A9 (cycle 0): T5 — "active debate" (used by `ask`/`auto` when `--debate-id` is omitted) resolves to
  the most recently created debate; CLI flags on `ask`/`auto` override that debate's stored config
  for the single call only, never mutating the stored row. Added an undocumented-by-the-plan global
  `--db-path` flag for test isolation and operational flexibility — low risk, purely additive.

## Cycle Log

### Cycle 0
Trigger: initial
UAT: not_run
Retries: none this cycle yet

### Cycle 1
Trigger: feature-validate-lead FAIL — must_fix items spanning T1, T2, T3, T4, T5 (T6 passed clean)
Findings:
- T1 (tests/test_store.py): turn fields (role/text/model_used/started_at/ended_at) never asserted
  by value on round-trip through create_turn/list_turns; DebateSummary.created_at never asserted by
  value.
- T2 (tests/test_omp_client.py::test_builds_argv_without_model_or_tools): return value discarded,
  never asserts result.model_used is None on the no-model path.
- T3 (src/debate/agents.py build_host_system_prompt): missing the Requirement 9 word-limit/
  web-search instruction present in every other persona — a real production bug, not just a test
  gap. Also: no Judge test asserts that same instruction is present in the Judge's own prompt.
- T4 (src/debate/engine.py / tests/test_engine.py): max_rebuttal_rounds only ever exercised at its
  default value; no test proves prior turns' text reaches later prompts via _render_transcript; no
  test runs two questions in one debate to prove question_index increments.
- T5 (src/debate/cli.py / tests/test_cli.py): override test values for max-rebuttal-rounds/
  max-minutes are indistinguishable from three different defaults at once; debate show's test only
  ever persists one question; the stage-order assertion is also satisfied by alphabetical sort since
  the fixture omits 'closing' and 'rebuttal'.
UAT: passed
UAT checks:
- REQ-1: `debate start --topic "..."` created a debate; `debate start --topic "   "` (whitespace-only) rejected with a clear error, exit code 1.
- REQ-2: transcript shows exactly 3 distinct roles (Researcher, Lead, Rebuttal) per side, six debater agents total.
- REQ-3: `debate ask "..." --debate-id 1` ran the full pipeline to completion (~85s wall-clock, 11 real omp subprocess calls).
- REQ-4: `debate auto --count 1` had the Host agent generate a real, on-topic, non-duplicate question, then ran it through the same pipeline.
- REQ-5: SKILL.md's "Delegated" vs "Self-composed" sections documented and cross-checked against live `--help` output and the runs actually executed.
- REQ-6: stage order confirmed exactly: huddle(2) -> opening(2, FOR then AGAINST) -> rebuttal(4, AGAINST-first alternating) -> closing(2, AGAINST then FOR) -> verdict(1); later turns visibly rebut specific claims from earlier turns.
- REQ-7: Judge verdict named a winner with a rationale citing specific sources/turns by stage and side; web-search-grounded evidence (QJE, NY Fed, Microsoft) appeared in huddle briefs and the verdict.
- REQ-8: DB query confirmed `model_used` is `None` on every turn (no `--model` passed), proving the engine never hardcodes a model.
- REQ-9: DB query confirmed `truncated=0` on all sampled real turns, correctly reporting backstop status; word-cap/truncation unit coverage cited from validate-lead's cycle-1 PASS.
- REQ-10: direct DB query confirmed every turn field (role/side/stage/model_used/text/citations/timestamps) round-trips correctly; 22 turns across 2 questions persisted and survived process exit.
- REQ-11: `debate show 1` printed both questions' full transcripts in ask order, each in exact pipeline stage order.
- REQ-12: `debate list` printed correct topic, question count (updated 1 -> 2), and creation timestamp.
- Standing checks cited (not re-run): validate-lead's cycle-1 PASS — 103 tests passed, ruff clean, subprocess/asyncio.create_subprocess_exec confined to omp_client.py, every cycle-0 must_fix item mutation-proven closed, no regressions.
