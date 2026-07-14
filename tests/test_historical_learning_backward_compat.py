from __future__ import annotations

import importlib



def test_sprint2_imports_do_not_break_existing_modules() -> None:
    modules = [
        "src.decision_memory",
        "src.analytics_evidence_join",
        "src.experiment_registry",
        "src.forward_evidence_capture",
        "src.learning_record_contract",
        "src.historical_learning_store",
        "src.learning_feature_projection",
        "src.run_historical_learning_audit",
    ]
    for name in modules:
        module = importlib.import_module(name)
        assert module is not None
