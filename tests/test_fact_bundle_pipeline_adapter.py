from __future__ import annotations

from src.fact_bundle_orchestrator import FactBundleOrchestrationResult
from src.fact_bundle_pipeline_adapter import (
    FactBundlePipelineAdapter,
    build_fact_bundle_pipeline_adapter,
)


class DummyProvider:
    pass


class StubOrchestrator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...] | None]] = []

    def orchestrate_all(self) -> FactBundleOrchestrationResult:
        self.calls.append(("all", None))
        provider = DummyProvider()
        return FactBundleOrchestrationResult(
            providers=(provider,),
            provider_names=(provider.__class__.__name__,),
        )

    def orchestrate_by_names(self, provider_names):
        names = tuple(provider_names)
        self.calls.append(("by_names", names))
        provider = DummyProvider()
        return FactBundleOrchestrationResult(
            providers=(provider,),
            provider_names=(provider.__class__.__name__,),
        )


def test_pipeline_adapter_is_noop_by_default_builder():
    adapter = build_fact_bundle_pipeline_adapter()

    assert adapter.enabled is False


def test_pipeline_adapter_noop_when_disabled():
    orchestrator = StubOrchestrator()
    adapter = FactBundlePipelineAdapter(orchestrator=orchestrator, enabled=False)

    result = adapter.run()

    assert result.enabled is False
    assert result.applied is False
    assert result.orchestration_result is None
    assert result.reason == "disabled"
    assert orchestrator.calls == []


def test_pipeline_adapter_runs_orchestrate_all_when_enabled():
    orchestrator = StubOrchestrator()
    adapter = FactBundlePipelineAdapter(orchestrator=orchestrator, enabled=True)

    result = adapter.run()

    assert result.enabled is True
    assert result.applied is True
    assert result.reason == "enabled"
    assert result.orchestration_result is not None
    assert result.orchestration_result.provider_count == 1
    assert orchestrator.calls == [("all", None)]


def test_pipeline_adapter_runs_orchestrate_by_names_when_enabled():
    orchestrator = StubOrchestrator()
    adapter = FactBundlePipelineAdapter(orchestrator=orchestrator, enabled=True)

    result = adapter.run(["news", "crypto"])

    assert result.applied is True
    assert result.orchestration_result is not None
    assert orchestrator.calls == [("by_names", ("news", "crypto"))]
