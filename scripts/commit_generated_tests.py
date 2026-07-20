#!/usr/bin/env python3
"""
commit_generated_tests.py

Commits any AI-generated test files back onto the PR's head branch using
plain git (the workflow checks out the PR head ref with a token that has
write access). This runs AFTER generate_tests.py has written files to disk.

Safe by design:
- No-ops cleanly if there is nothing to commit.
- Only stages files listed in generated_tests.json - never `git add -A`.
- Uses a dedicated bot identity (configurable) so commits are clearly
  attributable to automation, not a human.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.common.config_loader import get_config
from scripts.common.logger import get_logger

logger = get_logger(__name__)

GENERATED_MANIFEST_PATH = Path("pr-automation-artifacts/generated_tests.json")


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    logger.info("Running: %s", " ".join(cmd))
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def main() -> int:
    cfg = get_config()
    commit_cfg = cfg["test_generation"]["commit"]

    if not commit_cfg.get("enabled", True):
        logger.info("Committing generated tests is disabled via config. Skipping.")
        return 0

    if not GENERATED_MANIFEST_PATH.exists():
        logger.info("No generated-tests manifest found. Nothing to commit.")
        return 0

    generated = json.loads(GENERATED_MANIFEST_PATH.read_text(encoding="utf-8"))
    test_files = [entry["test_file"] for entry in generated if Path(entry["test_file"]).exists()]

    if not test_files:
        logger.info("No generated test files to commit.")
        return 0

    try:
        _run(["git", "config", "user.name", commit_cfg["author_name"]])
        _run(["git", "config", "user.email", commit_cfg["author_email"]])
        _run(["git", "add", "--", *test_files])

        diff_check = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], capture_output=True
        )
        if diff_check.returncode == 0:
            logger.info("No net changes after staging (files identical to existing content). Skipping commit.")
            return 0

        file_count = len(test_files)
        message = f"{commit_cfg['commit_message_prefix']} ({file_count} file(s)) [skip ci-build]"
        _run(["git", "commit", "-m", message])
        _run(["git", "push"])
        logger.info("Pushed %d generated test file(s) to PR branch.", file_count)
    except subprocess.CalledProcessError as exc:
        logger.error("Git command failed: %s\nstdout=%s\nstderr=%s", exc.cmd, exc.stdout, exc.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
