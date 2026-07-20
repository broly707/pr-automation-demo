import pytest

from scripts.common.retry import RetryExhaustedError, retry_with_backoff


def test_retry_succeeds_after_transient_failures():
    calls = {"count": 0}

    @retry_with_backoff(max_retries=3, base_delay_seconds=0.001)
    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise ValueError("transient")
        return "ok"

    assert flaky() == "ok"
    assert calls["count"] == 3


def test_retry_raises_after_exhausting_attempts():
    @retry_with_backoff(max_retries=2, base_delay_seconds=0.001)
    def always_fails():
        raise ValueError("permanent")

    with pytest.raises(RetryExhaustedError):
        always_fails()


def test_retry_only_catches_specified_exceptions():
    @retry_with_backoff(max_retries=2, base_delay_seconds=0.001, retryable_exceptions=(ValueError,))
    def raises_type_error():
        raise TypeError("not retryable")

    with pytest.raises(TypeError):
        raises_type_error()
