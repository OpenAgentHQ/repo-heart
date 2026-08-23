# Changelog

All notable changes to RepoHeart will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Phase 1 deterministic core (config loader, event context builder, router,
  idempotency, Safety Gate, structured logger, GitHub/git ops wrappers, main pipeline)

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

[Unreleased]: https://github.com/OpenAgentHQ/repoheart/compare/v0.0.0...HEAD
[0.0.0]: https://github.com/OpenAgentHQ/repoheart/releases/tag/v0.0.0
