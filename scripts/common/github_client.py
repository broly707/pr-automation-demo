"""
Thin wrapper around the GitHub REST API used across the pipeline.

Handles:
- Fetching PR diff / changed files
- Upserting a single PR comment (find-by-marker, update instead of spamming)
- Creating Check Runs (so branch protection can require a specific check name)
- Reading repo/PR context from the GITHUB_* environment variables that
  GitHub Actions injects automatically.

Auth: reads GITHUB_TOKEN from the environment. Never logs the token value.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from scripts.common.logger import get_logger
from scripts.common.retry import retry_with_backoff

logger = get_logger(__name__)

GITHUB_API_URL = os.environ.get("GITHUB_API_URL", "https://api.github.com")

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GitHubApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class PullRequestContext:
    owner: str
    repo: str
    pr_number: int
    head_sha: str
    head_ref: str
    base_ref: str

    @staticmethod
    def from_env() -> "PullRequestContext":
        """
        Reads standard GitHub Actions env vars. Expects the calling workflow
        to export PR_NUMBER, HEAD_SHA, HEAD_REF, BASE_REF explicitly (set in
        the reusable workflow's `env:` block) since these aren't always
        directly available depending on trigger/event type.
        """
        repo_full = os.environ["GITHUB_REPOSITORY"]  # "owner/repo"
        owner, repo = repo_full.split("/", 1)
        return PullRequestContext(
            owner=owner,
            repo=repo,
            pr_number=int(os.environ["PR_NUMBER"]),
            head_sha=os.environ["HEAD_SHA"],
            head_ref=os.environ["HEAD_REF"],
            base_ref=os.environ["BASE_REF"],
        )


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self._token = token or os.environ.get("GITHUB_TOKEN")
        if not self._token:
            raise GitHubApiError(
                "GITHUB_TOKEN is not set. It must be passed via GitHub Actions "
                "secrets, never hardcoded."
            )
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    # ------------------------------------------------------------------ #
    # Internal request helper
    # ------------------------------------------------------------------ #
    @retry_with_backoff(
        max_retries=4,
        base_delay_seconds=2.0,
        retryable_exceptions=(requests.RequestException, GitHubApiError),
    )
    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{GITHUB_API_URL}{path}"
        resp = self._session.request(method, url, timeout=30, **kwargs)
        if resp.status_code in _RETRYABLE_STATUS_CODES:
            raise GitHubApiError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 400:
            raise GitHubApiError(
                f"{method} {path} failed with {resp.status_code}: {resp.text[:500]}"
            )
        return resp

    # ------------------------------------------------------------------ #
    # Pull request data
    # ------------------------------------------------------------------ #
    def get_changed_files(self, ctx: PullRequestContext) -> List[Dict[str, Any]]:
        """Returns the raw GitHub 'files' payload (filename, status, patch, etc)."""
        files: List[Dict[str, Any]] = []
        page = 1
        while True:
            resp = self._request(
                "GET",
                f"/repos/{ctx.owner}/{ctx.repo}/pulls/{ctx.pr_number}/files",
                params={"per_page": 100, "page": page},
            )
            batch = resp.json()
            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return files

    # ------------------------------------------------------------------ #
    # PR comments (upsert by hidden marker so we don't spam the timeline)
    # ------------------------------------------------------------------ #
    def upsert_pr_comment(self, ctx: PullRequestContext, marker: str, body: str) -> None:
        existing_id = self._find_comment_id(ctx, marker)
        if existing_id is None:
            logger.info("Creating new PR comment on #%d", ctx.pr_number)
            self._request(
                "POST",
                f"/repos/{ctx.owner}/{ctx.repo}/issues/{ctx.pr_number}/comments",
                json={"body": body},
            )
        else:
            logger.info("Updating existing PR comment %d on #%d", existing_id, ctx.pr_number)
            self._request(
                "PATCH",
                f"/repos/{ctx.owner}/{ctx.repo}/issues/comments/{existing_id}",
                json={"body": body},
            )

    def _find_comment_id(self, ctx: PullRequestContext, marker: str) -> Optional[int]:
        page = 1
        while True:
            resp = self._request(
                "GET",
                f"/repos/{ctx.owner}/{ctx.repo}/issues/{ctx.pr_number}/comments",
                params={"per_page": 100, "page": page},
            )
            batch = resp.json()
            for comment in batch:
                if marker in comment.get("body", ""):
                    return comment["id"]
            if len(batch) < 100:
                return None
            page += 1

    # ------------------------------------------------------------------ #
    # Check Runs (for branch protection: "Require status checks to pass")
    # ------------------------------------------------------------------ #
    def create_check_run(
        self,
        ctx: PullRequestContext,
        name: str,
        conclusion: str,
        title: str,
        summary: str,
        status: str = "completed",
    ) -> None:
        """
        conclusion: success | failure | neutral | cancelled | timed_out | action_required
        Repositories add this check's `name` to Settings -> Branches ->
        Required status checks to make it merge-blocking.
        """
        payload = {
            "name": name,
            "head_sha": ctx.head_sha,
            "status": status,
            "conclusion": conclusion,
            "output": {"title": title, "summary": summary[:65000]},
        }
        self._request(
            "POST", f"/repos/{ctx.owner}/{ctx.repo}/check-runs", json=payload
        )
        logger.info("Published check run '%s' with conclusion=%s", name, conclusion)
