# ROADMAP.md — RepoHeart

Phased build plan. Each phase is shippable and testable on its own. Later phases assume earlier ones are done.

Legend: ☐ not started · ◐ in progress · ☑ done

---

## Phase 0 — Project Setup ◐

Goal: a repo you can clone, install, and run tests in — even before agents exist.

- ☑ Vision + final system design docs
- ☑ Workflow template (`repoheart.yml`)
- ☑ `CLAUDE.md`, `PROJECT.md`, `ROADMAP.md`
- ☐ Repo skeleton (package layout per design doc)
- ☐ `pyproject.toml` (deps, ruff, mypy, pytest config)
- ☐ `action.yml` + `Dockerfile`
- ☐ `opencode.schema.json` (published config schema)
- ☐ CI for RepoHeart itself (lint, type-check, test on PR)
- ☐ `CONTRIBUTING.md`, `LICENSE`

**Exit criteria:** `pip install -e ".[dev]"`, `pytest`, `ruff`, and `mypy` all run green on an empty skeleton.

---

## Phase 1 — Deterministic Core ☐

Goal: everything that is *not* an LLM. This is the backbone; get it rock-solid before adding agents.

- ☐ `config/` — load + validate `opencode.yml`, resolve provider/agents, fail fast on errors
- ☐ `events/context.py` — parse `GITHUB_EVENT_PATH`, normalize to `InternalEvent`
- ☐ `events/types.py` — typed event dataclasses
- ☐ `events/router.py` — event → candidate-agent lookup table
- ☐ `idempotency/fingerprint.py` — deterministic event fingerprinting
- ☐ `idempotency/markers.py` — label / comment-marker / commit-trailer read+write
- ☐ `safety/policy.py` — risk levels + permission table
- ☐ `safety/gate.py` — `authorize()` returning ALLOW/ESCALATE/DENY
- ☐ `observability/logger.py` — structured `key=value` logging
- ☐ `github_ops/client.py` + `budgeter.py` — API wrapper + rate-limit token bucket
- ☐ `git_ops/repo.py` — branch/commit/diff/merge-base primitives
- ☐ `main.py` — wire the pipeline end-to-end (with a no-op agent)

**Exit criteria:** feed a saved `issues.opened.json`, the pipeline routes, dedups, and exits cleanly — logging every step — without calling any LLM.

---

## Phase 2 — Provider Abstraction ☐

Goal: agents can talk to an AI provider through one interface.

- ☐ `providers/base.py` — `Provider` ABC (`complete`, `supports_tools`)
- ☐ Provider registry + resolution from config (global + per-agent override)
- ☐ `providers/opencode.py` — first real provider
- ☐ `providers/claude.py`
- ☐ `providers/openai.py`
- ☐ Mock provider for tests (deterministic canned responses)
- ☐ Retry/backoff + timeout handling at the provider boundary

**Exit criteria:** the same agent code runs against OpenCode or a mock by changing only config; provider errors escalate cleanly.

---

## Phase 3 — First Vertical Slice: Issue Intelligence ☐

Goal: one complete, genuinely useful flow, end to end.

- ☐ `agents/base.py` — `Agent` ABC + `AgentResult`, `ProposedAction`, `Finding`
- ☐ `agents/issue_triage.py` — classify, label, triage summary
- ☐ `agents/duplicate_detection.py` — GitHub Search candidate set + rerank
- ☐ `agents/issue_resolution.py` — "already fixed?" via search + pickaxe
- ☐ Orchestrator sequencing for the issue flow (triage → dedup → resolution)
- ☐ Escalation comment format (labeled, explains reasoning)
- ☐ Unit tests per agent (assert proposed actions + risk ceiling, mocked provider)

**Exit criteria:** open a test issue → RepoHeart labels it, flags duplicates, checks resolution, and posts one clean triage summary. Re-running the same event is a no-op (idempotent).

---

## Phase 4 — PR Intelligence ☐

Goal: useful PR reviews, not noisy comments.

- ☐ `agents/pr_review.py` — correctness + review synthesis over diff + dependents
- ☐ `agents/code_quality.py` — run linters/type-checkers on changed paths, feed tool output
- ☐ `agents/security.py` — secret scan + dependency audit on the diff
- ☐ `agents/test_agent.py` — test-impact mapping for changed modules
- ☐ Orchestrator sequencing for the PR flow
- ☐ Consolidated single review output (not one comment per agent)

**Exit criteria:** open a PR → one coherent review covering quality/security/tests, scoped to the diff, with actionable findings.

---

## Phase 5 — Large-Repo Scaling ☐

Goal: works on LangChain/opencode-class repos without timing out or blowing budgets.

- ☐ `repo_access/` — event-scoped sparse/shallow/partial checkout + merge-base
- ☐ `retrieval/structural.py` — tree-sitter symbol graph
- ☐ `retrieval/lexical.py` — ripgrep / GitHub code search
- ☐ `retrieval/chunking.py` + `budget.py` — semantic chunking + `ContextBudget`
- ☐ `retrieval/layer.py` — rank → dedup → truncate orchestration
- ☐ `cache/` — optional backends (`actions/cache` default), content-hash keys
- ☐ `retrieval/semantic.py` — opt-in embeddings (cache-backed)
- ☐ Per-run ceilings enforcement (`max_llm_calls`, `max_files_read`, `max_runtime_seconds`)

**Exit criteria:** run against a fork of a large public repo; a small PR checks out only relevant files, retrieval stays within budget, and total run time/cost is bounded.

---

## Phase 6 — CI Repair & Conflict Resolution ☐

Goal: the higher-risk automation, gated hard.

- ☐ `agents/ci_repair.py` — read failure logs, sparse-checkout implicated paths, attempt safe fix, verify with tests, retry-limited
- ☐ `agents/conflict_resolution.py` — 3-ref merge-base reasoning, semantic explanation required, low-confidence → ESCALATE
- ☐ `git_ops/conflicts.py` — 3-way merge inspection helpers
- ☐ Revert-on-failure safety (never leave a broken branch)
- ☐ Extra safety tests: assert no force-push, no merge, escalation on low confidence

**Exit criteria:** a failing CI run gets an attempted scoped fix that's verified before commit; an unsafe conflict escalates with a clear human-readable explanation instead of guessing.

---

## Phase 7 — Documentation Agent + Polish ☐

- ☐ `agents/documentation.py` — diff-scoped doc updates for changed public symbols
- ☐ `release.published` changelog scope (opt-in)
- ☐ End-to-end example repo + demo
- ☐ Hardening: rate-limit stress, prompt-injection-via-issue-text tests
- ☐ Docs pass: README, quickstart, config reference from `opencode.schema.json`

**Exit criteria:** a public example repo demonstrates the full loop; a new user can go from zero to working RepoHeart in under 10 minutes.

---

## v1.0 Definition of Done

- All MVP agents implemented and individually tested.
- Deterministic core fully covered by tests (routing, safety, idempotency).
- Provider switching works across at least OpenCode + one other, config-only.
- Runs safely on a large repo within bounded cost/time.
- Every hard safety invariant has a test that would fail if it were violated.
- One-workflow + one-config onboarding verified on a real repo.

---

## Explicitly Deferred (Post-v1.0)

More providers · local models · repository analytics · dependency maintenance · automated releases · cross-repo & org-level agents · web dashboard · agent marketplace · hosted RepoHeart service · DB-backed state (only if GitHub-native markers prove insufficient at scale).

---

## Guiding Sequence

> Deterministic core → provider layer → one vertical slice → broaden agents → scale → high-risk automation → polish.

Never build a higher phase on an unstable lower one. Safety and idempotency tests are written *with* each agent, not deferred.
