import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.experiment_registry import (
    build_experiment_id,
    create_experiment,
    get_experiment,
    list_experiments,
    load_experiment_events,
    update_experiment_status,
)


def _base_metadata():
    return {
        "hypothesis": "v2 thumbnail policy increases ctr",
        "variant": {"control": "thumbnail_v1", "treatment": "thumbnail_v2"},
        "randomization_unit": "video",
        "stratification": ["channel_id", "topic_cluster"],
        "start_date": "2026-07-10",
        "end_date": "2026-07-17",
        "kpi": {"primary": "ctr", "guardrails": ["watch_time"]},
        "minimum_sample": {"impressions": 10000, "min_days": 7},
        "significance_method": "frequentist_95_confidence",
    }


def test_build_experiment_id_is_uuid_hex_and_unique():
    first = build_experiment_id()
    second = build_experiment_id()

    assert first != second
    assert len(first) == 32
    assert len(second) == 32
    uuid.UUID(hex=first)
    uuid.UUID(hex=second)


def test_create_experiment_appends_one_jsonl_line_and_can_list(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"

    created = create_experiment(
        _base_metadata(),
        registry_path=registry_path,
        created_by="pipeline",
        schema_version="1.0",
    )

    assert registry_path.exists()
    lines = registry_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    event = json.loads(lines[0])
    assert event["event_type"] == "experiment_created"
    assert event["payload"]["status"] == "draft"
    assert event["payload"]["schema_version"] == "1.0"
    assert event["payload"]["registry_version"] == "1.0"
    assert event["payload"]["created_by"] == "pipeline"
    assert event["registry_version"] == "1.0"

    listed = list_experiments(registry_path=registry_path)
    assert len(listed) == 1
    assert listed[0]["experiment_id"] == created["experiment_id"]


def test_load_and_get_experiment_return_latest_snapshot(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    created = create_experiment(_base_metadata(), registry_path=registry_path)

    update_experiment_status(
        created["experiment_id"],
        "active",
        registry_path=registry_path,
        created_by="pipeline",
    )

    events = load_experiment_events(registry_path=registry_path)
    assert len(events) == 2

    latest = get_experiment(created["experiment_id"], registry_path=registry_path)
    assert latest is not None
    assert latest["status"] == "active"


def test_status_transition_and_append_only_history(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    created = create_experiment(_base_metadata(), registry_path=registry_path)

    first_line_before = registry_path.read_text(encoding="utf-8").splitlines()[0]

    update_experiment_status(created["experiment_id"], "active", registry_path=registry_path)
    completed = update_experiment_status(
        created["experiment_id"],
        "completed",
        registry_path=registry_path,
        winner="treatment",
    )

    assert completed["winner"] == "treatment"

    lines = registry_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    assert lines[0] == first_line_before

    events = [json.loads(line) for line in lines]
    assert [item["payload"]["status"] for item in events] == ["draft", "active", "completed"]


def test_invalid_transition_is_rejected(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    created = create_experiment(_base_metadata(), registry_path=registry_path)

    with pytest.raises(ValueError):
        update_experiment_status(created["experiment_id"], "completed", registry_path=registry_path)


def test_winner_cannot_be_set_before_completed(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    created = create_experiment(_base_metadata(), registry_path=registry_path)

    with pytest.raises(ValueError):
        update_experiment_status(
            created["experiment_id"],
            "active",
            registry_path=registry_path,
            winner="treatment",
        )


def test_rollback_status_requires_rolled_back_or_archived(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    created = create_experiment(_base_metadata(), registry_path=registry_path)

    with pytest.raises(ValueError):
        update_experiment_status(
            created["experiment_id"],
            "active",
            registry_path=registry_path,
            rollback_status="triggered",
        )


def test_create_requires_mandatory_metadata_fields(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    metadata = _base_metadata()
    metadata.pop("kpi")

    with pytest.raises(ValueError):
        create_experiment(metadata, registry_path=registry_path)


def test_create_requires_non_empty_schema_version_and_created_by(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"

    with pytest.raises(ValueError):
        create_experiment(_base_metadata(), registry_path=registry_path, schema_version="")

    with pytest.raises(ValueError):
        create_experiment(_base_metadata(), registry_path=registry_path, created_by="")

    with pytest.raises(ValueError):
        create_experiment(_base_metadata(), registry_path=registry_path, registry_version="")


def test_update_requires_non_empty_schema_and_registry_versions(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    created = create_experiment(_base_metadata(), registry_path=registry_path)

    with pytest.raises(ValueError):
        update_experiment_status(created["experiment_id"], "active", registry_path=registry_path, schema_version="")

    with pytest.raises(ValueError):
        update_experiment_status(created["experiment_id"], "active", registry_path=registry_path, registry_version="")


def test_duplicate_experiment_id_raises_clear_error(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    fixed_id = "fixed-id-001"

    create_experiment(_base_metadata(), registry_path=registry_path, experiment_id=fixed_id)

    with pytest.raises(ValueError, match="already exists"):
        create_experiment(_base_metadata(), registry_path=registry_path, experiment_id=fixed_id)
