"""Macroeconomic adapter for the Fact Bundle provider layer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from .fact_bundle import FactTemporalScope, FactVolatility
from .fact_bundle_providers import FactDataProvider, ProviderError, ProviderFactResponse


class MacroFactProviderError(ProviderError):
    """Raised when macroeconomic provider fetch or payload parsing fails."""


def _parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LiveMacroFactProvider(FactDataProvider):
    """Provider adapter fetching macroeconomic series from a trusted endpoint."""

    def __init__(
        self,
        *,
        provider_name: str = "live_macro",
        timeout_sec: float = 5.0,
        source_label: str = "macro_api",
        ttl_sec: int = 86400,
        confidence: float = 0.9,
        endpoint_template: str = "https://api.example.com/macro/{series}",
        series_map: dict[str, str] | None = None,
    ):
        self._provider_name = provider_name
        self._timeout_sec = timeout_sec
        self._source_label = source_label
        self._ttl_sec = ttl_sec
        self._confidence = confidence
        self._endpoint_template = endpoint_template
        self._series_map = series_map or {
            "us_cpi_yoy": "US_CPI_YOY",
            "us_unemployment_rate": "US_UNEMP_RATE",
            "us_policy_rate": "US_POLICY_RATE",
        }

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def timeout_sec(self) -> float:
        return self._timeout_sec

    def fetch(self, key: str) -> ProviderFactResponse:
        normalized_key = key.strip().lower()
        series = self._series_map.get(normalized_key)
        if not series:
            raise MacroFactProviderError(
                f"unsupported_macro_key: {key}",
                provider_name=self.provider_name,
                key=key,
            )

        url = self._endpoint_template.format(series=series)
        try:
            req = Request(url, headers={"User-Agent": "para-pusulasi-macro-facts/1.0"})
            with urlopen(req, timeout=self.timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))

            value = float(payload["value"])
            collected_at = _parse_timestamp(payload.get("as_of"))
        except Exception as e:
            raise MacroFactProviderError(
                f"macro_fetch_failed: {e}",
                provider_name=self.provider_name,
                key=key,
            ) from e

        return ProviderFactResponse(
            key=normalized_key,
            value=value,
            unit="percent",
            source=self._source_label,
            collected_at=collected_at,
            confidence=self._confidence,
            volatility=FactVolatility.MEDIUM,
            historical_current=FactTemporalScope.CURRENT,
            ttl=self._ttl_sec,
        )


__all__ = ["LiveMacroFactProvider", "MacroFactProviderError"]
