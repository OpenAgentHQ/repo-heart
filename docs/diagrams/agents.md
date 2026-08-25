# Agents — Contract and Execution Flow

This document describes the `repoheart/agents/` package: the `Agent` base
class, the result types an agent returns, and how the three Phase 3 agents
flow from an `AgentContext` input to an `AgentResult` output. It is intended
to help contributors understand what they need to implement when adding a new
agent.

## Part 1 — Agent ABC and result types

```mermaid
classDiagram
    class Agent {
        <<abstract>>
        +str name
        +RiskLevel risk_level
        +list~str~ handles_events
        +run(context: AgentContext) AgentResult
        +validate_ceiling(result) void
    }

    class AgentResult {
        +list~Finding~ findings
        +list~ProposedAction~ proposed_actions
        +float confidence
        +bool needs_human_review
    }

    class Finding {
        +str summary
        +str detail
        +list~str~ references
    }

    class ProposedAction {
        +ActionKind kind
        +dict payload
        +str reason
        +RiskLevel risk
    }

    class IssueTriageAgent
    class DuplicateDetectionAgent
    class IssueResolutionAgent
    class NoOpAgent

    IssueTriageAgent --|> Agent
    DuplicateDetectionAgent --|> Agent
    IssueResolutionAgent --|> Agent
    NoOpAgent --|> Agent

    AgentResult "1" --> "*" Finding
    AgentResult "1" --> "*" ProposedAction
```

`Agent` is an abstract base class. Subclasses set `name`, `risk_level`, and
`handles_events`, and implement `run()`, which returns a declarative
`AgentResult`. An agent never executes writes — the orchestrator and Safety
Gate decide which `ProposedAction`s actually run.

## Part 2 — AgentContext fields

`AgentContext` is a frozen dataclass; it is the read-only view of the world
passed into every agent. The orchestrator pre-fetches data so agents never
hold live clients.

| Field | Type | Notes |
| --- | --- | --- |
| `event` | `InternalEvent` | Normalized GitHub event that triggered the agent |
| `config` | `RepoHeartConfig` | Validated configuration for the repository |
| `provider` | `Provider \| None` | AI provider for this run |
| `issue_data` | `dict \| None` | Pre-fetched issue payload for `issues.*` events |
| `pr_data` | `dict \| None` | Pre-fetched PR payload for `pull_request.*` events |
| `diff` | `str` | Unified diff for PR/push events |
| `changed_files` | `list[str]` | Relative paths of changed files |
| `fingerprint` | `str` | Unique per-run fingerprint (for logging) |
| `repo_labels` | `list[dict]` | Pre-fetched for `issue_triage` |
| `candidate_issues` | `list[dict]` | Pre-fetched for `duplicate_detection` |
| `linked_pull_requests` | `list[dict]` | Pre-fetched for `issue_resolution` |

The three Phase 3-specific fields are `repo_labels`, `candidate_issues`, and
`linked_pull_requests`.

## Part 3 — Per-agent execution flow

### IssueTriageAgent

```mermaid
flowchart TD
    A["AgentContext<br/>(issue_data + repo_labels)"] --> B["Build LLM prompt<br/>(title + body + available labels)"]
    B --> C["Provider.complete()"]
    C --> D["Parse JSON<br/>{type, priority, labels, summary}"]
    D --> E["Filter labels to repo label set"]
    E --> F{Labels match?}
    F -- yes --> G["Propose ADD_LABEL"]
    G --> H["Propose POST_COMMENT<br/>(triage summary)"]
    F -- no --> H
```

### DuplicateDetectionAgent

```mermaid
flowchart TD
    A["AgentContext<br/>(issue_data + candidate_issues)"] --> B{candidate_issues empty?}
    B -- yes --> C["return no-op"]
    B -- no --> D["Build LLM prompt<br/>(current issue + candidates)"]
    D --> E["Provider.complete()"]
    E --> F["Parse JSON<br/>{duplicates: [{number, confidence, reason}]}"]
    F --> G{Confidence?}
    G -- high --> H["ADD_LABEL duplicate<br/>+ POST_COMMENT"]
    G -- medium --> I["POST_COMMENT only"]
    G -- low / none --> J["no actions"]
```

### IssueResolutionAgent

```mermaid
flowchart TD
    A["AgentContext<br/>(issue_data + linked_pull_requests)"] --> B["Filter to merged PRs only"]
    B --> C{no merged PRs?}
    C -- yes --> D["return no-op"]
    C -- no --> E["Build LLM prompt<br/>(issue + merged PR)"]
    E --> F["Provider.complete()"]
    F --> G["Parse JSON<br/>{resolved, confidence, explanation}"]
    G --> H{resolved?}
    H -- "resolved + high" --> I["POST_COMMENT<br/>+ ADD_LABEL already-fixed"]
    H -- "resolved + medium" --> J["POST_COMMENT only"]
    H -- "low / not resolved" --> K["no actions"]
```

## Part 4 — AGENT_REGISTRY

The registry maps agent names to implementing classes. In Phase 1 every slot
pointed to `NoOpAgent`; real implementations replace individual entries as
each phase is completed.

| Agent slot | Implementation |
| --- | --- |
| `issue_triage` | `IssueTriageAgent` |
| `duplicate_detection` | `DuplicateDetectionAgent` |
| `issue_resolution` | `IssueResolutionAgent` |
| `pr_review` | `NoOpAgent` |
| `code_quality` | `NoOpAgent` |
| `security` | `NoOpAgent` |
| `ci_repair` | `NoOpAgent` |
| `conflict_resolution` | `NoOpAgent` |
| `test` | `NoOpAgent` |
| `documentation` | `NoOpAgent` |
