from __future__ import annotations

import pytest

from src.thumbnail_experiment import (
    THUMBNAIL_EXPERIMENT_SCHEMA_VERSION,
    build_ab_variant_set,
    create_thumbnail_variant,
    validate_unique_variant_ids,
)


def test_create_valid_variant():
    item = create_thumbnail_variant(
        experiment_id="exp_thumb_001",
        variant_id="var_0001",
        variant_label="A",
        channel_id="egitim_rehberi",
        content_id="content_123",
        thumbnail_path="channels/egitim_rehberi/output/videos/t_a.jpg",
        prompt="high contrast title panel",
        strategy="manual_ab",
    )

    assert item.experiment_id == "exp_thumb_001"
    assert item.variant_id == "var_0001"
    assert item.variant_label == "A"
    assert item.channel_id == "egitim_rehberi"
    assert item.schema_version == THUMBNAIL_EXPERIMENT_SCHEMA_VERSION


@pytest.mark.parametrize(
    "field,kwargs",
    [
        ("experiment_id", {"experiment_id": ""}),
        ("variant_id", {"variant_id": ""}),
        ("variant_label", {"variant_label": ""}),
        ("channel_id", {"channel_id": ""}),
        ("thumbnail_path", {"thumbnail_path": ""}),
        ("schema_version", {"schema_version": ""}),
    ],
)
def test_missing_required_fields(field, kwargs):
    base = dict(
        experiment_id="exp_thumb_001",
        variant_id="var_0001",
        variant_label="A",
        channel_id="egitim_rehberi",
        content_id="content_123",
        thumbnail_path="channels/egitim_rehberi/output/videos/t_a.jpg",
        prompt="high contrast title panel",
        strategy="manual_ab",
        schema_version=THUMBNAIL_EXPERIMENT_SCHEMA_VERSION,
    )
    base.update(kwargs)

    with pytest.raises(ValueError, match=f"missing_required_field:{field}"):
        create_thumbnail_variant(**base)


def test_duplicate_variant_id_rejected_within_same_experiment():
    a = create_thumbnail_variant(
        experiment_id="exp_thumb_001",
        variant_id="var_0001",
        variant_label="A",
        channel_id="egitim_rehberi",
        content_id="content_123",
        thumbnail_path="channels/egitim_rehberi/output/videos/t_a.jpg",
        prompt="prompt a",
        strategy="manual_ab",
    )
    b = create_thumbnail_variant(
        experiment_id="exp_thumb_001",
        variant_id="var_0001",
        variant_label="B",
        channel_id="egitim_rehberi",
        content_id="content_123",
        thumbnail_path="channels/egitim_rehberi/output/videos/t_b.jpg",
        prompt="prompt b",
        strategy="manual_ab",
    )

    with pytest.raises(ValueError, match="duplicate_variant_id_in_experiment"):
        validate_unique_variant_ids([a, b])


def test_variant_label_rejects_non_enum_values():
    with pytest.raises(ValueError, match="invalid_variant_label"):
        create_thumbnail_variant(
            experiment_id="exp_thumb_001",
            variant_id="var_0003",
            variant_label="control",
            channel_id="egitim_rehberi",
            content_id="content_123",
            thumbnail_path="channels/egitim_rehberi/output/videos/t_x.jpg",
            prompt="prompt x",
            strategy="manual_ab",
        )


def test_schema_version_rejects_unknown_value():
    with pytest.raises(ValueError, match="invalid_schema_version"):
        create_thumbnail_variant(
            experiment_id="exp_thumb_001",
            variant_id="var_0001",
            variant_label="A",
            channel_id="egitim_rehberi",
            content_id="content_123",
            thumbnail_path="channels/egitim_rehberi/output/videos/t_a.jpg",
            prompt="prompt a",
            strategy="manual_ab",
            schema_version="2.0",
        )


def test_variant_id_accepts_contract_format():
    item = create_thumbnail_variant(
        experiment_id="exp_thumb_001",
        variant_id="var_0123",
        variant_label="A",
        channel_id="egitim_rehberi",
        content_id="content_123",
        thumbnail_path="channels/egitim_rehberi/output/videos/t_a.jpg",
        prompt="prompt a",
        strategy="manual_ab",
    )

    assert item.variant_id == "var_0123"


@pytest.mark.parametrize("bad_variant_id", ["abc", "1", "var_a", "var 0001", "VAR_0001", "var_12"])
def test_variant_id_rejects_invalid_format(bad_variant_id):
    with pytest.raises(ValueError, match="invalid_variant_id_format"):
        create_thumbnail_variant(
            experiment_id="exp_thumb_001",
            variant_id=bad_variant_id,
            variant_label="A",
            channel_id="egitim_rehberi",
            content_id="content_123",
            thumbnail_path="channels/egitim_rehberi/output/videos/t_a.jpg",
            prompt="prompt a",
            strategy="manual_ab",
        )


def test_build_ab_variant_set():
    items = build_ab_variant_set(
        experiment_id="exp_thumb_001",
        channel_id="egitim_rehberi",
        content_id="content_123",
        strategy="manual_ab",
        variants={
            "A": {
                "variant_id": "var_0001",
                "thumbnail_path": "channels/egitim_rehberi/output/videos/t_a.jpg",
                "prompt": "prompt a",
            },
            "B": {
                "variant_id": "var_0002",
                "thumbnail_path": "channels/egitim_rehberi/output/videos/t_b.jpg",
                "prompt": "prompt b",
            },
        },
    )

    assert len(items) == 2
    assert {x.variant_label for x in items} == {"A", "B"}
    assert {x.variant_id for x in items} == {"var_0001", "var_0002"}
