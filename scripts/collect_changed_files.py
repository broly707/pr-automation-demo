#!/usr/bin/env python3
"""
collect_changed_files.py

Fetches the PR's changed files from the GitHub API (not `git diff` against
an arbitrary local ref, which is unreliable on shallow checkouts) and writes
a filtered JSON manifest to disk for the AI review and test generation
scripts to consume. This is the single place that decides "what counts as
a changed source file", so review and test-generation always agree.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.common.config_loader import get_config
from scripts.common.diff_utils import ChangedFile, is_excluded
from scripts.common.github_client import GitHubClient, PullRequestContext
from scripts.common.logger import get_logger

logger = get_logger(__name__)

OUTPUT_PATH = Path("pr-automation-artifacts/changed_files.json")


def main() -> int:
    cfg = get_config()
    ctx = PullRequestContext.from_env()
    client = GitHubClient()

    raw_files = client.get_changed_files(ctx)
    logger.info("GitHub reports %d changed files in PR #%d", len(raw_files), ctx.pr_number)

    exclude_globs = cfg["general"]["excluded_paths"]
    android_exts = tuple(cfg["general"]["android_source_extensions"])
    ios_exts = tuple(cfg["general"]["ios_source_extensions"])
    all_source_exts = android_exts + ios_exts

    changed: list[ChangedFile] = []
    for f in raw_files:
        filename = f["filename"]
        if f.get("status") == "removed":
            continue
        if is_excluded(filename, exclude_globs):
            continue
        if not filename.endswith(all_source_exts):
            continue
        changed.append(
            ChangedFile(
                filename=filename,
                status=f.get("status", "modified"),
                patch=f.get("patch", ""),
                additions=f.get("additions", 0),
                deletions=f.get("deletions", 0),
            )
        )

    logger.info("%d files remain after extension/exclusion filtering", len(changed))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pr_number": ctx.pr_number,
        "head_sha": ctx.head_sha,
        "base_ref": ctx.base_ref,
        "files": [
            {
                "filename": cf.filename,
                "status": cf.status,
                "patch": cf.patch,
                "additions": cf.additions,
                "deletions": cf.deletions,
                "platform": "android" if cf.filename.endswith(android_exts) else "ios",
            }
            for cf in changed
        ],
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Wrote changed-file manifest to %s", OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
