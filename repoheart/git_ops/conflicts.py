"""3-way merge inspection helpers.

Parse git conflict markers from file content, estimate resolution difficulty,
and attempt a non-destructive conflict simulation via ``git merge-tree``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from repoheart.git_ops.repo import GitRepo

_OURS_MARKER = "<<<<<<<"
_SEP_MARKER = "======="
_THEIRS_MARKER = ">>>>>>>"

_LOG_CONFIDENCE_THRESHOLD = 0.7


@dataclass(frozen=True)
class ConflictBlock:
    """A single conflict section from a file."""

    ours: str
    theirs: str
    context_before: str = ""


@dataclass(frozen=True)
class ConflictFile:
    """A file with one or more conflict blocks."""

    path: str
    blocks: list[ConflictBlock] = field(default_factory=list)
    resolution_confidence: float = 1.0


def extract_conflict_blocks(content: str) -> list[ConflictBlock]:
    """Parse git conflict markers and return one block per conflict section.

    Handles the standard three-marker format::

        <<<<<<< HEAD
        our content
        =======
        their content
        >>>>>>> branch-name

    Args:
        content: File text that may contain conflict markers.

    Returns:
        One ``ConflictBlock`` per conflict section found. Empty list if none.
    """
    blocks: list[ConflictBlock] = []
    lines = content.splitlines(keepends=True)
    i = 0
    context_window: list[str] = []

    while i < len(lines):
        line = lines[i]
        if line.startswith(_OURS_MARKER):
            ours_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith(_SEP_MARKER):
                ours_lines.append(lines[i])
                i += 1
            i += 1  # skip =======
            theirs_lines: list[str] = []
            while i < len(lines) and not lines[i].startswith(_THEIRS_MARKER):
                theirs_lines.append(lines[i])
                i += 1
            i += 1  # skip >>>>>>>
            context = "".join(context_window[-5:])
            blocks.append(
                ConflictBlock(
                    ours="".join(ours_lines),
                    theirs="".join(theirs_lines),
                    context_before=context,
                )
            )
            context_window = []
        else:
            context_window.append(line)
            i += 1

    return blocks


def estimate_confidence(blocks: list[ConflictBlock]) -> float:
    """Estimate resolution confidence (0.0–1.0) based on conflict complexity.

    Heuristics:
    - No blocks → 1.0 (no conflicts)
    - Whitespace-only difference → 0.95 (trivially resolvable)
    - Small block (≤ 4 total lines) → 0.8
    - Medium block (5–10 total lines) → 0.6
    - Large block (> 10 total lines) → 0.3 (needs human review)

    Threshold for ESCALATE is < 0.7.
    """
    if not blocks:
        return 1.0

    scores: list[float] = []
    for block in blocks:
        if block.ours.strip() == block.theirs.strip():
            scores.append(0.95)
            continue
        total_lines = len(block.ours.splitlines()) + len(block.theirs.splitlines())
        if total_lines <= 4:
            scores.append(0.8)
        elif total_lines <= 10:
            scores.append(0.6)
        else:
            scores.append(0.3)

    return sum(scores) / len(scores)


def read_conflict_files(repo_path: Path, file_paths: list[str]) -> list[ConflictFile]:
    """Read files from disk and return those that contain conflict markers.

    Args:
        repo_path: Absolute path to the repository root.
        file_paths: Relative file paths to read.

    Returns:
        ``ConflictFile`` for every file that has at least one conflict block.
    """
    result: list[ConflictFile] = []
    for rel_path in file_paths:
        full = repo_path / rel_path
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        blocks = extract_conflict_blocks(content)
        if blocks:
            confidence = estimate_confidence(blocks)
            result.append(
                ConflictFile(path=rel_path, blocks=blocks, resolution_confidence=confidence)
            )
    return result


def inspect_conflicts(
    repo: GitRepo,
    ours_sha: str,
    theirs_sha: str,
) -> list[ConflictFile]:
    """Detect conflicts between two branches using ``git merge-tree``.

    This is non-destructive — it does not modify the working tree.
    Uses the old-style ``git merge-tree <base> <ours> <theirs>`` which is
    available in all git versions.

    Args:
        repo: A ``GitRepo`` instance for the repository.
        ours_sha: The SHA of the "ours" side (e.g., base branch HEAD).
        theirs_sha: The SHA of the "theirs" side (e.g., PR head).

    Returns:
        ``ConflictFile`` objects for any sections with conflict markers.
        Empty list if no conflicts detected or the command fails.
    """
    try:
        base = repo.get_merge_base(ours_sha, theirs_sha)
    except Exception:
        return []

    try:
        result = repo._run("merge-tree", base, ours_sha, theirs_sha, check=False)
        output = result.stdout
    except Exception:
        return []

    if _OURS_MARKER not in output:
        return []

    return _parse_merge_tree_output(output)


def _parse_merge_tree_output(output: str) -> list[ConflictFile]:
    """Parse old-format ``git merge-tree`` output into ``ConflictFile`` objects.

    The old merge-tree format embeds merged file content inline.  When
    conflicts exist the content contains standard ``<<<<<<<``/``>>>>>>>``
    markers.  File paths appear on lines matching the pattern::

        our    100644 <sha>\t<path>

    We collect content between path lines and extract conflict blocks.
    """
    path_re = re.compile(r"^\s+(?:base|our|their)\s+\d{6}\s+[0-9a-f]{40}\s+(.+)$")

    conflict_files: list[ConflictFile] = []
    current_path: str | None = None
    content_lines: list[str] = []
    seen_paths: set[str] = set()

    def _flush(path: str, lines: list[str]) -> None:
        content = "\n".join(lines)
        blocks = extract_conflict_blocks(content)
        if blocks:
            confidence = estimate_confidence(blocks)
            conflict_files.append(
                ConflictFile(path=path, blocks=blocks, resolution_confidence=confidence)
            )

    for line in output.splitlines():
        m = path_re.match(line)
        if m:
            path = m.group(1).strip()
            if path not in seen_paths:
                if current_path is not None:
                    _flush(current_path, content_lines)
                current_path = path
                content_lines = []
                seen_paths.add(path)
        elif current_path is not None:
            content_lines.append(line)

    if current_path is not None:
        _flush(current_path, content_lines)

    return conflict_files
