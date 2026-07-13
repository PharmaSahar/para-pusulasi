from __future__ import annotations

import os

import pytest

from src.script_lineage_evidence import (
    LineageLinkStatus,
    RetentionMode,
    ScriptCompletenessState,
    ScriptLineageEventType,
    ScriptSourceStage,
    build_lineage_link_status,
    build_retention_policy_from_env,
    classify_script_completeness,
    compute_evidence_id,
    hash_text,
    normalize_script_text,
    redact_script_excerpt,
    validate_script_lineage_row,
)


def test_enum_values_are_explicit_and_stable() -> None:
    assert ScriptCompletenessState.COMPLETE.value == "COMPLETE"
    assert ScriptSourceStage.FACT_CHECK_REGENERATION.value == "FACT_CHECK_REGENERATION"
    assert LineageLinkStatus.AMBIGUOUS.value == "AMBIGUOUS"
    assert ScriptLineageEventType.SCRIPT_CREATED.value == "SCRIPT_CREATED"


def test_normalized_hash_is_deterministic() -> None:
    left = hash_text(normalize_script_text("Merhaba  Dunya\n"))
    right = hash_text(normalize_script_text("merhaba dunya"))
    assert left == right


def test_compute_evidence_id_is_deterministic() -> None:
    a = compute_evidence_id(
        event_type=ScriptLineageEventType.SCRIPT_CREATED,
        content_id="c1",
        run_id="r1",
        script_hash="h1",
        script_version=1,
        generation_attempt=1,
    )
    b = compute_evidence_id(
        event_type=ScriptLineageEventType.SCRIPT_CREATED,
        content_id="c1",
        run_id="r1",
        script_hash="h1",
        script_version=1,
        generation_attempt=1,
    )
    assert a == b


def test_classify_script_completeness_states() -> None:
    assert classify_script_completeness(script_text="x" * 150, has_full_script=True, has_preview=False) == ScriptCompletenessState.COMPLETE
    assert classify_script_completeness(script_text="short", has_full_script=True, has_preview=False) == ScriptCompletenessState.PARTIAL
    assert classify_script_completeness(script_text="preview", has_full_script=False, has_preview=True) == ScriptCompletenessState.PREVIEW_ONLY
    assert classify_script_completeness(script_text="", has_full_script=False, has_preview=False) == ScriptCompletenessState.MISSING
    assert classify_script_completeness(script_text="ignored", has_full_script=True, has_preview=False, invalid=True) == ScriptCompletenessState.INVALID


def test_linkage_status_resolution() -> None:
    assert build_lineage_link_status(content_id="c", run_id="r", planning_context_id="p", blueprint_id="b") == LineageLinkStatus.LINKED
    assert build_lineage_link_status(content_id="c", run_id="r", planning_context_id="", blueprint_id="b") == LineageLinkStatus.PARTIAL
    assert build_lineage_link_status(content_id="c", run_id="r", planning_context_id="", blueprint_id="") == LineageLinkStatus.MISSING
    assert build_lineage_link_status(content_id="", run_id="r", planning_context_id="", blueprint_id="") == LineageLinkStatus.INVALID


def test_retention_policy_default_hash_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCRIPT_LINEAGE_RETENTION_MODE", raising=False)
    policy = build_retention_policy_from_env()
    assert policy.mode == RetentionMode.HASH_ONLY


def test_retention_policy_parses_malformed_as_disabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRIPT_LINEAGE_RETENTION_MODE", "weird")
    policy = build_retention_policy_from_env()
    assert policy.mode == RetentionMode.HASH_ONLY


def test_bounded_excerpt_and_secret_rejection() -> None:
    from src.script_lineage_evidence import ScriptLineageRetentionPolicy

    policy = ScriptLineageRetentionPolicy(mode=RetentionMode.BOUNDED_EXCERPT, excerpt_max_chars=50)
    excerpt = redact_script_excerpt("x" * 120, policy=policy)
    assert excerpt == "x" * 50

    with pytest.raises(ValueError):
        redact_script_excerpt("this includes API_KEY=abcd", policy=policy)


def test_full_local_script_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCRIPT_LINEAGE_RETENTION_MODE", raising=False)
    policy = build_retention_policy_from_env()
    assert policy.mode != RetentionMode.FULL_LOCAL_SCRIPT


def test_validate_row_requires_advisory_only_and_no_pipeline_change() -> None:
    row = {
        "schema_version": "v1",
        "event_type": "SCRIPT_CREATED",
        "evidence_id": "sle_x",
        "content_id": "c",
        "run_id": "r",
        "canonical_channel_id": "ch",
        "content_type": "mixed",
        "topic_hash": "h",
        "script_hash": "h2",
        "normalized_script_hash": "h3",
        "script_length_chars": 10,
        "script_word_count": 2,
        "script_sentence_count": 1,
        "script_completeness_state": "PARTIAL",
        "script_source_stage": "INITIAL_GENERATION",
        "script_version": 1,
        "parent_script_hash": None,
        "supersedes_script_hash": None,
        "generation_attempt": 1,
        "regeneration_reason": None,
        "prompt_metadata_hash": "h4",
        "planning_context_id": None,
        "blueprint_id": None,
        "blueprint_hash": None,
        "experiment_id": None,
        "lineage_link_status": "MISSING",
        "created_at": "2026-07-13T00:00:00+00:00",
        "finalized_at": None,
        "render_consumed": False,
        "shorts_consumed": False,
        "upload_result_linked": False,
        "advisory_only": True,
        "pipeline_output_changed": False,
        "retention_mode": "HASH_ONLY",
        "script_excerpt": None,
    }
    validated = validate_script_lineage_row(row)
    assert validated["pipeline_output_changed"] is False

    bad = dict(row)
    bad["pipeline_output_changed"] = True
    with pytest.raises(ValueError):
        validate_script_lineage_row(bad)
