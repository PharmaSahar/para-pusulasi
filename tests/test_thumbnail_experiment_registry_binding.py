from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.thumbnail_experiment import create_thumbnail_variant
from src.thumbnail_experiment_registry_binding import (
    THUMBNAIL_BINDING_EVENT_TYPE,
    register_thumbnail_variant_bindings,
)


def _candidate(
    *,
    experiment_id: str,
    variant_id: str,
    variant_label: str,
    content_id: str | None = "content_123",
    video_id: str | None = None,
):
    return create_thumbnail_variant(
        experiment_id=experiment_id,
        variant_id=variant_id,
        variant_label=variant_label,
        channel_id="egitim_rehberi",
        content_id=content_id,
        video_id=video_id,
        thumbnail_path=f"channels/egitim_rehberi/output/videos/{variant_id}.jpg",
        prompt=f"prompt {variant_label}",
        strategy="prompt_variants",
    )


def test_candidate_set_written_to_registry(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    items = [
        _candidate(experiment_id="exp_thumb_001", variant_id="var_0001", variant_label="A"),
        _candidate(experiment_id="exp_thumb_001", variant_id="var_0002", variant_label="B"),
    ]

    events = register_thumbnail_variant_bindings(
        experiment_id="exp_thumb_001",
        candidates=items,
        registry_path=registry_path,
    )

    assert len(events) == 2

    lines = registry_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["event_type"] == THUMBNAIL_BINDING_EVENT_TYPE
    assert first["experiment_id"] == "exp_thumb_001"
    assert first["variant_id"] == "var_0001"
    assert first["variant_label"] == "A"
    assert first["channel_id"] == "egitim_rehberi"
    assert first["content_id"] == "content_123"
    assert first["thumbnail_path"].endswith("var_0001.jpg")
    assert first["schema_version"] == "1.0"
    assert first["registry_version"] == "1.0"


def test_binding_event_has_distinct_registry_version(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    item = _candidate(experiment_id="exp_thumb_001", variant_id="var_0001", variant_label="A")

    events = register_thumbnail_variant_bindings(
        experiment_id="exp_thumb_001",
        candidates=[item],
        registry_path=registry_path,
        registry_version="2.1",
    )

    assert len(events) == 1
    assert events[0]["schema_version"] == "1.0"
    assert events[0]["registry_version"] == "2.1"


def test_duplicate_binding_rejected(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    item = _candidate(experiment_id="exp_thumb_001", variant_id="var_0001", variant_label="A")

    register_thumbnail_variant_bindings(
        experiment_id="exp_thumb_001",
        candidates=[item],
        registry_path=registry_path,
    )

    with pytest.raises(ValueError, match="duplicate_binding_exists"):
        register_thumbnail_variant_bindings(
            experiment_id="exp_thumb_001",
            candidates=[item],
            registry_path=registry_path,
        )


def test_missing_required_candidate_rejected(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    item = _candidate(
        experiment_id="exp_thumb_001",
        variant_id="var_0001",
        variant_label="A",
        content_id=None,
        video_id=None,
    )

    with pytest.raises(ValueError, match="missing_required_field:content_id_or_video_id"):
        register_thumbnail_variant_bindings(
            experiment_id="exp_thumb_001",
            candidates=[item],
            registry_path=registry_path,
        )


def test_append_only_behavior_preserved(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    first = _candidate(experiment_id="exp_thumb_001", variant_id="var_0001", variant_label="A")
    second = _candidate(experiment_id="exp_thumb_001", variant_id="var_0002", variant_label="B")

    register_thumbnail_variant_bindings(
        experiment_id="exp_thumb_001",
        candidates=[first],
        registry_path=registry_path,
    )

    first_line_before = registry_path.read_text(encoding="utf-8").splitlines()[0]

    register_thumbnail_variant_bindings(
        experiment_id="exp_thumb_001",
        candidates=[second],
        registry_path=registry_path,
    )

    lines = registry_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0] == first_line_before
