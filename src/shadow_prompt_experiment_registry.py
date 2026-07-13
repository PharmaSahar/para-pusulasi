from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SHADOW_PROMPT_VARIANT_REGISTRY_SCHEMA_VERSION = "v1"
SHADOW_PROMPT_VARIANT_REGISTRY_VERSION = "v1"

_REQUIRED_VARIANTS = (
    "CURRENT_PRODUCTION",
    "CONTROL",
    "CANDIDATE_A",
    "CANDIDATE_B",
    "FUTURE",
)


@dataclass(frozen=True)
class PromptVariantRegistryEntry:
    schema_version: str
    registry_version: str
    variant_id: str
    strategy_name: str
    rationale: str
    supported_channels: tuple[str, ...]
    supported_content_types: tuple[str, ...]
    supported_blueprint_versions: tuple[str, ...]
    status: str
    compatibility: dict[str, Any]
    experiment_scope: dict[str, Any]
    advisory_only: bool
    active: bool

    def __post_init__(self) -> None:
        if self.schema_version != SHADOW_PROMPT_VARIANT_REGISTRY_SCHEMA_VERSION:
            raise ValueError("invalid_field:schema_version")
        if self.registry_version != SHADOW_PROMPT_VARIANT_REGISTRY_VERSION:
            raise ValueError("invalid_field:registry_version")
        if self.variant_id not in _REQUIRED_VARIANTS:
            raise ValueError("invalid_field:variant_id")
        if not self.strategy_name.strip():
            raise ValueError("missing_field:strategy_name")
        if not self.rationale.strip():
            raise ValueError("missing_field:rationale")
        if not self.supported_channels:
            raise ValueError("missing_field:supported_channels")
        if not self.supported_content_types:
            raise ValueError("missing_field:supported_content_types")
        if not self.supported_blueprint_versions:
            raise ValueError("missing_field:supported_blueprint_versions")
        if not self.status.strip():
            raise ValueError("missing_field:status")
        if not isinstance(self.compatibility, dict):
            raise ValueError("invalid_field:compatibility")
        if not isinstance(self.experiment_scope, dict):
            raise ValueError("invalid_field:experiment_scope")
        if not self.advisory_only:
            raise ValueError("invalid_field:advisory_only")
        if self.active:
            raise ValueError("invalid_field:active")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["supported_channels"] = list(self.supported_channels)
        payload["supported_content_types"] = list(self.supported_content_types)
        payload["supported_blueprint_versions"] = list(self.supported_blueprint_versions)
        return payload


def _entry(
    *,
    variant_id: str,
    strategy_name: str,
    rationale: str,
    status: str,
    experiment_scope: dict[str, Any],
) -> PromptVariantRegistryEntry:
    return PromptVariantRegistryEntry(
        schema_version=SHADOW_PROMPT_VARIANT_REGISTRY_SCHEMA_VERSION,
        registry_version=SHADOW_PROMPT_VARIANT_REGISTRY_VERSION,
        variant_id=variant_id,
        strategy_name=strategy_name,
        rationale=rationale,
        supported_channels=("*",),
        supported_content_types=("video", "short", "mixed"),
        supported_blueprint_versions=("v1",),
        status=status,
        compatibility={
            "runtime_prompt_replacement_allowed": False,
            "pipeline_output_mutation_allowed": False,
            "scheduler_changes_allowed": False,
            "uploader_changes_allowed": False,
            "shadow_only": True,
        },
        experiment_scope=dict(experiment_scope),
        advisory_only=True,
        active=False,
    )


def get_prompt_variant_registry() -> dict[str, PromptVariantRegistryEntry]:
    registry = {
        "CURRENT_PRODUCTION": _entry(
            variant_id="CURRENT_PRODUCTION",
            strategy_name="Production Baseline Snapshot",
            rationale="Exact baseline reference used for deterministic comparison only.",
            status="baseline_locked",
            experiment_scope={"role": "baseline", "compare_against": []},
        ),
        "CONTROL": _entry(
            variant_id="CONTROL",
            strategy_name="Control Mirror",
            rationale="Secondary control to detect scoring drift and comparator instability.",
            status="control_locked",
            experiment_scope={"role": "control", "compare_against": ["CURRENT_PRODUCTION"]},
        ),
        "CANDIDATE_A": _entry(
            variant_id="CANDIDATE_A",
            strategy_name="Safety + Structure Emphasis",
            rationale="Adds explicit safety and narrative scaffolding signals for offline evaluation.",
            status="candidate_inactive",
            experiment_scope={"role": "candidate", "compare_against": ["CURRENT_PRODUCTION", "CONTROL"]},
        ),
        "CANDIDATE_B": _entry(
            variant_id="CANDIDATE_B",
            strategy_name="Retention + SEO Emphasis",
            rationale="Adds retention/SEO emphasis for offline quality comparison.",
            status="candidate_inactive",
            experiment_scope={"role": "candidate", "compare_against": ["CURRENT_PRODUCTION", "CONTROL"]},
        ),
        "FUTURE": _entry(
            variant_id="FUTURE",
            strategy_name="Future Reserved Slot",
            rationale="Reserved slot for future strategy definitions without activation.",
            status="reserved",
            experiment_scope={"role": "placeholder", "compare_against": ["CURRENT_PRODUCTION"]},
        ),
    }
    return registry


def list_prompt_variant_ids() -> tuple[str, ...]:
    return tuple(get_prompt_variant_registry().keys())


def get_prompt_variant(variant_id: str) -> PromptVariantRegistryEntry:
    registry = get_prompt_variant_registry()
    key = str(variant_id or "").strip().upper()
    if key not in registry:
        raise ValueError("unsupported_variant")
    return registry[key]
