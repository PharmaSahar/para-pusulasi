from __future__ import annotations

from src.decision_memory import DecisionMemoryStore
from src.experiment_lifecycle_store import ExperimentLifecycleStore
from src.experiment_evaluation_store import ExperimentEvaluationStore
from src.historical_learning_store import HistoricalLearningStore
from src.outcome_maturity_store import OutcomeMaturityStore
from src.statistical_confidence_store import StatisticalConfidenceStore


def test_existing_project003_layers_still_import() -> None:
    assert DecisionMemoryStore is not None
    assert ExperimentLifecycleStore is not None
    assert ExperimentEvaluationStore is not None
    assert HistoricalLearningStore is not None
    assert OutcomeMaturityStore is not None
    assert StatisticalConfidenceStore is not None
