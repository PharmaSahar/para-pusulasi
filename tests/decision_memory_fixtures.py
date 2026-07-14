from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.decision_contract import EvidenceClass, ExplanationBasis
from src.evidence_reference import build_evidence_reference


BASE_TIMESTAMP = "2026-07-13T12:00:00+00:00"
BASE_CREATED_AT = "2026-07-13T12:00:00+00:00"


def canonical_evidence_refs() -> dict[str, list[dict[str, Any]]]:
    return {
        "trend_evidence_refs": [
            build_evidence_reference(
                evidence_type="forward_evidence",
                evidence_id="fev_001",
                source_path="logs/forward_evidence_capture.jsonl",
                availability_state="available",
            ).to_dict()
        ],
        "analytics_evidence_refs": [
            build_evidence_reference(
                evidence_type="analytics_evidence_join",
                evidence_id="aej_001",
                source_path="logs/analytics_evidence_join.jsonl",
                availability_state="available",
            ).to_dict()
        ],
        "cqga_evidence_refs": [
            build_evidence_reference(
                evidence_type="cqga_revalidation",
                evidence_id="cqga_001",
                source_path="logs/cqga_revalidation.jsonl",
                availability_state="unknown",
            ).to_dict()
        ],
        "experiment_assignment_refs": [
            build_evidence_reference(
                evidence_type="experiment_assignment",
                evidence_id="exp_001",
                source_path="logs/experiment_registry.jsonl",
                availability_state="available",
            ).to_dict()
        ],
        "channel_capability_refs": [
            build_evidence_reference(
                evidence_type="channel_capability_state",
                evidence_id="cap_001",
                source_path="config/channel_capability_registry.json",
                availability_state="available",
            ).to_dict()
        ],
        "channel_dna_refs": [
            build_evidence_reference(
                evidence_type="channel_dna",
                evidence_id="dna_001",
                source_path="channels/channel_registry.json",
                availability_state="available",
            ).to_dict()
        ],
        "supporting_evidence_refs": [
            build_evidence_reference(
                evidence_type="script_lineage",
                evidence_id="scr_001",
                source_path="logs/script_lineage.jsonl",
                availability_state="available",
            ).to_dict()
        ],
        "execution_evidence_refs": [
            build_evidence_reference(
                evidence_type="execution_evidence",
                evidence_id="exec_001",
                source_path="logs/execution_events.jsonl",
                availability_state="unknown",
            ).to_dict()
        ],
        "observed_outcome_refs": [
            build_evidence_reference(
                evidence_type="analytics_feedback",
                evidence_id="fb_001",
                source_path="logs/analytics_feedback.jsonl",
                availability_state="unknown",
            ).to_dict()
        ],
        "attribution_result_refs": [
            build_evidence_reference(
                evidence_type="dashboard_evidence",
                evidence_id="dash_001",
                source_path="artifacts/latest/production_dashboard_latest.json",
                availability_state="available",
            ).to_dict()
        ],
    }


def build_decision_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "correlation_id": "corr_001",
        "parent_decision_id": None,
        "supersedes_decision_id": None,
        "channel_id": "chan_001",
        "content_id": "content_001",
        "content_type": "video",
        "decision_type": "content_planning",
        "decision_stage": "planning",
        "decision_timestamp": BASE_TIMESTAMP,
        "topic_candidate_set": ["economy", "markets"],
        "selected_topic": "economy",
        "rejected_topic_candidates": ["markets"],
        "planning_blueprint_ref": build_evidence_reference(
            evidence_type="planning_blueprint_lineage",
            evidence_id="bp_001",
            source_path="logs/planning_blueprint_lineage.jsonl",
            availability_state="available",
        ).to_dict(),
        "planning_blueprint_version": "bp_v1",
        "script_ref": build_evidence_reference(
            evidence_type="script_lineage",
            evidence_id="scr_001",
            source_path="logs/script_lineage.jsonl",
            availability_state="available",
        ).to_dict(),
        "script_version": "scr_v1",
        "thumbnail_candidates": ["thumb_a", "thumb_b"],
        "selected_thumbnail": "thumb_a",
        "rejected_thumbnail_candidates": ["thumb_b"],
        "audience_segment": "retail",
        "channel_capability_version": "cap_v1",
        "channel_dna_version": "dna_v1",
        "prompt_ref": {
            "prompt_ref": "pr_001",
            "prompt_version": "v1",
            "source_module": "tests.decision_memory_fixtures",
        },
        "prompt_version": "v1",
        "model_ref": {
            "model_ref": "model_001",
            "model_provider": "anthropic",
            "model_version": "claude-3",
        },
        "model_provider": "anthropic",
        "model_version": "claude-3",
        "policy_ref": {
            "policy_ref": "policy_001",
            "policy_version": "policy_v1",
            "policy_mode": "advisory",
        },
        "policy_version": "policy_v1",
        "policy_mode": "advisory",
        "title_candidates": ["Market Outlook", "Macro Update"],
        "selected_title": "Market Outlook",
        "rejected_title_candidates": ["Macro Update"],
        "tag_set": ["finance", "markets"],
        "hashtag_set": ["#finance", "#markets"],
        "publish_timing_decision": "09:00",
        "playlist_decision": "playlist_1",
        "shorts_strategy": "none",
        "cross_channel_reuse_decision": "no_reuse",
        "upload_intent": False,
        "recommendation_confidence": 0.87,
        "risk_score": 0.12,
        "human_approval_state": "not_required",
        "reviewer_ref": None,
        "review_timestamp": None,
        "review_reason": None,
        "decision_rationale": "Choose the finance topic based on observed demand.",
        "expected_kpi_impact": {"ctr": 0.02},
        "uncertainty_reasons": ["market volatility"],
        "fallback_status": None,
        "final_execution_status": None,
        "rollback_state": None,
        "rollback_reason": None,
        "created_by": "tester",
        "source_module": "tests.test_decision_contract",
        "source_version": "1.0",
        "decision_state": "draft",
        "decision_explanation": {
            "summary": "Choose the finance topic based on observed demand.",
            "selected_candidate_reason": "Highest observed demand.",
            "rejected_candidate_reasons": ["Markets topic is broader"],
            "supporting_evidence_refs": [
                build_evidence_reference(
                    evidence_type="forward_evidence",
                    evidence_id="fev_001",
                    source_path="logs/forward_evidence_capture.jsonl",
                    availability_state="available",
                ).to_dict()
            ],
            "expected_kpi_impact": {"ctr": 0.02},
            "confidence": 0.87,
            "uncertainty_reasons": ["market volatility"],
            "fallback_reason": None,
            "risk_factors": ["trend fatigue"],
            "human_review_requirement": False,
            "evidence_basis": ExplanationBasis.OBSERVATIONAL_EVIDENCE.value,
            "evidence_class": EvidenceClass.OBSERVATIONAL.value,
            "decision_basis": ExplanationBasis.OBSERVATIONAL_EVIDENCE.value,
        },
    }
    for key, value in canonical_evidence_refs().items():
        payload[key] = value
    payload.update(deepcopy(overrides))
    return payload
