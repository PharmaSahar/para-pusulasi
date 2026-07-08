"""Passive Google Trends collector for Research Foundation.

Scope boundary:
- Emits raw observations only
- Persists through research_db.append_raw_observation
- No scoring, no backlog generation, no production flow wiring
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .collector_contract import is_valid_raw_observation
from .research_db import DEFAULT_RESEARCH_ROOT, append_raw_observation


Fetcher = Callable[..., list[dict[str, Any]]]


def _default_fetcher(query: str, *, geo: str, timeframe: str) -> list[dict[str, Any]]:
    """Best-effort fetcher.

    This default implementation is optional and fail-open. If `pytrends` is not
    available or any error occurs, it returns an empty list.
    """
    try:
        from pytrends.request import TrendReq  # type: ignore

        pytrends = TrendReq(hl="en-US", tz=0)
        pytrends.build_payload([query], timeframe=timeframe, geo=geo)
        related = pytrends.related_queries()
        rows = (related.get(query, {}) or {}).get("top")
        if rows is None:
            return []

        items: list[dict[str, Any]] = []
        for _, row in rows.iterrows():
            items.append(
                {
                    "topic": row.get("query", query),
                    "search_volume": row.get("value"),
                }
            )
        return items
    except Exception:
        return []


class GoogleTrendsCollector:
    """Collects Google Trends observations and stores raw events only."""

    def __init__(
        self,
        *,
        research_root: Path | str = DEFAULT_RESEARCH_ROOT,
        fetcher: Fetcher | None = None,
        geo: str = "TR",
        timeframe: str = "now 7-d",
        default_country: str = "tr",
        default_language: str = "tr",
    ) -> None:
        self.research_root = Path(research_root)
        self.fetcher = fetcher or _default_fetcher
        self.geo = geo
        self.timeframe = timeframe
        self.default_country = default_country
        self.default_language = default_language

    def collect(self, queries: list[str], *, observed_at_utc: str | None = None) -> list[dict[str, Any]]:
        """Collect and persist raw observations.

        Fail-open behavior: fetch and persistence errors are swallowed per query.
        """
        emitted: list[dict[str, Any]] = []

        for query in queries:
            q = (query or "").strip()
            if not q:
                continue

            try:
                items = self.fetcher(q, geo=self.geo, timeframe=self.timeframe)
            except Exception:
                continue

            for item in items or []:
                topic = str(item.get("topic") or item.get("query") or q).strip()
                if not topic:
                    continue

                observed_at = observed_at_utc or datetime.now(timezone.utc).isoformat()
                raw_payload = {
                    "source": "google_trends",
                    "topic": topic,
                    "category": item.get("category", "general"),
                    "country": item.get("country", self.default_country),
                    "language": item.get("language", self.default_language),
                    "search_volume": item.get("search_volume"),
                    "raw_context": {
                        "seed_query": q,
                        "geo": self.geo,
                        "timeframe": self.timeframe,
                        "collector": "google_trends_v0",
                    },
                }
                raw_observation = {
                    "schema_version": 1,
                    "source": "google_trends",
                    "observed_at": observed_at,
                    "raw": raw_payload,
                }
                if not is_valid_raw_observation(raw_observation):
                    continue

                append_raw_observation(raw_observation, root=self.research_root, observed_at_utc=observed_at)
                emitted.append(raw_observation)

        return emitted
