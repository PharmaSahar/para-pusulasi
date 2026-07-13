from __future__ import annotations

import pytest

from src.planning_blueprint_lineage_evidence import (
    PlanningLineageLinkStatus,
    PlanningLineageSourceStage,
    compute_planning_lineage_evidence_id,
    extract_prompt_metadata_hash,
    resolve_planning_link_status,
    validate_planning_lineage_row,
)


def test_enum_values_stable() -> None:
    assert PlanningLineageLinkStatus.LINKED.value == "LINKED"
    assert PlanningLineageLinkStatus.AMBIGUOUS.value == "AMBIGUOUS"
    assert PlanningLineageSourceStage.FINALIZED.value == "FINALIZED"


def test_prompt_metadata_hash_extraction() -> None:
    value, conflict = extract_prompt_metadata_hash({"prompt_hash": "abc"})
    assert value == "abc"
    assert conflict is False

    value2, conflict2 = extract_prompt_metadata_hash({"safe_prompt": {"prompt_hash": "def"}})
    assert value2 == "def"
    assert conflict2 is False

    value3, conflict3 = extract_prompt_metadata_hash({"prompt_hash": "x", "safe_prompt": {"prompt_hash": "y"}})
    assert value3 is None
    assert conflict3 is True


def test_link_status_resolution() -> None:
    linked = resolve_planning_link_status(
        planning_context_id="r1",
        blueprint_id="bp",
        blueprint_hash="bh",
        prompt_metadata_hash="ph",
        content_id="c1",
        run_id="r1",
        script_hash="sh",
    )
    assert linked == PlanningLineageLinkStatus.LINKED

    partial = resolve_planning_link_status(
        planning_context_id="",
        blueprint_id="bp",
        blueprint_hash="",
        prompt_metadata_hash="",
        content_id="c1",
        run_id="r1",
        script_hash="sh",
    )
    assert partial == PlanningLineageLinkStatus.PARTIAL

    ambiguous = resolve_planning_link_status(
        planning_context_id="other_run",
        blueprint_id="bp",
        blueprint_hash="bh",
        prompt_metadata_hash="ph",
        content_id="c1",
        run_id="r1",
        script_hash="sh",
    )
    assert ambiguous == PlanningLineageLinkStatus.AMBIGUOUS


def test_evidence_id_deterministic() -> None:
    a = compute_planning_lineage_evidence_id(
        planning_context_id="r1",
        blueprint_id="bp",
        blueprint_hash="bh",
        prompt_metadata_hash="ph",
        experiment_id="exp",
        content_id="c",
        run_id="r",
        script_hash="sh",
        source_stage=PlanningLineageSourceStage.INITIAL_GENERATION,
        generation_attempt=1,
    )
    b = compute_planning_lineage_evidence_id(
        planning_context_id="r1",
        blueprint_id="bp",
        blueprint_hash="bh",
        prompt_metadata_hash="ph",
        experiment_id="exp",
        content_id="c",
        run_id="r",
        script_hash="sh",
        source_stage=PlanningLineageSourceStage.INITIAL_GENERATION,
        generation_attempt=1,
    )
    assert a == b


def test_validate_row_requires_advisory_and_no_mutation() -> None:
    row = {
        "schema_version": "v1",
        "evidence_id": "pble_1",
        "planning_context_id": "r1",
        "blueprint_id": "bp",
        "blueprint_hash": "bh",
        "prompt_metadata_hash": "ph",
        "experiment_id": "exp",
        "content_id": "c1",
        "run_id": "r1",
        "script_hash": "sh",
        "link_status": "LINKED",
        "source_stage": "INITIAL_GENERATION",
        "generation_attempt": 1,
        "created_at": "2026-07-13T00:00:00+00:00",
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
    validated = validate_planning_lineage_row(row)
    assert validated["pipeline_output_changed"] is False

    bad = dict(row)
    bad["pipeline_output_changed"] = True
    with pytest.raises(ValueError):
        validate_planning_lineage_row(bad)
