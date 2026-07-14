from __future__ import annotations

import importlib

from src.prompt_registry import build_prompt_metadata


def test_existing_modules_still_import_and_basic_helpers_work() -> None:
    modules = [
        "src.forward_evidence_capture",
        "src.script_lineage_evidence",
        "src.thumbnail_metadata_lineage",
        "src.analytics_evidence_join",
        "src.experiment_registry",
        "src.content_quality_guard",
        "src.prompt_registry",
    ]
    for module_name in modules:
        module = importlib.import_module(module_name)
        assert module is not None

    metadata = build_prompt_metadata("write a concise youtube title about finance")
    assert metadata["prompt_hash"]
    assert metadata["prompt_version"].startswith("v1-")
