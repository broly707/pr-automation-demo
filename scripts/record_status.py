#!/usr/bin/env python3
"""
record_status.py

Small CLI used directly from workflow steps (bash) to write a standardized
status_<stage>.json file, so aggregate_report.py has one consistent format
to read regardless of whether the stage was a Gradle task, xcodebuild, or a
Python script. Keeps that bookkeeping logic out of YAML.

Usage:
  python -m scripts.record_status --stage build --status success \
      --detail "Assembled debug APK in 42s" --duration 42
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ARTIFACT_DIR = Path("pr-automation-artifacts")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=["build", "lint", "existing_tests", "generated_tests"])
    parser.add_argument("--status", required=True, choices=["success", "failure", "skipped"])
    parser.add_argument("--detail", default="")
    parser.add_argument("--duration", type=float, default=0.0)
    args = parser.parse_args()

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": args.stage,
        "status": args.status,
        "detail": args.detail,
        "duration_seconds": args.duration,
    }
    (ARTIFACT_DIR / f"status_{args.stage}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Recorded status for '{args.stage}': {args.status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
