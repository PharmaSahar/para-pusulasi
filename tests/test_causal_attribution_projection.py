from __future__ import annotations

from src.causal_attribution_contract import build_causal_attribution_record
from src.causal_attribution_projection import build_causal_attribution_projection_from_rows
from tests.causal_attribution_fixtures import BASE_TIME, base_attribution_payload


def _record(**overrides: object) -> dict[str, object]:
    return build_causal_attribution_record(
        base_attribution_payload(**overrides),
        created_by="tester",
        source_module="tests.test_causal_attribution_projection",
        source_version="1.0",
        created_at=BASE_TIME,
    )


def test_projection_is_deterministic_and_preserves_counts() -> None:
    supported = _record()
    associational = _record(
        randomized_assignment_proven=False,
        assignment_method="observational",
        treatment_exposure_refs=[{"ref_type": "exposure", "ref_id": "exp_t_009"}],
        control_exposure_refs=[{"ref_type": "exposure", "ref_id": "exp_c_009"}],
        treatment_assignment_ref="assignment:treatment:009",
        control_assignment_ref="assignment:control:009",
        outcome_record_id="omr_009",
        correlation_id="corr_009",
        treatment_outcome_ref="outcome:treatment:009",
        control_outcome_ref="outcome:control:009",
    )

    projection_one = build_causal_attribution_projection_from_rows([associational, supported])
    projection_two = build_causal_attribution_projection_from_rows([supported, associational])

    assert projection_one == projection_two
    assert projection_one["state_counts"]["CAUSALLY_SUPPORTED"] == 1
    assert projection_one["state_counts"]["ASSOCIATIONAL_ONLY"] == 1
    assert projection_one["projection_identity"]
    assert projection_one["projection_hash"]


def test_projection_preserves_unknown_false_zero_distinctions() -> None:
    unknown_effect = _record(
        counterfactual_is_observed=False,
        counterfactual_status="UNAVAILABLE",
        treatment_effect_absolute=None,
        treatment_effect_relative=None,
        effect_size_available=False,
        uncertainty_available=False,
    )
    zero_effect = _record(
        treatment_effect_absolute=0.0,
        treatment_effect_relative=0.0,
        treatment_assignment_ref="assignment:treatment:010",
        control_assignment_ref="assignment:control:010",
        correlation_id="corr_010",
        outcome_record_id="omr_010",
        treatment_outcome_ref="outcome:treatment:010",
        control_outcome_ref="outcome:control:010",
        treatment_exposure_refs=[{"ref_type": "exposure", "ref_id": "exp_t_010"}],
        control_exposure_refs=[{"ref_type": "exposure", "ref_id": "exp_c_010"}],
    )

    projection = build_causal_attribution_projection_from_rows([unknown_effect, zero_effect])
    unknown = projection["latest_by_record_id"][unknown_effect["attribution_record_id"]]
    zero = projection["latest_by_record_id"][zero_effect["attribution_record_id"]]

    assert unknown["treatment_effect_absolute"] is None
    assert unknown["effect_size_available"] is False
    assert zero["treatment_effect_absolute"] == 0.0
    assert zero["effect_size_available"] is True
