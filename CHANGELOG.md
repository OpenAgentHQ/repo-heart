# Changelog

All notable changes to RepoHeart will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

---

## [0.8.0] - 2026-08-26

Phase 8 — PyPI Distribution & Zero-Copy Onboarding. First public PyPI release.
`repoheart init` generates all required config in one command; automated PyPI
publishing is gated behind GitHub Releases via OIDC trusted publishing.

### Added

- `repoheart init` CLI subcommand — interactive (or `--yes` non-interactive) wizard
  that generates `repoheart.yml` and `.github/workflows/repoheart.yml` in one shot;
  supports `--provider`, `--model`, `--output-dir`, `--force` flags for CI use
- `repoheart/cli/` package — split into four focused modules:
  `providers.py` (provider registry + default models), `agents.py` (agent registry
  + descriptions), `templates.py` (YAML renderers + file writer),
  `init.py` (orchestrator only); adding a new provider or agent requires editing
  exactly one file
- Agent descriptions rendered as inline YAML comments in generated `repoheart.yml`
  (e.g. `issue_triage: true  # label and prioritize new issues`)
- Provider selection prompt shows the default model name alongside each option
- `.github/workflows/publish.yml` — OIDC trusted publishing to PyPI; triggers only
  on published GitHub Releases (`release: types: [published]`); per-job permission
  scoping (`id-token: write` on `publish` job only); `fetch-depth: 0` for correct
  Hatch versioning
- `AGENTS.md` §13 Release Workflow — step-by-step release guide covering version
  bumps, CHANGELOG updates, annotated tags, and GitHub Release creation

### Changed

- `repoheart/main.py` — extended to support `run` and `init` subcommands via
  `argparse` subparsers; legacy flat invocation (`repoheart --event X --config Y`)
  preserved for backward compatibility with the GitHub Action container
- `pyproject.toml` — version bumped from `0.3.0` to `0.8.0` to reflect all
  completed phases (Phases 1–7 shipped without a PyPI release)

### Tests

- `tests/test_cli_init.py` — 6 tests covering file generation, conflict detection,
  force overwrite, provider/model flags, and version flag regression
- 543 tests total; ruff clean, mypy strict clean

---

## [0.7.0] - 2026-08-26

Phase 7 — Documentation Agent & Polish. The final MVP phase: a real
`DocumentationAgent` replaces the last `NoOpAgent` placeholder, hardening
tests cover rate-limit stress and prompt-injection attack surfaces, and the
example repo + docs are updated for a sub-10-minute onboarding experience.

### Added

- `repoheart/agents/documentation.py` — `DocumentationAgent` (`risk_level = SAFE`);
  two dispatch modes selected by `event.routing_key`:
  - **PR / push mode** (`pull_request.*`, `push`): parses the unified diff for
    newly added public Python symbols (`def`/`class` on `+` lines, skipping
    private `_name` prefixes); sends symbol list + diff excerpt to the LLM asking
    for missing or stale docstrings; returns `ReviewComment` objects for PR events
    and `IssueComment` objects for push events, both scoped only to changed symbols
  - **Release mode** (`release.published`): reads `tag_name` from the event
    payload; calls `commits_between(prev_tag, tag_name)` to collect commit messages
    since the previous tag; asks the LLM to produce a Keep-a-Changelog draft grouped
    under `Added / Changed / Fixed / Removed / Security`; returns a single
    `IssueComment` with the draft marked as "edit before publishing"; opt-out via
    `documentation_config.changelog_on_release: false`
- `repoheart/git_ops/repo.py` — `commits_between(base, head) → list[str]`:
  runs `git log --oneline base..head`; exclusive lower bound, inclusive upper
- `repoheart/config/schema.py` — `DocumentationAgentConfig` frozen dataclass:
  `enabled: bool = False`, `changelog_on_release: bool = True`,
  `docstring_style: str = "google"` (`"google" | "numpy" | "sphinx"`)
- `repoheart/config/loader.py` — explicit `_load_agents()` now maps each boolean
  field directly (typed, no `**kwargs`); reads optional `documentation_config`
  YAML block into `DocumentationAgentConfig`
- `repoheart.schema.json` — `documentation_config` object added under `agents`:
  `changelog_on_release` (boolean, default `true`) and `docstring_style` (enum)
- `examples/release.published.json` — sample `release.published` payload used by
  the integration smoke-test parametrization
- `tests/test_documentation_agent.py` — 18 unit tests:
  `_extract_changed_symbols` (public vs private vs non-Python),
  PR mode (review comments, empty diff, no public symbols, empty LLM response,
  provider error, bad JSON), push mode (issue comments), release mode
  (happy path, missing tag, opt-out flag, provider error), no-provider guard,
  risk ceiling via `validate_ceiling()`, registry wiring assertion
- `tests/test_rate_limit_stress.py` — 14 hardening tests:
  token-bucket starts full, decrements on acquire, header sync, bad-header
  tolerance, `used` counter; `RunBudget` raises on LLM-calls ceiling;
  `_BudgetedProvider` blocks inner call at ceiling; `_retry_with_backoff`
  succeeds after transient `ProviderRateLimitError`, raises after max retries,
  does not swallow non-transient errors; files-read ceiling and remaining counter;
  runtime ceiling; runtime ok within limit
- `tests/test_prompt_injection.py` — 9 prompt-injection hardening tests across
  three agents:
  `IssueTriageAgent` — injected title/body stays within `SAFE` ceiling, no
  `PUSH_BRANCH`/`COMMIT` proposed, label names contain no shell chars or
  `DELETE`/`PUSH` fragments;
  `PRReviewAgent` — injected diff/body stays within `SAFE` ceiling, no write
  kinds, bogus severity string does not escalate to an action;
  `DocumentationAgent` — injected release body produces no write actions, body
  stored as plain string; `IssueTriageAgent` — extra `proposed_action` JSON key
  is silently ignored by the parser

### Changed

- `repoheart/agents/registry.py` — `"documentation"` entry updated from
  `NoOpAgent` to `DocumentationAgent`; `NoOpAgent` import removed (now unused)
- `repoheart.yml` — `documentation: true` (enabled in the reference config so the
  smoke-test `release.published` payload routes to an active agent); new
  `documentation_config` commented block documents available options
- `docs/configuration.md` — `agents.documentation` description updated to
  mention both modes; new `agents.documentation_config` subsection with field
  table and YAML example
- `docs/quickstart.md` — new step 4 "Enable the documentation agent" with a
  minimal `documentation_config` snippet; existing step 4 renumbered to 5

### Tests

- 42 new tests, **524 tests total** (up from 482 at Phase 6 exit); all passing
- ruff clean, mypy strict clean on 62 source files

---

## [0.6.0] - 2026-08-26

Phase 6 — CI Repair & Conflict Resolution. The higher-risk automation tier,
gated hard behind the Safety Gate. Two new MEDIUM-risk agents replace their
`NoOpAgent` placeholders: `CIRepairAgent` proposes scoped code fixes for
failing CI runs (verified locally before committing), and
`ConflictResolutionAgent` gives semantic explanations of merge conflicts and
proposes resolutions when confidence is high enough to be safe.

### Added

- `repoheart/git_ops/conflicts.py` — three-way merge inspection helpers:
  `ConflictBlock` and `ConflictFile` frozen dataclasses; `extract_conflict_blocks`
  pure parser for `<<<<<<<`/`=======`/`>>>>>>>` markers; `estimate_confidence`
  heuristic (whitespace-only → 0.95, small blocks → 0.8, medium → 0.6, large
  → 0.3; threshold for escalation is < 0.7); `read_conflict_files` reads already-
  marked files from disk; `inspect_conflicts` non-destructive conflict simulation
  via `git merge-tree` (does not touch the working tree)
- `repoheart/agents/ci_repair.py` — `CIRepairAgent` (`risk_level = MEDIUM`);
  reads `ci_logs` from `AgentContext`; respects `config.ci.watch_workflows` filter
  and `conclusion` field (only acts on `failure`/`timed_out`/`cancelled`);
  sends log excerpt to LLM asking for root-cause + minimal patches; at confidence
  ≥ 0.8: proposes `CREATE_BRANCH` (fix branch `repoheart/fix-ci-<run_id>`) →
  `MODIFY_CODE` × N → `COMMIT` → `PUSH_BRANCH`; at confidence < 0.8: returns
  `needs_human_review=True` with zero write proposals; `PUSH_BRANCH` payload
  always has `force=False` — force-push is structurally impossible
- `repoheart/agents/conflict_resolution.py` — `ConflictResolutionAgent`
  (`risk_level = MEDIUM`); handles `pull_request.opened`, `.synchronize`, and
  `push`; reads `conflict_files` from `AgentContext` (pre-inspected by the
  Orchestrator); for each `ConflictFile` with `resolution_confidence >= 0.7`:
  sends the `ConflictBlock` pair to the LLM for a per-block resolution;
  LLM confidence ≥ 0.7 → `ReviewComment` (PR events) or `IssueComment` (push)
  plus `MODIFY_CODE` proposal; any block below threshold →
  `needs_human_review=True`, explanation only, no write; falls back to
  diff-based analysis when no conflict markers are found but `pr_data.mergeable`
  is `False`
- `repoheart/github_ops/client.py` — `get_workflow_run_logs(repo, run_id)`
  fetches up to 50 KB of CI log text from `GET /repos/{repo}/actions/runs/{id}/logs`;
  `get_check_run_details(repo, check_run_id)` wraps `GET /repos/{repo}/check-runs/{id}`;
  both are read-only (no `Decision` token required)

### Changed

- `repoheart/orchestrator/agent_context.py` — three new Phase 6 fields:
  `ci_logs: str`, `workflow_run_data: dict | None`, `conflict_files: list[ConflictFile]`;
  all default to empty / `None` for full backward compatibility
- `repoheart/orchestrator/orchestrator.py` — `_build_context()` pre-fetches
  workflow run data + CI logs for `ci_repair`; calls `inspect_conflicts` for
  `conflict_resolution` on PR events; `_execute_action()` gains Phase 6 handlers:
  `CREATE_BRANCH` (delegates to `GitRepo.create_branch`), `MODIFY_CODE` (patch-
  or full-replace file on disk), `COMMIT` (calls `_run_local_tests` gate first —
  skips the commit and logs `commit_skipped` if tests fail), `PUSH_BRANCH`
  (refuses `force=True` structurally); `_run_local_tests()` private helper runs
  `pytest` on changed `.py` paths before any commit is dispatched
- `repoheart/orchestrator/pr_flow.py` — `"conflict_resolution"` added to
  `_SECTION_TITLES` so its `ReviewComment` objects appear in the consolidated PR
  review under a **Conflict Resolution** section
- `repoheart/orchestrator/issue_flow.py` — idempotency markers added:
  `"ci_repair" → "<!-- repoheart:ci-repair -->"` and
  `"conflict_resolution" → "<!-- repoheart:conflict-resolution -->"`
- `repoheart/agents/registry.py` — `"ci_repair"` and `"conflict_resolution"`
  entries replaced from `NoOpAgent` to their real implementations
- `repoheart/events/router.py` — `pull_request.synchronize` now also routes to
  `conflict_resolution` (a new push to a PR branch can introduce fresh conflicts)
- `_PR_AGENT_NAMES` in `orchestrator.py` extended to include `conflict_resolution`
  so its `ReviewComment` objects flow into the consolidated PR review

### Safety tests

- `tests/test_git_ops_conflicts.py` — 17 tests: conflict-marker parsing (basic,
  multiple, no markers, context capture, whitespace-only), confidence heuristics
  (trivial → ≥ 0.9, small → ≥ 0.7, large → < 0.7), file reading with markers
- `tests/agents/test_ci_repair.py` — 15 tests including:
  `test_no_force_push` (PUSH_BRANCH payload never has `force=True`),
  `test_no_delete_branch_proposed` (DELETE_BRANCH must never appear),
  `test_low_confidence_escalates` (zero write proposals when confidence < 0.8),
  `test_ceiling_not_violated` (`validate_ceiling()` passes on all paths),
  `test_empty_logs_returns_finding`, `test_watch_workflows_filter`,
  `test_non_failure_conclusion`
- `tests/agents/test_conflict_resolution.py` — 17 tests including:
  `test_low_confidence_escalates` (large blocks → `needs_human_review=True`, no
  MODIFY_CODE), `test_low_confidence_file_level_escalates` (file already deemed
  low-confidence → no LLM call), `test_pr_event_uses_review_comments`,
  `test_push_event_uses_issue_comments`, `test_ceiling_not_violated`,
  `test_no_provider_returns_finding`, `test_clean_pr_returns_early`

### Tests

- 49 new tests, 482 tests total (up from 433 at Phase 5 exit); all passing
- ruff clean, mypy strict clean on 61 source files

---

## [0.5.0] - 2026-08-26

Phase 5 — Large-Repo Scaling. Budget-bounded retrieval, sparse checkout, and
optional embeddings so RepoHeart runs within time and cost limits on repos the
size of LangChain or opencode without timing out. See git history for full
details.

---

## [0.4.0] - 2026-08-25

Phase 4 — PR Intelligence + Unified Agent Output Architecture. Four PR agents
(`pr_review`, `code_quality`, `security`, `test`) producing a single consolidated
review comment; `ReviewComment`/`IssueComment` typed output replacing raw
`POST_COMMENT` proposals for all agents. See git history for full details.

---

## [0.3.0] - 2026-08-25

Phase 3 — Issue Intelligence. The first vertical slice: three LLM-driven
agents that activate on `issues.opened/reopened/edited` and produce real,
useful output — labels, triage summaries, duplicate links, and resolution
notices. All actions are `SAFE`-risk and flow through the Safety Gate.

### Added

- `repoheart/agents/issue_triage.py` — `IssueTriageAgent`: sends issue
  title + body to the LLM with the repo's available label set; parses
  structured JSON response (`type`, `priority`, `component`, `labels`,
  `summary`); proposes `ADD_LABEL` for any matching labels and a
  `POST_COMMENT` triage summary with an HTML idempotency marker
- `repoheart/agents/duplicate_detection.py` — `DuplicateDetectionAgent`:
  receives up to 10 candidate issues (pre-fetched by the Orchestrator via
  GitHub Search) and asks the LLM to rerank for duplicates; high confidence
  → `ADD_LABEL` (`duplicate`) + `POST_COMMENT`; medium confidence →
  related-issues comment only
- `repoheart/agents/issue_resolution.py` — `IssueResolutionAgent`: receives
  PRs referencing the issue (pre-fetched via GitHub Search); filters to
  merged only; asks the LLM to confirm resolution; high confidence →
  `POST_COMMENT` + `ADD_LABEL` (`already-fixed`); medium → comment only
- `repoheart/github_ops/client.py` — two new read methods:
  `search_issues(repo, query, state, max_results)` and
  `get_linked_pull_requests(repo, issue_number)` using `GET /search/issues`
- `tests/agents/` — 28 new unit tests across three files; all use
  `MockProvider` (no real LLM calls, no network)

### Changed

- `repoheart/orchestrator/agent_context.py` — three new fields:
  `repo_labels`, `candidate_issues`, `linked_pull_requests`; all default to
  empty list for backward compatibility
- `repoheart/orchestrator/orchestrator.py` — `_build_context()` performs
  agent-specific pre-fetches (repo labels for triage, search candidates for
  dedup, linked PRs for resolution); `_post_escalation()` now posts a
  structured comment including action kind, risk level, and automation level
- `repoheart/agents/registry.py` — `issue_triage`, `duplicate_detection`,
  and `issue_resolution` entries replaced from `NoOpAgent` to their real
  implementations

### Tests

- 28 new tests, 234 tests total (up from 205 at Phase 2 exit); all passing
- `tests/agents/test_issue_triage.py` — happy path, label filtering,
  no-label path, idempotency marker, malformed JSON, no provider, no data,
  ceiling validation, provider call count
- `tests/agents/test_duplicate_detection.py` — high/medium/no duplicates,
  empty candidates, idempotency marker, malformed JSON, no provider, ceiling
- `tests/agents/test_issue_resolution.py` — high/medium confidence, not
  resolved, no PRs, open PR ignored, idempotency marker, malformed JSON, no
  provider, ceiling

---

## [0.2.0] - 2026-08-25

Phase 2 — Provider Abstraction. Agents can now talk to an AI provider through
one interface. Swapping providers requires only a config change; no agent code
changes. No agent produces real LLM output yet (that is Phase 3), but every
agent receives a live, typed `Provider` in its context.

### Added

- `repoheart/providers/base.py` — `Provider` ABC with `complete()` and
  `supports_tools()`; frozen dataclasses `CompletionRequest`, `CompletionResponse`,
  `Message`, `ToolDefinition`, `ToolCall`; full error hierarchy
  (`ProviderError` → `ProviderTimeoutError`, `ProviderRateLimitError`,
  `ProviderAuthError`, `ProviderUnavailableError`);
  `_retry_with_backoff` utility (exponential backoff + full jitter, capped at 60 s)
- `repoheart/providers/opencode.py` — OpenCode HTTP provider using stdlib
  `urllib.request` only; no extra install dependency; maps 429/401/403/5xx/timeout
  to the appropriate `ProviderError` subclass; retries on rate-limit and server errors
- `repoheart/providers/claude.py` — Anthropic provider with guarded
  `import anthropic` (raises helpful `ProviderError` when SDK absent); maps
  `text` and `tool_use` content blocks; maps all Anthropic error types to the
  shared hierarchy
- `repoheart/providers/openai.py` — OpenAI provider with guarded `import openai`;
  prepends `system` role message when `request.system` is non-empty; same error
  mapping pattern
- `repoheart/providers/mock.py` — `MockProvider` deterministic test double;
  keyed canned responses, `default_response`, `call_count`, `raise_on_complete`;
  never touches the network
- `repoheart/providers/registry.py` — `build_provider()` factory dispatching on
  provider name; `resolve_provider()` respects per-agent config overrides and
  caches instances by `(name, model)` for the process lifetime; `clear_cache()`
  for test isolation
- `repoheart/providers/__init__.py` — public re-exports for all types, errors,
  `MockProvider`, and `CannedResponse`

### Changed

- `repoheart/orchestrator/agent_context.py` — added `provider: Provider | None = None`
  field (backward-compatible default); uses `TYPE_CHECKING` guard to avoid circular import
- `repoheart/orchestrator/orchestrator.py` — added `provider_factory: Callable[[str], Provider] | None = None`
  constructor parameter; `_build_context` calls the factory and passes the
  result into `AgentContext`
- `repoheart/main.py` — instantiates a provider factory from config; probes the
  provider at startup (fail-fast before pipeline runs); passes the factory to
  `Orchestrator`

### Tests

- 6 new test modules, 205 tests total (up from 137 at Phase 1 exit); all passing
- `test_providers_base.py` — frozen dataclasses, error hierarchy, retry util
- `test_providers_mock.py` — key lookup, `call_count`, `raise_on_complete`, determinism
- `test_providers_registry.py` — factory dispatch, `ConfigError` on unknown name,
  `ProviderError` on missing SDK, cache identity, per-agent override, end-to-end
  orchestrator integration with `MockProvider`
- `test_providers_opencode.py` — HTTP serialization, error mapping, retry-on-429,
  timeout handling (all via mocked `urlopen`)
- `test_providers_claude.py` — SDK mapping via `sys.modules` patch, error mapping,
  missing-SDK path
- `test_providers_openai.py` — same pattern as Claude

---

## [0.1.0] - 2026-08-24

Phase 1 — Deterministic Core. Everything that is not an LLM: the backbone the
agent system runs on. No LLM is called anywhere in this release.

### Added

- `repoheart/config/schema.py` — typed dataclasses mirroring `repoheart.schema.json`
  (`RepoHeartConfig`, `ProviderConfig`, `AgentsConfig`, `AutomationConfig`, etc.)
- `repoheart/config/loader.py` — fail-fast YAML loader and validator; raises
  `ConfigError` before any agent or API call is made
- `repoheart/events/types.py` — frozen `InternalEvent` dataclass with `routing_key`
  property; normalizes raw GitHub payloads into a typed value object
- `repoheart/events/context.py` — `load_event` reads `GITHUB_EVENT_PATH` / `--event`
  and produces an `InternalEvent`; `infer_event_name` heuristic for local runs
- `repoheart/events/router.py` — deterministic `ROUTING_TABLE` mapping 13 GitHub
  event types to ordered agent name lists; `route()` filters by config
- `repoheart/idempotency/fingerprint.py` — SHA-256 per-agent fingerprinting over
  `{event}.{action}:{repo}:{entity_id}:{agent}`; no external state required
- `repoheart/idempotency/markers.py` — reads/writes idempotency fingerprints as
  hidden HTML comments in GitHub issues/PRs; all writes require `Decision.ALLOW`
- `repoheart/safety/gate.py` — `SafetyGate.authorize()` enforces hard invariants
  (DELETE_BRANCH always DENY), `require_human_approval`, and automation-level
  ceilings (assist/auto-safe/auto); logs every decision
- `repoheart/github_ops/budgeter.py` — token-bucket `RateLimiter` (5 000 req/hr);
  syncs from `X-RateLimit-*` response headers
- `repoheart/github_ops/client.py` — GitHub REST API wrapper using `urllib.request`
  (zero new deps); write methods require `Decision.ALLOW` or raise `PermissionDenied`
- `repoheart/git_ops/repo.py` — `GitRepo` class wrapping local `git` via subprocess:
  merge-base, diff, changed-files, branch creation, commit, rev-parse
- `repoheart/orchestrator/agent_context.py` — frozen `AgentContext` passed into
  every agent; contains pre-fetched data only (no live client references)
- `repoheart/agents/noop.py` — `NoOpAgent` Phase 1 placeholder; returns empty
  `AgentResult`, no LLM calls
- `repoheart/agents/registry.py` — `AGENT_REGISTRY` dict mapping all 10 agent
  names to their implementing class (all `NoOpAgent` in Phase 1)
- `repoheart/orchestrator/orchestrator.py` — `Orchestrator.run()` sequences the
  per-agent loop: idempotency check → context build → agent run → ceiling validate
  → safety gate → execute/escalate/deny; per-agent exception isolation
- `repoheart/main.py` — full pipeline wiring replaces Phase 0 skeleton:
  config load → event parse → route → orchestrate → log summary

### Tests

- 13 new test modules, 137 tests total (up from 7); all passing
- Coverage: config loading, event normalization, routing, fingerprinting, marker
  parse/write, safety gate decision paths, rate limiter math, GitHub client
  permission guard, git repo primitives, orchestrator sequencing, CLI happy/error paths

---

## [0.0.0] - 2026-08-24

Initial project skeleton. All Phase 0 exit criteria are verified green.

### Added

- Repository skeleton matching the final system design layout
  (`config/`, `events/`, `orchestrator/`, `agents/`, `retrieval/`,
  `repo_access/`, `cache/`, `providers/`, `git_ops/`, `github_ops/`,
  `safety/`, `idempotency/`, `observability/`)
- `repoheart/safety/policy.py` — `RiskLevel`, `ActionKind`, `Decision` enums
  and the `ACTION_RISK` permission table
- `repoheart/agents/base.py` — `Agent` ABC, `AgentResult`, `ProposedAction`,
  `Finding` value objects with structural safety enforcement
- `repoheart/observability/logger.py` — structured `key=value` logger
- `pyproject.toml` — hatchling build, ruff/mypy/pytest config, provider extras
  (`claude`, `openai`)
- `action.yml` + `Dockerfile` — GitHub Action entry point
- `repoheart.schema.json` — published config schema for `repoheart.yml`
- `repoheart.yml` — reference configuration template
- `tests/test_safety_invariants.py` — guardrail tests for no-MERGE,
  no-force-push, risk-level ordering, ceiling enforcement, and
  downgrade prevention
- CI workflow (lint, type-check, test on every PR and push to `main`)
- Docker publish workflow (push to GHCR on `main` and version tags)
- `CONTRIBUTING.md`, `ARCHITECTURE.md`, `PROJECT.md`, `ROADMAP.md`,
  `AGENTS.md`, `CLAUDE.md`
- `docs/repoheart-final-system-design.md` — authoritative system design
- `examples/` directory for saved event payloads

---

## Versioning

This project follows [Semantic Versioning](https://semver.org/):

- **MAJOR** — breaking changes to the `repoheart.yml` config schema or the
  `Agent` / `Provider` ABCs
- **MINOR** — new agents, providers, or backward-compatible features
- **PATCH** — bug fixes and safe improvements

## Links

[Unreleased]: https://github.com/OpenAgentHQ/repoheart/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/OpenAgentHQ/repoheart/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/OpenAgentHQ/repoheart/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/OpenAgentHQ/repoheart/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/OpenAgentHQ/repoheart/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/OpenAgentHQ/repoheart/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/OpenAgentHQ/repoheart/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/OpenAgentHQ/repoheart/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/OpenAgentHQ/repoheart/compare/v0.0.0...v0.1.0
[0.0.0]: https://github.com/OpenAgentHQ/repoheart/releases/tag/v0.0.0
