from __future__ import annotations

from src.shadow_quality_taxonomy import TAXONOMY_VERSION, get_finding_spec, list_finding_specs


def test_taxonomy_version_and_lookup() -> None:
    assert TAXONOMY_VERSION == "v1"
    spec = get_finding_spec("guaranteed_return_wording_detection")
    assert spec.code == "guaranteed_return_wording_detection"
    assert spec.category == "financial_claim_risk"
    assert spec.default_severity in {"HIGH", "MEDIUM", "LOW", "INFO", "CRITICAL"}


def test_unknown_finding_fallback() -> None:
    spec = get_finding_spec("unknown_code_for_test")
    assert spec.code == "unknown_code_for_test"
    assert spec.category == "validator_failure"


def test_registry_contains_unique_codes() -> None:
    specs = list_finding_specs()
    codes = [s["code"] for s in specs]
    assert len(codes) == len(set(codes))
    assert "unsupported_financial_claim_detection" in set(codes)
