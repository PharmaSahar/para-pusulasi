from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.script_lineage_evidence import (
    RetentionMode,
    ScriptLineageRecorder,
    ScriptLineageRetentionPolicy,
    ScriptSourceStage,
    build_legacy_import_assessment,
    classify_script_completeness,
    hash_text,
    load_script_lineage_rows,
    reconstruct_current_final_scripts,
)


def _recorder(tmp_path: Path) -> tuple[ScriptLineageRecorder, Path]:
    path = tmp_path / "events.jsonl"
    rec = ScriptLineageRecorder(
        content_id="content_s",
        run_id="run_s",
        canonical_channel_id="channel_s",
        content_type="mixed",
        topic="topic_s",
        experiment_id="exp_s",
        evidence_path=path,
    )
    return rec, path


def _assert_invariant(path: Path) -> None:
    rows, malformed, _errors = load_script_lineage_rows(input_path=path)
    assert malformed == 0
    assert rows
    assert all(bool(row.get("advisory_only")) for row in rows)
    assert all(not bool(row.get("pipeline_output_changed")) for row in rows)


def test_scenario_01_initial_script_only(tmp_path: Path) -> None:
    rec, path = _recorder(tmp_path)
    rec.record_script_created(
        script_text="initial script" * 20,
        source_stage=ScriptSourceStage.INITIAL_GENERATION,
        generation_attempt=1,
        regeneration_reason=None,
        prompt_metadata={"p": 1},
        planning_context_id="plan1",
        blueprint_id="bp1",
        blueprint_hash="bh1",
    )
    _assert_invariant(path)


def test_scenario_02_initial_plus_fact_check_regen(tmp_path: Path) -> None:
    rec, path = _recorder(tmp_path)
    rec.record_script_created("a" * 180, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "plan", "bp", "bh")
    rec.record_script_created("b" * 180, ScriptSourceStage.FACT_CHECK_REGENERATION, 2, "fact-check", {}, "plan", "bp", "bh")
    _assert_invariant(path)


def test_scenario_03_initial_plus_quality_regen(tmp_path: Path) -> None:
    rec, path = _recorder(tmp_path)
    rec.record_script_created("a" * 180, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "plan", "bp", "bh")
    rec.record_script_created("c" * 180, ScriptSourceStage.QUALITY_REGENERATION, 2, "quality", {}, "plan", "bp", "bh")
    _assert_invariant(path)


def test_scenario_04_editor_rewrite(tmp_path: Path) -> None:
    rec, path = _recorder(tmp_path)
    rec.record_script_created("draft" * 60, ScriptSourceStage.EDITOR_REWRITE, 1, "editor", {}, "plan", "bp", "bh")
    _assert_invariant(path)


def test_scenario_05_identical_retry_idempotent(tmp_path: Path) -> None:
    rec, path = _recorder(tmp_path)
    rec.record_script_created("same" * 50, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "plan", "bp", "bh")
    rec.record_script_created("same" * 50, ScriptSourceStage.QUALITY_REGENERATION, 2, "retry", {}, "plan", "bp", "bh")
    state, _diag = reconstruct_current_final_scripts(evidence_path=path)
    assert len(state["content_s::run_s"]["versions"]) == 1
    _assert_invariant(path)


def test_scenario_06_missing_planning_context(tmp_path: Path) -> None:
    rec, path = _recorder(tmp_path)
    rec.record_script_created("x" * 180, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, None, None, None)
    rows, _, _ = load_script_lineage_rows(input_path=path)
    assert rows[-1]["lineage_link_status"] in {"MISSING", "PARTIAL"}
    _assert_invariant(path)


def test_scenario_07_linked_blueprint(tmp_path: Path) -> None:
    rec, path = _recorder(tmp_path)
    rec.record_script_created("x" * 180, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "plan", "bp", "bh")
    rows, _, _ = load_script_lineage_rows(input_path=path)
    assert rows[-1]["blueprint_id"] == "bp"
    _assert_invariant(path)


def test_scenario_08_render_consumption(tmp_path: Path) -> None:
    rec, path = _recorder(tmp_path)
    rec.record_script_created("x" * 180, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "plan", "bp", "bh")
    rec.record_consumed_by_render(script_text="x" * 180)
    state, _diag = reconstruct_current_final_scripts(evidence_path=path)
    assert state["content_s::run_s"]["render_consumed"] is True
    _assert_invariant(path)


def test_scenario_09_shorts_consumption(tmp_path: Path) -> None:
    rec, path = _recorder(tmp_path)
    rec.record_script_created("x" * 180, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "plan", "bp", "bh")
    rec.record_consumed_by_shorts(script_text="x" * 180)
    state, _diag = reconstruct_current_final_scripts(evidence_path=path)
    assert state["content_s::run_s"]["shorts_consumed"] is True
    _assert_invariant(path)


def test_scenario_10_upload_linkage(tmp_path: Path) -> None:
    rec, path = _recorder(tmp_path)
    rec.record_script_created("x" * 180, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "plan", "bp", "bh")
    rec.record_linked_to_upload(script_text="x" * 180)
    state, _diag = reconstruct_current_final_scripts(evidence_path=path)
    assert state["content_s::run_s"]["upload_result_linked"] is True
    _assert_invariant(path)


def test_scenario_11_preview_only_legacy_record(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    ownership = tmp_path / "ownership"
    runtime.mkdir()
    ownership.mkdir()
    (runtime / "content_1.json").write_text(json.dumps({"generation_id": "content_1"}), encoding="utf-8")
    (ownership / "content_1_run_1.json").write_text(json.dumps({"content_id": "content_1", "script_preview": "preview" * 8}), encoding="utf-8")
    assessment = build_legacy_import_assessment(runtime_evidence_dir=runtime, ownership_dir=ownership, limit=10)
    assert assessment.preview_only >= 1


def test_scenario_12_ambiguous_legacy_record(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    ownership = tmp_path / "ownership"
    runtime.mkdir()
    ownership.mkdir()
    (runtime / "content_1.json").write_text(json.dumps({"generation_id": "content_1"}), encoding="utf-8")
    (ownership / "content_2_run_1.json").write_text(json.dumps({"content_id": "content_2", "script_preview": "preview" * 8}), encoding="utf-8")
    assessment = build_legacy_import_assessment(runtime_evidence_dir=runtime, ownership_dir=ownership, limit=10)
    assert assessment.ambiguous >= 0


def test_scenario_13_missing_script(tmp_path: Path) -> None:
    assert classify_script_completeness(script_text="", has_full_script=False, has_preview=False).value == "MISSING"


def test_scenario_14_malformed_evidence_row(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("{bad json}\n", encoding="utf-8")
    rows, malformed, _errors = load_script_lineage_rows(input_path=path)
    assert malformed >= 1
    assert rows == []


def test_scenario_15_storage_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec, _path = _recorder(tmp_path)
    import src.script_lineage_evidence as sle

    def _raise(_self, _row):
        raise RuntimeError("boom")

    monkeypatch.setattr(sle.ScriptLineageEvidenceStore, "append", _raise)
    with pytest.raises(RuntimeError):
        rec.record_script_created("x" * 100, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "plan", "bp", "bh")


def test_scenario_16_retention_hash_only(tmp_path: Path) -> None:
    policy = ScriptLineageRetentionPolicy(mode=RetentionMode.HASH_ONLY, excerpt_max_chars=120)
    rec = ScriptLineageRecorder(
        content_id="c",
        run_id="r",
        canonical_channel_id="ch",
        content_type="mixed",
        topic="t",
        experiment_id="e",
        evidence_path=tmp_path / "e.jsonl",
        retention_policy=policy,
    )
    rec.record_script_created("x" * 180, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "p", "b", "h")
    rows, _, _ = load_script_lineage_rows(input_path=tmp_path / "e.jsonl")
    assert rows[-1]["script_excerpt"] is None


def test_scenario_17_retention_bounded_excerpt_mode(tmp_path: Path) -> None:
    policy = ScriptLineageRetentionPolicy(mode=RetentionMode.BOUNDED_EXCERPT, excerpt_max_chars=20)
    rec = ScriptLineageRecorder(
        content_id="c",
        run_id="r",
        canonical_channel_id="ch",
        content_type="mixed",
        topic="t",
        experiment_id="e",
        evidence_path=tmp_path / "e.jsonl",
        retention_policy=policy,
    )
    rec.record_script_created("x" * 180, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "p", "b", "h")
    rows, _, _ = load_script_lineage_rows(input_path=tmp_path / "e.jsonl")
    assert len(rows[-1]["script_excerpt"]) == 20


def test_scenario_18_secret_like_script_rejection(tmp_path: Path) -> None:
    policy = ScriptLineageRetentionPolicy(mode=RetentionMode.BOUNDED_EXCERPT, excerpt_max_chars=40)
    rec = ScriptLineageRecorder(
        content_id="c",
        run_id="r",
        canonical_channel_id="ch",
        content_type="mixed",
        topic="t",
        experiment_id="e",
        evidence_path=tmp_path / "e.jsonl",
        retention_policy=policy,
    )
    rec.record_script_created("token=abc123 and api_key=xyz", ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "p", "b", "h")
    rows, _, _ = load_script_lineage_rows(input_path=tmp_path / "e.jsonl")
    assert rows[-1]["script_completeness_state"] == "INVALID"


def test_scenario_19_multiple_versions_one_final_selection(tmp_path: Path) -> None:
    rec, path = _recorder(tmp_path)
    rec.record_script_created("v1 " * 100, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "p", "b", "h")
    rec.record_script_created("v2 " * 100, ScriptSourceStage.QUALITY_REGENERATION, 2, "quality", {}, "p", "b", "h")
    rec.record_script_finalized("v2 " * 100, ScriptSourceStage.QUALITY_REGENERATION, 2, {}, "p", "b", "h")
    state, _diag = reconstruct_current_final_scripts(evidence_path=path)
    final_hash = state["content_s::run_s"]["final_script_hash"]
    assert final_hash == hash_text("v2 " * 100)
    _assert_invariant(path)


def test_scenario_20_replay_final_state_reconstruction(tmp_path: Path) -> None:
    rec, path = _recorder(tmp_path)
    rec.record_script_created("v1 " * 100, ScriptSourceStage.INITIAL_GENERATION, 1, None, {}, "p", "b", "h")
    rec.record_script_finalized("v1 " * 100, ScriptSourceStage.INITIAL_GENERATION, 1, {}, "p", "b", "h")
    rec.record_consumed_by_render(script_text="v1 " * 100)
    rec.record_linked_to_upload(script_text="v1 " * 100)

    states, diagnostics = reconstruct_current_final_scripts(evidence_path=path)
    assert diagnostics.replay_errors == []
    assert states["content_s::run_s"]["render_consumed"] is True
    assert states["content_s::run_s"]["upload_result_linked"] is True
    _assert_invariant(path)
