# Contributing to RepoHeart

Thanks for helping build RepoHeart. This guide covers setup, conventions, and the rules that keep the architecture sound.

Before writing code, read **`CLAUDE.md`** (the architecture invariants apply to humans too) and **`ARCHITECTURE.md`**.

---

## Development Setup

Requirements: Python 3.11+, Git.

```bash
git clone https://github.com/OpenAgentHQ/repoheart.git
cd repoheart
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Verify:

```bash
ruff check .
mypy repoheart
pytest
```

Run locally against a saved event payload (no live GitHub needed):

```bash
python -m repoheart.main --event examples/issues.opened.json --config opencode.yml
```

---

## The Non-Negotiables

A PR that violates any of these will be asked to change, regardless of how useful the feature is:

1. **Stateless between runs** — no required database; state lives in GitHub or the optional cache.
2. **Agents never execute writes** — `run()` returns declarative actions; only Orchestrator + Safety Gate execute.
3. **No write bypasses the Safety Gate.**
4. **Deterministic core** — no LLM in routing, safety, idempotency, or retrieval orchestration.
5. **Provider-agnostic agents** — no provider SDK imports inside agents.
6. **Safety invariants** — no self-escalation, no force-push, no merge capability, no committed secrets.
7. **Bounded per event** — respect `ContextBudget` and per-run ceilings.

If a task seems to require breaking one of these, open an issue to discuss the architecture rather than working around it.

---

## Conventions

- **Type hints** on all public functions; dataclasses for value objects; ABCs for extension points.
- **Structured logging** only (`key=value` via `observability/logger.py`). Log every proposed action + its `Decision`.
- **Small, focused changes** — mirror the "minimal changes" principle RepoHeart itself follows.
- **One responsibility per module** — put code in the component that owns the concern.
- **Fail fast** on config errors; **catch per-agent** exceptions at the orchestrator.

### Commit & branch style

- Task-based branch names: `feat/issue-triage-agent`, `fix/rate-limit-backoff`. No agent-name or random-suffix branches.
- Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- Human authorship — do not add AI attribution footers or co-author trailers.

---

## Testing Requirements

- Every agent needs a test that feeds a synthetic event and asserts its `ProposedAction`s.
- Every agent test must assert **no proposed action exceeds the agent's risk ceiling**.
- Every hard safety invariant needs a test that would fail if the invariant were violated (e.g. a test proving no `MERGE` action can be produced, a test proving force-push is never issued).
- **Mock the provider** — unit tests never call a real LLM.
- Deterministic core (routing, safety, idempotency) should be near-fully covered.

---

## Adding an Agent

1. Subclass `Agent` in `repoheart/agents/<name>.py` — set `name`, `risk_level`, `handles_events`.
2. Implement `run(context) -> AgentResult`; no direct writes.
3. Register event types in `events/router.py`.
4. Add a config toggle to the schema + `opencode.schema.json`.
5. Add tests (proposed actions + risk ceiling).
6. Update the roster + routing table in the design doc.

## Adding a Provider

1. Subclass `Provider` in `repoheart/providers/<name>.py`.
2. Register in the provider registry; add to the config enum.
3. Add the credential env var to `action.yml` + the workflow template.
4. Add a smoke test using recorded/mocked responses.

---

## Pull Request Checklist

- [ ] `ruff`, `mypy`, `pytest` pass.
- [ ] No architecture invariant violated.
- [ ] New agent/provider follows its checklist.
- [ ] Safety-relevant changes include a test that would catch regression.
- [ ] Docs updated if behavior, config, or routing changed.
- [ ] Conventional Commit messages; human authorship.

---

## Reporting Issues

Use the issue templates. For security-sensitive reports (e.g. a way to bypass the Safety Gate or trigger an unsafe action via crafted issue/PR text), follow `SECURITY.md` instead of opening a public issue.
