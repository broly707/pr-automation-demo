"""
Thin client for the Groq API (OpenAI-compatible /chat/completions endpoint).

Handles:
- Auth via GROQ_API_KEY (never logged, never hardcoded)
- Timeouts + retry with backoff for transient failures (429/5xx/timeouts)
- A single `complete()` call returning plain text, so callers don't touch
  HTTP details.
"""
from __future__ import annotations

import os
from typing import Optional

import requests

from scripts.common.logger import get_logger
from scripts.common.retry import retry_with_backoff

logger = get_logger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class GroqApiError(RuntimeError):
    pass


class GroqClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "llama-3.3-70b-versatile",
        timeout_seconds: int = 60,
        max_retries: int = 4,
        retry_backoff_base_seconds: float = 2.0,
    ):
        self._api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self._api_key:
            raise GroqApiError(
                "GROQ_API_KEY is not set. It must be provided via GitHub "
                "Secrets, never hardcoded in workflows or scripts."
            )
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._backoff_base = retry_backoff_base_seconds

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        response_format_json: bool = True,
    ) -> str:
        """Calls Groq chat completions and returns the assistant's raw text content."""

        @retry_with_backoff(
            max_retries=self._max_retries,
            base_delay_seconds=self._backoff_base,
            retryable_exceptions=(requests.RequestException, GroqApiError),
        )
        def _call() -> str:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if response_format_json:
                payload["response_format"] = {"type": "json_object"}

            try:
                resp = requests.post(
                    GROQ_API_URL, headers=headers, json=payload, timeout=self._timeout
                )
            except requests.Timeout as exc:
                raise GroqApiError(f"Groq request timed out: {exc}") from exc

            if resp.status_code in _RETRYABLE_STATUS_CODES:
                raise GroqApiError(
                    f"Groq API transient error {resp.status_code}: {resp.text[:300]}"
                )
            if resp.status_code >= 400:
                raise GroqApiError(
                    f"Groq API error {resp.status_code}: {resp.text[:500]}"
                )

            data = resp.json()
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as exc:
                raise GroqApiError(f"Unexpected Groq response shape: {data}") from exc

        return _call()
