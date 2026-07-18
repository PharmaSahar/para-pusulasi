from __future__ import annotations

import hashlib
from dataclasses import dataclass


TRANSIENT_RETRYABLE = "retryable_transient"
RETRYABLE_WITH_BACKOFF = "retryable_with_backoff"
RETRYABLE_AFTER_EXTERNAL_RESET = "retryable_after_external_reset"
NON_RETRYABLE_CONFIGURATION = "non_retryable_configuration"
NON_RETRYABLE_SAFETY_BLOCK = "non_retryable_safety_block"
NON_RETRYABLE_CONTENT_QUALITY = "non_retryable_content_quality_failure"
EXHAUSTED_RETRY = "exhausted_retry"


@dataclass(frozen=True, slots=True)
class RetryDecision:
    classification: str
    retryable: bool
    reason_code: str
    message: str


def classify_retry_decision(*, error_text: str, exc: Exception | None = None, stage: str = "unknown") -> RetryDecision:
    text = str(error_text or "").strip().lower()

    if exc is not None and exc.__class__.__name__ == "ProductionSafetyGateBlocked":
        return RetryDecision(
            classification=NON_RETRYABLE_SAFETY_BLOCK,
            retryable=False,
            reason_code="production_safety_gate_blocked",
            message="Production safety gate blocked the operation.",
        )

    if getattr(exc, "_skip_scheduler_pipeline_retry", False):
        return RetryDecision(
            classification=NON_RETRYABLE_CONTENT_QUALITY,
            retryable=False,
            reason_code="explicit_skip_retry",
            message="Retry explicitly disabled for this failure.",
        )

    if any(token in text for token in (
        "topic_domain_blocked",
        "topic_provenance_collision",
        "channel_dna_mismatch",
        "upload_precheck_blocked",
        "content_quality_blocked",
        "failed_fact_check",
        "automatic_qa_blocked",
    )):
        return RetryDecision(
            classification=NON_RETRYABLE_CONTENT_QUALITY,
            retryable=False,
            reason_code="deterministic_quality_or_domain_failure",
            message="Deterministic quality or domain failure should not retry.",
        )

    if any(token in text for token in (
        "authentication",
        "credential",
        "invalid api key",
        "invalid_request",
        "validation_error",
        "required_env_missing",
        "api_credentials_missing",
        "release_integrity_mismatch",
        "active_deployment_lock",
        "clock_sanity_failed",
        "queue_file_unreadable",
        "writable_directories_unavailable",
    )):
        return RetryDecision(
            classification=NON_RETRYABLE_CONFIGURATION,
            retryable=False,
            reason_code="operator_action_required",
            message="Operator action is required before retrying.",
        )

    if any(token in text for token in (
        "quota",
        "credit balance",
        "provider_circuit_open",
        "global_overload_pause_open",
    )):
        return RetryDecision(
            classification=RETRYABLE_AFTER_EXTERNAL_RESET,
            retryable=False,
            reason_code="external_reset_required",
            message="Retry requires quota reset, cooldown expiry, or provider recovery.",
        )

    if any(token in text for token in (
        "rate limit",
        "ratelimit",
        "http 429",
        "timeout",
        "dns",
        "connection",
        "network",
        "service unavailable",
        "internal server error",
        "http 5",
        "server_error",
        "overloaded",
        "resumable_conflict",
    )):
        return RetryDecision(
            classification=RETRYABLE_WITH_BACKOFF,
            retryable=True,
            reason_code="transient_external_failure",
            message="Transient external failure eligible for bounded retry.",
        )

    return RetryDecision(
        classification=TRANSIENT_RETRYABLE,
        retryable=True,
        reason_code=f"{stage}_retry_fallback",
        message="Fallback retry classification.",
    )


def compute_backoff_delay(*, base_delay_seconds: float, attempt: int, stage: str) -> float:
    exponent = max(0, int(attempt) - 1)
    base = float(base_delay_seconds) * float(2 ** exponent)
    digest = hashlib.sha256(f"{stage}:{attempt}".encode("utf-8")).digest()
    jitter_ratio = 0.85 + ((digest[0] / 255.0) * 0.3)
    return round(base * jitter_ratio, 3)