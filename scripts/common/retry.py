"""
Generic retry-with-backoff decorator used by github_client.py and
groq_client.py to handle transient network failures (timeouts, 429s, 5xx).
"""
from __future__ import annotations

import functools
import random
import time
from typing import Callable, Iterable, Type, TypeVar

from scripts.common.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class RetryExhaustedError(RuntimeError):
    """Raised when all retry attempts fail; wraps the last exception."""

    def __init__(self, attempts: int, last_exception: BaseException):
        super().__init__(
            f"Operation failed after {attempts} attempts: {last_exception!r}"
        )
        self.last_exception = last_exception


def retry_with_backoff(
    max_retries: int = 3,
    base_delay_seconds: float = 2.0,
    max_delay_seconds: float = 30.0,
    retryable_exceptions: Iterable[Type[BaseException]] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator factory. Retries the wrapped function on the given exception
    types using exponential backoff with jitter. On final failure, raises
    RetryExhaustedError wrapping the last exception (never silently swallows).
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: BaseException | None = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except tuple(retryable_exceptions) as exc:  # type: ignore[arg-type]
                    last_exception = exc
                    if attempt == max_retries:
                        break
                    delay = min(base_delay_seconds * (2 ** (attempt - 1)), max_delay_seconds)
                    delay += random.uniform(0, delay * 0.25)  # jitter
                    logger.warning(
                        "Attempt %d/%d for %s failed (%s). Retrying in %.1fs...",
                        attempt,
                        max_retries,
                        func.__name__,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
            assert last_exception is not None
            raise RetryExhaustedError(max_retries, last_exception) from last_exception

        return wrapper

    return decorator
