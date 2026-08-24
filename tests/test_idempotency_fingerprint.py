"""Tests for repoheart.idempotency.fingerprint."""

from __future__ import annotations

import json
from pathlib import Path

from repoheart.events.types import InternalEvent
from repoheart.idempotency.fingerprint import compute_fingerprint, fingerprint_for_event

_SAMPLE_PAYLOAD = json.loads(
    Path("examples/issues.opened.json").read_text(encoding="utf-8")
)

_SAMPLE_EVENT = InternalEvent(
    event_name="issues",
    action="opened",
    repo_full_name="example-org/example-repo",
    payload=_SAMPLE_PAYLOAD,
    sender_login="example-contributor",
)


def test_deterministic_same_inputs() -> None:
    fp1 = compute_fingerprint("issues", "opened", "org/repo", 42, "issue_triage")
    fp2 = compute_fingerprint("issues", "opened", "org/repo", 42, "issue_triage")
    assert fp1 == fp2


def test_different_agent_name_produces_different_hash() -> None:
    fp1 = compute_fingerprint("issues", "opened", "org/repo", 42, "issue_triage")
    fp2 = compute_fingerprint("issues", "opened", "org/repo", 42, "duplicate_detection")
    assert fp1 != fp2


def test_different_entity_id_produces_different_hash() -> None:
    fp1 = compute_fingerprint("issues", "opened", "org/repo", 1)
    fp2 = compute_fingerprint("issues", "opened", "org/repo", 2)
    assert fp1 != fp2


def test_output_is_64_lowercase_hex_chars() -> None:
    fp = compute_fingerprint("issues", "opened", "org/repo", 42)
    assert len(fp) == 64
    assert fp == fp.lower()
    assert all(c in "0123456789abcdef" for c in fp)


def test_empty_agent_name_is_event_level_fingerprint() -> None:
    fp_event = compute_fingerprint("issues", "opened", "org/repo", 42, "")
    fp_agent = compute_fingerprint("issues", "opened", "org/repo", 42, "issue_triage")
    assert fp_event != fp_agent


def test_fingerprint_for_event_extracts_issue_number() -> None:
    fp = fingerprint_for_event(_SAMPLE_EVENT, "issue_triage")
    # entity_id should be 42 (from the sample payload)
    expected = compute_fingerprint(
        "issues", "opened", "example-org/example-repo", 42, "issue_triage"
    )
    assert fp == expected


def test_fingerprint_for_event_pull_request() -> None:
    payload = {"pull_request": {"number": 7}, "repository": {"full_name": "org/repo"}}
    event = InternalEvent(
        event_name="pull_request",
        action="opened",
        repo_full_name="org/repo",
        payload=payload,
        sender_login="alice",
    )
    fp = fingerprint_for_event(event)
    expected = compute_fingerprint("pull_request", "opened", "org/repo", 7, "")
    assert fp == expected


def test_fingerprint_for_event_push_uses_after_sha() -> None:
    sha = "abc123def456"
    payload = {"after": sha, "repository": {"full_name": "org/repo"}}
    event = InternalEvent(
        event_name="push",
        action="",
        repo_full_name="org/repo",
        payload=payload,
        sender_login="",
    )
    fp = fingerprint_for_event(event)
    expected = compute_fingerprint("push", "", "org/repo", sha, "")
    assert fp == expected


def test_fingerprint_for_event_fallback_empty_entity() -> None:
    event = InternalEvent(
        event_name="push",
        action="",
        repo_full_name="org/repo",
        payload={"repository": {"full_name": "org/repo"}},
        sender_login="",
    )
    fp = fingerprint_for_event(event)
    expected = compute_fingerprint("push", "", "org/repo", "", "")
    assert fp == expected


def test_sample_event_fingerprint_is_stable() -> None:
    """Pin the fingerprint so canonical-form changes are caught immediately."""
    fp = fingerprint_for_event(_SAMPLE_EVENT, "")
    expected = compute_fingerprint("issues", "opened", "example-org/example-repo", 42, "")
    assert fp == expected
