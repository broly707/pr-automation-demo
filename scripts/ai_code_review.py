#!/usr/bin/env python3
"""
ai_code_review.py

Reads pr-automation-artifacts/changed_files.json, sends only the diff
content (not whole files, not the whole repo) to Groq per platform, and
writes:
  - pr-automation-artifacts/ai_review_android.json (raw findings)
  - pr-automation-artifacts/ai_review_ios.json
  - pr-automation-artifacts/ai_review_report.md (human-readable)

Exit code is non-zero if any finding meets/exceeds the configured
fail_on_severity threshold, so this step can gate the pipeline on its own
if desired (in addition to the aggregate gate job).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from scripts.common.config_loader import get_config
from scripts.common.diff_utils import ChangedFile, build_diff_bundle
from scripts.common.groq_client import GroqClient, GroqApiError
from scripts.common.logger import get_logger

logger = get_logger(__name__)

MANIFEST_PATH = Path("pr-automation-artifacts/changed_files.json")
ARTIFACT_DIR = Path("pr-automation-artifacts")

SEVERITY_ORDER = {"critical": 3, "high": 2, "medium": 1, "low": 0}


def _load_prompt_template(platform: str) -> str:
    filename = "android_prompt.txt" if platform == "android" else "ios_prompt.txt"
    path = Path("config/review_prompts") / filename
    return path.read_text(encoding="utf-8")


def _review_platform(platform: str, files: List[Dict[str, Any]], cfg: dict) -> Dict[str, Any]:
    if not files:
        return {"summary": f"No {platform} files changed.", "findings": []}

    review_cfg = cfg["ai_review"]
    changed_files = [
        ChangedFile(
            filename=f["filename"],
            status=f["status"],
            patch=f["patch"],
            additions=f["additions"],
            deletions=f["deletions"],
        )
        for f in files
    ]
    diff_bundle = build_diff_bundle(
        changed_files,
        max_total_chars=review_cfg["max_diff_characters"],
        max_chars_per_file=review_cfg["max_characters_per_file"],
        max_files=review_cfg["max_files_per_request"],
    )

    template = _load_prompt_template(platform)
    prompt = template.replace("{diff_content}", diff_bundle)

    client = GroqClient(
        model=review_cfg["model"],
        timeout_seconds=review_cfg["request_timeout_seconds"],
        max_retries=review_cfg["max_retries"],
        retry_backoff_base_seconds=review_cfg["retry_backoff_base_seconds"],
    )

    try:
        raw = client.complete(
            system_prompt="You are a precise, senior code reviewer. Always respond with valid JSON only.",
            user_prompt=prompt,
            temperature=review_cfg["temperature"],
            max_tokens=review_cfg["max_output_tokens"],
            response_format_json=True,
        )
    except GroqApiError as exc:
        logger.error("AI review for %s failed after retries: %s", platform, exc)
        return {
            "summary": f"AI review could not be completed for {platform}: {exc}",
            "findings": [],
            "error": True,
        }

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Model did not return valid JSON for %s review. Raw: %.500s", platform, raw)
        return {
            "summary": f"AI review returned unparsable output for {platform}.",
            "findings": [],
            "error": True,
        }

    parsed.setdefault("findings", [])
    parsed.setdefault("summary", "")
    return parsed


def _render_markdown(android_result: dict, ios_result: dict, fail_severity: str) -> str:
    lines = ["## 🤖 AI Code Review Report\n"]
    for platform, result in (("Android", android_result), ("iOS", ios_result)):
        lines.append(f"### {platform}\n")
        lines.append(f"{result.get('summary', '(no summary)')}\n")
        findings = result.get("findings", [])
        if not findings:
            lines.append("_No issues found._\n")
            continue
        lines.append("| Severity | Category | File | Issue | Suggested Fix |")
        lines.append("|---|---|---|---|---|")
        for finding in sorted(
            findings, key=lambda f: SEVERITY_ORDER.get(f.get("severity", "low"), 0), reverse=True
        ):
            sev = finding.get("severity", "low")
            emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(sev, "⚪")
            file_ref = finding.get("file", "?")
            line_no = finding.get("line")
            loc = f"{file_ref}:{line_no}" if line_no else file_ref
            issue = str(finding.get("issue", "")).replace("|", "\\|")
            fix = str(finding.get("suggested_fix", "")).replace("|", "\\|")
            lines.append(f"| {emoji} {sev} | {finding.get('category','')} | `{loc}` | {issue} | {fix} |")
        lines.append("")
    return "\n".join(lines)


def _max_severity(findings: List[Dict[str, Any]]) -> str:
    if not findings:
        return "none"
    return max(findings, key=lambda f: SEVERITY_ORDER.get(f.get("severity", "low"), 0))["severity"]


def main() -> int:
    cfg = get_config()
    if not MANIFEST_PATH.exists():
        logger.error("Changed-files manifest not found at %s. Run collect_changed_files.py first.", MANIFEST_PATH)
        return 2

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    all_files = manifest["files"]
    android_files = [f for f in all_files if f["platform"] == "android"]
    ios_files = [f for f in all_files if f["platform"] == "ios"]

    android_result = _review_platform("android", android_files, cfg)
    ios_result = _review_platform("ios", ios_files, cfg)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "ai_review_android.json").write_text(json.dumps(android_result, indent=2))
    (ARTIFACT_DIR / "ai_review_ios.json").write_text(json.dumps(ios_result, indent=2))

    fail_severity = cfg["ai_review"]["fail_on_severity"]
    report_md = _render_markdown(android_result, ios_result, fail_severity)
    (ARTIFACT_DIR / "ai_review_report.md").write_text(report_md, encoding="utf-8")
    logger.info("AI review report written to %s", ARTIFACT_DIR / "ai_review_report.md")

    all_findings = android_result.get("findings", []) + ios_result.get("findings", [])
    worst = _max_severity(all_findings)
    logger.info("Worst finding severity across platforms: %s", worst)

    if fail_severity != "none" and worst != "none":
        threshold = SEVERITY_ORDER.get(fail_severity, 3)
        if SEVERITY_ORDER.get(worst, 0) >= threshold:
            logger.error(
                "AI review found a '%s' severity issue, meeting/exceeding fail threshold '%s'.",
                worst, fail_severity,
            )
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
