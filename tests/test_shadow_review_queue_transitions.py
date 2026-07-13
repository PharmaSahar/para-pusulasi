from __future__ import annotations

import pytest

from src.shadow_review_queue import ReviewQueueTransitionError, validate_status_transition


@pytest.mark.parametrize(
    "from_status,to_status",
    [
        ("OPEN", "IN_REVIEW"),
        ("OPEN", "DISMISSED"),
        ("OPEN", "RESOLVED"),
        ("OPEN", "SUPERSEDED"),
        ("IN_REVIEW", "RESOLVED"),
        ("IN_REVIEW", "DISMISSED"),
        ("IN_REVIEW", "SUPERSEDED"),
    ],
)
def test_allowed_transitions(from_status: str, to_status: str) -> None:
    validate_status_transition(review_item_id="rq_1", from_status=from_status, to_status=to_status)


@pytest.mark.parametrize(
    "from_status,to_status",
    [
        ("RESOLVED", "OPEN"),
        ("DISMISSED", "IN_REVIEW"),
        ("SUPERSEDED", "OPEN"),
        ("INVALID", "RESOLVED"),
    ],
)
def test_disallowed_transitions_raise_structured_error(from_status: str, to_status: str) -> None:
    with pytest.raises(ReviewQueueTransitionError) as exc:
        validate_status_transition(review_item_id="rq_2", from_status=from_status, to_status=to_status)

    payload = exc.value.to_dict()
    assert payload["error"] == "invalid_transition"
    assert payload["from_status"] == from_status
    assert payload["to_status"] == to_status
