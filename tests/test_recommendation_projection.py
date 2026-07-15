from __future__ import annotations

from src.recommendation_contract import build_recommendation_record
from src.recommendation_projection import build_recommendation_projection_from_rows
from tests.recommendation_fixtures import BASE_TIME, base_recommendation_payload


def _build(payload: dict[str, object], *, created_at: str = BASE_TIME) -> dict[str, object]:
    return build_recommendation_record(
        payload,
        created_by="tester",
        source_module="tests.test_recommendation_projection",
        source_version="1.0",
        created_at=created_at,
    )


def test_projection_counts_and_identity_are_deterministic() -> None:
    first = _build(base_recommendation_payload())

    second_payload = base_recommendation_payload()
    second_payload["decision_id"] = "dec_002"
    second_payload["recommendation_policy_status"] = "REVIEW_REQUIRED"
    second_payload["advisory_recommendation"] = {
        "title_variant": "Option B",
        "reasoning": "requires manual approval",
    }
    second = _build(second_payload, created_at="2026-07-15T16:01:00+00:00")

    projection_one = build_recommendation_projection_from_rows([first, second])
    projection_two = build_recommendation_projection_from_rows([first, second])

    assert projection_one == projection_two
    assert projection_one["state_counts"]["ADVISORY_RECOMMENDATION"] == 1
    assert projection_one["state_counts"]["HUMAN_REVIEW_REQUIRED"] == 1
    assert projection_one["policy_status_counts"]["ALLOW"] == 1
    assert projection_one["policy_status_counts"]["REVIEW_REQUIRED"] == 1
    assert projection_one["recommendation_eligible_count"] == 2
    assert projection_one["human_review_required_count"] == 2
    assert projection_one["projection_identity"].startswith("rcp_")
    assert projection_one["projection_hash"].startswith("rcph_")
