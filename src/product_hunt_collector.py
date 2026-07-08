"""Passive Product Hunt collector for Research Foundation.

Scope boundary:
- Emits raw observations only
- Persists through research_db.append_raw_observation
- No scoring, no backlog generation
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .collector_contract import is_valid_raw_observation
from .research_db import DEFAULT_RESEARCH_ROOT, append_raw_observation


Fetcher = Callable[..., list[dict[str, Any]]]


def _default_fetcher(topic: str, *, limit: int) -> list[dict[str, Any]]:
    """Best-effort default fetcher.

    Intentionally passive and fail-open. Network-backed collection can be added
    in a future patch.
    """
    return []


class ProductHuntCollector:
    """Collect Product Hunt launch observations and store raw events only."""

    def __init__(
        self,
        *,
        research_root: Path | str = DEFAULT_RESEARCH_ROOT,
        fetcher: Fetcher | None = None,
        default_country: str = "global",
        default_language: str = "en",
        limit: int = 20,
    ) -> None:
        self.research_root = Path(research_root)
        self.fetcher = fetcher or _default_fetcher
        self.default_country = default_country
        self.default_language = default_language
        self.limit = limit

    def collect(self, topics: list[str], *, observed_at_utc: str | None = None) -> list[dict[str, Any]]:
        """Collect and persist contract-shaped raw observations.

        Fail-open behavior: one topic fetch/persist issue does not stop other
        topic collection in the same run.
        """
        emitted: list[dict[str, Any]] = []

        for topic in topics:
            seed_topic = (topic or "").strip()
            if not seed_topic:
                continue

            try:
                launches = self.fetcher(seed_topic, limit=self.limit)
            except Exception:
                continue

            for launch in launches or []:
                product_name = str(launch.get("name") or "").strip()
                if not product_name:
                    continue

                observed_at = observed_at_utc or datetime.now(timezone.utc).isoformat()
                raw_payload = {
                    "source": "product_hunt",
                    "topic": f"product:{product_name}",
                    "category": launch.get("category", "product_launch"),
                    "country": launch.get("country", self.default_country),
                    "language": launch.get("language", self.default_language),
                    "engagement": {
                        "votes": launch.get("votes"),
                        "comments": launch.get("comments"),
                    },
                    "raw_context": {
                        "seed_topic": seed_topic,
                        "product_name": product_name,
                        "tagline": launch.get("tagline"),
                        "product_url": launch.get("url"),
                        "collector": "product_hunt_v0",
                    },
                }

                observation = {
                    "schema_version": 1,
                    "source": "product_hunt",
                    "observed_at": observed_at,
                    "raw": raw_payload,
                }
                if not is_valid_raw_observation(observation):
                    continue

                append_raw_observation(observation, root=self.research_root, observed_at_utc=observed_at)
                emitted.append(observation)

        return emitted
