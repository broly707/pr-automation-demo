#!/usr/bin/env python3
"""
detect_project_type.py

Scans the checked-out repository for Android and/or iOS project markers and
writes boolean flags to $GITHUB_OUTPUT so downstream workflow jobs can
condition on them (`if: needs.detect.outputs.has_android == 'true'`).

Exit code is always 0 unless neither platform is detected, in which case we
fail loudly rather than silently no-op the whole pipeline.
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

from scripts.common.config_loader import get_config
from scripts.common.logger import get_logger

logger = get_logger(__name__)


def _any_marker_exists(root: Path, markers: list[str]) -> bool:
    for marker in markers:
        if "*" in marker:
            if list(root.rglob(marker)):
                return True
        else:
            if list(root.rglob(marker)):
                return True
    return False


def main() -> int:
    cfg = get_config()
    root = Path(os.environ.get("REPO_ROOT", "."))

    android_markers = cfg["general"]["android_markers"]
    ios_markers = cfg["general"]["ios_markers"]

    has_android = _any_marker_exists(root, android_markers)
    has_ios = _any_marker_exists(root, ios_markers)

    logger.info("Detection result: android=%s ios=%s", has_android, has_ios)

    if not has_android and not has_ios:
        logger.error(
            "No Android or iOS project markers found under '%s'. "
            "Checked android markers=%s, ios markers=%s",
            root,
            android_markers,
            ios_markers,
        )
        _write_output({"has_android": "false", "has_ios": "false"})
        return 1

    _write_output({"has_android": str(has_android).lower(), "has_ios": str(has_ios).lower()})
    return 0


def _write_output(values: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        logger.warning("GITHUB_OUTPUT not set (not running in Actions?); printing instead.")
        for k, v in values.items():
            print(f"{k}={v}")
        return
    with open(output_path, "a", encoding="utf-8") as f:
        for k, v in values.items():
            f.write(f"{k}={v}\n")


if __name__ == "__main__":
    sys.exit(main())
