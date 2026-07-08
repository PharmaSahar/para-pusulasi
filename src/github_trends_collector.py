"""Passive GitHub trends collector for Research Foundation.

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


def _default_fetcher(language: str, *, since: str) -> list[dict[str, Any]]:
    """Best-effort default fetcher.

    Intentionally passive and fail-open. Network collection can be added later.
    """
    return []


class GitHubTrendsCollector:
    """Collect GitHub repository trend observations and store raw events only."""

    def __init__(
        self,
        *,
        research_root: Path | str = DEFAULT_RESEARCH_ROOT,
        fetcher: Fetcher | None = None,
        default_country: str = "global",
        default_language: str = "en",
        since: str = "daily",
    ) -> None:
        self.research_root = Path(research_root)
        self.fetcher = fetcher or _default_fetcher
        self.default_country = default_country
        self.default_language = default_language
        self.since = since

    def collect(self, languages: list[str], *, observed_at_utc: str | None = None) -> list[dict[str, Any]]:
        """Collect and persist contract-shaped raw observations.

        Fail-open behavior: fetch and persistence errors are swallowed per
        language so one source issue never breaks full passive research runs.
        """
        emitted: list[dict[str, Any]] = []

        for language in languages:
            lang = (language or "").strip().lower()
            if not lang:
                continue

            try:
                repos = self.fetcher(lang, since=self.since)
            except Exception:
                continue

            for repo in repos or []:
                name = str(repo.get("name") or "").strip()
                if not name:
                    continue

                observed_at = observed_at_utc or datetime.now(timezone.utc).isoformat()
                raw_payload = {
                    "source": "github_trends",
                    "topic": f"repo:{name}",
                    "category": "developer_tools",
                    "country": repo.get("country", self.default_country),
                    "language": repo.get("language", lang or self.default_language),
                    "stars": repo.get("stars"),
                    "raw_context": {
                        "repo_name": name,
                        "repo_url": repo.get("url"),
                        "description": repo.get("description"),
                        "since": self.since,
                        "collector": "github_trends_v0",
                    },
                }

                observation = {
                    "source": "github_trends",
                    "observed_at": observed_at,
                    "raw": raw_payload,
                }
                if not is_valid_raw_observation(observation):
                    continue

                append_raw_observation(observation, root=self.research_root, observed_at_utc=observed_at)
                emitted.append(observation)

        return emitted
