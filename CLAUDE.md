# CLAUDE.md

Guidance for AI coding agents (Claude Code, etc.) working in the RepoHeart repository.
Read this before making changes. It encodes the non-negotiable architecture so agents don't accidentally violate it.

---

## What RepoHeart Is

A **stateless, event-driven, multi-agent system** that runs inside a user's GitHub Actions workflow and automatically activates specialized AI agents to triage issues, review PRs, repair CI, resolve conflicts, and maintain repository health.

One-line mental model:
> Add one workflow. Choose an AI provider. RepoHeart takes care of the repository.

The authoritative spec is `docs/repoheart-final-system-design.md`. **If code and that doc disagree, the doc wins** — update the doc deliberately, don't drift from it silently.

---

## Non-Negotiable Architecture Rules

These are invariants. Do not violate them even if a task seems to ask for it — flag the conflict instead.

1. **Stateless between runs.** No process may assume state persists across GitHub Actions invocations. All state lives in GitHub (issues, labels, comments, commits) or an *optional* content-hash cache. Never introduce a required database.

2. **Agents never execute writes.** An `Agent.run()` returns a declarative `AgentResult` (findings + `ProposedAction`s). It must **never** call the GitHub API or git directly. Only the Orchestrator + Safety Gate execute actions.

3. **No write bypasses the Safety Gate.** Every mutating call in `github_ops`/`git_ops` requires a `Decision.ALLOW` token from `SafetyGate.authorize()`. Do not add a write path that skips it.

4. **Deterministic core, LLM only in agent reasoning.** Event routing, permissions, idempotency, and retrieval orchestration are plain code with no LLM call. Only the *content* of what an agent decides is model-driven.

5. **Provider-agnostic.** Agents depend only on the `Provider` ABC. Never `import anthropic` / `import openai` inside an agent. Provider selection happens once, in `main.py`, from config.

6. **Safety hard invariants (code, not config):**
   - No agent can raise its own risk level.
   - No force-push, ever.
   - **No `MERGE` `ActionKind` exists** in the MVP enum — don't add one.
   - Never commit secrets, expose credentials, rewrite protected history, or bypass required checks.
   - Conflict resolution never blindly picks `ours`/`theirs`; low confidence → ESCALATE.

7. **Bounded work per event.** Cost scales with the event's blast radius, not repo size. Respect `ContextBudget` and per-run ceilings (`max_llm_calls`, `max_files_read`, `max_runtime_seconds`). Never load a whole large repo into context.

---

## Risk Levels

```text
SAFE     read repo, add label, post comment
LOW      create branch
MEDIUM   modify code, push branch
HIGH     merge PR, delete branch, force ops   (HIGH ops mostly unreachable in MVP)
```

Every `ProposedAction` carries a `risk`. The Safety Gate authorizes per-action, not per-agent.

---

## Repository Layout

```text
repoheart/
├── config/         opencode.yml schema + loader
├── events/         context builder, event types, router
├── orchestrator/   sequencing, agent context, budgets
├── agents/         one file per agent (base.py = ABC)
├── retrieval/      structural/lexical/semantic retrieval + chunking + budget
├── repo_access/    sparse/shallow/partial checkout, merge-base
├── cache/          optional cache backends (actions cache, vector store)
├── providers/      one file per provider (base.py = ABC)
├── git_ops/        local git operations
├── github_ops/     GitHub API wrappers + rate-limit budgeter
├── safety/         policy table + gate
├── idempotency/    fingerprint + markers
└── observability/  structured logger
```

When adding a feature, put it in the component that owns that responsibility. Don't spread one concern across layers.

---

## Coding Conventions

- **Language:** Python 3.11+.
- **Style:** type hints everywhere; dataclasses for value objects; ABCs for extension points (Agent, Provider, CacheBackend).
- **No hidden I/O in agents.** Agents receive an `AgentContext` and return an `AgentResult`. Pure-ish: reasoning in, declaration out.
- **Logging:** structured single-line `key=value` records via `observability/logger.py`. The Actions run log is the audit trail — log every proposed action and its `Decision`.
- **Errors:** fail fast on config errors (before any agent runs); catch per-agent exceptions at the orchestrator so one bad agent doesn't kill the run.
- **Tests:** every agent needs a test that feeds a synthetic event and asserts the `ProposedAction`s (and that none exceed the agent's risk ceiling). Mock the provider — never hit a real LLM in unit tests.

---

## Adding a New Agent (checklist)

1. Subclass `Agent` in `agents/<name>.py`; set `name`, `risk_level` (ceiling), `handles_events`.
2. Implement `run(context) -> AgentResult`. No direct writes.
3. Register the agent's event types in `events/router.py`.
4. Add config toggle in the `opencode.yml` schema + `opencode.schema.json`.
5. Add a unit test asserting proposed actions + risk ceiling.
6. Update the routing table + roster in the final design doc.

## Adding a New Provider (checklist)

1. Subclass `Provider` in `providers/<name>.py`; implement `complete()` + `supports_tools()`.
2. Register it in the provider registry.
3. Add it to the `provider.name` enum in the config schema.
4. Add credential env var to `action.yml` and the workflow template (unused secrets resolve empty).
5. Never leak provider specifics above the `Provider` interface.

---

## What NOT To Do

- Don't add Redis/Postgres as a requirement.
- Don't let an agent call `github_ops`/`git_ops` write methods directly.
- Don't add a merge capability.
- Don't clone full history by default (`fetch-depth: 0`) — use event-scoped checkout.
- Don't feed raw whole files to the LLM when tool output (linter, tests, symbol graph, search hits) will do.
- Don't make the cache required for correctness.
- Don't silently diverge from the final design doc.

---

## Quick Commands (fill in as build progresses)

```bash
# install
pip install -e ".[dev]"

# lint + type check
ruff check . && mypy repoheart

# tests
pytest

# run locally against a saved event payload
python -m repoheart.main --event examples/issues.opened.json --config opencode.yml
```
