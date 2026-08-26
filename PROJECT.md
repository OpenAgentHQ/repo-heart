# PROJECT.md — RepoHeart

> **The autonomous heart of your GitHub repository.**

---

## What It Is

RepoHeart is a **24/7, event-driven, multi-agent system** that observes a GitHub repository and automatically activates specialized AI agents to understand, review, maintain, and safely improve it — from a weekend project to a LangChain/opencode-scale monorepo.

It runs **entirely inside the user's GitHub Actions workflow**. No hosted server, no database, no external infrastructure is required. The user provides one workflow file, one config file, and provider credentials.

---

## The Problem

Maintaining an active repository is constant manual work: triaging issues, detecting duplicates, checking whether something was already fixed, reviewing PRs, watching CI, resolving conflicts, keeping docs current. RepoHeart automates the repetitive maintenance while keeping humans in control of high-risk decisions.

---

## How It Works (in one breath)

A GitHub event fires → RepoHeart starts in an ephemeral Actions runner → it normalizes the event, checks config, and dedups against GitHub-native markers → a deterministic router picks the relevant agents → each agent retrieves only the context it needs, reasons over it with the configured AI provider, and proposes actions → a Safety Gate authorizes each action by risk level → allowed actions are written back to GitHub, risky ones are escalated to a human → the run exits. Nothing persists between runs except what's in GitHub.

---

## Core Principles

| Principle | Meaning |
|---|---|
| **Event-driven** | React to meaningful GitHub events, not constant polling. |
| **Specialized agents** | Many focused agents, not one giant prompt. |
| **Provider-agnostic** | OpenCode / Claude / OpenAI / Gemini / local are interchangeable. |
| **Deterministic core** | Routing, permissions, state, safety are plain code — not LLM-decided. |
| **Stateless** | Every run reconstructs context from GitHub; no run depends on a prior run. |
| **Idempotent** | Repeated events never create duplicate actions. |
| **Observable** | Every agent execution is traceable in the Actions log. |
| **Safe by default** | Dangerous actions are unreachable, not merely disabled. |
| **Minimal changes** | Agents make the smallest change that solves the problem. |
| **Human escalation** | The system knows when to stop and ask. |
| **Bounded per event** | Cost scales with the event's blast radius, not repo size. |

---

## The Agents

```text
Issue Triage · Duplicate Detection · Issue Resolution ·
PR Review · Code Quality · Security · CI Repair ·
Conflict Resolution · Test · Documentation
```

Each has a fixed responsibility, a static risk ceiling, a permission set, and a config toggle.

---

## Deployment Model

```text
User Repo
 ├── .github/workflows/repoheart.yml   ← one workflow
 └── opencode.yml                      ← config + provider choice
        │
        ▼
   GitHub Actions (execution environment)
        │
        ▼
   RepoHeart Runtime (all business logic)
        │
        ▼
   Writes results back to GitHub, then exits
```

GitHub Actions is the *execution environment*, not the business logic. The same core can later run under Docker, a local CLI, or a self-hosted runner without a rewrite.

---

## User Experience

**1. Add the workflow** (`.github/workflows/repoheart.yml`):

```yaml
- uses: OpenAgentHQ/repoheart@main
  with:
    config: opencode.yml
```

**2. Configure** (`opencode.yml`):

```yaml
repoheart:
  provider:
    name: opencode
    model: your-model
  agents:
    issue_triage: true
    pr_review: true
    ci_repair: true
```

**3. Add provider credentials** as Actions secrets.

That's it.

---

## Scaling to Large Repos

RepoHeart doesn't ingest the whole repo — it **retrieves** only what each event needs. Deterministic tools (tree-sitter, ripgrep, linters, GitHub Search) do the O(repo) work; the LLM only ever sees a bounded, budgeted context. Checkout is event-scoped (sparse/shallow/partial), not a full clone. An optional content-hash cache makes big repos cheap without ever being required for correctness.

---

## Safety Posture

> **Safety first, then correctness, then automation.**

- Every write passes a mandatory Safety Gate.
- Agents can never escalate their own permissions.
- No force-push. No merge capability in the MVP. No committed secrets.
- Low-confidence or high-risk situations escalate to a human with a clear explanation, and never leave broken state behind.

---

## Tech Stack (MVP)

```text
Python 3.11+
  + GitHub Actions
  + GitHub API
  + Git
  + tree-sitter / ripgrep (retrieval)
  + Provider abstraction (OpenCode / Claude / OpenAI / Gemini / local)
  + opencode.yml config
```

No Redis, no Postgres required.

---

## Documentation Map

| Doc | Purpose |
|---|---|
| `PROJECT.md` | This file — orientation and overview. |
| `CLAUDE.md` | Rules for AI coding agents working in the repo. |
| `ROADMAP.md` | Phased build plan and milestones. |
| `ARCHITECTURE.md` | Condensed architecture reference (see full design doc). |
| `CONTRIBUTING.md` | How to contribute, dev setup, conventions. |
| `docs/repoheart-final-system-design.md` | The authoritative, complete system design. |

---

## Status

**v1.0 — Fully Implemented.** All 7 roadmap phases completed: deterministic core, provider abstraction, issue intelligence, PR intelligence, large-repo scaling, CI repair & conflict resolution, and documentation agent. Every phase exit criteria verified (524+ tests passing, ruff clean, mypy strict clean). Provider switching works config-only. One-workflow + one-config onboarding verified on real repos. See `ROADMAP.md` for full phase details.
