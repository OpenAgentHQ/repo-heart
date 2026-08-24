"""Read and write idempotency markers to/from GitHub.

Fingerprints are stored as hidden HTML comments in issue/PR comments so that
re-running an event is a no-op. All writes require ``Decision.ALLOW`` and
delegate the permission check to ``GitHubClient``.
"""

from __future__ import annotations

import re

from repoheart.github_ops.client import GitHubClient
from repoheart.observability.logger import StructuredLogger
from repoheart.safety.policy import Decision

_MARKER_RE = re.compile(r"<!--\s*repoheart:fingerprint:([a-f0-9]{64})\s*-->")
_COMMENT_MARKER_TEMPLATE = "<!-- repoheart:fingerprint:{fingerprint} -->"


class IdempotencyMarkers:
    """Read and write per-agent idempotency markers via ``GitHubClient``."""

    def __init__(self, client: GitHubClient, logger: StructuredLogger) -> None:
        self._client = client
        self._logger = logger

    def has_been_processed(
        self,
        repo: str,
        issue_or_pr_number: int,
        fingerprint: str,
    ) -> bool:
        """Return True if this fingerprint has already been recorded.

        Checks issue/PR comments for a hidden marker. Returns False if the
        GitHub token is absent (conservative: treat as not yet processed).
        """
        if not self._client._token:
            return False

        try:
            comments = self._client.get_issue_comments(repo, issue_or_pr_number)
        except Exception as exc:
            self._logger.log(
                event_msg="idempotency_check_error",
                repo=repo,
                number=issue_or_pr_number,
                error=str(exc),
            )
            return False

        for comment in comments:
            body = comment.get("body", "") if isinstance(comment, dict) else ""
            if self.extract_fingerprint_from_comment(str(body)) == fingerprint:
                return True

        return False

    def record_processed(
        self,
        repo: str,
        issue_or_pr_number: int,
        fingerprint: str,
        label: str,
        decision: Decision,
    ) -> None:
        """Write an idempotency marker as a hidden comment.

        Args:
            decision: Must be ``Decision.ALLOW``; otherwise ``PermissionDenied``
                is raised (delegated to ``GitHubClient``).
        """
        marker = _COMMENT_MARKER_TEMPLATE.format(fingerprint=fingerprint)
        self._client.post_comment(repo, issue_or_pr_number, marker, decision)
        self._logger.log(
            event_msg="idempotency_recorded",
            repo=repo,
            number=issue_or_pr_number,
            fingerprint=fingerprint[:12] + "...",
        )

    def extract_fingerprint_from_comment(self, comment_body: str) -> str | None:
        """Parse a fingerprint from a comment body.

        Returns:
            The 64-char hex fingerprint, or ``None`` if not found.
        """
        match = _MARKER_RE.search(comment_body)
        return match.group(1) if match else None
