"""Passive Reddit trends collector for Research Foundation.

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


def _default_fetcher(subreddit: str, *, limit: int) -> list[dict[str, Any]]:
    """Best-effort default fetcher.

    Intentionally passive and fail-open. Network-backed collection can be added
    in a future patch.
    """
    return []


class RedditTrendsCollector:
    """Collect Reddit post trend observations and store raw events only."""

    def __init__(
        self,
        *,
        research_root: Path | str = DEFAULT_RESEARCH_ROOT,
        fetcher: Fetcher | None = None,
        default_country: str = "global",
        default_language: str = "en",
        limit: int = 25,
    ) -> None:
        self.research_root = Path(research_root)
        self.fetcher = fetcher or _default_fetcher
        self.default_country = default_country
        self.default_language = default_language
        self.limit = limit

    def collect(self, subreddits: list[str], *, observed_at_utc: str | None = None) -> list[dict[str, Any]]:
        """Collect and persist contract-shaped raw observations.

        Fail-open behavior: one subreddit fetch/persist issue does not stop
        other subreddit collection in the same run.
        """
        emitted: list[dict[str, Any]] = []

        for subreddit in subreddits:
            sub = (subreddit or "").strip()
            if not sub:
                continue

            try:
                posts = self.fetcher(sub, limit=self.limit)
            except Exception:
                continue

            for post in posts or []:
                title = str(post.get("title") or "").strip()
                if not title:
                    continue

                observed_at = observed_at_utc or datetime.now(timezone.utc).isoformat()
                raw_payload = {
                    "source": "reddit_trends",
                    "topic": title,
                    "category": post.get("category", "community_trend"),
                    "country": post.get("country", self.default_country),
                    "language": post.get("language", self.default_language),
                    "engagement": {
                        "score": post.get("score"),
                        "comments": post.get("num_comments"),
                    },
                    "raw_context": {
                        "subreddit": sub,
                        "post_id": post.get("id"),
                        "post_url": post.get("url"),
                        "collector": "reddit_trends_v0",
                    },
                }

                observation = {
                    "schema_version": 1,
                    "source": "reddit_trends",
                    "observed_at": observed_at,
                    "raw": raw_payload,
                }
                if not is_valid_raw_observation(observation):
                    continue

                append_raw_observation(observation, root=self.research_root, observed_at_utc=observed_at)
                emitted.append(observation)

        return emitted
