import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.run_research_once as runner


def test_main_calls_scheduler_and_prints_json(monkeypatch, capsys, tmp_path):
    called = {}

    def fake_run_research_collectors_once(*, collector_inputs, research_root, observed_at_utc):
        called["collector_inputs"] = collector_inputs
        called["research_root"] = research_root
        called["observed_at_utc"] = observed_at_utc
        return {
            "collectors_run": 1,
            "observations_written": 2,
            "failures": [],
            "results": [],
        }

    monkeypatch.setattr(runner, "run_research_collectors_once", fake_run_research_collectors_once)

    code = runner.main(
        [
            "--query",
            "bitcoin",
            "--query",
            "bist",
            "--research-root",
            str(tmp_path),
            "--observed-at",
            "2026-07-08T12:00:00+00:00",
        ]
    )

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)

    assert code == 0
    assert payload["collectors_run"] == 1
    assert called["collector_inputs"]["google_trends"]["queries"] == ["bitcoin", "bist"]
    assert str(called["research_root"]) == str(tmp_path)
    assert called["observed_at_utc"] == "2026-07-08T12:00:00+00:00"


def test_main_returns_nonzero_and_prints_error_json_on_exception(monkeypatch):
    def fake_run_research_collectors_once(*, collector_inputs, research_root, observed_at_utc):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "run_research_collectors_once", fake_run_research_collectors_once)

    code = runner.main(["--query", "bitcoin"])
    assert code == 1


def test_main_pretty_output_is_valid_json(monkeypatch, capsys):
    def fake_run_research_collectors_once(*, collector_inputs, research_root, observed_at_utc):
        return {
            "collectors_run": 1,
            "observations_written": 0,
            "failures": [],
            "results": [],
        }

    monkeypatch.setattr(runner, "run_research_collectors_once", fake_run_research_collectors_once)

    code = runner.main(["--pretty"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["collectors_run"] == 1
