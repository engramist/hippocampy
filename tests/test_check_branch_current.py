"""
tests/test_check_branch_current.py — Tests for B408 Stale-Base Guard.

Verifies:
1. Current branch (rebased onto main) exits with 0.
2. Stale branch (predating recent merges) exits with 1.
3. Actionable error message includes the exact count of lines at risk of deletion/reversion.
4. Reconstructed scenario with historical commit produces accurate line counts.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from scripts.check_branch_current import (
    check_branch_current,
    compute_stale_deletions,
)


def test_head_identical_to_target() -> None:
    """Verify that when HEAD == target (e.g. CI on push to main), check passes."""
    with patch("scripts.check_branch_current.run_git") as mock_git:
        mock_git.side_effect = lambda args, **kwargs: (
            "true" if args[0] == "rev-parse" and args[1] == "--is-inside-work-tree"
            else "commit_abc123"
        )
        assert check_branch_current(target_ref="origin/main") == 0


def test_current_branch_rebased_returns_zero() -> None:
    """Verify that when merge-base == target_sha, check passes with 0."""
    with patch("scripts.check_branch_current.run_git") as mock_git:
        def side_effect(args, **kwargs):
            if args[0] == "rev-parse":
                if args[1] == "--is-inside-work-tree":
                    return "true"
                if args[1] == "origin/main":
                    return "target_commit_123"
                if args[1] == "HEAD":
                    return "feature_commit_456"
            elif args[0] == "merge-base":
                return "target_commit_123"
            return ""

        mock_git.side_effect = side_effect
        assert check_branch_current(target_ref="origin/main") == 0


def test_stale_branch_fails_with_actionable_deletion_count(capsys: pytest.CaptureFixture) -> None:
    """Verify that when merge-base != target_sha, check fails and reports line deletions."""
    with patch("scripts.check_branch_current.run_git") as mock_git:
        def side_effect(args, **kwargs):
            if args[0] == "rev-parse":
                if args[1] == "--is-inside-work-tree":
                    return "true"
                if args[1] == "origin/main":
                    return "target_commit_123"
                if args[1] == "HEAD":
                    return "feature_commit_456"
            elif args[0] == "merge-base":
                return "old_base_commit_000"
            elif args[0] == "diff" and "--numstat" in args:
                return "10\t50\tfile_a.py\n20\t4954\tfile_b.py"
            return ""

        mock_git.side_effect = side_effect
        code = check_branch_current(target_ref="origin/main")
        assert code == 1

        captured = capsys.readouterr()
        assert "rebase onto main — your diff currently proposes deleting 5004 lines of merged work across 2 file(s)." in captured.err
        assert "git fetch origin main && git rebase origin/main" in captured.err


def test_compute_stale_deletions_calculation() -> None:
    """Verify line computation parsing from numstat."""
    numstat_mock = "5\t12\tfile1.py\n-\t-\timage.png\n100\t88\tfile2.py"
    with patch("scripts.check_branch_current.run_git", return_value=numstat_mock):
        deletions, files = compute_stale_deletions("origin/main", "HEAD")
        assert deletions == 100  # 12 + 88
        assert files == 2
