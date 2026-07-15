from __future__ import annotations

BASE_TIME = "2026-07-15T16:00:00+00:00"


def base_recommendation_payload() -> dict[str, object]:
    return {
        "decision_id": "dec_001",
        "learning_record_id": "lr_001",
        "outcome_record_id": "otr_001",
        "lifecycle_id": "asn_001",
        "evaluation_id": "evr_001",
        "confidence_id": "scid_001",
        "attribution_record_id": "car_001",
        "model_version_ref": "model:v3.2",
        "prompt_version_ref": "prompt:v1.7",
        "policy_version_ref": "policy:v2.4",
        "feature_lineage_refs": [
            {"ref_type": "decision", "ref_id": "dec_001"},
            {"ref_type": "evaluation", "ref_id": "evr_001"},
            {"ref_type": "attribution", "ref_id": "car_001"},
        ],
        "lifecycle_state": "stable",
        "evaluation_state": "VALIDATED_RESULT",
        "confidence_state": "STATISTICALLY_SUPPORTED",
        "attribution_state": "CAUSALLY_SUPPORTED",
        "outcome_maturity_state": "mature",
        "recommendation_policy_status": "ALLOW",
        "lineage_complete": True,
        "upstream_records_resolved": True,
        "contamination_state": "NONE",
        "replay_integrity": True,
        "evidence_is_synthetic": False,
        "invalidation_reasons": [],
        "advisory_recommendation": {
            "title_variant": "Option A",
            "thumbnail_variant": "Thumb 3",
            "playlist_hint": "macro-finance",
            "reasoning": "causal support with stable window",
            "confidence_note": "advisory-only, human review required",
        },
    }
