#!/usr/bin/env python3
"""
aggregate_report.py

Combines the individual stage results (build, lint, existing tests,
generated tests, AI review) — each passed in as a JSON "status file" written
by the corresponding workflow job — into a single professional markdown
report, and determines the overall PASS/FAIL gate.

Each status file is expected at pr-automation-artifacts/status_<stage>.json
with shape: {"stage": str, "status": "success"|"failure"|"skipped", "detail": str, "duration_seconds": number}

This script does not talk to GitHub; it only produces
pr-automation-artifacts/final_report.md and final_status.json. Publishing is
handled by publish_pr_comment.py so responsibilities stay separated.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from scripts.common.config_loader import get_config
from scripts.common.logger import get_logger

logger = get_logger(__name__)

ARTIFACT_DIR = Path("pr-automation-artifacts")
STAGES = ["build", "lint", "existing_tests", "generated_tests"]


def _load_status(stage: str) -> Dict[str, Any]:
    path = ARTIFACT_DIR / f"status_{stage}.json"
    if not path.exists():
        logger.warning("No status file for stage '%s' at %s; treating as skipped.", stage, path)
        return {"stage": stage, "status": "skipped", "detail": "No status reported.", "duration_seconds": 0}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_text(path: Path, fallback: str) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else fallback


def _badge(status: str) -> str:
    return {"success": "✅ PASS", "failure": "❌ FAIL", "skipped": "⏭️ SKIPPED"}.get(status, "❓ UNKNOWN")


def main() -> int:
    cfg = get_config()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    statuses = {stage: _load_status(stage) for stage in STAGES}

    ai_review_md = _load_text(ARTIFACT_DIR / "ai_review_report.md", "_AI review did not run or produced no output._")
    android_review = json.loads(_load_text(ARTIFACT_DIR / "ai_review_android.json", "{}") or "{}")
    ios_review = json.loads(_load_text(ARTIFACT_DIR / "ai_review_ios.json", "{}") or "{}")
    generated_tests = json.loads(_load_text(ARTIFACT_DIR / "generated_tests.json", "[]") or "[]")

    fail_on = set(cfg["reporting"]["fail_pipeline_on"])
    overall_pass = True
    for stage in STAGES:
        if stage in fail_on and statuses[stage]["status"] == "failure":
            overall_pass = False

    ai_findings = android_review.get("findings", []) + ios_review.get("findings", [])
    fail_severity = cfg["ai_review"]["fail_on_severity"]
    severity_order = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    if "ai_review_critical" in fail_on and fail_severity != "none" and ai_findings:
        worst = max(severity_order.get(f.get("severity", "low"), 0) for f in ai_findings)
        if worst >= severity_order.get(fail_severity, 3):
            overall_pass = False

    total_duration = sum(s.get("duration_seconds", 0) for s in statuses.values())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    lines.append(f"# PR Automation Report — {'✅ PASS' if overall_pass else '❌ FAIL'}\n")
    lines.append(f"_Generated {now} · total pipeline time ~{total_duration:.0f}s_\n")

    lines.append("## Summary\n")
    lines.append("| Stage | Status | Detail |")
    lines.append("|---|---|---|")
    for stage in STAGES:
        s = statuses[stage]
        lines.append(f"| {stage.replace('_', ' ').title()} | {_badge(s['status'])} | {s.get('detail','')} |")
    lines.append(f"| AI Review (critical gate) | {_badge('failure' if not overall_pass and ai_findings else 'success')} | "
                  f"{len(ai_findings)} finding(s) across Android/iOS |")
    lines.append("")

    lines.append("## Files Reviewed\n")
    manifest_path = ARTIFACT_DIR / "changed_files.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for f in manifest["files"]:
            lines.append(f"- `{f['filename']}` ({f['platform']}, {f['status']})")
    else:
        lines.append("_No changed-file manifest found._")
    lines.append("")

    lines.append("## Issues Found & Suggested Fixes\n")
    lines.append(ai_review_md)
    lines.append("")

    lines.append("## AI-Generated Tests\n")
    if generated_tests:
        lines.append("| Source File | Generated Test File | Platform |")
        lines.append("|---|---|---|")
        for g in generated_tests:
            lines.append(f"| `{g['source_file']}` | `{g['test_file']}` | {g['platform']} |")
    else:
        lines.append("_No new tests were generated for this PR (either no eligible source changes, or tests already existed)._")
    lines.append("")

    lines.append("## Build / Lint / Test Status\n")
    for stage in ("build", "lint", "existing_tests", "generated_tests"):
        s = statuses[stage]
        lines.append(f"### {stage.replace('_', ' ').title()}: {_badge(s['status'])}")
        lines.append(f"{s.get('detail', '(no detail provided)')}\n")

    report_md = "\n".join(lines)
    (ARTIFACT_DIR / "final_report.md").write_text(report_md, encoding="utf-8")

    final_status = {
        "overall_pass": overall_pass,
        "generated_at": now,
        "stage_statuses": statuses,
        "ai_findings_count": len(ai_findings),
    }
    (ARTIFACT_DIR / "final_status.json").write_text(json.dumps(final_status, indent=2), encoding="utf-8")

    logger.info("Aggregate report written. overall_pass=%s", overall_pass)
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
