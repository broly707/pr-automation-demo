"""
Loads config/pipeline.yml once per process and exposes it as a plain dict.

Design notes:
- Single Responsibility: this module does exactly one thing - load and cache
  configuration. It knows nothing about GitHub, Groq, or Gradle.
- Values can be overridden at run time via environment variables of the form
  PIPELINE_<SECTION>_<KEY> (uppercased, dots -> underscores) for the rare
  cases where CI needs to override config without editing the YAML file
  (e.g. a repo-specific IOS_SCHEME variable set in GitHub Actions).
"""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any, Dict

import yaml

_DEFAULT_CONFIG_PATH = Path(
    os.environ.get("PIPELINE_CONFIG_PATH", "config/pipeline.yml")
)


@functools.lru_cache(maxsize=1)
def _load_raw(config_path: str) -> Dict[str, Any]:
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Pipeline config not found at '{path}'. "
            "Run scripts from the repository root, or set PIPELINE_CONFIG_PATH."
        )
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def get_config(config_path: str | None = None) -> Dict[str, Any]:
    """Return the parsed pipeline.yml contents (cached after first call)."""
    return _load_raw(config_path or str(_DEFAULT_CONFIG_PATH))


def get_env_override(section: str, key: str, default: str | None = None) -> str | None:
    """Look up PIPELINE_<SECTION>_<KEY> as an escape hatch for repo-specific tuning."""
    env_key = f"PIPELINE_{section.upper()}_{key.upper()}"
    return os.environ.get(env_key, default)
