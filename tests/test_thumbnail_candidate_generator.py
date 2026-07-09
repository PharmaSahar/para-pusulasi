from __future__ import annotations

import pytest

from src.thumbnail_candidate_generator import generate_thumbnail_candidates
from src.thumbnail_experiment import validate_unique_variant_ids


def _base_candidates() -> list[dict]:
    return [
        {"thumbnail_path": "channels/egitim_rehberi/output/videos/t_a.jpg", "prompt": "prompt a"},
        {"thumbnail_path": "channels/egitim_rehberi/output/videos/t_b.jpg", "prompt": "prompt b"},
        {"thumbnail_path": "channels/egitim_rehberi/output/videos/t_c.jpg", "prompt": "prompt c"},
    ]


def test_default_ab_candidate_set():
    items = generate_thumbnail_candidates(
        experiment_id="exp_thumb_001",
        channel_id="egitim_rehberi",
        content_id="content_123",
        strategy="prompt_variants",
        candidates=_base_candidates(),
    )

    assert len(items) == 2
    assert [x.variant_id for x in items] == ["var_0001", "var_0002"]
    assert [x.variant_label for x in items] == ["A", "B"]


def test_custom_count_three_generates_abc():
    items = generate_thumbnail_candidates(
        experiment_id="exp_thumb_001",
        channel_id="egitim_rehberi",
        content_id="content_123",
        strategy="prompt_variants",
        candidates=_base_candidates(),
        count=3,
    )

    assert len(items) == 3
    assert [x.variant_label for x in items] == ["A", "B", "C"]
    assert [x.variant_id for x in items] == ["var_0001", "var_0002", "var_0003"]


@pytest.mark.parametrize("bad_count", [0, -1])
def test_invalid_count_rejection(bad_count):
    with pytest.raises(ValueError, match="invalid_count"):
        generate_thumbnail_candidates(
            experiment_id="exp_thumb_001",
            channel_id="egitim_rehberi",
            content_id="content_123",
            strategy="prompt_variants",
            candidates=_base_candidates(),
            count=bad_count,
        )


def test_count_above_label_capacity_rejected():
    with pytest.raises(ValueError, match="count_exceeds_supported_labels"):
        generate_thumbnail_candidates(
            experiment_id="exp_thumb_001",
            channel_id="egitim_rehberi",
            content_id="content_123",
            strategy="prompt_variants",
            candidates=_base_candidates() * 10,
            count=27,
        )


@pytest.mark.parametrize(
    "field,kwargs",
    [
        ("experiment_id", {"experiment_id": ""}),
        ("channel_id", {"channel_id": ""}),
        ("content_id", {"content_id": ""}),
        ("strategy", {"strategy": ""}),
    ],
)
def test_missing_required_input_rejection(field, kwargs):
    base = dict(
        experiment_id="exp_thumb_001",
        channel_id="egitim_rehberi",
        content_id="content_123",
        strategy="prompt_variants",
        candidates=_base_candidates(),
    )
    base.update(kwargs)

    with pytest.raises(ValueError, match=f"missing_required_field:{field}"):
        generate_thumbnail_candidates(**base)


def test_generated_candidates_are_model_valid():
    items = generate_thumbnail_candidates(
        experiment_id="exp_thumb_001",
        channel_id="egitim_rehberi",
        content_id="content_123",
        strategy="prompt_variants",
        candidates=_base_candidates(),
    )

    # If model contract is violated, this raises.
    validate_unique_variant_ids(items)


def test_invalid_thumbnail_path_rejected():
    candidates = _base_candidates()
    candidates[0]["thumbnail_path"] = "not_an_image.txt"

    with pytest.raises(ValueError, match="invalid_thumbnail_path"):
        generate_thumbnail_candidates(
            experiment_id="exp_thumb_001",
            channel_id="egitim_rehberi",
            content_id="content_123",
            strategy="prompt_variants",
            candidates=candidates,
        )
