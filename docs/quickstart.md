# Quickstart

This walks through setting up RepoHeart on a repository for the first time: adding the workflow, configuring it, wiring up a provider secret, and confirming it actually runs.

## Prerequisites

- A GitHub repository you can push to and that has **Actions enabled** (Settings → Actions → General → "Allow all actions and reusable workflows", or your org's equivalent).
- Permission to add repository secrets (Settings → Secrets and variables → Actions).
- An API key for at least one supported AI provider: `opencode`, `claude` (Anthropic), `openai`, `gemini`, or a `local` model endpoint.

RepoHeart runs entirely inside GitHub Actions — there's no server to deploy and no database to provision.

## 1. Add the workflow

Create `.github/workflows/repoheart.yml` in your repository:

```yaml
name: RepoHeart

on:
  issues:
    types: [opened, edited]

  issue_comment:
    types: [created]

  pull_request:
    types: [opened, synchronize, reopened]

  pull_request_review:
    types: [submitted]

  push:

  workflow_run:
    workflows: ["*"]
    types: [completed]

  release:
    types: [published]

permissions:
  contents: write
  issues: write
  pull-requests: write
  checks: read
  actions: read

concurrency:
  group: repoheart-${{ github.event.issue.number || github.event.pull_request.number || github.ref }}
  cancel-in-progress: false

jobs:
  repoheart:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run RepoHeart
        uses: OpenAgentHQ/repoheart@main
        with:
          config: opencode.yml
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          # Provider credentials — only the ones referenced in opencode.yml
          # need to actually be set; unused secrets simply resolve empty.
          OPENCODE_API_KEY: ${{ secrets.OPENCODE_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

You don't need every trigger above — trim the `on:` block to the events you actually want RepoHeart reacting to. But note `pull_request` alone won't cover CI Repair; that agent relies on `workflow_run` events completing after your CI workflow finishes.

## 2. Copy and fill in `opencode.yml`

Create `opencode.yml` in your repository root:

```yaml
repoheart:

  provider:
    name: opencode            # opencode | claude | openai | gemini | local
    model: your-model

  agents:
    issue_triage: true
    duplicate_detection: true
    issue_resolution: true
    pr_review: true
    code_quality: true
    security: true
    ci_repair: true
    conflict_resolution: true
    test: false
    documentation: false

  automation:
    # assist    → propose + comment, never modify code
    # auto-safe → auto-apply SAFE/LOW actions, escalate the rest
    # auto      → auto-apply up to MEDIUM, escalate HIGH
    level: assist

    require_human_approval:
      - HIGH
      - MEDIUM
```

At minimum you need `provider.name` set and at least one agent enabled — everything else falls back to safe defaults (see `docs/configuration.md` for the full field reference and `docs/safety.md` for what the automation levels and risk labels mean).

For a first run, leave `automation.level` at `assist`. RepoHeart will comment and propose actions without touching code, which is the safest way to see what it would do before giving it write access.

## 3. Add the secret to the repo

Go to **Settings → Secrets and variables → Actions → New repository secret**, and add the key that matches your chosen provider:

| `provider.name` in `opencode.yml` | Secret to add       |
| ---------------------------------- | -------------------- |
| `opencode`                         | `OPENCODE_API_KEY`   |
| `claude`                           | `ANTHROPIC_API_KEY`  |
| `openai`                           | `OPENAI_API_KEY`     |
| `gemini`                           | `GEMINI_API_KEY`     |
| `local`                            | none (points at your own endpoint — see `docs/providers.md`) |

You only need to set the secret for the provider you're actually using; the workflow above wires up all four env vars, but unset ones just resolve empty and are ignored.

## 4. Open a test issue

Commit and push both files to `main`, then open a new issue in the repository — any title and body will do.

Within a minute or two, you should see:

- A new run appear under the **Actions** tab, named `RepoHeart`.
- A comment or label added to the issue by RepoHeart (issue triage runs on `issues: opened` by default).

That confirms the workflow is wired up, the provider credential is valid, and at least one agent is active.

## Troubleshooting: "why didn't it run?"

Work through these in order:

1. **Check the Actions tab.** If there's no run at all for your event, the workflow trigger didn't match — double check the `on:` block includes the event type you triggered (e.g. `issues: opened`), and that Actions are enabled for the repo.
2. **Check if the run failed.** Open the run and look at the `Run RepoHeart` step logs. A failure here is almost always a missing or invalid provider secret — confirm the secret name matches exactly what `provider.name` expects (table above) and that the key is valid.
3. **Check labels.** Some agents skip events based on labels RepoHeart itself manages (e.g. it won't re-triage an issue already labeled `repoheart:triaged`). If you're testing repeatedly on the same issue, remove RepoHeart's labels before re-triggering, or open a fresh issue.
4. **Check `permissions:`.** If the run succeeds but nothing shows up on GitHub (no comment, no label), the job likely lacks `issues: write` or `pull-requests: write` in the workflow's `permissions:` block.
5. **Check the agent is enabled.** Confirm the relevant agent is `true` under `agents:` in `opencode.yml` — disabled agents never run, and RepoHeart won't log an error for a deliberately skipped agent.
6. **Check `automation.level`.** With `level: assist`, RepoHeart proposes and comments but never modifies code — if you were expecting an auto-applied fix, this is expected behavior, not a bug. See `docs/safety.md`.

If none of that explains it, the run logs (Actions tab → the failed/completed run → `Run RepoHeart` step) are the next place to look; RepoHeart logs which agents it evaluated for the event and why each did or didn't act.
