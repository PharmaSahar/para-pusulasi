import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_scheduler import build_registered_collectors, run_research_collectors_once


class _MockCollectorOk:
    def __init__(self):
        self.calls = []

    def collect(self, **kwargs):
        self.calls.append(kwargs)
        return [{"source": "mock", "observed_at": "2026-07-08T00:00:00+00:00", "raw": {}}]


class _MockCollectorFail:
    def collect(self, **kwargs):
        raise RuntimeError("collector failed")


def test_build_registered_collectors_starts_with_google_trends_only(tmp_path):
    registry = build_registered_collectors(research_root=tmp_path)
    assert set(registry.keys()) == {"google_trends", "github_trends", "reddit_trends"}


def test_run_research_collectors_once_fail_open_per_collector():
    ok = _MockCollectorOk()
    fail = _MockCollectorFail()
    registry = {
        "ok_collector": ok,
        "failing_collector": fail,
    }

    result = run_research_collectors_once(
        collectors=registry,
        collector_inputs={
            "ok_collector": {"queries": ["bitcoin"]},
            "failing_collector": {"queries": ["ethereum"]},
        },
        observed_at_utc="2026-07-08T12:00:00+00:00",
    )

    assert result["collectors_run"] == 2
    assert result["observations_written"] == 1
    assert len(result["failures"]) == 1
    assert result["failures"][0]["collector"] == "failing_collector"
    assert "collector failed" in result["failures"][0]["error"]

    assert result["collector_count"] == 2
    assert len(result["results"]) == 2

    ok_result = next(x for x in result["results"] if x["collector"] == "ok_collector")
    fail_result = next(x for x in result["results"] if x["collector"] == "failing_collector")

    assert ok_result["status"] == "ok"
    assert ok_result["emitted_count"] == 1
    assert fail_result["status"] == "failed"
    assert fail_result["emitted_count"] == 0
    assert "collector failed" in fail_result["error"]


def test_run_research_collectors_once_passes_inputs_and_observed_at():
    ok = _MockCollectorOk()

    result = run_research_collectors_once(
        collectors={"ok_collector": ok},
        collector_inputs={"ok_collector": {"queries": ["bist"]}},
        observed_at_utc="2026-07-08T15:00:00+00:00",
    )

    assert len(ok.calls) == 1
    assert ok.calls[0]["queries"] == ["bist"]
    assert ok.calls[0]["observed_at_utc"] == "2026-07-08T15:00:00+00:00"
    assert result["collectors_run"] == 1
    assert result["observations_written"] == 1
    assert result["failures"] == []
