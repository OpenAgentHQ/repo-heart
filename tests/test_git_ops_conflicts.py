"""Tests for repoheart.git_ops.conflicts."""

from __future__ import annotations

from pathlib import Path

import pytest

from repoheart.git_ops.conflicts import (
    ConflictBlock,
    ConflictFile,
    estimate_confidence,
    extract_conflict_blocks,
    read_conflict_files,
)

_SIMPLE_CONFLICT = """\
normal line before
<<<<<<< HEAD
our version of code
=======
their version of code
>>>>>>> feature-branch
normal line after
"""

_MULTI_CONFLICT = """\
<<<<<<< HEAD
line a1
line a2
=======
line b1
line b2
>>>>>>> branch
middle
<<<<<<< HEAD
x = 1
=======
x = 2
>>>>>>> branch
"""

_WHITESPACE_ONLY = """\
<<<<<<< HEAD
    return value
=======
    return value
>>>>>>> branch
"""

_NO_CONFLICT = "just normal content\nno markers here\n"

_LARGE_CONFLICT = """\
<<<<<<< HEAD
{}
=======
{}
>>>>>>> branch
""".format("\n".join(f"line {i}" for i in range(30)), "\n".join(f"other {i}" for i in range(30)))


# ── extract_conflict_blocks ───────────────────────────────────────────────────

def test_extract_conflict_blocks_basic() -> None:
    blocks = extract_conflict_blocks(_SIMPLE_CONFLICT)
    assert len(blocks) == 1
    assert "our version" in blocks[0].ours
    assert "their version" in blocks[0].theirs


def test_extract_conflict_blocks_multiple() -> None:
    blocks = extract_conflict_blocks(_MULTI_CONFLICT)
    assert len(blocks) == 2


def test_extract_conflict_blocks_no_conflict() -> None:
    blocks = extract_conflict_blocks(_NO_CONFLICT)
    assert blocks == []


def test_extract_conflict_blocks_context_before() -> None:
    blocks = extract_conflict_blocks(_SIMPLE_CONFLICT)
    assert "normal line before" in blocks[0].context_before


def test_extract_conflict_blocks_whitespace_only() -> None:
    blocks = extract_conflict_blocks(_WHITESPACE_ONLY)
    assert len(blocks) == 1
    assert blocks[0].ours.strip() == blocks[0].theirs.strip()


def test_extract_conflict_blocks_empty_string() -> None:
    assert extract_conflict_blocks("") == []


# ── estimate_confidence ───────────────────────────────────────────────────────

def test_estimate_confidence_no_blocks() -> None:
    assert estimate_confidence([]) == 1.0


def test_estimate_confidence_whitespace_only_is_high() -> None:
    blocks = extract_conflict_blocks(_WHITESPACE_ONLY)
    confidence = estimate_confidence(blocks)
    assert confidence >= 0.9


def test_estimate_confidence_small_block() -> None:
    blocks = extract_conflict_blocks(_SIMPLE_CONFLICT)
    confidence = estimate_confidence(blocks)
    assert 0.7 <= confidence <= 1.0


def test_estimate_confidence_low_for_large_block() -> None:
    blocks = extract_conflict_blocks(_LARGE_CONFLICT)
    confidence = estimate_confidence(blocks)
    assert confidence < 0.7


def test_estimate_confidence_medium_block() -> None:
    medium = """\
<<<<<<< HEAD
line 1
line 2
line 3
line 4
line 5
=======
other 1
other 2
other 3
other 4
other 5
>>>>>>> branch
"""
    blocks = extract_conflict_blocks(medium)
    confidence = estimate_confidence(blocks)
    assert confidence < 0.7  # 10 total lines → medium score


# ── ConflictFile ──────────────────────────────────────────────────────────────

def test_conflict_file_dataclass_immutable() -> None:
    cf = ConflictFile(path="foo.py", blocks=[], resolution_confidence=0.8)
    with pytest.raises((AttributeError, TypeError)):
        cf.path = "bar.py"  # type: ignore[misc]


def test_conflict_block_dataclass_immutable() -> None:
    cb = ConflictBlock(ours="a", theirs="b")
    with pytest.raises((AttributeError, TypeError)):
        cb.ours = "c"  # type: ignore[misc]


# ── read_conflict_files ───────────────────────────────────────────────────────

def test_read_conflict_files_with_markers(tmp_path: Path) -> None:
    f = tmp_path / "conflict.py"
    f.write_text(_SIMPLE_CONFLICT, encoding="utf-8")
    result = read_conflict_files(tmp_path, ["conflict.py"])
    assert len(result) == 1
    assert result[0].path == "conflict.py"
    assert len(result[0].blocks) == 1


def test_read_conflict_files_no_markers(tmp_path: Path) -> None:
    f = tmp_path / "clean.py"
    f.write_text(_NO_CONFLICT, encoding="utf-8")
    result = read_conflict_files(tmp_path, ["clean.py"])
    assert result == []


def test_read_conflict_files_missing_file(tmp_path: Path) -> None:
    result = read_conflict_files(tmp_path, ["nonexistent.py"])
    assert result == []


def test_read_conflict_files_confidence_propagated(tmp_path: Path) -> None:
    f = tmp_path / "large_conflict.py"
    f.write_text(_LARGE_CONFLICT, encoding="utf-8")
    result = read_conflict_files(tmp_path, ["large_conflict.py"])
    assert result[0].resolution_confidence < 0.7
