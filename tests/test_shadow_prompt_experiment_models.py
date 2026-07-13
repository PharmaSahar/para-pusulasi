from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.content_intelligence_foundation import GenerationBlueprint
from src.shadow_blueprint_prompt_alignment import build_safe_prompt_representation
from src.shadow_prompt_experiment_framework import (
    SHADOW_PROMPT_EXPERIMENT_SCHEMA_VERSION,
    PromptExperimentValidationError,
    append_prompt_experiment_row,
    benchmark_prompt_experiment,
    build_prompt_experiment_storage_row,
    load_prompt_experiment_rows,
    replay_prompt_experiments,
    run_prompt_experiment,
    run_prompt_experiment_and_store,
)
from tests.fixtures.slice4_phase4_prompt_experiment_fixtures import build_phase4_prompt_experiment_fixtures


def _first_fixture_blueprint() -> GenerationBlueprint:
    fixture = build_phase4_prompt_experiment_fixtures()[0]
    return GenerationBlueprint.from_dict(fixture.blueprint)


def _first_prompt_representation():
    fixture = build_phase4_prompt_experiment_fixtures()[0]
    return build_safe_prompt_representation(
        prompt_text=fixture.prompt_text,
        prompt_type="content_generation",
        template_id="content_generator_v2_json",
    )


def test_run_prompt_experiment_contract() -> None:
    result = run_prompt_experiment(
        blueprint=_first_fixture_blueprint(),
        prompt_representation=_first_prompt_representation(),
        run_id="run_phase4_models",
        channel_id="para_pusulasi",
        content_type="mixed",
    )

    payload = result.to_dict()
    assert payload["schema_version"] == SHADOW_PROMPT_EXPERIMENT_SCHEMA_VERSION
    assert payload["advisory_only"] is True
    assert payload["pipeline_output_changed"] is False
    assert payload["decision"]["decision"] == "NO_RUNTIME_CHANGE"
    assert payload["decision"]["selected_variant_id"] == "CURRENT_PRODUCTION"
    assert len(payload["variants_evaluated"]) >= 5



def test_immutable_result_object() -> None:
    result = run_prompt_experiment(
        blueprint=_first_fixture_blueprint(),
        prompt_representation=_first_prompt_representation(),
        run_id="run_phase4_immutable",
        channel_id="para_pusulasi",
        content_type="mixed",
    )

    with pytest.raises(FrozenInstanceError):
        result.run_id = "mutated"  # type: ignore[misc]



def test_storage_append_load_and_replay(tmp_path: Path) -> None:
    output = tmp_path / "shadow_prompt_experiments.jsonl"

    payload = run_prompt_experiment_and_store(
        blueprint=_first_fixture_blueprint(),
        prompt_representation=_first_prompt_representation(),
        run_id="run_phase4_store",
        channel_id="para_pusulasi",
        content_type="mixed",
        storage_path=output,
    )

    row = build_prompt_experiment_storage_row(
        run_prompt_experiment(
            blueprint=_first_fixture_blueprint(),
            prompt_representation=_first_prompt_representation(),
            run_id="run_phase4_row",
            channel_id="para_pusulasi",
            content_type="mixed",
        )
    ).to_dict()
    append_prompt_experiment_row(row, output_path=output)

    output.write_text(output.read_text(encoding="utf-8") + "{malformed}\n", encoding="utf-8")

    rows, malformed = load_prompt_experiment_rows(input_path=output, limit=20)
    replay = replay_prompt_experiments(input_path=output, limit=20)

    assert payload["results_path"].endswith("shadow_prompt_experiments.jsonl")
    assert len(rows) == 2
    assert malformed == 1
    assert replay["rows"] == 2
    assert replay["malformed_rows"] == 1



def test_storage_rejects_prompt_leakage() -> None:
    with pytest.raises(PromptExperimentValidationError):
        append_prompt_experiment_row(
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
                "prompt_hash": "ph",
                "template_id": "t",
                "prompt_version": "v1",
                "analyzer_version": "v1",
                "variants": ["CURRENT_PRODUCTION"],
                "recommendation": "KEEP_CURRENT",
                "selected_variant_id": "CURRENT_PRODUCTION",
                "recommendation_reason": "authorization: bearer secret",
                "aggregate_metrics": {},
                "advisory_only": True,
                "pipeline_output_changed": False,
                "created_at": "2026-07-13T10:00:00+00:00",
            }
        )



def test_benchmark_runs() -> None:
    metrics = benchmark_prompt_experiment(
        blueprint=_first_fixture_blueprint(),
        prompt_representation=_first_prompt_representation(),
        runs=10,
    )

    assert metrics["one_experiment_ms"] >= 0.0
    assert metrics["fifty_experiment_ms"] >= 0.0
    assert metrics["variant_count"] >= 5
