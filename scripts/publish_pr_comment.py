#!/usr/bin/env python3
"""
publish_pr_comment.py

Publishes pr-automation-artifacts/final_report.md as a single, upserted PR
comment, and creates a GitHub Check Run named "pr-automation/gate" whose
conclusion mirrors the overall pass/fail. Add "pr-automation/gate" to the
repository's required status checks (Settings -> Branches -> Branch
protection rules) to make this merge-blocking.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.common.config_loader import get_config
from scripts.common.github_client import GitHubClient, PullRequestContext
from scripts.common.logger import get_logger

logger = get_logger(__name__)

ARTIFACT_DIR = Path("pr-automation-artifacts")
CHECK_RUN_NAME = "pr-automation/gate"


def main() -> int:
    cfg = get_config()
    ctx = PullRequestContext.from_env()
    client = GitHubClient()

    report_path = ARTIFACT_DIR / "final_report.md"
    status_path = ARTIFACT_DIR / "final_status.json"

    if not report_path.exists() or not status_path.exists():
        logger.error("Missing final_report.md or final_status.json. Run aggregate_report.py first.")
        return 2

    report_md = report_path.read_text(encoding="utf-8")
    final_status = json.loads(status_path.read_text(encoding="utf-8"))
    overall_pass = final_status["overall_pass"]

    marker = cfg["reporting"]["pr_comment_marker"]
    comment_body = f"{marker}\n{report_md}"
    client.upsert_pr_comment(ctx, marker, comment_body)

    conclusion = "success" if overall_pass else "failure"
    title = "PR Automation: PASS" if overall_pass else "PR Automation: FAIL"
    summary = (
        f"Overall result: {'PASS' if overall_pass else 'FAIL'}. "
        f"{final_status.get('ai_findings_count', 0)} AI review finding(s). "
        "See PR comment for full report."
    )
    client.create_check_run(ctx, CHECK_RUN_NAME, conclusion, title, summary)

    logger.info("Published PR comment and check run. overall_pass=%s", overall_pass)
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
