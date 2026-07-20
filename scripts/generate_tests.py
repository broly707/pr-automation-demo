#!/usr/bin/env python3
"""
generate_tests.py

For each changed, non-test Android/iOS source file, asks Groq to generate a
complete, compilable test file and writes it into the conventional test
location:

  Android: <module>/src/main/kotlin/<pkg>/Foo.kt
        -> <module>/src/test/kotlin/<pkg>/FooTest.kt

  iOS:     Sources/<Target>/Foo.swift
        -> Tests/<Target>Tests/FooTests.swift   (falls back to config test_source_root)

Skips files that already have a corresponding test file when
skip_if_test_file_exists is true. Writes a manifest of generated files for
the commit step and the reporting step to consume.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.common.config_loader import get_config
from scripts.common.groq_client import GroqClient, GroqApiError
from scripts.common.logger import get_logger

logger = get_logger(__name__)

MANIFEST_PATH = Path("pr-automation-artifacts/changed_files.json")
ARTIFACT_DIR = Path("pr-automation-artifacts")
GENERATED_MANIFEST_PATH = ARTIFACT_DIR / "generated_tests.json"


# --------------------------------------------------------------------------- #
# Android path resolution
# --------------------------------------------------------------------------- #
def _android_test_path(source_path: Path, cfg: dict) -> Optional[Path]:
    main_marker = f"/{cfg['android']['main_source_set']}/"
    test_marker = f"/{cfg['android']['test_source_set']}/"
    posix = "/" + source_path.as_posix()
    if main_marker not in posix:
        logger.warning("Cannot map %s to a test path: no '%s' segment found.", source_path, main_marker)
        return None
    module_and_prefix, rest = posix.split(main_marker, 1)
    class_name = Path(rest).stem
    test_rest = str(Path(rest).parent / f"{class_name}Test.kt")
    test_path = Path((module_and_prefix + test_marker + test_rest).lstrip("/"))
    return test_path


def _kotlin_package(source_content: str) -> str:
    match = re.search(r"^package\s+([\w.]+)", source_content, flags=re.MULTILINE)
    return match.group(1) if match else ""


# --------------------------------------------------------------------------- #
# iOS path resolution
# --------------------------------------------------------------------------- #
def _ios_test_path(source_path: Path, cfg: dict) -> Path:
    class_name = source_path.stem
    # Convention: Sources/<Target>/File.swift -> Tests/<Target>Tests/FileTests.swift
    parts = source_path.parts
    if "Sources" in parts:
        idx = parts.index("Sources")
        target = parts[idx + 1] if len(parts) > idx + 1 else "App"
        return Path("Tests") / f"{target}Tests" / f"{class_name}Tests.swift"
    # Fallback: use configured test_source_root, mirror directory structure.
    root = Path(cfg["ios"]["test_source_root"])
    return root / source_path.parent / f"{class_name}Tests.swift"


def _ios_module_name(source_path: Path) -> str:
    parts = source_path.parts
    if "Sources" in parts:
        idx = parts.index("Sources")
        if len(parts) > idx + 1:
            return parts[idx + 1]
    return "App"


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:kotlin|swift)?\n", "", text)
    text = re.sub(r"\n```$", "", text)
    return text.strip() + "\n"


def _generate_android_test(
    client: GroqClient, source_path: Path, source_content: str, cfg: dict
) -> Optional[str]:
    class_name = source_path.stem
    template = Path("config/test_prompts/android_test_prompt.txt").read_text(encoding="utf-8")
    prompt = (
        template.replace("{file_path}", str(source_path))
        .replace("{class_name}", class_name)
        .replace("{source_content}", source_content)
    )
    tg_cfg = cfg["test_generation"]
    try:
        raw = client.complete(
            system_prompt="You are a senior Android engineer. Output only raw Kotlin source code.",
            user_prompt=prompt,
            temperature=tg_cfg["temperature"],
            max_tokens=tg_cfg["max_output_tokens"],
            response_format_json=False,
        )
    except GroqApiError as exc:
        logger.error("Test generation failed for %s: %s", source_path, exc)
        return None
    return _strip_code_fences(raw)


def _generate_ios_test(
    client: GroqClient, source_path: Path, source_content: str, cfg: dict
) -> Optional[str]:
    class_name = source_path.stem
    module_name = _ios_module_name(source_path)
    template = Path("config/test_prompts/ios_test_prompt.txt").read_text(encoding="utf-8")
    prompt = (
        template.replace("{file_path}", str(source_path))
        .replace("{class_name}", class_name)
        .replace("{module_name}", module_name)
        .replace("{source_content}", source_content)
    )
    tg_cfg = cfg["test_generation"]
    try:
        raw = client.complete(
            system_prompt="You are a senior iOS engineer. Output only raw Swift source code.",
            user_prompt=prompt,
            temperature=tg_cfg["temperature"],
            max_tokens=tg_cfg["max_output_tokens"],
            response_format_json=False,
        )
    except GroqApiError as exc:
        logger.error("Test generation failed for %s: %s", source_path, exc)
        return None
    return _strip_code_fences(raw)


def main() -> int:
    cfg = get_config()
    tg_cfg = cfg["test_generation"]

    if not MANIFEST_PATH.exists():
        logger.error("Changed-files manifest not found at %s. Run collect_changed_files.py first.", MANIFEST_PATH)
        return 2

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    candidates = [
        f
        for f in manifest["files"]
        if f["status"] in ("added", "modified")
        and not Path(f["filename"]).stem.endswith(("Test", "Tests"))
    ]
    candidates = candidates[: tg_cfg["max_files_to_generate"]]
    logger.info("%d candidate source files eligible for test generation", len(candidates))

    client = GroqClient(
        model=tg_cfg["model"],
        timeout_seconds=tg_cfg["request_timeout_seconds"],
        max_retries=tg_cfg["max_retries"],
        retry_backoff_base_seconds=tg_cfg["retry_backoff_base_seconds"],
    )

    generated: List[Dict[str, Any]] = []

    for f in candidates:
        source_path = Path(f["filename"])
        if not source_path.exists():
            logger.warning("Skipping %s: not present in working tree (deleted/renamed).", source_path)
            continue

        platform = f["platform"]
        test_path = (
            _android_test_path(source_path, cfg) if platform == "android" else _ios_test_path(source_path, cfg)
        )
        if test_path is None:
            continue

        if tg_cfg["skip_if_test_file_exists"] and test_path.exists():
            logger.info("Skipping %s: test file already exists at %s", source_path, test_path)
            continue

        source_content = source_path.read_text(encoding="utf-8", errors="replace")

        if platform == "android":
            test_content = _generate_android_test(client, source_path, source_content, cfg)
        else:
            test_content = _generate_ios_test(client, source_path, source_content, cfg)

        if not test_content:
            continue

        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text(test_content, encoding="utf-8")
        logger.info("Generated test: %s -> %s", source_path, test_path)

        generated.append(
            {
                "source_file": str(source_path),
                "test_file": str(test_path),
                "platform": platform,
            }
        )

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_MANIFEST_PATH.write_text(json.dumps(generated, indent=2), encoding="utf-8")
    logger.info("Wrote generated-tests manifest (%d files) to %s", len(generated), GENERATED_MANIFEST_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
