from __future__ import annotations

from src.statistical_confidence_contract import build_statistical_confidence_record
from src.statistical_confidence_projection import build_statistical_confidence_projection_from_rows
from tests.statistical_confidence_fixtures import BASE_TIME, base_confidence_payload


def test_projection_is_deterministic_and_counts_states() -> None:
    first = build_statistical_confidence_record(
        base_confidence_payload(),
        created_by="tester",
        source_module="tests.test_statistical_confidence_projection",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    second = build_statistical_confidence_record(
        base_confidence_payload(
            sample_size=1000,
            treatment_size=500,
            control_size=500,
            effect_size_absolute=0.01,
            effect_size_relative=0.01,
        ),
        created_by="tester",
        source_module="tests.test_statistical_confidence_projection",
        source_version="1.0",
        created_at=BASE_TIME,
    )

    projection1 = build_statistical_confidence_projection_from_rows([second, first])
    projection2 = build_statistical_confidence_projection_from_rows([first, second])

    assert projection1 == projection2
    assert projection1["state_counts"]["STATISTICALLY_SUPPORTED"] == 1
    assert projection1["state_counts"]["DIRECTIONAL_SIGNAL"] == 1
    assert projection1["projection_identity"]
    assert projection1["projection_hash"]
