"""Factual freshness guard for volatile financial claims in scripts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .fact_sources import FactSourceError, TrustedFactProvider


class FactCheckFailed(RuntimeError):
    """Raised when volatile factual freshness validation fails."""

    def __init__(self, reason: str, metadata: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.metadata = metadata or {}


FX_RANGE_RE = re.compile(
    r"(?P<label>USD\s*/\s*TRY|USDTRY|Dolar\s*/\s*TL|Dolar\s*TL|dolar\s*kuru)[^\n]{0,40}?"
    r"(?P<low>\d{1,3}(?:[\.,]\d+)?)\s*(?:-|–|to|ile)\s*(?P<high>\d{1,3}(?:[\.,]\d+)?)\s*TL",
    re.IGNORECASE,
)
FX_SINGLE_RE = re.compile(
    r"(?P<label>USD\s*/\s*TRY|USDTRY|Dolar\s*/\s*TL|Dolar\s*TL|dolar\s*kuru)[^\n]{0,30}?"
    r"(?P<value>\d{1,3}(?:[\.,]\d+)?)\s*TL",
    re.IGNORECASE,
)

INFLATION_RE = re.compile(r"enflasyon[^\n]{0,25}?%\s*(\d{1,3}(?:[\.,]\d+)?)", re.IGNORECASE)
INTEREST_RE = re.compile(r"faiz[^\n]{0,25}?%\s*(\d{1,3}(?:[\.,]\d+)?)", re.IGNORECASE)
CRYPTO_RE = re.compile(r"(bitcoin|btc|ethereum|eth|altcoin)[^\n]{0,30}?(\d{2,8}(?:[\.,]\d+)?)", re.IGNORECASE)
STOCK_RE = re.compile(r"(bist|nasdaq|s&p|dow|hisse|endeks)[^\n]{0,30}?(\d{2,8}(?:[\.,]\d+)?)", re.IGNORECASE)
COMMODITY_RE = re.compile(r"(altin|ons|gram altin|gumus|petrol|brent)[^\n]{0,30}?(\d{1,6}(?:[\.,]\d+)?)", re.IGNORECASE)
DATE_RE = re.compile(r"(\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\bson\s+tarih\b|\bdeadline\b)", re.IGNORECASE)


@dataclass
class Claim:
    claim_type: str
    label: str
    raw_text: str
    context: str = ""
    historical_context: bool = False
    value_low: float | None = None
    value_high: float | None = None
    value_single: float | None = None


def _to_float(v: str) -> float:
    return float(v.replace(",", "."))


HISTORICAL_CONTEXT_RE = re.compile(
    r"(geçmişte|gecmiste|örnek olarak|ornek olarak|varsayalım|varsayalim|tarihsel olarak|"
    r"20\d{2}[’']?de|20\d{2}[’']?deki|örneğin|ornegin)",
    re.IGNORECASE,
)


def _split_sentences(script: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?\n])\s+", script)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def _sentence_has_historical_context(sentence: str) -> bool:
    return bool(HISTORICAL_CONTEXT_RE.search(sentence))


def extract_volatile_claims(script: str) -> list[Claim]:
    claims: list[Claim] = []
    sentences = _split_sentences(script)

    for sentence in sentences:
        sentence_historical = _sentence_has_historical_context(sentence)

        for m in FX_RANGE_RE.finditer(sentence):
            claims.append(
                Claim(
                    claim_type="fx_usd_try",
                    label="USD/TRY",
                    raw_text=m.group(0),
                    context=sentence,
                    historical_context=sentence_historical,
                    value_low=_to_float(m.group("low")),
                    value_high=_to_float(m.group("high")),
                )
            )
        for m in FX_SINGLE_RE.finditer(sentence):
            text = m.group(0)
            if any(c.raw_text == text for c in claims):
                continue
            claims.append(
                Claim(
                    claim_type="fx_usd_try",
                    label="USD/TRY",
                    raw_text=text,
                    context=sentence,
                    historical_context=sentence_historical,
                    value_single=_to_float(m.group("value")),
                )
            )

        for pattern, ctype, label in [
        (INFLATION_RE, "inflation", "inflation"),
        (INTEREST_RE, "interest", "interest_rate"),
        (CRYPTO_RE, "crypto", "crypto_price"),
        (STOCK_RE, "stock", "stock_price"),
        (COMMODITY_RE, "commodity", "commodity_price"),
        (DATE_RE, "date_deadline", "date_or_deadline"),
        ]:
            for m in pattern.finditer(sentence):
                claims.append(
                    Claim(
                        claim_type=ctype,
                        label=label,
                        raw_text=m.group(0),
                        context=sentence,
                        historical_context=sentence_historical,
                    )
                )

    return claims


def _validate_usd_try_claim(claim: Claim, live_rate: float, tolerance_pct: float) -> tuple[bool, str]:
    if claim.value_single is not None:
        low = claim.value_single * (1.0 - tolerance_pct)
        high = claim.value_single * (1.0 + tolerance_pct)
    else:
        low = (claim.value_low or 0.0) * (1.0 - tolerance_pct)
        high = (claim.value_high or 0.0) * (1.0 + tolerance_pct)
    ok = low <= live_rate <= high
    if ok:
        return True, ""
    return (
        False,
        f"USD/TRY stale claim: script='{claim.raw_text}' live={live_rate:.2f} outside [{low:.2f}, {high:.2f}]",
    )


def validate_script_factual_freshness(
    script: str,
    provider: TrustedFactProvider,
    *,
    tolerance_pct: float = 0.08,
) -> dict:
    """Validate volatile factual claims against trusted live sources.

    Returns validation metadata on pass.
    Raises FactCheckFailed on any policy/verification failure.
    """
    claims = extract_volatile_claims(script)
    if not claims:
        return {
            "fact_check_status": "passed",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "sources": [],
            "volatile_claims_checked": [],
            "historical_claims_exempted": [],
        }

    checked_labels: list[str] = []
    sources: list[str] = []
    historical_exemptions: list[str] = []

    for claim in claims:
        if claim.historical_context:
            historical_exemptions.append(claim.raw_text)
            continue

        if claim.claim_type == "fx_usd_try":
            try:
                usd_try = provider.get_usd_try()
            except FactSourceError as e:
                raise FactCheckFailed(f"fx_source_unavailable: {e}") from e
            ok, reason = _validate_usd_try_claim(claim, usd_try.value, tolerance_pct)
            if not ok:
                raise FactCheckFailed(reason)
            checked_labels.append("USD/TRY")
            if usd_try.source not in sources:
                sources.append(usd_try.source)
        elif claim.claim_type in {"inflation", "interest", "crypto", "stock", "commodity", "date_deadline"}:
            raise FactCheckFailed(
                f"unverifiable_volatile_claim: '{claim.raw_text}' ({claim.claim_type})"
            )

    metadata = {
        "fact_check_status": "passed",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "volatile_claims_checked": sorted(set(checked_labels)),
        "historical_claims_exempted": historical_exemptions,
    }

    # Hard rule: scripts with live market data must carry freshness metadata.
    if any(
        c.claim_type in {"fx_usd_try", "crypto", "stock", "commodity", "inflation", "interest"}
        and not c.historical_context
        for c in claims
    ):
        if not metadata.get("checked_at") or not metadata.get("sources"):
            raise FactCheckFailed("missing_freshness_metadata_for_market_data", metadata=metadata)

    return metadata
