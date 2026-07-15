from __future__ import annotations

from src.causal_attribution_store import CausalAttributionStore
from src.decision_memory import DecisionMemoryStore
from src.experiment_evaluation_store import ExperimentEvaluationStore
from src.experiment_lifecycle_store import ExperimentLifecycleStore
from src.historical_learning_store import HistoricalLearningStore
from src.outcome_maturity_store import OutcomeMaturityStore
from src.prompt_registry import build_prompt_metadata
from src.recommendation_store import RecommendationStore
from src.statistical_confidence_store import StatisticalConfidenceStore


def test_existing_project003_layers_and_prompt_helper_still_import() -> None:
    assert DecisionMemoryStore is not None
    assert HistoricalLearningStore is not None
    assert OutcomeMaturityStore is not None
    assert ExperimentLifecycleStore is not None
    assert ExperimentEvaluationStore is not None
    assert StatisticalConfidenceStore is not None
    assert CausalAttributionStore is not None
    assert RecommendationStore is not None
    metadata = build_prompt_metadata("write a concise title")
    assert metadata["prompt_hash"]
