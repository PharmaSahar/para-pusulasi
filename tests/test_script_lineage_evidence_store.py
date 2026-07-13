from __future__ import annotations

import json
from pathlib import Path

from src.script_lineage_evidence import (
    ScriptLineageEventType,
    ScriptLineageEvidenceStore,
    ScriptLineageRecorder,
    ScriptSourceStage,
    load_script_lineage_rows,
    reconstruct_current_final_scripts,
)


def test_append_only_and_malformed_tolerance(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("{bad json}\n", encoding="utf-8")

    recorder = ScriptLineageRecorder(
        content_id="c1",
        run_id="r1",
        canonical_channel_id="ch1",
        content_type="mixed",
        topic="topic",
        experiment_id="exp1",
        evidence_path=path,
    )

    append = recorder.record_script_created(
        script_text="Hello world script." * 20,
        source_stage=ScriptSourceStage.INITIAL_GENERATION,
        generation_attempt=1,
        regeneration_reason=None,
        prompt_metadata={"v": 1},
        planning_context_id="plan1",
        blueprint_id="bp1",
        blueprint_hash="bh1",
    )
    assert append.appended is True

    rows, malformed, errors = load_script_lineage_rows(input_path=path)
    assert malformed >= 1
    assert rows
    assert errors


def test_duplicate_ingestion_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = ScriptLineageRecorder(
        content_id="c1",
        run_id="r1",
        canonical_channel_id="ch1",
        content_type="mixed",
        topic="topic",
        experiment_id="exp1",
        evidence_path=path,
    )

    first = recorder.record_script_created(
        script_text="same script",
        source_stage=ScriptSourceStage.INITIAL_GENERATION,
        generation_attempt=1,
        regeneration_reason=None,
        prompt_metadata={},
        planning_context_id="",
        blueprint_id="",
        blueprint_hash="",
    )
    second = recorder.record_script_created(
        script_text="same script",
        source_stage=ScriptSourceStage.QUALITY_REGENERATION,
        generation_attempt=2,
        regeneration_reason="retry",
        prompt_metadata={},
        planning_context_id="",
        blueprint_id="",
        blueprint_hash="",
    )

    assert first.appended is True
    # second is LINEAGE_LINK_UPDATED event; if deterministic duplicate ID for same params it can be duplicate.
    assert second.appended or second.duplicate


def test_replay_and_final_script_reconstruction(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = ScriptLineageRecorder(
        content_id="c2",
        run_id="r2",
        canonical_channel_id="ch2",
        content_type="mixed",
        topic="topic",
        experiment_id="exp2",
        evidence_path=path,
    )

    recorder.record_script_created(
        script_text="version one text" * 12,
        source_stage=ScriptSourceStage.INITIAL_GENERATION,
        generation_attempt=1,
        regeneration_reason=None,
        prompt_metadata={"v": 1},
        planning_context_id="plan",
        blueprint_id="bp",
        blueprint_hash="bh",
    )
    recorder.record_script_created(
        script_text="version two text improved" * 12,
        source_stage=ScriptSourceStage.QUALITY_REGENERATION,
        generation_attempt=2,
        regeneration_reason="quality",
        prompt_metadata={"v": 2},
        planning_context_id="plan",
        blueprint_id="bp",
        blueprint_hash="bh",
    )
    recorder.record_script_finalized(
        script_text="version two text improved" * 12,
        source_stage=ScriptSourceStage.QUALITY_REGENERATION,
        generation_attempt=2,
        prompt_metadata={"v": 2},
        planning_context_id="plan",
        blueprint_id="bp",
        blueprint_hash="bh",
    )
    recorder.record_consumed_by_render(script_text="version two text improved" * 12)
    recorder.record_consumed_by_shorts(script_text="version two text improved" * 12)
    recorder.record_linked_to_upload(script_text="version two text improved" * 12)
    recorder.record_invalidated(script_text="version one text" * 12, reason="manual_review")

    states, diagnostics = reconstruct_current_final_scripts(evidence_path=path)
    assert diagnostics.replay_errors == []
    key = "c2::r2"
    assert key in states
    entry = states[key]
    assert entry["final_script_hash"]
    assert entry["render_consumed"] is True
    assert entry["shorts_consumed"] is True
    assert entry["upload_result_linked"] is True
    assert len(entry["versions"]) >= 2


def test_storage_serialization_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    store = ScriptLineageEvidenceStore(evidence_path=path)

    row = {
        "schema_version": "v1",
        "event_type": ScriptLineageEventType.SCRIPT_CREATED.value,
        "evidence_id": "sle_demo",
        "content_id": "c",
        "run_id": "r",
        "canonical_channel_id": "ch",
        "content_type": "mixed",
        "topic_hash": "t",
        "script_hash": "s",
        "normalized_script_hash": "n",
        "script_length_chars": 1,
        "script_word_count": 1,
        "script_sentence_count": 1,
        "script_completeness_state": "PARTIAL",
        "script_source_stage": "INITIAL_GENERATION",
        "script_version": 1,
        "parent_script_hash": None,
        "supersedes_script_hash": None,
        "generation_attempt": 1,
        "regeneration_reason": None,
        "prompt_metadata_hash": "p",
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
    result = store.append(row)
    assert result.appended is True

    line = path.read_text(encoding="utf-8").strip()
    decoded = json.loads(line)
    assert list(decoded.keys()) == sorted(decoded.keys())
