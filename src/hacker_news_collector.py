"""Passive Hacker News collector for Research Foundation.

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


def _default_fetcher(board: str, *, limit: int) -> list[dict[str, Any]]:
    """Best-effort default fetcher.

    Intentionally passive and fail-open. Network-backed collection can be added
    in a future patch.
    """
    return []


class HackerNewsCollector:
    """Collect Hacker News observations and store raw events only."""

    def __init__(
        self,
        *,
        research_root: Path | str = DEFAULT_RESEARCH_ROOT,
        fetcher: Fetcher | None = None,
        default_country: str = "global",
        default_language: str = "en",
        limit: int = 30,
    ) -> None:
        self.research_root = Path(research_root)
        self.fetcher = fetcher or _default_fetcher
        self.default_country = default_country
        self.default_language = default_language
        self.limit = limit

    def collect(self, boards: list[str], *, observed_at_utc: str | None = None) -> list[dict[str, Any]]:
        """Collect and persist contract-shaped raw observations.

        Fail-open behavior: one board fetch/persist issue does not stop other
        board collection in the same run.
        """
        emitted: list[dict[str, Any]] = []

        for board in boards:
            board_name = (board or "").strip().lower()
            if not board_name:
                continue

            try:
                stories = self.fetcher(board_name, limit=self.limit)
            except Exception:
                continue

            for story in stories or []:
                title = str(story.get("title") or "").strip()
                if not title:
                    continue

                observed_at = observed_at_utc or datetime.now(timezone.utc).isoformat()
                raw_payload = {
                    "source": "hacker_news",
                    "topic": title,
                    "category": story.get("category", "developer_trend"),
                    "country": story.get("country", self.default_country),
                    "language": story.get("language", self.default_language),
                    "engagement": {
                        "points": story.get("points"),
                        "comments": story.get("comments"),
                    },
                    "raw_context": {
                        "board": board_name,
                        "story_id": story.get("id"),
                        "story_url": story.get("url"),
                        "collector": "hacker_news_v0",
                    },
                }

                observation = {
                    "schema_version": 1,
                    "source": "hacker_news",
                    "observed_at": observed_at,
                    "raw": raw_payload,
                }
                if not is_valid_raw_observation(observation):
                    continue

                append_raw_observation(observation, root=self.research_root, observed_at_utc=observed_at)
                emitted.append(observation)

        return emitted
