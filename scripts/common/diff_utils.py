"""
Helpers for keeping what we send to the LLM small, cheap, and within
context limits. Single Responsibility: text shaping only - no HTTP, no I/O
beyond what's passed in.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Iterable, List


@dataclass
class ChangedFile:
    filename: str
    status: str          # added | modified | removed | renamed
    patch: str            # unified diff hunk as returned by GitHub
    additions: int
    deletions: int


def is_excluded(path: str, exclude_globs: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in exclude_globs)


def filter_by_extension(paths: List[str], extensions: Iterable[str]) -> List[str]:
    exts = tuple(extensions)
    return [p for p in paths if p.endswith(exts)]


def truncate(text: str, max_chars: int, marker: str = "\n... [TRUNCATED] ...\n") -> str:
    if len(text) <= max_chars:
        return text
    keep = max_chars - len(marker)
    head = text[: keep // 2]
    tail = text[-(keep - len(head)) :]
    return head + marker + tail


def build_diff_bundle(
    changed_files: List[ChangedFile],
    max_total_chars: int,
    max_chars_per_file: int,
    max_files: int,
) -> str:
    """
    Concatenates per-file diffs into one prompt-ready string, respecting both
    a per-file cap and a global cap so we never blow past context limits or
    send the whole repository - only the actual diff.
    """
    parts: List[str] = []
    total = 0
    for cf in changed_files[:max_files]:
        header = f"### FILE: {cf.filename} ({cf.status}, +{cf.additions}/-{cf.deletions})\n"
        body = truncate(cf.patch or "(no textual diff available - binary or too large)", max_chars_per_file)
        chunk = header + body + "\n\n"
        if total + len(chunk) > max_total_chars:
            parts.append(f"... [remaining {len(changed_files) - len(parts)} files omitted, prompt size cap reached] ...\n")
            break
        parts.append(chunk)
        total += len(chunk)
    return "".join(parts)
