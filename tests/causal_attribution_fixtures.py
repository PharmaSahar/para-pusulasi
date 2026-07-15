from __future__ import annotations

from typing import Any


BASE_TIME = "2026-07-15T15:00:00+00:00"


def base_attribution_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "experiment_id": "exp_007",
        "experiment_version": "v3",
        "evaluation_id": "evr_007",
        "confidence_id": "scid_007",
        "decision_id": "dec_007",
        "learning_record_id": "hlr_007",
        "outcome_record_id": "omr_007",
        "assignment_id": "assign_007",
        "correlation_id": "corr_007",
        "channel_id": "channel_007",
        "content_id": "content_007",
        "treatment_variant": "variant_b",
        "control_variant": "variant_a",
        "treatment_assignment_ref": "assignment:treatment:007",
        "control_assignment_ref": "assignment:control:007",
        "treatment_exposure_refs": [
            {"ref_type": "exposure", "ref_id": "exp_t_001"},
        ],
        "control_exposure_refs": [
            {"ref_type": "exposure", "ref_id": "exp_c_001"},
        ],
        "assignment_method": "randomized",
        "randomized_assignment_proven": True,
        "control_group_present": True,
        "treatment_group_present": True,
        "exposure_completeness": True,
        "observation_window": {
            "window_type": "SEVEN_DAYS",
            "start": "2026-07-08T00:00:00+00:00",
            "end": "2026-07-15T00:00:00+00:00",
        },
        "observation_window_type": "SEVEN_DAYS",
        "outcome_maturity_state": "mature",
        "treatment_outcome_ref": "outcome:treatment:007",
        "control_outcome_ref": "outcome:control:007",
        "outcome_completeness": True,
        "confidence_state": "STATISTICALLY_SUPPORTED",
        "sample_sufficiency": True,
        "power_sufficiency": True,
        "multiple_comparison_governed": True,
        "effect_size_available": True,
        "uncertainty_available": True,
        "confounder_set_id": "conf_set_007",
        "declared_confounders": ["seasonality", "inventory_shift"],
        "unresolved_confounders": [],
        "confounder_status": "RESOLVED",
        "confounder_evidence_refs": [
            {"ref_type": "confounder_evidence", "ref_id": "conf_001"},
        ],
        "counterfactual_method": "holdout_control_observed",
        "counterfactual_status": "OBSERVED_CONTROL_OUTCOME",
        "counterfactual_evidence_refs": [
            {"ref_type": "counterfactual", "ref_id": "cf_001"},
        ],
        "counterfactual_is_observed": True,
        "counterfactual_is_synthetic": False,
        "contamination_state": "NONE",
        "contamination_severity": "NONE",
        "lineage_complete": True,
        "replay_integrity": True,
        "evidence_is_synthetic": False,
        "invalidation_reasons": [],
        "treatment_effect_absolute": 0.11,
        "treatment_effect_relative": 0.18,
        "created_at": BASE_TIME,
        "created_by": "tester",
        "source_module": "tests.causal_attribution_fixtures",
        "source_version": "1.0",
    }
    payload.update(overrides)
    return payload
