import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.experiment_registry import create_experiment, get_experiment, list_experiments, load_experiment_events


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


def test_load_experiment_events_skips_corrupted_and_partial_lines(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"

    created = create_experiment(_base_metadata(), registry_path=registry_path, experiment_id="exp-ok-1")
    assert created["experiment_id"] == "exp-ok-1"

    with registry_path.open("a", encoding="utf-8") as fh:
        fh.write("{\n")
        fh.write('"broken_partial_json"\n')
        fh.write(json.dumps({"event_type": "noop", "payload": {"experiment_id": "exp-ok-2", "status": "draft"}}) + "\n")

    events = load_experiment_events(registry_path=registry_path)
    assert len(events) == 2
    assert events[0].get("event_type") == "experiment_created"
    assert events[1].get("event_type") == "noop"



def test_list_and_get_recover_valid_records_when_file_has_bad_lines(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"

    create_experiment(_base_metadata(), registry_path=registry_path, experiment_id="exp-a")
    with registry_path.open("a", encoding="utf-8") as fh:
        fh.write("not-json-at-all\n")
    create_experiment(_base_metadata(), registry_path=registry_path, experiment_id="exp-b")

    items = list_experiments(registry_path=registry_path)
    ids = {item.get("experiment_id") for item in items}

    assert "exp-a" in ids
    assert "exp-b" in ids
    assert get_experiment("exp-a", registry_path=registry_path) is not None
    assert get_experiment("exp-b", registry_path=registry_path) is not None
