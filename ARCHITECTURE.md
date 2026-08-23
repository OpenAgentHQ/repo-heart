# ARCHITECTURE.md — RepoHeart

Condensed architecture reference. The authoritative, complete version is `docs/repoheart-final-system-design.md` — this is the fast orientation.

---

## One-Sentence Architecture

A GitHub event triggers an ephemeral Actions run in which a deterministic core routes the event to specialized AI agents that retrieve bounded context, propose actions, and pass every write through a mandatory Safety Gate before results are written back to GitHub — then the run exits, holding no state.

---

## The Nine Components

```text
Event Context Builder  → normalize raw payload to InternalEvent
Config Loader          → load + validate opencode.yml
Idempotency Markers    → GitHub-native dedup (labels/comments/trailers)
Event Router           → deterministic event → agent lookup
Orchestrator           → sequence agents, enforce budgets + ceilings
Agents                 → domain logic; declare actions, never execute
Retrieval Layer        → fill bounded context from (possibly huge) codebase
Provider Layer         → abstract the LLM backend
Safety / Policy Engine → authorize every write by risk level
```

Plus supporting layers: Repo Access (checkout strategy), Cache (optional), Git Ops, GitHub Ops (+ rate budgeter), Observability.

---

## Request Lifecycle

```text
event → checkout(event-scoped) → context → config → idempotency-check
      → route → [per agent: retrieve → reason → propose → gate → execute/escalate]
      → idempotency-write → exit
```

---

## The Three Load-Bearing Guarantees

1. **Stateless between runs** — state lives in GitHub, not in RepoHeart.
2. **Deterministic core** — only agent *reasoning* is LLM-driven; routing, safety, idempotency, retrieval orchestration are plain code.
3. **No write bypasses the Safety Gate** — enforced structurally: write methods require a `Decision.ALLOW` token.

---

## Key Interfaces

```python
class Agent(ABC):
    name: str
    risk_level: RiskLevel          # static ceiling
    handles_events: list[str]
    def run(self, ctx: AgentContext) -> AgentResult: ...

class Provider(ABC):
    def complete(self, req: CompletionRequest) -> CompletionResponse: ...
    def supports_tools(self) -> bool: ...

class SafetyGate:
    def authorize(self, action: ProposedAction, config) -> Decision: ...

class RetrievalLayer:
    def retrieve(self, query: RetrievalQuery, budget: ContextBudget) -> BoundedContext: ...
```

---

## Data Objects

```python
AgentResult   = findings + proposed_actions + confidence + needs_human_review + explanation
ProposedAction = kind(ActionKind) + risk(RiskLevel) + payload + reason
ContextBudget  = max_tokens + max_files + max_chunks_per_file + priority[]
Decision       = ALLOW | ESCALATE | DENY
```

---

## Risk Model

```text
SAFE   read, label, comment
LOW    create branch
MEDIUM modify code, push branch
HIGH   merge, delete branch, force ops   (mostly unreachable in MVP)
```

Enforced in four layers: static per-agent ceiling → config gating (restrict only) → per-action runtime gate → escalation path.

---

## Idempotency Without a Database

```text
fingerprint = sha256(event_type + repo + subject_id + subject_updated_at + agent_name)
```

Stored as: hidden comment markers, labels, and commit trailers. GitHub's own `updated_at` means edits re-trigger naturally. Marker written last, so a crash never falsely marks work done.

---

## Scaling Model (large repos)

- **Retrieve, don't ingest.** Deterministic tools do O(repo) work; the LLM sees O(budget) input.
- **Event-scoped checkout** — sparse/shallow/partial, never full clone by default.
- **Cheapest-first retrieval** — structural (tree-sitter) → lexical (ripgrep/GH search) → semantic (opt-in, cached).
- **Optional cache** — content-hash keyed; correctness-neutral (cold = slower, never wrong).

---

## Provider-Agnostic Boundary

Agents import only `Provider`. Selection happens once in `main.py` from config. Switching providers is a one-line config change; agents are untouched.

```yaml
provider:
  name: opencode   # → claude | openai | gemini | local
  model: model-name
```

---

## Extension Points

| Extend | How |
|---|---|
| New agent | Subclass `Agent`, register in router, add config toggle + test |
| New provider | Subclass `Provider`, register, add to config enum + credentials |
| New cache | Subclass `CacheBackend` |
| New execution env | Reuse the same entrypoint (Docker / CLI / self-hosted runner) |

All extension points preserve the three load-bearing guarantees. Scaling and new capabilities are **additive** — no fork from small repo to monorepo.
