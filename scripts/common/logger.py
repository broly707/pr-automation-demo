"""
Centralized logging configuration.

Every script calls get_logger(__name__) instead of configuring logging
itself, so log format/level stay consistent across the whole pipeline and
can be tuned in one place (config/pipeline.yml -> logging).
"""
from __future__ import annotations

import logging
import sys
import threading

from scripts.common.config_loader import get_config

_lock = threading.Lock()
_configured = False


def _configure_root() -> None:
    global _configured
    with _lock:
        if _configured:
            return
        cfg = get_config()
        level_name = cfg.get("logging", {}).get("level", "INFO")
        fmt = cfg.get("logging", {}).get(
            "format", "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )
        level = getattr(logging, str(level_name).upper(), logging.INFO)

        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(logging.Formatter(fmt))

        root = logging.getLogger()
        root.setLevel(level)
        # Avoid duplicate handlers if this module is imported multiple times
        # under different module names during a single process.
        if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
            root.addHandler(handler)

        _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger with pipeline-wide configuration applied."""
    _configure_root()
    return logging.getLogger(name)
