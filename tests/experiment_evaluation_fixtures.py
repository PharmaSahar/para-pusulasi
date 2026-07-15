from __future__ import annotations

from typing import Any


BASE_TIME = "2026-07-15T12:00:00+00:00"


def base_evaluation_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "experiment_id": "exp_eval_001",
        "experiment_version": "5.0.0",
        "assignment_id": "asn_eval_001",
        "assignment_seed": "seed_eval_001",
        "assignment_hash": "ash_eval_001",
        "assignment_version": "v1",
        "randomization_unit": "channel_id",
        "eligibility_snapshot_hash": "esh_eval_001",
        "control_exposure_count": 40,
        "treatment_exposure_count": 40,
        "total_exposure_count": 80,
        "minimum_exposure_count": 20,
        "control_sample_size": 50,
        "treatment_sample_size": 50,
        "total_sample_size": 100,
        "minimum_sample_size": 100,
        "control_metric_value": 0.12,
        "treatment_metric_value": 0.18,
        "observation_window_type": "TWENTY_FOUR_HOURS",
        "observation_window_start": "2026-07-14T00:00:00+00:00",
        "observation_window_end": "2026-07-15T00:00:00+00:00",
        "observation_timestamp": BASE_TIME,
        "outcome_maturity_state": "mature",
        "contamination_severity": "NONE",
        "evidence_lineage_refs": [
            {"ref_type": "assignment", "ref_id": "evl_001"},
            {"ref_type": "outcome", "ref_id": "out_001"},
        ],
        "evidence_lineage_count": 2,
        "evidence_lineage_required_count": 2,
        "evidence_lineage_completeness": 1.0,
        "replay_integrity_verified": True,
    }
    payload.update(overrides)
    return payload
