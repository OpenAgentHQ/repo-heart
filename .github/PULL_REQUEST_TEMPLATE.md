## Summary

<!-- What does this PR do? Link the issue it closes if applicable. -->

Closes #

## Type of Change

- [ ] Bug fix
- [ ] New agent
- [ ] New provider
- [ ] New feature / enhancement
- [ ] Refactor (no behavior change)
- [ ] Test
- [ ] Documentation
- [ ] CI / tooling

## Architecture Checklist

These are the non-negotiables from `CLAUDE.md`. Tick each one you've verified:

- [ ] **Stateless** — no new required database or persistent process state
- [ ] **Agent declares, never executes** — `run()` returns `ProposedAction`s only; no direct `github_ops` / `git_ops` writes
- [ ] **Safety Gate respected** — every write path goes through `SafetyGate.authorize()`
- [ ] **Deterministic core** — no LLM call in routing, idempotency, or safety logic
- [ ] **Provider-agnostic** — no provider SDK import inside an agent
- [ ] **Safety invariants intact** — no `MERGE`, no force-push, no self-escalation
- [ ] **Bounded work** — respects `ContextBudget` and per-run ceilings

## Testing

- [ ] `ruff check .` passes
- [ ] `mypy repoheart` passes
- [ ] `pytest` passes
- [ ] New agent has a test asserting `ProposedAction`s and risk ceiling
- [ ] Safety-relevant changes include a regression test

## Notes for Reviewers

<!-- Anything non-obvious about the approach, trade-offs made, or areas to scrutinize. -->
