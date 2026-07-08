"""Passive scheduler entrypoint for research collectors.

Scope boundary:
- One-shot callable only (no daemon, no cron wiring)
- Runs registered passive collectors once
- Fail-open per collector
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .github_trends_collector import GitHubTrendsCollector
from .google_trends_collector import GoogleTrendsCollector
from .hacker_news_collector import HackerNewsCollector
from .reddit_trends_collector import RedditTrendsCollector
from .research_db import DEFAULT_RESEARCH_ROOT


def build_registered_collectors(*, research_root: Path | str = DEFAULT_RESEARCH_ROOT) -> dict[str, Any]:
    """Build default collector registry.

    Starts with Google Trends only.
    """
    return {
        "google_trends": GoogleTrendsCollector(research_root=research_root),
        "github_trends": GitHubTrendsCollector(research_root=research_root),
        "reddit_trends": RedditTrendsCollector(research_root=research_root),
        "hacker_news": HackerNewsCollector(research_root=research_root),
    }


def run_research_collectors_once(
    *,
    collectors: dict[str, Any] | None = None,
    collector_inputs: dict[str, dict[str, Any]] | None = None,
    research_root: Path | str = DEFAULT_RESEARCH_ROOT,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    """Run registered passive collectors exactly once.

    collector_inputs format example:
    {
      "google_trends": {"queries": ["bitcoin", "bist"]}
    }
    """
    registry = collectors or build_registered_collectors(research_root=research_root)
    inputs = collector_inputs or {}

    started_at = datetime.now(timezone.utc).isoformat()
    run_summary: list[dict[str, Any]] = []
    observations_written = 0
    failures: list[dict[str, str]] = []

    for name, collector in registry.items():
        payload = dict(inputs.get(name, {}))
        if name == "google_trends":
            payload.setdefault("queries", [])
        elif name == "github_trends":
            payload.setdefault("languages", [])
        elif name == "reddit_trends":
            payload.setdefault("subreddits", [])
        elif name == "hacker_news":
            payload.setdefault("boards", [])
        else:
            payload.setdefault("queries", [])
        payload.setdefault("observed_at_utc", observed_at_utc)

        try:
            emitted = collector.collect(**payload)
            emitted_count = len(emitted or [])
            observations_written += emitted_count
            run_summary.append(
                {
                    "collector": name,
                    "status": "ok",
                    "emitted_count": emitted_count,
                    "error": None,
                }
            )
        except Exception as exc:
            # Fail-open: continue with other collectors.
            failures.append({"collector": name, "error": str(exc)})
            run_summary.append(
                {
                    "collector": name,
                    "status": "failed",
                    "emitted_count": 0,
                    "error": str(exc),
                }
            )

    return {
        "started_at": started_at,
        "collectors_run": len(registry),
        "observations_written": observations_written,
        "failures": failures,
        "collector_count": len(registry),
        "results": run_summary,
    }
