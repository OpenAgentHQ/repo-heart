# Idempotency -- Fingerprint and Marker Flow

This document describes `repoheart/idempotency/`: how RepoHeart derives a deterministic fingerprint for an event+agent pair, how it looks for that fingerprint in issue/PR comments, and how a marker is written after a successful run.

Idempotency is a core correctness guarantee. Re-running the workflow on the same GitHub event must always be a no-op for an agent that has already recorded a marker. A different event name, action, repository, entity, or agent name produces a different fingerprint, so skipping is never incorrect for a first-time combination.

## Part 1 -- Fingerprint generation

`fingerprint_for_event()` in `repoheart/idempotency/fingerprint.py` extracts an entity id from the payload, then `compute_fingerprint()` hashes a canonical string with SHA-256. The result is a 64-character lowercase hex digest.

Entity id resolution order: issue number, pull request number, workflow_run id, release id, payload after (push head SHA), then empty string.

When `agent_name` is empty the fingerprint is event-level (pre-routing). When it is set (as the Orchestrator does per agent), the fingerprint is per-agent, so two agents can independently process the same issue event.

```mermaid
flowchart TD
    A[InternalEvent + agent_name] --> B{Extract entity_id}
    B --> C1[issue.number]
    B --> C2[pull_request.number]
    B --> C3[workflow_run.id]
    B --> C4[release.id]
    B --> C5[payload.after or empty]
    C1 --> D[canonical string]
    C2 --> D
    C3 --> D
    C4 --> D
    C5 --> D
    D --> E[SHA-256 UTF-8 digest]
    E --> F[64-char hex fingerprint]
```

The canonical form is `{event_name}.{action}:{repo_full_name}:{entity_id}:{agent_name}`.

## Part 2 -- Marker read (`has_been_processed`)

`IdempotencyMarkers.has_been_processed(repo, issue_or_pr_number, fingerprint)` lists comments on the issue or PR and looks for a hidden HTML comment of the form `<!-- repoheart:fingerprint:{64-hex} -->`.

If the GitHub token is missing, or the comments request fails, the method returns False (conservative: treat as not yet processed so work is not silently dropped).

```mermaid
flowchart TD
    S[has_been_processed] --> T{GitHub token present?}
    T -->|No| F1[return False]
    T -->|Yes| G[GET issue comments]
    G -->|error| F1
    G -->|ok| L[For each comment body]
    L --> M{contains fingerprint marker?}
    M -->|Yes| Y[return True -- skip agent]
    M -->|No| L
    L -->|no match| N[return False -- proceed]
```

## Part 3 -- Marker write (`record_processed`)

`IdempotencyMarkers.record_processed(...)` posts the hidden comment. The write goes through `GitHubClient.post_comment(..., decision)` and therefore requires `Decision.ALLOW`. Any other decision raises `PermissionDenied` -- the same Safety Gate rule as other writes.

```mermaid
flowchart TD
    W[record_processed] --> D{decision == ALLOW?}
    D -->|No| X[raise PermissionDenied]
    D -->|Yes| P[POST issue comment]
    P --> B[hidden fingerprint marker]
    B --> L[log idempotency_recorded]
```

## Part 4 -- Orchestrator loop

Inside the per-agent loop the Orchestrator fingerprints the current event for that agent, checks markers when an entity number and token are available, and skips the agent when a marker is already present.

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant F as fingerprint_for_event
    participant M as IdempotencyMarkers
    participant A as Agent
    loop each agent_name
        O->>F: fingerprint_for_event(event, agent_name)
        F-->>O: fingerprint
        alt entity number and token available
            O->>M: has_been_processed(repo, number, fingerprint)
            M-->>O: already_done
        else
            O-->>O: already_done = False
        end
        alt already_done is True
            O-->>O: log already seen, skip agent
        else
            O->>O: _build_context()
            O->>A: run agent
            Note over O,M: record_processed requires Decision.ALLOW
            O->>M: record_processed(...)
        end
    end
```

## Why re-running is always safe

The fingerprint includes event name, action, repository, entity, and agent. A replay of the same webhook therefore hashes to the same digest. Once that digest is stored as a comment marker, `has_been_processed` returns true and the Orchestrator does not run the agent again. A different issue, action, or agent cannot collide with that marker because the canonical string -- and therefore the SHA-256 digest -- would differ.
