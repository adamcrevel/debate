# Retrospective

## What happened

- **Cycle 0 (build):** T1–T6 built the whole engine (scaffolding/store, `omp_client`, `agents`,
  `engine`, `cli`+README, `SKILL.md`) with no reviewer or tester tasks in between — the plan went
  straight from six builders to `feature-validate-lead` with zero per-task review/mutation-proof
  gates in this cycle, unlike cycle 1. Every cycle-0 task also finished far faster than planned:
  T1 took ~2.5 real minutes against an `expected_minutes` of 25, T2 ~3.1 against 20, T3 ~3.1
  against 20, T4 ~5.7 against 35, T5 ~4.8 against 25, T6 ~1.7 against 15 — actual wall time ran at
  roughly 10–25% of estimate on every single cycle-0 task, a one-directional estimation bias, not
  noise.
- **Cycle 1 (trigger — `feature-validate-lead` FAIL):** 5 of the 6 cycle-0 build tasks failed —
  only T6 (the SKILL.md doc task) passed clean. The findings were almost entirely test-coverage
  gaps caught by mutation testing — T1 (turn fields and `DebateSummary.created_at` never asserted
  by value), T2 (`test_builds_argv_without_model_or_tools` discarded its own return value), T4
  (`max_rebuttal_rounds` only ever exercised at its default; no cross-call transcript-propagation
  assertion; no two-question-same-debate test), T5 (override test values indistinguishable from
  three different defaults at once; `debate show` fixture too thin to prove ordering) — plus one
  real production bug in T3: `build_host_system_prompt` never appended the Requirement 9
  word-cap/verified-search instruction that the debater and judge prompt builders both carried,
  even though Requirement 9 explicitly names "every agent's system prompt" including the Host's
  question generation.
- Cycle 1 added 15 tasks to close those five findings: T7–T11 (the fixes, `expected_minutes`
  12+10+12+18+18 = 70) plus a dedicated reviewer and mutation-proof task per fix, R7–R11 and
  TE7–TE11 (5 × 5 = 25 minutes expected each, 50 total). All 15 ran in parallel lanes per fix and
  the whole batch — fixes, then review/mutation-proof — completed in about 11 real minutes
  (08:35:00 → 08:46:00) against 120 minutes of summed `expected_minutes`, i.e., heavy
  parallelization recovered most of the estimation slack cycle 0 already showed.
- `actual_tokens` is `null` for every single task in the table, cycle 0 and cycle 1 alike (T1–T11
  all show `null` in that column even where `estimated_tokens` was filled in, e.g. T1's 20900).
  `estimated_tokens` itself is also missing for T4, T5, and T6 in cycle 0 — the PM filled it for
  T1–T3 and every cycle-1 fix task but not for the three largest cycle-0 builders. Net effect: this
  plan cannot support any real token-cost analysis after the fact — every number in the "did this
  cost what we thought" question is either absent or itself an estimate.
- UAT (U1) ran once, in cycle 1, and passed against the real `omp` CLI (REQ-1 through REQ-12 all
  checked, 22 real turns across 2 questions persisted and round-tripped correctly via direct DB
  query). Cycle 0's log records `UAT: not_run` — U1 was gated behind validate-lead's cycle-0 FAIL
  and only executed once the fix cycle's PASS cleared it, so the feature only ever ran UAT once,
  not once per cycle.

## Proposals

- Give cycle 0's own build tasks (T1–T6, or whichever tasks a future plan's first cycle contains) a
  reviewer + mutation-proof task immediately after each builder, the same shape cycle 1 used for
  T7–T11, instead of routing straight to `feature-validate-lead`. Four of the five cycle-1 findings
  were exactly the class of gap a per-task mutation-proof step is built to catch (assertions on
  discarded return values, parameters only ever exercised at their default, fixtures too thin to
  distinguish pass from fail); catching them at the task level would plausibly have avoided the
  second cycle entirely rather than deferring the same check to a later cross-cutting gate.
- For any requirement whose wording implies a property must hold identically across multiple sibling
  builder functions — here, Requirement 9's "every agent's system prompt" across
  `build_debater_system_prompt`, `build_judge_system_prompt`, and `build_host_system_prompt` — write
  one parametrized test that iterates over all three builders and asserts the shared instruction text
  in each, rather than three independent per-builder tests. T3's bug was exactly a missing-in-one
  inconsistency across three sibling functions that per-function tests didn't structurally compare.
- Require every task-table row to carry a real `actual_tokens` value before a task is marked
  `complete`, and require `estimated_tokens` on every builder task at plan time (T4/T5/T6 shipped
  without one). As written, this plan's token column is unusable for judging real cost against
  estimate on any task, cycle 0 or cycle 1.
- Given that cycle-0 actual durations landed at roughly 10–25% of `expected_minutes` on all six
  tasks (not one outlier), recalibrate the estimator for this task shape (single-module builder
  task, Python, this repo) downward rather than treating each individual estimate as independent
  guesswork — the same bias recurred across every task in the cycle.

---
This report cost approximately 4600 tokens (self-reported estimate) /
not available (measured) tokens. Not counted in the feature's own total —
this analysis happened after the feature was already done.
