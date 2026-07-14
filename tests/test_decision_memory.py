from __future__ import annotations

from pathlib import Path

import pytest

from src.decision_contract import DecisionState, build_decision_record
from src.evidence_reference import build_evidence_reference
from src.decision_memory import DecisionMemoryStore, DecisionMemoryTransitionError, build_decision_memory_audit_summary


def _base_payload() -> dict[str, object]:
    return {
        "correlation_id": "corr_001",
        "channel_id": "chan_001",
        "content_id": "content_001",
        "content_type": "video",
        "decision_type": "content_planning",
        "decision_stage": "planning",
        "topic_candidate_set": ["economy", "markets"],
        "selected_topic": "economy",
        "rejected_topic_candidates": ["markets"],
        "trend_evidence_refs": [],
        "audience_segment": "retail",
        "channel_dna_version": "dna_v1",
        "channel_capability_version": "cap_v1",
        "planning_blueprint_ref": None,
        "planning_blueprint_version": None,
        "prompt_ref": None,
        "prompt_version": None,
        "model_ref": None,
        "model_provider": None,
        "model_version": None,
        "script_ref": None,
        "script_version": None,
        "title_candidates": ["Market Outlook"],
        "selected_title": "Market Outlook",
        "rejected_title_candidates": [],
        "thumbnail_candidates": ["thumb_a"],
        "selected_thumbnail": "thumb_a",
        "rejected_thumbnail_candidates": [],
        "description_ref": None,
        "description_version": None,
        "tag_set": ["finance"],
        "hashtag_set": ["#finance"],
        "publish_timing_decision": "09:00",
        "playlist_decision": "playlist_1",
        "shorts_strategy": "none",
        "cross_channel_reuse_decision": "no_reuse",
        "upload_intent": False,
        "experiment_assignment_refs": [],
        "policy_ref": None,
        "policy_version": None,
        "policy_mode": None,
        "recommendation_confidence": 0.87,
        "risk_score": 0.12,
        "human_approval_state": "not_required",
        "reviewer_ref": None,
        "review_timestamp": None,
        "review_reason": None,
        "decision_rationale": "Choose the finance topic based on observed demand.",
        "supporting_evidence_refs": [],
        "rejected_alternative_rationales": [],
        "expected_kpi_impact": {"ctr": 0.02},
        "uncertainty_reasons": [],
        "fallback_status": None,
        "final_execution_status": None,
        "execution_evidence_refs": [],
        "observed_outcome_refs": [],
        "attribution_result_refs": [],
        "rollback_state": None,
        "rollback_reason": None,
        "created_by": "tester",
        "source_module": "tests.test_decision_memory",
        "source_version": "1.0",
        "decision_state": DecisionState.DRAFT.value,
        "decision_explanation": {
            "summary": "Choose the finance topic based on observed demand.",
            "selected_candidate_reason": "Highest observed demand.",
            "rejected_candidate_reasons": ["Markets topic is broader"],
            "supporting_evidence_refs": [
                build_evidence_reference(
                    evidence_type="analytics",
                    evidence_id="analytics_001",
                    source_path="analytics/2026-07-13.jsonl",
                    availability_state="available",
                ).to_dict()
            ],
            "expected_kpi_impact": {"ctr": 0.02},
            "confidence": 0.87,
            "uncertainty_reasons": [],
            "fallback_reason": None,
            "risk_factors": [],
            "human_review_requirement": False,
            "decision_basis": "observational_evidence",
        },
    }


def test_append_replay_and_audit_summary(tmp_path: Path) -> None:
    path = tmp_path / "decision_memory.jsonl"
    store = DecisionMemoryStore(memory_path=path)

    candidate = build_decision_record(_base_payload(), created_by="tester", source_module="tests.test_decision_memory", source_version="1.0")
    result = store.append_decision(
        candidate,
        created_by="tester",
        source_module="tests.test_decision_memory",
        source_version="1.0",
    )

    assert result.appended is True

    rows = store.get_rows()
    assert len(rows) == 1
    projections, diagnostics = store.replay()
    assert diagnostics.malformed_rows == 0
    assert projections["current_state_by_decision_id"][result.decision_id]["decision_id"] == result.decision_id
    assert projections["decision_feature_projection"][0]["evidence_completeness_score"] == 1.0

    summary = build_decision_memory_audit_summary(store=store)
    assert summary["row_count"] == 1
    assert summary["hash_chain"]["valid"] is True


def test_invalid_state_transition_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "decision_memory.jsonl"
    store = DecisionMemoryStore(memory_path=path)

    candidate = build_decision_record(_base_payload(), created_by="tester", source_module="tests.test_decision_memory", source_version="1.0")
    store.append_decision(
        candidate,
        created_by="tester",
        source_module="tests.test_decision_memory",
        source_version="1.0",
    )

    with pytest.raises(DecisionMemoryTransitionError):
        store.append_state_transition(
            candidate["decision_id"],
            DecisionState.EXECUTED,
            created_by="tester",
            source_module="tests.test_decision_memory",
            source_version="1.0",
        )
