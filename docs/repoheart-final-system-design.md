# RepoHeart — Final System Design

> **A 24/7, event-driven, multi-agent system that observes GitHub repositories and automatically activates specialized AI agents to understand, review, maintain, and safely improve them — from small projects to LangChain/opencode-scale monorepos.**

Version: **1.0 (Final MVP spec)**
Deployment model: **GitHub Actions–native, stateless per run, no mandatory external infrastructure.**

---

## Part I — Foundations

### 1. Product Decision (Locked)

RepoHeart runs **inside the user's GitHub Actions workflow**. The user provides only:

1. One workflow file (`.github/workflows/repoheart.yml`)
2. One config file (`repoheart.yml`)
3. Provider/model credentials (as Actions secrets)

No hosted RepoHeart server, no Redis, no PostgreSQL, no external infrastructure is required for the MVP. GitHub itself is the source of truth and the compute environment.

> **Developer experience: Add one workflow. Choose your AI provider. RepoHeart takes care of the repository.**

### 2. Deployment Model

```text
┌──────────────────────────────────────────────┐
│              User GitHub Repository          │
│                                              │
│  .github/workflows/repoheart.yml             │
│  repoheart.yml                               │
│                                              │
│       ┌──────────────────────────────┐       │
│       │       GitHub Actions         │       │
│       │        (execution env)       │       │
│       │             │                │       │
│       │       Event / Context        │       │
│       │             ▼                │       │
│       │       Orchestrator           │       │
│       │    ┌────────┼────────┐       │       │
│       │    ▼        ▼        ▼       │       │
│       │  Issue     PR       CI       │       │
│       │  Agent    Agent    Agent     │       │
│       │    └────────┼────────┘       │       │
│       │             ▼                │       │
│       │       Provider Layer         │       │
│       │    ┌────────┼────────┐       │       │
│       │    ▼        ▼        ▼       │       │
│       │ OpenCode  Claude    OpenAI   │       │
│       └──────────────────────────────┘       │
└──────────────────────────────────────────────┘
```

**GitHub Actions is the execution environment, not the business logic.** The same RepoHeart core can later run under Docker, a local CLI, or a self-hosted runner without a rewrite — the entrypoint is identical.

---

## Part II — Core Architecture

### 3. Architecture Boundary

```text
GitHub Actions  (scheduling, triggering, compute, secrets)
      │
      ▼
RepoHeart Runtime  (all business logic below this line)
      │
      ├── Event Context
      ├── Orchestrator
      ├── Agents
      ├── Retrieval Layer      ← scales to large repos
      ├── Git Operations
      ├── GitHub Operations
      ├── Safety / Policy
      └── Provider Abstraction
                 │
                 ├── OpenCode
                 ├── Claude
                 ├── OpenAI
                 ├── Gemini
                 └── Local
```

### 4. Component Map

| Component | Responsibility |
|---|---|
| Event Context Builder | Normalize raw GitHub payload → typed `InternalEvent` |
| Config Loader | Load + validate `repoheart.yml`, resolve providers/agents |
| Idempotency Markers | GitHub-native dedup (labels, comment markers, commit trailers) |
| Event Router | Deterministic event-type → candidate-agent lookup |
| Orchestrator | Sequence agents, enforce context budgets + per-run ceilings |
| Agents | Domain logic; return declarative results, never execute writes |
| **Retrieval Layer** | Fill each agent's bounded context from a large codebase |
| **Repo Access** | Sparse / shallow / partial checkout strategy per event |
| **Cache Backend** | *Optional*, correctness-neutral index/embedding cache |
| Provider Layer | Abstract the LLM backend behind one interface |
| Git Ops | All local git (branch, commit, diff, merge-base) |
| GitHub Ops | All GitHub API calls + rate-limit budgeter |
| Safety / Policy Engine | Authorize every write by risk level; the one mandatory checkpoint |
| Observability | Structured logs → Actions run log (the audit trail) |

### 5. Data Flow (End to End)

```text
1. GitHub fires event
2. Runner starts → EVENT-SCOPED checkout (sparse/shallow, not full clone)
3. Event Context Builder → InternalEvent
4. Config Loader → validate repoheart.yml, resolve provider + enabled agents
5. Idempotency check → fingerprint match? → exit fast if already processed
6. Event Router → candidate agents (pure lookup, no LLM)
7. Orchestrator, per eligible agent:
     a. Agent derives retrieval query from event
     b. Retrieval Layer fills bounded context:
          structural (tree-sitter) → lexical (ripgrep/GH search)
          → semantic (cached embeddings, optional)
          → dependency expansion → rank → dedup → truncate to budget
     c. Agent reasons over BOUNDED context (LLM sees tool output + top chunks)
     d. Agent returns AgentResult (review_comments | issue_comments | proposed_actions)
     e. Safety Gate authorizes each action → ALLOW | ESCALATE | DENY
     f. Execute allowed actions / escalate the rest to human review:
          - Issue agents: issue_flow.format_issue_comment() → POST_COMMENT (with marker)
          - PR agents: pr_flow.consolidate() → CREATE_PR_REVIEW (inline + body)
     g. Update cache with content-hashed results
8. Idempotency write (marker recorded as last step of successful run)
9. Exit — all state lives back in GitHub
```

---

## Part III — Interfaces

### 6. Agent Interface

Agents **never** call GitHub or git directly. They return declarative results; the Orchestrator + Safety Gate decide what executes. This boundary is what makes safety enforceable in code, not convention.

```python
class Agent(ABC):
    name: str
    risk_level: RiskLevel          # static ceiling this agent can never exceed
    handles_events: list[str]

    @abstractmethod
    def run(self, context: AgentContext) -> AgentResult: ...

@dataclass
class ReviewComment:
    """Structured code-level finding for PR agents (file/line/severity/suggestion).
    Agents produce these; the orchestrator delivers them via CREATE_PR_REVIEW."""
    title: str; body: str; severity: str
    file: str | None; line: int | None
    suggestion: str | None; category: str | None; source: str

@dataclass
class IssueComment:
    """Structured issue-level finding for issue agents.
    Agents produce these; the orchestrator formats and posts them with an idempotency marker."""
    title: str; body: str; severity: str
    references: list[str]; source: str

@dataclass
class AgentResult:
    findings: list[Finding]              # status/error messages only
    review_comments: list[ReviewComment] # PR agent output
    issue_comments: list[IssueComment]   # Issue agent output
    proposed_actions: list[ProposedAction]
    confidence: float
    needs_human_review: bool
    explanation: str
```

### 7. Provider Interface

Agents depend only on `Provider`. Selection happens once, from config.

```python
class Provider(ABC):
    @abstractmethod
    def complete(self, request: CompletionRequest) -> CompletionResponse: ...
    @abstractmethod
    def supports_tools(self) -> bool: ...
```

### 8. Safety Gate — the mandatory checkpoint

```python
@dataclass
class ProposedAction:
    kind: ActionKind        # ADD_LABEL, POST_COMMENT, CREATE_BRANCH, COMMIT, PUSH, ...
    risk: RiskLevel          # SAFE, LOW, MEDIUM, HIGH
    payload: dict
    reason: str

class SafetyGate:
    def authorize(self, action: ProposedAction, config) -> Decision:
        # 1. Action allowed for this agent? (permission table)
        # 2. Risk level requires human approval per config?
        # 3. Below retry/attempt ceiling for this event?
        # → ALLOW | ESCALATE | DENY
```

`github_ops` and `git_ops` write methods **require a `Decision.ALLOW` token** to execute — no path can skip the gate.

### 9. Retrieval Layer Interface (large-repo core)

```python
@dataclass
class ContextBudget:
    max_tokens: int
    max_files: int
    max_chunks_per_file: int
    priority: list[ContextKind]   # e.g. [DIFF, DIRECT_DEPS, TESTS, DOCS]

class RetrievalLayer:
    def retrieve(self, query: RetrievalQuery, budget: ContextBudget) -> BoundedContext:
        # structural → lexical → semantic → dependency expansion
        # → rank → dedup → truncate to budget
```

---

## Part IV — Behavior

### 10. Event Routing Table

| GitHub Event | Candidate Agents |
|---|---|
| `issues.opened` / `.edited` | Issue Triage → Duplicate Detection → Issue Resolution Check |
| `issue_comment.created` | Issue Triage (re-evaluate), Issue Resolution Check |
| `pull_request.opened` / `.synchronize` / `.reopened` | PR Review, Code Quality, Security, Test Agent |
| `pull_request_review.submitted` | PR Review (incorporate feedback) |
| `push` | Conflict Resolution (if diverged), Documentation |
| `workflow_run.completed` (failure) | CI Repair |
| `check_run.completed` (failure) | CI Repair |
| `release.published` | Documentation (changelog scope, opt-in) |

Routing is pure code — no LLM decides *which* agents run, only what each *does*.

### 11. Multi-Agent Roster

```text
Issue Triage · Duplicate Detection · Issue Resolution ·
PR Review · Code Quality · Security · CI Repair ·
Conflict Resolution · Test · Documentation
```

Each has a fixed responsibility, permission set, static risk ceiling, and config toggle.

### 12. Provider Switching

Users never touch agents. Only config changes:

```yaml
provider:
  name: opencode      # → claude | openai | gemini | local
  model: model-name
```

Per-agent overrides are allowed:

```yaml
providers:
  default: opencode
  agents:
    issue_triage: claude
    conflict_resolution: openai
```

---

## Part V — Scale (LangChain / opencode class)

### 13. The Core Shift: Retrieval, Not Ingestion

Small-repo RepoHeart *ingests* the repo. Large-repo RepoHeart *retrieves* only what's relevant to the event. **Deterministic tools (tree-sitter, ripgrep, linters, GitHub Search) do the O(repo) work; the LLM only ever sees O(budget) input.**

### 14. Event-Scoped Repo Access (no full clone)

| Event | Checkout strategy |
|---|---|
| `issues.*` | No code checkout; work on issue text + index. Sparse only if a file is needed. |
| `pull_request.*` | Shallow + sparse: PR commits, changed paths + direct dependents. |
| `push` / conflict | Shallow fetch of two branch tips + merge base (3 commits). |
| CI repair | Shallow at failing SHA + sparse-checkout of paths named in failure logs. |

Mechanisms: tuned `fetch-depth` (not `0`), `git sparse-checkout`, partial clone (`--filter=blob:none`), `git merge-base` on shallow refs.

### 15. Retrieval Modes (cheapest first)

1. **Structural** — tree-sitter symbol graph. No LLM, no embeddings, free. Default.
2. **Lexical** — ripgrep over sparse tree / GitHub code search API.
3. **Semantic** — embeddings, **opt-in**, cached externally by content hash.

Always ends: **rank → dedup → truncate to `ContextBudget`.**

### 16. History & Duplicate Search at Scale

- Duplicate issues: **GitHub Search API** candidate set → bounded embedding rerank (top ~50, never whole corpus).
- "Already fixed?": search for PRs/commits referencing the issue number + `git log -S` pickaxe on named files over a shallow window.
- Both capped by candidate limit; low confidence → **ESCALATE**, never auto-act.

### 17. Optional Cache Backend

The "no database" rule holds for **correctness**. The cache is purely cost/latency, **never required**, invalidated by **content hash**.

- **Default: `actions/cache`** — zero extra infra.
- Alternatives: orphan cache branch, or external vector store (opt-in only).
- Cold cache = slower, never wrong. No cache configured = structural retrieval still works, embeddings simply disabled.

### 18. Concurrency & Rate Limits

- Path-based `concurrency` groups: unrelated PRs parallel, same PR/issue serialized.
- `github_ops` **request budgeter**: token bucket respecting primary + secondary limits, `Retry-After` aware.
- Cheap-first gating + agent early-exit (hard duplicate found → skip expensive agents).
- Per-run ceilings in config: `max_llm_calls`, `max_files_read`, `max_runtime_seconds`.

---

## Part VI — Safety

### 19. Permission & Risk Model

```text
SAFE     → read repo, add label, post comment, create PR review
LOW      → create branch
MEDIUM   → modify code, push branch
HIGH     → merge PR, delete branch, force operations
```

**ActionKind table:**

| ActionKind | Risk | Notes |
|---|---|---|
| `READ_REPO` | SAFE | |
| `ADD_LABEL` | SAFE | |
| `REMOVE_LABEL` | SAFE | |
| `POST_COMMENT` | SAFE | Used by issue flow; not by agents directly |
| `CREATE_PR_REVIEW` | SAFE | Posts consolidated PR review with optional inline comments |
| `CREATE_BRANCH` | LOW | |
| `MODIFY_CODE` | MEDIUM | |
| `COMMIT` | MEDIUM | |
| `PUSH_BRANCH` | MEDIUM | |
| `DELETE_BRANCH` | HIGH | |
| *(no MERGE)* | — | Deliberately absent from MVP enum |

Enforced in four layers: static per-agent ceiling → config gating (can only restrict) → per-action runtime gate → escalation path.

### 20. Hard Invariants (code, not config)

- No agent can raise its own risk level.
- **No force-push, ever.**
- **No merge `ActionKind` exists in the MVP enum** — merge isn't "denied," it's unreachable, closing prompt-injection-via-issue-text.
- Never commit secrets, expose credentials, rewrite protected history, or bypass required checks.
- Conflict resolution never blindly picks `ours`/`theirs`; low-confidence → ESCALATE (static ceiling, not config).

> **Safety first, then correctness, then automation.**

### 21. Human-in-the-Loop

Stop and request review when: confidence is low · change is high-risk · security-sensitive code · DB migration · breaking API change · unsafe conflict · repeated fix failures.

```text
Low Confidence / High Risk → STOP → Explain → Request Human Review
```

Escalation posts a clearly-labeled comment (with the agent's own reasoning) and exits cleanly — it never fails the run or leaves broken state behind.

---

## Part VII — Reliability

### 22. Idempotency (no database)

```text
fingerprint = sha256(
    event_type + repo + subject_id + subject_updated_at + agent_name
)
```

Using GitHub's own `updated_at` means edits naturally produce new fingerprints. Stored three ways:

| Mechanism | Used for |
|---|---|
| Hidden comment marker `<!-- repoheart:fingerprint:<hash> -->` | Triage/review comments |
| Label (`repoheart:triaged`, `repoheart:reviewed`) | Coarse "already ran" checks |
| Commit trailer (`RepoHeart-Fingerprint: <hash>`) | RepoHeart-authored commits |

Marker written **last**, so a mid-run crash never falsely marks work done.

### 23. Failure Handling

| Failure | Behavior |
|---|---|
| Provider error/timeout | Backoff retry (bounded) → ESCALATE |
| Agent exception | Caught at orchestrator; discard that agent, continue others |
| GitHub rate limit | `Retry-After` backoff → fail run cleanly (visible signal) |
| CI fix fails after retries | ESCALATE, revert speculative branch, never leave broken branch |
| Config invalid | Fail fast before any agent runs, point at offending key |
| Retrieval can't fit budget | Drop lowest-priority context, log what was cut, run or escalate |

### 24. Observability

The **Actions run log is the observability system** (MVP). Structured single-line records:

```text
[repoheart] event=issues.opened fingerprint=a1b2c3 agents=[issue_triage,duplicate_detection]
[repoheart] issue_triage: type=bug confidence=0.91 action=ADD_LABEL(bug) risk=SAFE decision=ALLOW
[repoheart] duplicate_detection: candidate=#142 similarity=0.87 needs_review=true decision=ESCALATE
[repoheart] run complete: 2 actions taken, 1 escalated, 0 denied
```

---

## Part VIII — Project Layout

```text
repoheart/
├── action.yml
├── Dockerfile
├── repoheart.schema.json
│
├── repoheart/
│   ├── main.py                      # entrypoint: wires everything
│   ├── config/        schema.py loader.py
│   ├── events/        context.py types.py router.py
│   ├── orchestrator/  orchestrator.py agent_context.py
│   ├── agents/        base.py issue_triage.py duplicate_detection.py
│   │                  issue_resolution.py pr_review.py code_quality.py
│   │                  security.py ci_repair.py conflict_resolution.py
│   │                  test_agent.py documentation.py
│   ├── retrieval/     layer.py structural.py lexical.py semantic.py
│   │                  chunking.py budget.py
│   ├── repo_access/   checkout.py sparse.py merge_base.py
│   ├── cache/         base.py actions_cache.py vector_store.py
│   ├── providers/     base.py opencode.py claude.py openai.py gemini.py local.py
│   ├── git_ops/       repo.py conflicts.py
│   ├── github_ops/    client.py issues.py pulls.py checks.py comments.py budgeter.py
│   ├── safety/        policy.py gate.py
│   ├── idempotency/   markers.py fingerprint.py
│   └── observability/ logger.py
│
└── tests/
```

---

## Part IX — Config Surface (`repoheart.yml`)

```yaml
repoheart:
  provider:
    name: opencode          # opencode | claude | openai | gemini | local
    model: your-model

  # optional per-agent provider overrides
  providers:
    agents:
      issue_triage: claude
      conflict_resolution: openai

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
    level: assist           # assist | auto-safe | auto
    require_human_approval:
      - HIGH
      - MEDIUM

  scale:
    checkout: event-scoped  # event-scoped | full
    retrieval:
      semantic: false       # opt-in embeddings
    cache:
      backend: actions      # none | actions | branch | vector-store
    limits:
      max_llm_calls: 30
      max_files_read: 200
      max_runtime_seconds: 600
```

---

## Part X — Scope

### 25. MVP (this spec)

GitHub event handling · routing · issue triage · duplicate detection · resolution detection · labeling · PR review · code-quality · CI failure analysis · safe conflict resolution · Git safety · provider abstraction · idempotency · `repoheart.yml` · human escalation · **large-repo retrieval + event-scoped checkout**.

### 26. Future Scope

More providers · local models · analytics · dependency maintenance · release automation · changelog generation · cross-repo & org-level agents · web dashboard · agent marketplace · hosted service · DB-backed state (only if GitHub-native markers prove insufficient at scale).

---

## Design Guarantees (Final)

- **Stateless between runs** — every run reconstructs context from GitHub.
- **Deterministic core** — routing, permissions, idempotency, and retrieval orchestration are plain code; only agent reasoning is LLM-driven.
- **No write bypasses the Safety Gate** — enforced structurally via `Decision` tokens.
- **Provider-swappable without touching agents.**
- **Bounded work per event** — cost scales with the event's blast radius, not repo size.
- **Optional cache is correctness-neutral** — cold cache is slower, never wrong.
- **Same interfaces from small repo to monorepo** — scaling is additive, no fork.
- **Safe by default** — dangerous actions are unreachable, not merely disabled.

> **RepoHeart is not simply a code reviewer or GitHub bot. It is an autonomous, event-driven repository engineering system that scales from a weekend project to a monorepo — safely, statelessly, and provider-agnostically.**
