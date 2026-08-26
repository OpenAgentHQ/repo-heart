"""DocumentationAgent — diff-scoped doc updates and release changelog generation.

Two modes selected by event type:

* PR / push events  — scan changed Python symbols for missing or stale
  docstrings and return ``ReviewComment`` (PR) or ``IssueComment`` (push)
  suggestions scoped only to what changed.

* ``release.published`` — summarise commits since the previous tag and return
  a single ``IssueComment`` containing a Keep-a-Changelog draft. Opt-out via
  ``documentation.changelog_on_release: false`` in config.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict

from repoheart.agents.base import Agent, AgentResult, Finding, IssueComment, ReviewComment
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.base import CompletionRequest, Message
from repoheart.safety.policy import RiskLevel

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_DOC_REVIEW_SYSTEM = """\
You are a documentation reviewer for a Python project. Given a set of changed
Python symbols (functions, classes, methods) and their current source, identify
which ones are missing docstrings, have stale docstrings that no longer match
the signature, or lack Args/Returns sections for non-trivial callables.

Return ONLY valid JSON in this exact format:
{
  "comments": [
    {
      "file": "<relative file path>",
      "line": <line number of the def/class statement or null>,
      "title": "<short title, one phrase>",
      "body": "<explanation of the documentation gap>",
      "suggestion": "<complete suggested docstring, ready to paste in>"
    }
  ]
}

Rules:
- Only flag symbols that genuinely need documentation improvement.
- Do NOT suggest changes for trivial one-liners, private helpers (_name), or
  symbols whose docstring is already adequate.
- Keep suggestions concise and factual — no marketing language.
- If no gaps are found, return an empty comments array.\
"""

_CHANGELOG_SYSTEM = """\
You are a technical writer producing a changelog for a software release.
Given a list of git commit messages in --oneline format, produce a concise
Keep-a-Changelog section for this release.

Group changes under these headings (omit empty groups):
### Added
### Changed
### Fixed
### Removed
### Security

Return ONLY valid JSON in this exact format:
{
  "version": "<version string provided>",
  "date": "<ISO date provided>",
  "changelog": "<full markdown changelog section as a single string>"
}

Rules:
- Merge related commits into one bullet point where sensible.
- Use present tense imperative ("Add X", "Fix Y").
- Omit purely internal or chore commits unless they matter to users.
- If commits follow Conventional Commits, use the type prefix to guide grouping.\
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SYMBOL_RE = re.compile(
    r"^\+(?P<indent>\s*)(?:async\s+)?(?:def|class)\s+(?P<name>\w+)",
    re.MULTILINE,
)

_CONVENTIONAL_PREFIXES = ("feat", "fix", "docs", "refactor", "perf", "chore", "test", "build")


def _extract_changed_symbols(diff: str) -> dict[str, list[tuple[str, int | None]]]:
    """Return {file_path: [(symbol_name, approx_line), ...]} from a unified diff.

    Only considers added (+) lines that define a top-level or method symbol.
    Private symbols (leading underscore) are skipped.
    """
    result: dict[str, list[tuple[str, int | None]]] = defaultdict(list)
    current_file: str | None = None
    current_line: int | None = None

    for raw_line in diff.splitlines():
        # Track current file
        if raw_line.startswith("+++ b/"):
            path = raw_line[6:].strip()
            current_file = path if path.endswith(".py") else None
            continue

        if raw_line.startswith("@@ "):
            # Parse hunk header to get starting line in new file: @@ -a,b +c,d @@
            m = re.search(r"\+(\d+)", raw_line)
            current_line = int(m.group(1)) if m else None
            continue

        if current_file is None:
            continue

        # Track line number in new file
        if not raw_line.startswith("-") and current_line is not None:
            current_line += 1

        if raw_line.startswith("+"):
            m = _SYMBOL_RE.match(raw_line)
            if m:
                name = m.group("name")
                if not name.startswith("_"):
                    result[current_file].append((name, current_line))

    return dict(result)


def _group_commits(commits: list[str]) -> str:
    """Format commit list for the LLM prompt."""
    return "\n".join(f"- {c}" for c in commits) if commits else "(no commits found)"


def _parse_json_response(content: str) -> dict[str, object]:
    """Strip markdown fences and parse JSON."""
    raw = re.sub(r"^```(?:json)?\s*", "", content.strip())
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class DocumentationAgent(Agent):
    """Suggests docstring improvements on changed symbols; drafts release changelogs."""

    name = "documentation"
    risk_level = RiskLevel.SAFE
    handles_events = [
        "pull_request.opened",
        "pull_request.synchronize",
        "push",
        "release.published",
    ]

    def run(self, context: AgentContext) -> AgentResult:
        if context.provider is None:
            return AgentResult(
                findings=[Finding(summary="No provider configured; skipping documentation agent")]
            )

        if context.event.routing_key == "release.published":
            return self._changelog_mode(context)

        return self._doc_review_mode(context)

    # ------------------------------------------------------------------
    # Mode: diff-scoped docstring review (PR + push)
    # ------------------------------------------------------------------

    def _doc_review_mode(self, context: AgentContext) -> AgentResult:
        assert context.provider is not None  # caller checked

        if not context.diff:
            return AgentResult(
                findings=[Finding(summary="Empty diff; nothing to document")]
            )

        symbols_by_file = _extract_changed_symbols(context.diff)
        if not symbols_by_file:
            return AgentResult(
                findings=[Finding(summary="No new public symbols in diff; skipping doc review")]
            )

        # Build a concise summary for the LLM — no need to send full file contents
        symbol_lines: list[str] = []
        for path, symbols in symbols_by_file.items():
            for name, line in symbols:
                loc = f"line {line}" if line else "unknown line"
                symbol_lines.append(f"  {path}:{loc}  →  `{name}`")

        # Also include the diff excerpt so the LLM can read signatures
        diff_excerpt = context.diff[:20_000]

        user_content = (
            "Changed public symbols:\n"
            + "\n".join(symbol_lines)
            + "\n\nUnified diff (for signature context):\n```diff\n"
            + diff_excerpt
            + "\n```"
        )

        request = CompletionRequest(
            system=_DOC_REVIEW_SYSTEM,
            messages=[Message(role="user", content=user_content)],
            model=context.config.provider.model,
            temperature=0.0,
        )

        try:
            response = context.provider.complete(request)
        except Exception as exc:
            return AgentResult(
                findings=[Finding(summary="Provider error during doc review", detail=str(exc))]
            )

        try:
            parsed = _parse_json_response(response.content)
        except (json.JSONDecodeError, ValueError) as exc:
            return AgentResult(
                findings=[
                    Finding(
                        summary="Doc review JSON parsing failed",
                        detail=f"{exc} — raw: {response.content[:300]}",
                    )
                ]
            )

        raw_comments = parsed.get("comments") or []
        if not isinstance(raw_comments, list):
            raw_comments = []
        is_pr = "pull_request" in context.event.event_name

        review_comments: list[ReviewComment] = []
        issue_comments: list[IssueComment] = []

        for item in raw_comments:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "Missing or stale docstring"))
            body = str(item.get("body", ""))
            suggestion = item.get("suggestion") or None
            file_path = item.get("file") or None
            line = item.get("line") or None

            if is_pr:
                review_comments.append(
                    ReviewComment(
                        title=title,
                        body=body,
                        severity="info",
                        file=file_path,
                        line=line,
                        suggestion=suggestion,
                        category="docs",
                    )
                )
            else:
                ref = f"`{file_path}`" if file_path else ""
                full_body = body
                if suggestion:
                    full_body += f"\n\n**Suggested docstring:**\n```python\n{suggestion}\n```"
                issue_comments.append(
                    IssueComment(
                        title=title,
                        body=full_body,
                        severity="info",
                        references=[ref] if ref else [],
                    )
                )

        return AgentResult(
            review_comments=review_comments,
            issue_comments=issue_comments,
        )

    # ------------------------------------------------------------------
    # Mode: release changelog
    # ------------------------------------------------------------------

    def _changelog_mode(self, context: AgentContext) -> AgentResult:
        assert context.provider is not None  # caller checked

        # Honour opt-out flag
        doc_cfg = getattr(context.config.agents, "documentation_config", None)
        if doc_cfg is not None and not getattr(doc_cfg, "changelog_on_release", True):
            return AgentResult(
                findings=[Finding(summary="changelog_on_release disabled; skipping")]
            )

        release = context.event.payload.get("release", {})
        tag_name: str = release.get("tag_name", "")
        release_name: str = release.get("name", "") or tag_name
        release_body: str = (release.get("body") or "")[:500]
        published_at: str = (release.get("published_at") or "")[:10]  # ISO date

        if not tag_name:
            return AgentResult(
                findings=[Finding(summary="No tag_name in release payload; skipping changelog")]
            )

        # Get commits since previous tag; fall back gracefully if git unavailable
        commits: list[str] = []
        try:
            from repoheart.git_ops.repo import GitRepo

            repo = GitRepo()
            # Find the previous tag to bound the range
            prev_result = repo._run(
                "describe", "--tags", "--abbrev=0", f"{tag_name}^", check=False
            )
            if prev_result.returncode == 0:
                prev_tag = prev_result.stdout.strip()
                commits = repo.commits_between(prev_tag, tag_name)
            else:
                # No previous tag — take last 50 commits
                raw = repo._run("log", "--oneline", "-50", tag_name, check=False)
                commits = [ln for ln in raw.stdout.strip().splitlines() if ln]
        except Exception:
            commits = []

        user_content = (
            f"Release version: {tag_name}\n"
            f"Release name: {release_name}\n"
            f"Date: {published_at}\n"
            f"Existing release notes (if any):\n{release_body}\n\n"
            f"Commits:\n{_group_commits(commits)}"
        )

        request = CompletionRequest(
            system=_CHANGELOG_SYSTEM,
            messages=[Message(role="user", content=user_content)],
            model=context.config.provider.model,
            temperature=0.2,
        )

        try:
            response = context.provider.complete(request)
        except Exception as exc:
            return AgentResult(
                findings=[
                    Finding(summary="Provider error during changelog generation", detail=str(exc))
                ]
            )

        try:
            parsed = _parse_json_response(response.content)
        except (json.JSONDecodeError, ValueError) as exc:
            return AgentResult(
                findings=[
                    Finding(
                        summary="Changelog JSON parsing failed",
                        detail=f"{exc} — raw: {response.content[:300]}",
                    )
                ]
            )

        changelog_md = str(parsed.get("changelog", ""))
        version = str(parsed.get("version", tag_name))
        date = str(parsed.get("date", published_at))

        if not changelog_md:
            return AgentResult(
                findings=[Finding(summary="LLM returned empty changelog; nothing to post")]
            )

        body = (
            f"## Release Notes Draft — {version} ({date})\n\n"
            + changelog_md
            + "\n\n---\n*Generated by RepoHeart DocumentationAgent. "
            "Edit before publishing.*"
        )

        return AgentResult(
            issue_comments=[
                IssueComment(
                    title=f"Release Notes Draft: {version}",
                    body=body,
                    severity="info",
                )
            ]
        )
