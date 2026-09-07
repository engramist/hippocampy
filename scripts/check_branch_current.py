#!/usr/bin/env python3
"""
scripts/check_branch_current.py — Stale-Base Guard.

Enforces that PR branches are rebased on the latest HEAD of main before merge.
Prevents silent regressions where stale branches inadvertently propose reverting
or deleting work merged concurrently by other agents.

Exit codes:
- 0: Branch is up to date with target base branch (merge-base == target HEAD).
- 1: Branch is stale (merge-base != target HEAD). Displays deleted lines count.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def run_git(args: list[str], check: bool = True) -> str:
    res = subprocess.run(
        ["git"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed (code {res.returncode}): {res.stderr.strip()}")
    return res.stdout.strip()


def compute_stale_deletions(target_ref: str, head_ref: str = "HEAD") -> tuple[int, int]:
    """
    Compute number of lines in target_ref that would be deleted/reverted in head_ref.
    Returns (total_deletions, affected_files_count).
    """
    out = run_git(["diff", "--numstat", target_ref, head_ref], check=False)
    deletions = 0
    files = 0
    for line in out.splitlines():
        parts = line.split("	")
        if len(parts) >= 3 and parts[0] != "-" and parts[1] != "-":
            del_count = int(parts[1])
            if del_count > 0:
                deletions += del_count
                files += 1
    return deletions, files


def check_branch_current(target_ref: str | None = None) -> int:
    # 1. Determine target branch
    if not target_ref:
        base_ref = os.environ.get("GITHUB_BASE_REF")
        if base_ref:
            target_ref = f"origin/{base_ref}"
        else:
            target_ref = "origin/main"

    # Verify git repository
    try:
        run_git(["rev-parse", "--is-inside-work-tree"])
    except Exception as e:
        print(f"ERROR: Not inside a git worktree: {e}", file=sys.stderr)
        return 1

    # Check if target_ref exists locally; if not, try fetching
    try:
        target_sha = run_git(["rev-parse", target_ref])
    except Exception:
        # Attempt fetch
        print(f"Target ref '{target_ref}' not found locally. Attempting to fetch...", file=sys.stderr)
        run_git(["fetch", "origin", "main"], check=False)
        try:
            target_sha = run_git(["rev-parse", target_ref])
        except Exception:
            # Fallback to local main if origin/main not available
            target_ref = "main"
            target_sha = run_git(["rev-parse", target_ref])

    head_sha = run_git(["rev-parse", "HEAD"])

    # If HEAD is target_ref (e.g. running on main push in CI), pass immediately
    if head_sha == target_sha:
        print(f"OK: Branch HEAD is identical to {target_ref} ({target_sha[:8]}).")
        return 0

    # 2. Check merge-base
    merge_base = run_git(["merge-base", "HEAD", target_ref], check=False)
    if not merge_base:
        print(f"ERROR: Could not compute merge-base between HEAD and {target_ref}.", file=sys.stderr)
        return 1

    if merge_base == target_sha:
        print(f"OK: Branch is current with {target_ref} (merge-base is {target_sha[:8]}).")
        return 0

    # 3. Branch is stale!
    deletions, affected_files = compute_stale_deletions(target_ref, "HEAD")
    print("=" * 72, file=sys.stderr)
    print(f"ERROR: Stale-base detected! Branch is not rebased onto latest {target_ref}.", file=sys.stderr)
    print(f"  Current merge-base : {merge_base[:8]}", file=sys.stderr)
    print(f"  {target_ref} HEAD   : {target_sha[:8]}", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        f"rebase onto main — your diff currently proposes deleting {deletions} lines "
        f"of merged work across {affected_files} file(s).",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    print("To resolve this, rebase your branch onto current main:", file=sys.stderr)
    print("  git fetch origin main && git rebase origin/main", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Check if current branch is rebased on target base branch.")
    parser.add_argument("--target", default=None, help="Target base branch (default: origin/main or $GITHUB_BASE_REF)")
    args = parser.parse_args()
    sys.exit(check_branch_current(target_ref=args.target))


if __name__ == "__main__":
    main()
