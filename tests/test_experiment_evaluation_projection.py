from __future__ import annotations

from src.experiment_evaluation_contract import build_experiment_evaluation_record
from src.experiment_evaluation_projection import build_experiment_evaluation_projection_from_rows
from tests.experiment_evaluation_fixtures import BASE_TIME, base_evaluation_payload


def test_projection_is_deterministic_and_counts_states() -> None:
    first = build_experiment_evaluation_record(
        base_evaluation_payload(),
        created_by="tester",
        source_module="tests.test_experiment_evaluation_projection",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    second = build_experiment_evaluation_record(
        base_evaluation_payload(evidence_lineage_completeness=0.5, evidence_lineage_count=1, evidence_lineage_required_count=2),
        created_by="tester",
        source_module="tests.test_experiment_evaluation_projection",
        source_version="1.0",
        created_at=BASE_TIME,
    )

    projection1 = build_experiment_evaluation_projection_from_rows([second, first])
    projection2 = build_experiment_evaluation_projection_from_rows([first, second])

    assert projection1 == projection2
    assert projection1["state_counts"]["VALIDATED_RESULT"] == 1
    assert projection1["state_counts"]["EVALUABLE"] == 1
    assert projection1["projection_identity"]
    assert projection1["projection_hash"]
