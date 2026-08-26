"""LexicalRetriever — find files containing query terms.

Strategy (cheapest-first):
  1. ripgrep subprocess (fast, requires rg on PATH)
  2. Python re.search over in-memory file contents (fallback)
  3. GitHub code search API (last resort, rate-limited)

Never does a full repo walk unless rg is available.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from repoheart.retrieval.budget import ContextBudget

if TYPE_CHECKING:
    from repoheart.github_ops.client import GitHubClient
    from repoheart.repo_access.reader import FileContent


@dataclass(frozen=True)
class LexicalMatch:
    file: str
    line: int
    snippet: str
    score: float


class LexicalRetriever:
    """Find files containing query terms using ripgrep or fallbacks."""

    def __init__(
        self,
        repo_root: str | Path = ".",
        github_client: GitHubClient | None = None,
    ) -> None:
        self._root = Path(repo_root)
        self._github = github_client

    def search(
        self,
        terms: list[str],
        budget: ContextBudget,
        *,
        file_extensions: list[str] | None = None,
        in_memory_files: list[FileContent] | None = None,
    ) -> list[LexicalMatch]:
        """Search for terms; return deduplicated matches capped at budget.max_files."""
        if not terms:
            return []

        all_matches: list[LexicalMatch] = []
        for term in terms:
            matches = self._search_term(term, budget, file_extensions, in_memory_files)
            all_matches.extend(matches)

        return _dedup_by_file(all_matches)[: budget.max_files]

    def _search_term(
        self,
        term: str,
        budget: ContextBudget,
        extensions: list[str] | None,
        in_memory: list[FileContent] | None,
    ) -> list[LexicalMatch]:
        try:
            return self._ripgrep(term, budget, extensions)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        if in_memory:
            return self._search_in_memory(term, in_memory, budget)

        return self._github_code_search(term, budget)

    def _ripgrep(
        self,
        term: str,
        budget: ContextBudget,
        extensions: list[str] | None,
    ) -> list[LexicalMatch]:
        cmd = ["rg", "--json", "-m", "3", "--", term, str(self._root)]
        if extensions:
            for ext in extensions:
                cmd += ["-g", f"*{ext}"]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20, check=False
        )
        matches = _parse_rg_json(result.stdout, self._root)
        return matches[: budget.max_files]

    def _search_in_memory(
        self,
        term: str,
        files: list[FileContent],
        budget: ContextBudget,
    ) -> list[LexicalMatch]:
        matches: list[LexicalMatch] = []
        pattern = re.compile(re.escape(term))
        for fc in files:
            for i, line in enumerate(fc.content.splitlines(), 1):
                if pattern.search(line):
                    matches.append(
                        LexicalMatch(
                            file=fc.path,
                            line=i,
                            snippet=line.strip()[:120],
                            score=1.0,
                        )
                    )
                    break  # one match per file
            if len(matches) >= budget.max_files:
                break
        return matches

    def _github_code_search(self, term: str, budget: ContextBudget) -> list[LexicalMatch]:
        if self._github is None:
            return []
        # Placeholder — wired through GitHubClient when needed
        return []


# ── ripgrep JSON output parser ─────────────────────────────────────────────────

def _parse_rg_json(output: str, repo_root: Path) -> list[LexicalMatch]:
    matches: list[LexicalMatch] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "match":
            continue
        data = obj.get("data", {})
        abs_path = data.get("path", {}).get("text", "")
        line_number = data.get("line_number", 0)
        lines_obj = data.get("lines", {})
        snippet = lines_obj.get("text", "").strip()[:120]
        try:
            rel = str(Path(abs_path).relative_to(repo_root))
        except ValueError:
            rel = abs_path
        matches.append(LexicalMatch(file=rel, line=line_number, snippet=snippet, score=1.0))
    return matches


def _dedup_by_file(matches: list[LexicalMatch]) -> list[LexicalMatch]:
    seen: set[str] = set()
    result: list[LexicalMatch] = []
    for m in matches:
        if m.file not in seen:
            seen.add(m.file)
            result.append(m)
    return result
