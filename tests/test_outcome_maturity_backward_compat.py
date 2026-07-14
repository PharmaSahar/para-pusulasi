from __future__ import annotations

import importlib


def test_sprint3_imports_do_not_break_existing_modules() -> None:
    modules = [
        "src.decision_memory",
        "src.learning_record_contract",
        "src.historical_learning_store",
        "src.outcome_maturity_contract",
        "src.outcome_maturity_store",
        "src.outcome_snapshot",
        "src.run_outcome_maturity_audit",
    ]
    for name in modules:
        module = importlib.import_module(name)
        assert module is not None
