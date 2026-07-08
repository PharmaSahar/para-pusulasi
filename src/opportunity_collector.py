"""Passive opportunity collector for Research Foundation v0.

This module accepts already-available observations and stores them through
the append-only research event store. It does not fetch external data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .opportunity_normalizer import normalize_observation
from .research_db import DEFAULT_RESEARCH_ROOT, append_or_update_opportunity, append_raw_observation


class OpportunityCollector:
    """Collect raw observations and persist normalized opportunities."""

    def __init__(self, *, research_root: Path | str = DEFAULT_RESEARCH_ROOT) -> None:
        self.research_root = Path(research_root)

    def collect(self, raw_observation: dict[str, Any], *, observed_at_utc: str | None = None) -> dict[str, Any]:
        append_raw_observation(raw_observation, root=self.research_root, observed_at_utc=observed_at_utc)
        normalized = normalize_observation(raw_observation, observed_at_utc=observed_at_utc)
        return append_or_update_opportunity(normalized, root=self.research_root, observed_at_utc=observed_at_utc)
