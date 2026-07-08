"""Thin adapter to optionally invoke Fact Bundle orchestration from pipeline code."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .fact_bundle_orchestrator import (
    FactBundleOrchestrationResult,
    FactBundleOrchestrator,
    build_fact_bundle_orchestrator,
)


@dataclass(frozen=True, slots=True)
class FactBundlePipelineAdapterResult:
    """Pipeline-facing result for optional Fact Bundle orchestration."""

    enabled: bool
    applied: bool
    orchestration_result: FactBundleOrchestrationResult | None
    reason: str


@dataclass(frozen=True, slots=True)
class FactBundlePipelineAdapter:
    """Invoke the orchestrator only when explicitly enabled."""

    orchestrator: FactBundleOrchestrator
    enabled: bool = False

    def run(self, provider_names: Iterable[str] | None = None) -> FactBundlePipelineAdapterResult:
        if not self.enabled:
            return FactBundlePipelineAdapterResult(
                enabled=False,
                applied=False,
                orchestration_result=None,
                reason="disabled",
            )

        if provider_names is None:
            result = self.orchestrator.orchestrate_all()
            return FactBundlePipelineAdapterResult(
                enabled=True,
                applied=True,
                orchestration_result=result,
                reason="enabled",
            )

        result = self.orchestrator.orchestrate_by_names(provider_names)
        return FactBundlePipelineAdapterResult(
            enabled=True,
            applied=True,
            orchestration_result=result,
            reason="enabled",
        )


def build_fact_bundle_pipeline_adapter(enabled: bool = False) -> FactBundlePipelineAdapter:
    return FactBundlePipelineAdapter(
        orchestrator=build_fact_bundle_orchestrator(),
        enabled=enabled,
    )


__all__ = [
    "FactBundlePipelineAdapter",
    "FactBundlePipelineAdapterResult",
    "build_fact_bundle_pipeline_adapter",
]
