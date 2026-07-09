from __future__ import annotations

import pytest

from src.thumbnail_selection_policy import (
    select_thumbnail_candidate,
    select_thumbnail_candidate_index,
)


def _candidates() -> list[dict]:
    return [
        {"variant_id": "var_0001", "label": "A"},
        {"variant_id": "var_0002", "label": "B"},
        {"variant_id": "var_0003", "label": "C"},
    ]


def test_first_policy_selects_first_candidate():
    items = _candidates()

    selected = select_thumbnail_candidate(candidates=items, policy="first")

    assert selected is items[0]


def test_round_robin_policy_uses_run_number():
    items = _candidates()

    selected = select_thumbnail_candidate(candidates=items, policy="round_robin", run_number=4)

    assert selected is items[1]


def test_deterministic_hash_policy_is_stable_for_same_content_id():
    items = _candidates()

    first_pick = select_thumbnail_candidate(
        candidates=items,
        policy="deterministic_hash",
        content_id="content_abc_123",
    )
    second_pick = select_thumbnail_candidate(
        candidates=items,
        policy="deterministic_hash",
        content_id="content_abc_123",
    )

    assert first_pick is second_pick


def test_unknown_policy_rejected():
    items = _candidates()

    with pytest.raises(ValueError, match="unknown_selection_policy"):
        select_thumbnail_candidate(candidates=items, policy="weighted")


def test_empty_candidates_rejected():
    with pytest.raises(ValueError, match="empty_candidates"):
        select_thumbnail_candidate(candidates=[], policy="first")


def test_selected_candidate_comes_from_input_list():
    items = _candidates()

    idx = select_thumbnail_candidate_index(candidates=items, policy="deterministic_hash", video_id="video_123")
    selected = select_thumbnail_candidate(candidates=items, policy="deterministic_hash", video_id="video_123")

    assert 0 <= idx < len(items)
    assert selected is items[idx]
    assert selected in items


def test_deterministic_hash_requires_content_or_video_id():
    items = _candidates()

    with pytest.raises(ValueError, match="missing_required_field:content_id_or_video_id"):
        select_thumbnail_candidate(candidates=items, policy="deterministic_hash")


def test_deterministic_hash_can_change_with_different_content_id():
    items = _candidates()
    base_idx = select_thumbnail_candidate_index(
        candidates=items,
        policy="deterministic_hash",
        content_id="content_base",
    )

    found_different = False
    for i in range(1, 500):
        idx = select_thumbnail_candidate_index(
            candidates=items,
            policy="deterministic_hash",
            content_id=f"content_alt_{i}",
        )
        if idx != base_idx:
            found_different = True
            break

    assert found_different is True


def test_deterministic_hash_can_change_with_different_video_id():
    items = _candidates()
    base_idx = select_thumbnail_candidate_index(
        candidates=items,
        policy="deterministic_hash",
        video_id="video_base",
    )

    found_different = False
    for i in range(1, 500):
        idx = select_thumbnail_candidate_index(
            candidates=items,
            policy="deterministic_hash",
            video_id=f"video_alt_{i}",
        )
        if idx != base_idx:
            found_different = True
            break

    assert found_different is True


def test_round_robin_negative_inputs_rejected():
    items = _candidates()

    with pytest.raises(ValueError, match="invalid_index"):
        select_thumbnail_candidate(candidates=items, policy="round_robin", index=-1)

    with pytest.raises(ValueError, match="invalid_run_number"):
        select_thumbnail_candidate(candidates=items, policy="round_robin", run_number=-7)


def test_round_robin_returns_original_object_not_copy():
    items = _candidates()

    selected = select_thumbnail_candidate(candidates=items, policy="round_robin", index=2)

    assert selected is items[2]
