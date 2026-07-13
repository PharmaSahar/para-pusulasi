from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.content_intelligence_foundation import GenerationBlueprint
from src.offline_prompt_candidate_generator import (
    OfflinePromptCandidateValidationError,
    PromptCandidateGenerator,
    append_storage_row,
    build_storage_row,
    load_storage_rows,
    replay_storage,
    run_offline_prompt_candidate_lab,
    run_offline_prompt_candidate_lab_and_store,
)
from tests.fixtures.slice4_phase5_prompt_candidate_fixtures import build_phase5_prompt_candidate_fixtures



def _fixture_blueprint() -> GenerationBlueprint:
    fixture = build_phase5_prompt_candidate_fixtures()[0]
    return GenerationBlueprint.from_dict(fixture.blueprint)



def test_candidate_generator_outputs_multiple_candidates() -> None:
    blueprint = _fixture_blueprint()
    generator = PromptCandidateGenerator()

    experiment_id, candidates = generator.generate(
        blueprint=blueprint,
        run_id="run_phase5_models",
        channel_id=blueprint.channel_profile.channel_id,
        content_type="mixed",
        objective="offline_candidate_generation",
        hypothesis="deterministic_ranking",
        expected_improvement="safety_and_quality_balance",
    )

    assert experiment_id
    assert len(candidates) >= 12
    assert len({item.candidate_id for item in candidates}) == len(candidates)
    assert all(item.advisory_only for item in candidates)



def test_models_are_immutable() -> None:
    blueprint = _fixture_blueprint()
    generator = PromptCandidateGenerator()
    _, candidates = generator.generate(
        blueprint=blueprint,
        run_id="run_phase5_immutable",
        channel_id=blueprint.channel_profile.channel_id,
        content_type="mixed",
        objective="offline_candidate_generation",
        hypothesis="deterministic_ranking",
        expected_improvement="safety_and_quality_balance",
    )

    with pytest.raises(FrozenInstanceError):
        candidates[0].candidate_id = "mutated"  # type: ignore[misc]



def test_storage_append_load_replay(tmp_path: Path) -> None:
    output = tmp_path / "offline_prompt_candidates.jsonl"
    blueprint = _fixture_blueprint()

    payload = run_offline_prompt_candidate_lab_and_store(
        blueprint=blueprint,
        run_id="run_phase5_store",
        channel_id=blueprint.channel_profile.channel_id,
        content_type="mixed",
        storage_path=output,
    )

    result = run_offline_prompt_candidate_lab(
        blueprint=blueprint,
        run_id="run_phase5_store_2",
        channel_id=blueprint.channel_profile.channel_id,
        content_type="mixed",
    )
    row = build_storage_row(result).to_dict()
    append_storage_row(row, output_path=output)

    output.write_text(output.read_text(encoding="utf-8") + "{malformed}\n", encoding="utf-8")

    rows, malformed = load_storage_rows(input_path=output, limit=20)
    replay = replay_storage(input_path=output, limit=20)

    assert payload["results_path"].endswith("offline_prompt_candidates.jsonl")
    assert len(rows) == 2
    assert malformed == 1
    assert replay["rows"] == 2
    assert replay["malformed_rows"] == 1



def test_storage_rejects_advisory_contract_violation() -> None:
    with pytest.raises(OfflinePromptCandidateValidationError):
        append_storage_row(
            {
                "schema_version": "v1",
                "experiment_id": "exp_bad",
                "run_id": "run_bad",
                "channel_id": "x",
                "content_type": "mixed",
                "objective": "o",
                "hypothesis": "h",
                "expected_improvement": "e",
                "blueprint_hash": "bp",
                "plan_hashes": ["abc"],
                "ranking": {},
                "score_summary": {},
                "explanation_summary": {},
                "advisory_only": False,
                "pipeline_output_changed": False,
                "created_at": "2026-07-13T10:00:00+00:00",
            }
        )
