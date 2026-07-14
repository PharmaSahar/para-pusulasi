from __future__ import annotations

from src.learning_feature_projection import build_learning_index_from_rows
from src.learning_record_contract import build_learning_record
from tests.learning_record_fixtures import BASE_TIME, base_learning_payload


def test_learning_index_is_deterministic_and_observed_only() -> None:
    row_a = build_learning_record(
        base_learning_payload(content_id="content_a", impressions=100, views=10),
        created_by="tester",
        source_module="tests.test_learning_feature_projection",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    row_b = build_learning_record(
        base_learning_payload(content_id="content_b", impressions=200, views=40),
        created_by="tester",
        source_module="tests.test_learning_feature_projection",
        source_version="1.0",
        created_at=BASE_TIME,
    )

    first = build_learning_index_from_rows([row_b, row_a])
    second = build_learning_index_from_rows([row_a, row_b])
    assert first == second
    assert len(first["learning_index"]) == 2

    item = first["learning_index"][0]
    assert "learning_record_id" in item
    assert "decision_id" in item
    assert "ctr_ratio" in item
    assert "maturity_state" in item
    assert "recommendation_score" not in item
    assert "predicted_ctr" not in item
