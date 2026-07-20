#!/usr/bin/env python3
"""
merge_status.py

When both Android and iOS run for the same stage (build, lint,
existing_tests, generated_tests), each platform's job uploads its own
status_<stage>.json artifact. This script merges same-stage files that were
downloaded into sibling directories (one per artifact) into a single
status_<stage>.json in the shared artifacts directory, using "worst status
wins" (failure > skipped > success is NOT the rule — failure beats
everything, then success beats skipped, since skipped just means that
platform doesn't exist in this repo).

Usage: python -m scripts.merge_status --downloads-dir all-artifacts
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

STAGES = ["build", "lint", "existing_tests", "generated_tests"]
ARTIFACT_DIR = Path("pr-automation-artifacts")

_RANK = {"failure": 2, "success": 1, "skipped": 0}


def _merge_one_stage(stage: str, files: List[Path]) -> Dict:
    if not files:
        return {"stage": stage, "status": "skipped", "detail": "No job produced this stage.", "duration_seconds": 0}

    entries = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    worst = max(entries, key=lambda e: _RANK.get(e.get("status", "skipped"), 0))
    combined_detail = " | ".join(e.get("detail", "") for e in entries if e.get("detail"))
    total_duration = sum(e.get("duration_seconds", 0) for e in entries)
    return {
        "stage": stage,
        "status": worst["status"],
        "detail": combined_detail,
        "duration_seconds": total_duration,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--downloads-dir", required=True, help="Directory containing all downloaded artifact folders")
    args = parser.parse_args()

    downloads = Path(args.downloads_dir)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    for stage in STAGES:
        matches = sorted(downloads.rglob(f"status_{stage}.json"))
        merged = _merge_one_stage(stage, matches)
        (ARTIFACT_DIR / f"status_{stage}.json").write_text(json.dumps(merged, indent=2), encoding="utf-8")
        print(f"Merged {len(matches)} file(s) for stage '{stage}' -> status={merged['status']}")

    # Also surface the AI review + generated-tests + changed-files artifacts
    # into the shared artifact dir if present, so aggregate_report.py finds them.
    passthrough = [
        "ai_review_report.md",
        "ai_review_android.json",
        "ai_review_ios.json",
        "generated_tests.json",
        "changed_files.json",
    ]
    for name in passthrough:
        matches = list(downloads.rglob(name))
        if matches:
            ARTIFACT_DIR.joinpath(name).write_bytes(matches[0].read_bytes())

    return 0


if __name__ == "__main__":
    sys.exit(main())
