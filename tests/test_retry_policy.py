from __future__ import annotations

from src.retry_policy import (
    NON_RETRYABLE_CONTENT_QUALITY,
    NON_RETRYABLE_SAFETY_BLOCK,
    RETRYABLE_WITH_BACKOFF,
    classify_retry_decision,
    compute_backoff_delay,
)


class ProductionSafetyGateBlocked(RuntimeError):
    pass


def test_safety_block_is_not_retryable():
    exc = ProductionSafetyGateBlocked("blocked")
    decision = classify_retry_decision(error_text=str(exc), exc=exc, stage="upload")
    assert decision.classification == NON_RETRYABLE_SAFETY_BLOCK
    assert decision.retryable is False


def test_domain_failure_is_not_retryable():
    decision = classify_retry_decision(error_text="topic_domain_blocked:no_valid_candidate", exc=RuntimeError("x"), stage="render")
    assert decision.classification == NON_RETRYABLE_CONTENT_QUALITY
    assert decision.retryable is False


def test_timeout_failure_uses_backoff():
    decision = classify_retry_decision(error_text="timeout contacting upstream", exc=RuntimeError("timeout"), stage="upload")
    assert decision.classification == RETRYABLE_WITH_BACKOFF
    assert decision.retryable is True
    assert compute_backoff_delay(base_delay_seconds=2.0, attempt=2, stage="upload") > 2.0