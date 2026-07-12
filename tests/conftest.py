from __future__ import annotations

import sys
from pathlib import Path

import pytest


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