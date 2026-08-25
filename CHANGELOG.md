# Changelog

All notable changes to RepoHeart will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

- `repoheart/config/schema.py` — typed dataclasses mirroring `opencode.schema.json`
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
- `opencode.schema.json` — published config schema for `opencode.yml`
- `opencode.yml` — reference configuration template
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

- **MAJOR** — breaking changes to the `opencode.yml` config schema or the
  `Agent` / `Provider` ABCs
- **MINOR** — new agents, providers, or backward-compatible features
- **PATCH** — bug fixes and safe improvements

## Links

[Unreleased]: https://github.com/OpenAgentHQ/repoheart/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/OpenAgentHQ/repoheart/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/OpenAgentHQ/repoheart/compare/v0.0.0...v0.1.0
[0.0.0]: https://github.com/OpenAgentHQ/repoheart/releases/tag/v0.0.0
