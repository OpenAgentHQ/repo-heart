# Configuration Reference

Full reference for `opencode.yml`, the single file that controls RepoHeart. This document mirrors [`opencode.schema.json`](../opencode.schema.json) field-for-field, plus the defaults applied by `repoheart/config/loader.py` when a field is omitted.

Everything lives under one top-level key:

```yaml
repoheart:
  provider: {}
  providers: {}
  agents: {}
  automation: {}
  scale: {}
  labels: {}
  ci: {}
```

Only `provider` and `agents` are required (per the schema's `required` list); every other section is optional and falls back to the defaults documented below. `additionalProperties: false` is set at every level of the schema — unrecognized fields will fail validation rather than being silently ignored.

---

## `provider`

The default AI provider used by every agent, unless overridden per-agent under `providers.agents`.

| Field   | Type   | Default | Description |
|---------|--------|---------|-------------|
| `name`  | string (`opencode` \| `claude` \| `openai` \| `gemini` \| `local`) | *required, no default* | Which provider RepoHeart calls. Must match a value the corresponding credential secret is set for (see `docs/quickstart.md`). |
| `model` | string | `""` | Provider-specific model identifier (e.g. a specific Claude or GPT model string). If left empty, the provider implementation's own default model is used. |

```yaml
repoheart:
  provider:
    name: claude
    model: claude-sonnet-4-6
```

---

## `providers`

Per-agent provider overrides. Lets you run, say, a cheaper/faster model for issue triage and a stronger one for security review.

| Field         | Type                      | Default | Description |
|---------------|---------------------------|---------|-------------|
| `agents`      | map of `string → string`  | `{}`    | Keys are agent names (from the `agents` section below); values are provider names from the same enum as `provider.name`. Any agent not listed here falls back to the top-level `provider.name`. |

```yaml
repoheart:
  providers:
    agents:
      issue_triage: gemini      # cheap/fast triage
      security: claude          # stronger reasoning for security review
      pr_review: openai
      # any agent not listed here uses `provider.name`
```

Note that a per-agent override only changes *which provider* is called — it does not change the model unless you also give that provider a model elsewhere (the schema only exposes a single `model` field, on `provider`, so a per-agent override uses that provider's own default model).

---

## `agents`

Boolean toggle per agent. A disabled agent never runs — RepoHeart won't log an error for a deliberately skipped agent, it's simply excluded from event routing.

| Field                  | Type    | Default | Description |
|------------------------|---------|---------|-------------|
| `issue_triage`         | boolean | `true`  | Labels and categorizes new/edited issues. |
| `duplicate_detection`  | boolean | `true`  | Flags issues that look like duplicates of existing ones. |
| `issue_resolution`     | boolean | `true`  | Attempts to resolve straightforward issues (proposes code changes via a branch/PR). |
| `pr_review`            | boolean | `true`  | Reviews opened/updated pull requests and leaves comments. |
| `code_quality`         | boolean | `true`  | Flags code quality issues (style, complexity, dead code, etc.) on PRs. |
| `security`             | boolean | `true`  | Flags security-relevant issues in changed code. |
| `ci_repair`            | boolean | `true`  | Attempts to fix failing CI runs (driven by `workflow_run` events — see `ci` below). |
| `conflict_resolution`  | boolean | `true`  | Proposes merge-conflict resolutions. Never auto-picks `ours`/`theirs`; low-confidence cases always escalate (see Safety Gate section). |
| `test`                 | boolean | `false` | Proposes or updates tests. Off by default. |
| `documentation`        | boolean | `false` | Proposes or updates documentation. Off by default. |

```yaml
repoheart:
  agents:
    issue_triage: true
    duplicate_detection: true
    issue_resolution: false   # keep this off until you trust it
    pr_review: true
    code_quality: true
    security: true
    ci_repair: true
    conflict_resolution: true
    test: false
    documentation: false
```

Only fields explicitly present in your YAML override the default — omit a field entirely and it takes the default listed above, it does not become `false`.

---

## `automation`

Controls how much RepoHeart is allowed to do without a human clicking approve. This is the primary interface to the Safety Gate — see the [Safety Gate](#safety-gate--risk-levels) section below for exactly how these fields are evaluated.

| Field                     | Type                                        | Default              | Description |
|---------------------------|----------------------------------------------|-----------------------|-------------|
| `level`                   | string (`assist` \| `auto-safe` \| `auto`)   | `assist`              | The ceiling on which risk levels can be auto-approved. See table below. |
| `require_human_approval`  | array of (`SAFE` \| `LOW` \| `MEDIUM` \| `HIGH`) | `[HIGH, MEDIUM]`  | Risk levels that always require a human to approve, regardless of `level`. Evaluated *before* the `level` ceiling — listing a risk here escalates it even if `level` would otherwise allow it. |

`level` → auto-approval ceiling:

| `level`      | Highest risk auto-approved | In practice |
|--------------|------------------------------|-------------|
| `assist`     | `SAFE`                       | RepoHeart reads, comments, and labels — it never modifies code or pushes a branch without approval. |
| `auto-safe`  | `LOW`                        | Adds auto-creating branches (still no code changes/pushes without approval). |
| `auto`       | `MEDIUM`                     | Adds auto-applying code changes, commits, and pushes. `HIGH`-risk actions are *always* escalated regardless of `level` — there is no setting that auto-approves them. |

```yaml
# Safest possible configuration — comment/label only, nothing auto-applied
repoheart:
  automation:
    level: assist
```

```yaml
# Auto-apply low + medium risk actions (code changes, pushes), but still
# require a human for anything HIGH-risk, and additionally require a human
# for MEDIUM even though `auto` would otherwise allow it
repoheart:
  automation:
    level: auto
    require_human_approval:
      - HIGH
      - MEDIUM
```

```yaml
# Maximally permissive within the MVP's safety invariants: auto-apply
# everything up to MEDIUM, only escalate HIGH
repoheart:
  automation:
    level: auto
    require_human_approval:
      - HIGH
```

---

## `scale`

Controls how much of the repo RepoHeart pulls into context and how it bounds a single run's cost.

| Field                        | Type                                  | Default          | Description |
|-------------------------------|----------------------------------------|-------------------|-------------|
| `checkout`                   | string (`event-scoped` \| `full`)     | `event-scoped`    | `event-scoped` checks out only what's needed for the triggering event (e.g. the PR's diff and touched files) instead of the whole repo history. Prefer this — see `CLAUDE.md`'s "don't clone full history by default" rule. |
| `retrieval.semantic`         | boolean                               | `false`           | Enables semantic (embedding-based) retrieval in addition to structural/lexical search when an agent needs to find related code. |
| `cache.backend`              | string (`none` \| `actions` \| `branch` \| `vector-store`) | `actions` | Where RepoHeart persists its optional cache (e.g. embeddings, prior analysis) between runs. RepoHeart is stateless by design, so this is a performance optimization, never something correctness depends on — `none` disables caching entirely. |
| `limits.max_llm_calls`       | integer (min `1`)                     | `30`              | Hard ceiling on LLM calls in a single run. |
| `limits.max_files_read`      | integer (min `1`)                     | `200`             | Hard ceiling on files read in a single run. |
| `limits.max_runtime_seconds` | integer (min `1`)                     | `600`             | Hard ceiling on wall-clock runtime for a single run, in seconds. |

```yaml
repoheart:
  scale:
    checkout: event-scoped
    retrieval:
      semantic: false
    cache:
      backend: actions
    limits:
      max_llm_calls: 30
      max_files_read: 200
      max_runtime_seconds: 600
```

Raise these limits for large monorepos where a single event (e.g. a big PR) genuinely needs more context — but per `CLAUDE.md`, cost should scale with the event's blast radius, not repo size, so treat a need to raise these substantially as a signal something else (checkout scope, retrieval strategy) may be misconfigured first.

---

## `labels`

Names of the labels RepoHeart applies to track its own state. Override these if they collide with labels you already use.

| Field         | Type   | Default                    | Description |
|---------------|--------|------------------------------|-------------|
| `triaged`     | string | `repoheart:triaged`          | Applied by `issue_triage` once an issue has been categorized, so it isn't re-triaged on every edit. |
| `reviewed`    | string | `repoheart:reviewed`         | Applied by `pr_review` once a PR has received an initial review pass. |
| `needs_human` | string | `repoheart:needs-human`      | Applied when the Safety Gate escalates an action that needs manual approval. |

```yaml
repoheart:
  labels:
    triaged: repoheart:triaged
    reviewed: repoheart:reviewed
    needs_human: repoheart:needs-human
```

If you're re-testing an agent repeatedly on the same issue/PR, removing these labels manually will let RepoHeart re-process the event (see the troubleshooting section of `docs/quickstart.md`).

---

## `ci`

Configures the CI Repair agent. Only relevant if `agents.ci_repair` is `true`.

| Field                | Type              | Default | Description |
|----------------------|-------------------|---------|-------------|
| `watch_workflows`    | array of string   | `[]`    | Names of your CI workflow(s) to watch for failures via `workflow_run` events. An empty list means CI Repair won't react to any workflow completion — you must list the workflow(s) you want it watching. |
| `max_fix_attempts`   | integer (min `0`) | `2`     | Maximum number of automated fix attempts per failing run before RepoHeart gives up and escalates instead of retrying indefinitely. |

```yaml
repoheart:
  ci:
    watch_workflows:
      - CI
      - Tests
    max_fix_attempts: 2
```

Your `.github/workflows/repoheart.yml` also needs a `workflow_run` trigger for this agent to receive any events in the first place — see `docs/quickstart.md`.

---

## Complete examples

### `assist` mode (safest — recommended starting point)

Comments and labels only. Nothing is modified, committed, or pushed without a human clicking approve.

```yaml
repoheart:
  provider:
    name: claude
    model: claude-sonnet-4-6

  agents:
    issue_triage: true
    duplicate_detection: true
    issue_resolution: true
    pr_review: true
    code_quality: true
    security: true
    ci_repair: true
    conflict_resolution: true

  automation:
    level: assist
    require_human_approval:
      - HIGH
      - MEDIUM
      - LOW
```

(Listing `LOW` under `require_human_approval` here is redundant with `level: assist` — SAFE is already the ceiling — but it's harmless and makes the intent explicit if you later bump `level` up.)

### `auto` mode (auto-apply up to MEDIUM)

For teams that trust RepoHeart to push code changes on its own, holding back only on the highest-risk actions.

```yaml
repoheart:
  provider:
    name: claude
    model: claude-sonnet-4-6

  agents:
    issue_triage: true
    duplicate_detection: true
    issue_resolution: true
    pr_review: true
    code_quality: true
    security: true
    ci_repair: true
    conflict_resolution: true

  automation:
    level: auto
    require_human_approval:
      - HIGH
```

### Per-agent provider overrides

Route cheap/high-volume agents to a fast model and reasoning-heavy agents to a stronger one.

```yaml
repoheart:
  provider:
    name: openai        # default for any agent not overridden below
    model: gpt-5-mini

  providers:
    agents:
      security: claude        # stronger reasoning for security review
      issue_resolution: claude
      conflict_resolution: claude

  agents:
    issue_triage: true
    duplicate_detection: true
    issue_resolution: true
    pr_review: true
    code_quality: true
    security: true
    ci_repair: true
    conflict_resolution: true

  automation:
    level: auto-safe
```

Remember: each provider named here (`openai`, `claude`, …) needs its matching secret set in the repo (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) — see the secrets table in `docs/quickstart.md`.

---

## Safety Gate & risk levels

Two `opencode.yml` fields feed the Safety Gate directly: **`automation.level`** and **`automation.require_human_approval`**. Every other field is orthogonal to safety (provider selection, scale limits, labels, CI watch list).

The Safety Gate itself is deterministic code, not an LLM call — per `CLAUDE.md`'s architecture invariants, agents only ever *propose* actions; the gate decides whether each proposed action is allowed, escalated, or denied.

### The four risk levels

Every action RepoHeart can take carries an intrinsic risk level, ordered from least to most dangerous:

| Risk     | What it covers | Example actions |
|----------|-----------------|------------------|
| `SAFE`   | Read-only or purely additive/social actions | reading the repo, adding/removing a label, posting a comment |
| `LOW`    | Creates new state but touches no existing code | creating a branch |
| `MEDIUM` | Modifies code | modifying files, committing, pushing a branch |
| `HIGH`   | Destructive or irreversible | deleting a branch, force-push — **mostly unreachable in the MVP** |

A risk level is intrinsic to the *action kind*, not something an agent can choose — `MODIFY_CODE` is always `MEDIUM`, for instance, regardless of which agent proposes it.

Two things are structurally impossible, not just denied by config: there is no `MERGE` action kind at all (it doesn't exist in the code, so no agent — and no cleverly-worded issue text — can cause a merge), and `DELETE_BRANCH` is hard-coded to always `DENY` in the current MVP, independent of any `opencode.yml` setting.

### How the gate evaluates each proposed action

For every action an agent proposes, the gate checks, in order:

1. **Hard invariants.** If the action is one of the small set that's always denied in the MVP (currently just branch deletion), it's `DENY` immediately — no config can change this.
2. **`require_human_approval`.** If the action's risk level is named in this list, it's `ESCALATE` — a human has to approve it, regardless of `automation.level`.
3. **`automation.level` ceiling.** If the action's risk exceeds the ceiling for the configured level (table above), it's `ESCALATE`.
4. **`HIGH` risk is always escalated**, even under `level: auto` and even if `HIGH` isn't explicitly listed in `require_human_approval` — there is no way to configure `opencode.yml` to auto-approve a `HIGH`-risk action.
5. Otherwise, it's `ALLOW`.

Every decision — `ALLOW`, `ESCALATE`, or `DENY` — is logged to the Actions run log with the acting agent, the action kind, its risk, and the reason, so the run log doubles as a full audit trail of what RepoHeart considered doing and why it did or didn't.

### Practical implications

- Setting `level: auto` does **not** mean RepoHeart can do anything — it only raises the ceiling to `MEDIUM`. There is no level that raises the ceiling to `HIGH`.
- `require_human_approval` is a way to carve out exceptions *below* your `level` ceiling — e.g. run `auto` generally but still gate `MEDIUM` specifically for a sensitive repo.
- Agents can never propose an action below their own risk floor, and per the architecture invariants, no agent can raise its own risk level to escape the gate.
- If you see `repoheart:needs-human` appear on an issue/PR, that's the `needs_human` label from the `labels` section being applied because the gate returned `ESCALATE` for a proposed action — check the Actions run log for the specific action and reason.
