from __future__ import annotations

from src.outcome_maturity_contract import build_outcome_maturity_record
from src.outcome_snapshot import build_outcome_snapshot_from_rows
from tests.outcome_maturity_fixtures import BASE_TIME, base_outcome_payload


def test_outcome_snapshot_is_deterministic() -> None:
    row_a = build_outcome_maturity_record(
        base_outcome_payload(content_id="content_a", impressions=100, ctr_ratio=0.1),
        created_by="tester",
        source_module="tests.test_outcome_snapshot",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    row_b = build_outcome_maturity_record(
        base_outcome_payload(content_id="content_b", impressions=200, ctr_ratio=0.2),
        created_by="tester",
        source_module="tests.test_outcome_snapshot",
        source_version="1.0",
        created_at=BASE_TIME,
    )

    first = build_outcome_snapshot_from_rows([row_b, row_a])
    second = build_outcome_snapshot_from_rows([row_a, row_b])
    assert first == second
    assert len(first["outcome_snapshot"]) == 2
    assert first["snapshot_identity"].startswith("osm_")
    assert first["snapshot_hash"].startswith("osh_")

    item = first["outcome_snapshot"][0]
    assert "outcome_record_id" in item
    assert "observation_window_type" in item
    assert "kpi_categories" in item
    assert item["kpi_categories"]["exposure"] == ("impressions", "ctr_ratio")
