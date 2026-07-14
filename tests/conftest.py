from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Sequence, TypeVar

import pytest

from tools.project002_sprint1e_phase4b_precondition_check import CheckResult, GateState, check_phase4b_environment


_T = TypeVar("_T")
_PHASE4C_BASELINE_TEST_FILES = {
    "test_unresolved_analytics_recovery_integration.py",
    "test_unresolved_analytics_recovery_manifest.py",
}


def _format_phase4b_precondition_failure(result: CheckResult) -> str:
    lines = ["PHASE4B ENVIRONMENT PRECONDITION FAILED", f"STATE: {result.state.value}"]
    for idx, problem in enumerate(result.problems, start=1):
        lines.append(f"{idx}. [{problem.code}] {problem.message}")
    return "\n".join(lines)


def run_phase4c_with_precondition(repository_root: Path, phase4c_callable: Callable[[], _T]) -> _T:
    result = check_phase4b_environment(repository_root)
    if result.state is not GateState.READY:
        raise RuntimeError(_format_phase4b_precondition_failure(result))
    return phase4c_callable()


def _requires_phase4c_gate(item_paths: Sequence[str]) -> bool:
    return any(Path(path).name in _PHASE4C_BASELINE_TEST_FILES for path in item_paths)


def pytest_runtestloop(session: pytest.Session) -> None:
    if bool(getattr(session.config.option, "collectonly", False)):
        return

    if not _requires_phase4c_gate([str(item.fspath) for item in session.items]):
        return

    repository_root = Path(__file__).resolve().parents[1]
    result = check_phase4b_environment(repository_root)
    if result.state is GateState.READY:
        return

    pytest.exit(_format_phase4b_precondition_failure(result), returncode=2)


@pytest.fixture(autouse=True)
def _isolate_dashboard_artifacts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep dashboard artifacts outside tracked docs during tests."""
    dashboard_md_path = tmp_path / "production_dashboard_latest.md"
    dashboard_json_path = tmp_path / "production_dashboard_latest.json"

    monkeypatch.setenv("PRODUCTION_DASHBOARD_MD_PATH", str(dashboard_md_path))
    monkeypatch.setenv("PRODUCTION_DASHBOARD_JSON_PATH", str(dashboard_json_path))

    production_quality_platform = sys.modules.get("src.production_quality_platform")
    if production_quality_platform is not None:
        monkeypatch.setattr(
            production_quality_platform,
            "PRODUCTION_DASHBOARD_MD_PATH",
            dashboard_md_path,
            raising=False,
        )
        monkeypatch.setattr(
            production_quality_platform,
            "PRODUCTION_DASHBOARD_JSON_PATH",
            dashboard_json_path,
            raising=False,
        )

    for module_name in ("scheduler", "src.pipeline"):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        update_func = getattr(module, "update_production_dashboard", None)
        if update_func is None:
            continue
        prod_globals = update_func.__globals__
        monkeypatch.setitem(prod_globals, "PRODUCTION_DASHBOARD_MD_PATH", dashboard_md_path)
        monkeypatch.setitem(prod_globals, "PRODUCTION_DASHBOARD_JSON_PATH", dashboard_json_path)