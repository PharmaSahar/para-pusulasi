"""Market indices adapter for the Fact Bundle provider layer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from .fact_bundle import FactTemporalScope, FactVolatility
from .fact_bundle_providers import FactDataProvider, ProviderError, ProviderFactResponse


class MarketFactProviderError(ProviderError):
    """Raised when market fact provider fetch/parsing fails."""


def _parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LiveMarketFactProvider(FactDataProvider):
    """Provider adapter fetching market index values from a trusted endpoint."""

    def __init__(
        self,
        *,
        provider_name: str = "live_market",
        timeout_sec: float = 5.0,
        source_label: str = "market_api",
        ttl_sec: int = 300,
        confidence: float = 0.9,
        endpoint_template: str = "https://api.example.com/indices/{symbol}",
        index_map: dict[str, str] | None = None,
    ):
        self._provider_name = provider_name
        self._timeout_sec = timeout_sec
        self._source_label = source_label
        self._ttl_sec = ttl_sec
        self._confidence = confidence
        self._endpoint_template = endpoint_template
        self._index_map = index_map or {
            "bist100": "XU100",
            "sp500": "SPX",
            "nasdaq100": "NDX",
        }

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def timeout_sec(self) -> float:
        return self._timeout_sec

    def fetch(self, key: str) -> ProviderFactResponse:
        normalized_key = key.strip().lower()
        symbol = self._index_map.get(normalized_key)
        if not symbol:
            raise MarketFactProviderError(
                f"unsupported_market_key: {key}",
                provider_name=self.provider_name,
                key=key,
            )

        url = self._endpoint_template.format(symbol=symbol)
        try:
            req = Request(url, headers={"User-Agent": "para-pusulasi-market-facts/1.0"})
            with urlopen(req, timeout=self.timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))

            value = float(payload["value"])
            collected_at = _parse_timestamp(payload.get("as_of"))
        except Exception as e:
            raise MarketFactProviderError(
                f"market_fetch_failed: {e}",
                provider_name=self.provider_name,
                key=key,
            ) from e

        return ProviderFactResponse(
            key=normalized_key,
            value=value,
            unit="index_points",
            source=self._source_label,
            collected_at=collected_at,
            confidence=self._confidence,
            volatility=FactVolatility.HIGH,
            historical_current=FactTemporalScope.CURRENT,
            ttl=self._ttl_sec,
        )


__all__ = ["LiveMarketFactProvider", "MarketFactProviderError"]