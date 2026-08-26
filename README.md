<div align="center">

# ❤️ RepoHeart

![RepoHeart](assets/social-preview.png)

**The autonomous heart of your GitHub repository.**

A 24/7, event-driven, multi-agent system that watches your repo and automatically activates specialized AI agents to triage issues, review PRs, repair CI, resolve conflicts, and keep the repository healthy — safely, and provider-agnostically.

[![PyPI version](https://img.shields.io/pypi/v/repoheart?color=crimson&label=PyPI)](https://pypi.org/project/repoheart/)
[![Python](https://img.shields.io/pypi/pyversions/repoheart)](https://pypi.org/project/repoheart/)
[![Downloads](https://img.shields.io/pypi/dm/repoheart)](https://pypi.org/project/repoheart/)
[![License](https://img.shields.io/github/license/OpenAgentHQ/repo-heart)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/OpenAgentHQ/repo-heart/ci.yml?label=CI)](https://github.com/OpenAgentHQ/repo-heart/actions/workflows/ci.yml)

</div>

---

## Install

```bash
pip install repoheart
```

Use `repoheart init` to generate all required config files in one command:

```bash
repoheart init
```

This interactively creates `repoheart.yml` and `.github/workflows/repoheart.yml` in your repository. Pass `--yes` for non-interactive (CI-safe) mode:

```bash
repoheart init --provider claude --model claude-sonnet-4-6 --yes
```

---

## Why

Maintaining an active repository is endless manual work: triaging issues, spotting duplicates, checking what was already fixed, reviewing PRs, watching CI, resolving conflicts, keeping docs current. RepoHeart automates the repetitive parts while keeping humans in control of anything risky.

It runs **entirely inside your GitHub Actions workflow** — no hosted server, no database, no external infrastructure. Add one workflow, choose an AI provider, done.

---

## How It Works

```text
GitHub Event → Actions runner → normalize + dedup → route to agents
            → each agent retrieves bounded context, reasons, proposes actions
            → Safety Gate authorizes every write
            → results written back to GitHub → run exits (holds no state)
```

Deterministic where it must be (routing, permissions, idempotency), AI-driven where it helps (the reasoning inside each agent).

---

## Quick Start

**Option A — zero-copy (recommended):**

```bash
pip install repoheart
cd your-repo
repoheart init
```

`repoheart init` generates both files below interactively and prints the next steps.

**Option B — manual:**

**1. Add the workflow** — `.github/workflows/repoheart.yml`:

```yaml
name: RepoHeart
on:
  issues:
    types: [opened, edited]
  pull_request:
    types: [opened, synchronize, reopened]
  workflow_run:
    types: [completed]

permissions:
  contents: write
  issues: write
  pull-requests: write

jobs:
  repoheart:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: OpenAgentHQ/repo-heart@main
        with:
          config: repoheart.yml
```

**2. Configure** — `repoheart.yml`:

```yaml
# repoheart.yml — RepoHeart configuration
#
# Only `provider` and at least one enabled agent are required.
# Everything else has safe defaults.

repoheart:

  # ── AI provider ────────────────────────────────────────────────
  # Switch providers by changing `name` (and `model`). Agents are untouched.
  provider:
    name: opencode            # opencode | claude | openai | gemini | local
    model: mimo-v2.5-free

  # Optional: override the provider for specific agents.
  # Anything not listed uses `provider` above.
  # providers:
  #   agents:
  #     issue_triage: claude
  #     conflict_resolution: openai

  # ── Agents ─────────────────────────────────────────────────────
  # Enable only what you want. Disabled agents never run.
  agents:
    issue_triage: true        # label and prioritize new issues
    duplicate_detection: true # find duplicate/related issues
    issue_resolution: true    # detect issues fixed by prior PRs
    pr_review: true           # coherent PR review (correctness, quality, risk)
    code_quality: true        # lint / format / type checks on changed paths
    security: true            # secret + dependency scanning on the diff
    ci_repair: true           # diagnose CI failures, attempt safe fixes
    conflict_resolution: true # resolve safe merge conflicts, escalate the rest
    test: true                # test-impact mapping and test generation
    documentation: true       # keep docs current with changed public symbols

    # Fine-grained options for the documentation agent (only read when documentation: true).
    # documentation_config:
    #   changelog_on_release: true    # draft release notes on release.published events
    #   docstring_style: google       # google | numpy | sphinx

  # ── Automation posture ─────────────────────────────────────────
  automation:
    # assist    → propose + comment, never modify code
    # auto-safe → auto-apply SAFE/LOW actions, escalate the rest
    # auto      → auto-apply up to MEDIUM, escalate HIGH
    level: assist

    # Risk levels that always require a human, regardless of `level`.
    require_human_approval:
      - HIGH
      - MEDIUM

  # ── Scaling (large repos) ──────────────────────────────────────
  scale:
    # event-scoped → sparse/shallow checkout per event (recommended)
    # full         → full clone (small repos only)
    checkout: event-scoped

    retrieval:
      semantic: false         # opt-in embeddings; needs a cache backend

    cache:
      backend: actions        # none | actions | branch | vector-store

    # Hard ceilings per run — a runaway event can never exceed these.
    limits:
      max_llm_calls: 30
      max_files_read: 200
      max_runtime_seconds: 600

  # ── Labels (optional) ──────────────────────────────────────────
  # Customize the labels RepoHeart applies/reads. Defaults shown.
  # labels:
  #   triaged: "repoheart:triaged"
  #   reviewed: "repoheart:reviewed"
  #   needs_human: "repoheart:needs-human"

  # ── CI behavior (optional) ─────────────────────────────────────
  # ci:
  #   watch_workflows: ["ci.yml", "tests.yml"]   # narrow which failures trigger CI Repair
  #   max_fix_attempts: 2
```

**3. Add provider credentials** as repository secrets (e.g. `OPENCODE_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`).

That's it.

---

## The Agents

| Agent | Does |
|---|---|
| Issue Triage | Classifies, labels, and summarizes new issues |
| Duplicate Detection | Finds duplicate/related issues |
| Issue Resolution | Detects issues already fixed by prior PRs/commits |
| PR Review | Coherent review of correctness, quality, and risk |
| Code Quality | Lint / format / type checks on changed paths |
| Security | Secret + dependency scanning on the diff |
| CI Repair | Diagnoses CI failures and attempts safe, verified fixes |
| Conflict Resolution | Resolves safe merge conflicts; escalates the rest |
| Test | Test-impact mapping and test generation |
| Documentation | Keeps docs current with changed public symbols |

Enable only what you want in `repoheart.yml`.

---

## Switching AI Providers

Change one line. Agents are untouched.

```yaml
provider:
  name: claude      # was: opencode
  model: claude-model
```

---

## Built for Big Repos Too

RepoHeart doesn't load your whole codebase into a prompt. It **retrieves** only what each event needs — using tree-sitter, ripgrep, and GitHub Search to do the heavy lifting, with event-scoped (sparse/shallow) checkout and an optional content-hash cache. Cost scales with the event's blast radius, not your repo size.

---

## Safety First

> Safety first, then correctness, then automation.

- Every write passes a mandatory Safety Gate.
- Agents can never escalate their own permissions.
- No force-push. No auto-merge in the MVP. No committed secrets.
- Low-confidence or high-risk situations escalate to a human with a clear explanation — never a silent guess, never broken state left behind.

---

## Documentation

| Doc | Purpose |
|---|---|
| [PROJECT.md](PROJECT.md) | Overview and orientation |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Condensed architecture reference |
| [ROADMAP.md](ROADMAP.md) | Phased build plan |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup and conventions |
| [CLAUDE.md](CLAUDE.md) | Rules for AI coding agents |
| `docs/repoheart-final-system-design.md` | Full authoritative system design |

---

## Status

**v1.0 — Fully Implemented.** All 7 roadmap phases complete: deterministic core, provider abstraction, issue intelligence, PR intelligence, large-repo scaling, CI repair & conflict resolution, and documentation agent. 524+ tests passing, `ruff` clean, `mypy strict` clean, provider switching config-only. One-workflow + one-config onboarding verified on real repos. See [ROADMAP.md](ROADMAP.md) for full details.

---

## License

See [LICENSE](LICENSE).

<div align="center">

**RepoHeart is not just a bot. It's an autonomous repository engineering system.**

</div>
