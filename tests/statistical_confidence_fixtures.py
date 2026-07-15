from __future__ import annotations

from typing import Any


BASE_TIME = "2026-07-15T13:00:00+00:00"


def base_confidence_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "experiment_id": "exp_conf_001",
        "evaluation_id": "ev_eval_001",
        "observation_window": {
            "window_type": "TWENTY_FOUR_HOURS",
            "start": "2026-07-14T00:00:00+00:00",
            "end": "2026-07-15T00:00:00+00:00",
        },
        "sample_size": 120,
        "treatment_size": 60,
        "control_size": 60,
        "minimum_sample_required": 100,
        "minimum_power_required": 0.8,
        "minimum_detectable_effect": 0.05,
        "effect_size_absolute": 0.08,
        "effect_size_relative": 0.12,
        "confidence_inputs": {
            "comparison_family": "experiment_primary",
            "correction_method": "bonferroni",
            "comparison_count": 1,
            "synthetic_evidence": False,
        },
        "contamination_state": "NONE",
        "maturity_state": "mature",
        "lineage_reference": [
            {"ref_type": "evaluation", "ref_id": "evr_001"},
            {"ref_type": "outcome", "ref_id": "out_001"},
        ],
        "created_at": BASE_TIME,
        "created_by": "tester",
        "source_module": "tests.test_statistical_confidence_contract",
        "source_version": "1.0",
    }
    payload.update(overrides)
    return payload
