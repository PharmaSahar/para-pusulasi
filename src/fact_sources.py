"""Live trusted fact sources used by factual freshness guard."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class FactSourceError(RuntimeError):
    """Raised when trusted fact source fetch fails."""


@dataclass
class FactValue:
    name: str
    value: float
    source: str


class TrustedFactProvider:
    """Interface for live fact lookups used by factual freshness checks."""

    def get_usd_try(self) -> FactValue:
        raise NotImplementedError


class LiveFXProvider(TrustedFactProvider):
    """Fetches USD/TRY using a trusted live provider endpoint."""

    def __init__(self, timeout_sec: float = 8.0, *, url: str | None = None, source_label: str | None = None):
        self.timeout_sec = timeout_sec
        self.url = url or os.getenv(
            "TRUSTED_FX_PROVIDER_URL",
            "https://api.frankfurter.app/latest?from=USD&to=TRY",
        )
        self.source_label = source_label or os.getenv("TRUSTED_FX_SOURCE_LABEL", "trusted_fx_provider")

    def get_usd_try(self) -> FactValue:
        try:
            req = Request(self.url, headers={"User-Agent": "para-pusulasi-fact-check/1.0"})
            with urlopen(req, timeout=self.timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            rate = float(payload["rates"]["TRY"])
            return FactValue(name="USD/TRY", value=rate, source=self.source_label)
        except Exception as e:
            raise FactSourceError(f"usd_try_fetch_failed: {e}") from e


class FallbackFXProvider(TrustedFactProvider):
    """Try multiple trusted FX providers and fail closed if all are unavailable."""

    def __init__(self, providers: list[TrustedFactProvider]):
        self.providers = providers

    def get_usd_try(self) -> FactValue:
        errors: list[str] = []
        for provider in self.providers:
            try:
                return provider.get_usd_try()
            except FactSourceError as e:
                errors.append(str(e))
        raise FactSourceError("; ".join(errors) or "all_fx_providers_failed")


def _build_default_provider_specs() -> list[tuple[str, str]]:
    urls = os.getenv(
        "TRUSTED_FX_PROVIDER_URLS",
        "https://api.frankfurter.app/latest?from=USD&to=TRY,https://api.exchangerate.host/latest?base=USD&symbols=TRY",
    )
    labels = os.getenv("TRUSTED_FX_PROVIDER_LABELS", "").split(",")
    url_list = [item.strip() for item in urls.split(",") if item.strip()]
    label_list = [item.strip() for item in labels if item.strip()]

    specs: list[tuple[str, str]] = []
    for index, url in enumerate(url_list):
        label = label_list[index] if index < len(label_list) else urlparse(url).netloc or f"trusted_fx_provider_{index + 1}"
        specs.append((url, label))
    return specs


def build_default_fact_provider() -> TrustedFactProvider:
    providers = [LiveFXProvider(url=url, source_label=label) for url, label in _build_default_provider_specs()]
    return FallbackFXProvider(providers)
