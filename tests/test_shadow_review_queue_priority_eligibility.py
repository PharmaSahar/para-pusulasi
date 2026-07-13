from __future__ import annotations

from src.shadow_review_queue import (
    build_queue_reason,
    calculate_queue_priority,
    is_finding_review_eligible,
)


def _row() -> dict:
    return {
        "schema_version": "v2",
        "evaluation_id": "eval_2",
        "run_id": "run_2",
        "content_id": "content_2",
        "channel_id": "ch",
        "content_type": "mixed",
        "checkpoint": "generation",
        "created_at": "2026-07-13T10:00:00+00:00",
        "hashes": {"title_excerpt": "THYAO kesin yukselecek"},
    }


def test_high_severity_always_eligible() -> None:
    finding = {
        "code": "title_script_semantic_consistency",
        "category": "semantic_consistency",
        "severity": "HIGH",
        "confidence": "MEDIUM",
        "affected_artifact": "title_script",
    }
    eligible, reason = is_finding_review_eligible(row=_row(), finding=finding, related_findings=[finding])
    assert eligible is True
    assert reason == "always_eligible_high_severity"


def test_financial_medium_high_confidence_is_always_eligible() -> None:
    finding = {
        "code": "not_priced_in_claim_detection",
        "category": "financial_claim_risk",
        "severity": "MEDIUM",
        "confidence": "HIGH",
        "affected_artifact": "script",
    }
    eligible, reason = is_finding_review_eligible(row=_row(), finding=finding, related_findings=[finding])
    assert eligible is True
    assert reason == "always_eligible_financial_claim"


def test_safe_negation_not_eligible() -> None:
    finding = {
        "code": "guaranteed_return_wording_detection",
        "category": "financial_claim_risk",
        "severity": "MEDIUM",
        "confidence": "HIGH",
        "affected_artifact": "script",
        "details": {"contextual_classification": "negated"},
    }
    eligible, reason = is_finding_review_eligible(row=_row(), finding=finding, related_findings=[finding])
    assert eligible is False
    assert reason == "non_reviewable_safe_educational_negation"


def test_info_unsupported_feature_de_escalates_to_info_priority() -> None:
    finding = {
        "code": "end_screen_recommendation_not_implemented",
        "category": "unsupported_feature",
        "severity": "INFO",
        "confidence": "HIGH",
        "affected_artifact": "seo_discovery",
    }
    priority, _reason = calculate_queue_priority(
        row=_row(),
        finding=finding,
        related_findings=[finding],
        now_iso="2026-07-13T12:00:00+00:00",
    )
    assert priority == "P4_INFO"


def test_correlated_financial_signals_escalate_priority() -> None:
    row = _row()
    findings = [
        {
            "code": "guaranteed_return_wording_detection",
            "category": "financial_claim_risk",
            "severity": "HIGH",
            "confidence": "HIGH",
            "affected_artifact": "script",
        },
        {
            "code": "urgent_trade_pressure_detection",
            "category": "financial_claim_risk",
            "severity": "HIGH",
            "confidence": "HIGH",
            "affected_artifact": "script",
        },
        {
            "code": "pump_style_title_detection",
            "category": "title_quality",
            "severity": "HIGH",
            "confidence": "HIGH",
            "affected_artifact": "title",
        },
    ]
    priority, _reason = calculate_queue_priority(
        row=row,
        finding=findings[0],
        related_findings=findings,
        now_iso="2026-07-13T12:00:00+00:00",
    )
    assert priority in {"P0_CRITICAL", "P1_HIGH"}


def test_queue_reason_mappings() -> None:
    finance = {
        "code": "unverifiable_insider_information_detection",
        "category": "financial_claim_risk",
        "details": {},
    }
    shorts = {
        "code": "shorts_context_without_payoff",
        "category": "shorts_structure",
        "details": {},
    }
    dup = {
        "code": "duplicate_script_detection",
        "category": "duplication",
        "details": {"duplicate_type": "exact_hash"},
    }
    assert build_queue_reason(row=_row(), finding=finance, related_findings=[finance]).startswith("finance_")
    assert build_queue_reason(row=_row(), finding=shorts, related_findings=[shorts]).startswith("shorts_")
    assert build_queue_reason(row=_row(), finding=dup, related_findings=[dup]).startswith("duplication_")
