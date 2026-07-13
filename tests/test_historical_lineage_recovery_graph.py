from __future__ import annotations

from src.historical_lineage_recovery import _build_recovery_graph_definition


def test_recovery_graph_contains_only_allowed_priority_sources() -> None:
    graph = _build_recovery_graph_definition()
    assert graph["edge_priority"] == [
        "explicit_ids",
        "canonical_hashes",
        "ownership_linkage",
        "content_id_plus_run_id",
        "validated_blueprint_hash",
    ]


def test_recovery_graph_forbids_guessing() -> None:
    graph = _build_recovery_graph_definition()
    forbidden = set(graph["forbidden_inference"])
    assert "timestamp_proximity" in forbidden
    assert "title_similarity" in forbidden
    assert "ai_inference" in forbidden
