from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.recommendation_store import (
    RecommendationCorruptionError,
    RecommendationStore,
)
from tests.recommendation_fixtures import BASE_TIME, base_recommendation_payload


def _append_once(store: RecommendationStore) -> None:
    result = store.append_recommendation_event(
        base_recommendation_payload(),
        created_by="tester",
        source_module="tests.test_recommendation_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True


def test_append_duplicate_and_replay(tmp_path: Path) -> None:
    path = tmp_path / "recommendation_governance.jsonl"
    store = RecommendationStore(recommendation_path=path)

    first = store.append_recommendation_event(
        base_recommendation_payload(),
        created_by="tester",
        source_module="tests.test_recommendation_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert first.appended is True

    duplicate = store.append_recommendation_event(
        base_recommendation_payload(),
        created_by="tester",
        source_module="tests.test_recommendation_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert duplicate.appended is False
    assert duplicate.duplicate is True
    assert duplicate.reason == "exact_duplicate"

    rows = store.get_rows()
    assert len(rows) == 1

    projection, diagnostics = store.replay()
    assert diagnostics.malformed_rows == 0
    assert projection["state_counts"]["ADVISORY_RECOMMENDATION"] == 1


def test_conflicting_duplicate_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "recommendation_governance.jsonl"
    store = RecommendationStore(recommendation_path=path)
    _append_once(store)

    payload = base_recommendation_payload()
    payload["recommendation_policy_status"] = "REVIEW_REQUIRED"
    payload["advisory_recommendation"] = {"title_variant": "Changed"}

    result = store.append_recommendation_event(
        payload,
        created_by="tester",
        source_module="tests.test_recommendation_store",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.conflict is True
    assert result.reason == "conflicting_duplicate"


def test_corrupted_history_blocks_append(tmp_path: Path) -> None:
    path = tmp_path / "recommendation_governance.jsonl"
    path.write_text("{\"bad\":\"row\"}\n", encoding="utf-8")
    store = RecommendationStore(recommendation_path=path)

    with pytest.raises(RecommendationCorruptionError, match="corrupt_recommendation_governance"):
        store.append_recommendation_event(
            base_recommendation_payload(),
            created_by="tester",
            source_module="tests.test_recommendation_store",
            source_version="1.0",
            created_at=BASE_TIME,
        )


def test_verify_hash_chain_reports_valid(tmp_path: Path) -> None:
    path = tmp_path / "recommendation_governance.jsonl"
    store = RecommendationStore(recommendation_path=path)
    _append_once(store)

    chain = store.verify_hash_chain()
    assert chain["valid"] is True
    assert chain["row_count"] == 1
    assert chain["issues"] == []


def test_partial_trailing_line_detected(tmp_path: Path) -> None:
    path = tmp_path / "recommendation_governance.jsonl"
    store = RecommendationStore(recommendation_path=path)
    _append_once(store)

    text = path.read_text(encoding="utf-8").rstrip("\n")
    path.write_text(text + "\n" + "{\"broken\"", encoding="utf-8")

    with pytest.raises(RecommendationCorruptionError):
        store.get_rows()

    with pytest.raises(RecommendationCorruptionError):
        RecommendationStore(recommendation_path=path).replay()

    _rows, diagnostics = RecommendationStore(recommendation_path=path)._load()
    assert diagnostics.partial_trailing_rows >= 1
