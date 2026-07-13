"""Slice 3 Phase 2 shadow-mode content quality integration.

This module is strictly advisory and fail-open. It must never block, mutate,
or regenerate content.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
from typing import Any, Literal

from .learning_foundation import (
    QUALITY_SCORE_SCHEMA_VERSION,
    QualityValidationInput,
    content_hash,
    detect_duplicate_text,
    detect_guaranteed_return_wording,
    detect_repeated_cta,
    detect_repetitive_opening,
    detect_unsupported_financial_claims,
    detect_unverifiable_insider_information,
    evaluate_quality_checkpoints,
    semantic_similarity_score,
    tokenize_text,
)
from .shadow_quality_taxonomy import (
    ConfidenceLevel,
    SeverityLevel,
    TAXONOMY_VERSION,
    get_finding_spec,
)
from .shadow_review_contract import build_human_review_item


SHADOW_CONTENT_QUALITY_SCHEMA_VERSION = "v2"
SHADOW_CONTENT_QUALITY_VALIDATOR_VERSION = "v2"
SHADOW_RESULTS_PATH = Path("logs/shadow_content_quality_results.jsonl")
SHADOW_MODE_ENV = "CONTENT_QUALITY_SHADOW_MODE_ENABLED"
DEFAULT_HISTORY_WINDOW = 250
EXACT_DUPLICATE_THRESHOLD = 0.97
NEAR_DUPLICATE_THRESHOLD = 0.84

_TRUE_VALUES = {"1", "true", "yes", "on"}


class ShadowQualityValidationError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(value: str | None) -> str:
    return content_hash(value or "")


def _bounded_excerpt(value: str | None, *, limit: int = 180) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def content_quality_shadow_mode_enabled(value: object | None = None) -> bool:
    """Strict opt-in parser for shadow-mode feature flag.

    Disabled on absent/empty/malformed values unless explicitly true.
    """
    raw = os.getenv(SHADOW_MODE_ENV) if value is None else value
    if raw is None:
        return False
    normalized = str(raw).strip().lower()
    if not normalized:
        return False
    return normalized in _TRUE_VALUES


@dataclass(frozen=True)
class ShadowEvaluationContext:
    schema_version: str
    evaluation_id: str
    run_id: str
    content_id: str
    channel_id: str
    content_type: Literal["video", "short", "mixed"]
    created_at: str
    topic: str
    title: str
    script: str
    description: str
    thumbnail_prompt: str
    cta_text: str
    topic_hash: str
    title_hash: str
    script_hash: str
    description_hash: str
    thumbnail_prompt_hash: str
    cta_hash: str

    def debug_payload(self) -> dict[str, Any]:
        """Return only bounded non-secret debug payload."""
        return {
            "topic_excerpt": _bounded_excerpt(self.topic, limit=120),
            "title_excerpt": _bounded_excerpt(self.title, limit=120),
            "thumbnail_prompt_excerpt": _bounded_excerpt(self.thumbnail_prompt, limit=160),
            "topic_hash": self.topic_hash,
            "title_hash": self.title_hash,
            "script_hash": self.script_hash,
            "description_hash": self.description_hash,
            "thumbnail_prompt_hash": self.thumbnail_prompt_hash,
        }


@dataclass(frozen=True)
class ShadowFinding:
    code: str
    category: str
    severity: SeverityLevel
    confidence: ConfidenceLevel
    validator_version: str
    message: str
    affected_artifact: str
    evidence_excerpt: str
    evidence_hash: str
    remediation_class: str
    blocking_eligible_future: bool
    mode: Literal["advisory"]
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShadowQualityScore:
    score_name: str
    score_value: float
    status: Literal["pass", "warn", "fail"]
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _status_for_score(value: float, *, warn_below: float = 0.7, fail_below: float = 0.45) -> Literal["pass", "warn", "fail"]:
    if value < fail_below:
        return "fail"
    if value < warn_below:
        return "warn"
    return "pass"


_SEVERITY_ORDER: dict[SeverityLevel, int] = {
    "INFO": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


def _max_severity(findings: list[ShadowFinding]) -> Literal["low", "medium", "high", "none"]:
    if not findings:
        return "none"
    highest = sorted((f.severity for f in findings), key=lambda x: _SEVERITY_ORDER.get(x, 0))[-1]
    if highest in {"INFO", "LOW"}:
        return "low"
    if highest == "MEDIUM":
        return "medium"
    return "high"


def _max_severity_level(findings: list[ShadowFinding]) -> SeverityLevel:
    if not findings:
        return "INFO"
    return sorted((f.severity for f in findings), key=lambda x: _SEVERITY_ORDER.get(x, 0))[-1]


def _normalize_word_tokens(text: str | None) -> list[str]:
    return tokenize_text(text or "")


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", str(text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _keyword_set(text: str) -> set[str]:
    return {token for token in _normalize_word_tokens(text) if len(token) >= 3}


def _normalize_for_match(text: str | None) -> str:
    value = str(text or "").lower()
    tr_map = str.maketrans({
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "İ": "i",
    })
    value = value.translate(tr_map)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip()


_NEGATION_MARKERS = {
    "guvenmeyin",
    "güvenmeyin",
    "yoktur",
    "degildir",
    "değildir",
    "kesin degildir",
    "kesin değildir",
    "garanti etmez",
    "iddialarina",
    "uyari",
    "uyarı",
    "tavsiyesi degildir",
    "tavsiyesi değildir",
}

_HYPOTHETICAL_MARKERS = {
    "ornek",
    "örnek",
    "varsayalim",
    "varsayalım",
    "diyelim",
    "iddia",
    "iddiasi",
    "iddiası",
    "quote",
    "alıntı",
    "alinti",
}


def _window(text: str, start: int, end: int, *, radius: int = 60) -> str:
    return text[max(0, start - radius): min(len(text), end + radius)]


def _has_any(window_text: str, markers: set[str]) -> bool:
    lower = window_text.lower()
    return any(marker in lower for marker in markers)


def _contextual_pattern_detection(text: str, patterns: list[str]) -> dict[str, list[str]]:
    lower = _normalize_for_match(text)
    assertive: list[str] = []
    negated: list[str] = []
    ambiguous: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, lower):
            ctx = _window(lower, match.start(), match.end())
            if _has_any(ctx, _NEGATION_MARKERS):
                negated.append(pattern)
            elif _has_any(ctx, _HYPOTHETICAL_MARKERS):
                ambiguous.append(pattern)
            else:
                assertive.append(pattern)
    return {
        "assertive": assertive,
        "negated": negated,
        "ambiguous": ambiguous,
    }


def _financial_risk_signal(text: str, *, patterns: list[str]) -> tuple[float, SeverityLevel, ConfidenceLevel, dict[str, list[str]]]:
    detail = _contextual_pattern_detection(text, patterns)
    if detail["assertive"]:
        return 0.0, "HIGH", "HIGH", detail
    if detail["ambiguous"]:
        return 0.4, "MEDIUM", "MEDIUM", detail
    if detail["negated"]:
        return 0.9, "INFO", "HIGH", detail
    return 1.0, "INFO", "HIGH", detail


def _detect_not_priced_in_claims(text: str) -> list[str]:
    patterns = [
        r"\b(fiyata|fiyatlara)\s+yansimadi\b",
        r"\b(not\s+yet\s+priced\s+in)\b",
        r"\b(piyasaya\s+hen[uz]+\s+yansimadi)\b",
        r"\bhen[uz]+\s+fiyatlanmadi\b",
    ]
    normalized = _normalize_for_match(text)
    return [p for p in patterns if re.search(p, normalized)]


def _detect_secret_institutional_claims(text: str) -> list[str]:
    patterns = [
        r"\b(kurumlar\s+ozel\s+toplantida)\b",
        r"\b(fonlar\s+gizlice\s+topluyor)\b",
        r"\b(fonlarin\s+gizlice\s+topladigi)\b",
        r"\b(kurumsal\s+yatirimci\w*\s+gizli)\b",
        r"\b(yatirim\s+komitesinde\s+konusuluyor)\b",
        r"\b(toplanti\s+odalarinda\s+konusulan)\b",
    ]
    normalized = _normalize_for_match(text)
    return [p for p in patterns if re.search(p, normalized)]


def _detect_extreme_return_claims(text: str) -> list[str]:
    patterns = [
        r"\b%\s*(2\d\d|[3-9]\d)\b",
        r"\b(\d{2,4})\s*%\s*(getiri|kazanc|kar)\b",
        r"\b\d+\s+kat\s+kazanc\b",
        r"\byuzde\s*(2\d\d|[3-9]\d{1,3})\s*(getiri|kazanc|kar)?\b",
    ]
    normalized = _normalize_for_match(text)
    return [p for p in patterns if re.search(p, normalized)]


def _detect_urgent_trade_pressure(text: str) -> list[str]:
    patterns = [
        r"\bhemen\s+al\b",
        r"\bgec\s+kalmadan\s+sat\b",
        r"\bson\s+sansi?\b",
        r"\bbugun\s+almazsan\b",
    ]
    normalized = _normalize_for_match(text)
    return [p for p in patterns if re.search(p, normalized)]


def _detect_specific_security_certainty(text: str) -> list[str]:
    patterns = [
        r"\b(hisse|coin|btc|eth|bist\s*100)\b.{0,30}\b(kesin|garanti)\b.{0,30}\b(yukselir|artar|ucacak)\b",
        r"\b(xu100|bist\s*100)\b.{0,25}\b(kesin)\b",
    ]
    normalized = _normalize_for_match(text)
    return [p for p in patterns if re.search(p, normalized)]


def _detect_fabricated_authority(text: str) -> list[str]:
    patterns = [
        r"\b(uzmanlar\s+diyor\s+ki)\b",
        r"\b(iceriden\s+kaynaklar)\b",
        r"\b(kaynak\s+vermeyecegim\s+ama)\b",
        r"\b(ust\s+duzey\s+isim\s+paylasti)\b",
    ]
    normalized = _normalize_for_match(text)
    return [p for p in patterns if re.search(p, normalized)]


def _detect_pump_style_title(title: str) -> list[str]:
    patterns = [
        r"\b(ucacak|patlayacak|roket|moon|x10|x100)\b",
        r"\b(hemen\s+al|son\s+firsat)\b",
    ]
    normalized = _normalize_for_match(title)
    return [p for p in patterns if re.search(p, normalized)]


_TICKER_TO_COMPANY = {
    "THYAO": ["turk hava", "turk hava yollari"],
    "ASELS": ["aselsan"],
    "SISE": ["sisecam", "şişecam"],
    "KCHOL": ["koc", "koç"],
    "SAHOL": ["sabanci", "sabancı"],
}

_UNSUPPORTED_CLAIM_PATTERNS = [
    r"\bkesin\s+(kazanc|getiri|kar)\b",
    r"\bgaranti\s+(kazanc|getiri|kar)\b",
    r"\bgaranti\s+kazan(c|ç)\b",
    r"\bkesin\s+yuksel(ecek|ir)\b",
    r"\byuzde\s*100\s*garanti\b",
]

_INSIDER_PATTERNS = [
    r"\biceriden\s+bilgi\b",
    r"\bi[çc]eriden\s+alinan\s+bilgi\b",
    r"\binsider\s+bilgi\b",
    r"\bgizli\s+kaynak\b",
    r"\bkimsenin\s+bilmedigi\b",
    r"\byatirimcilarin\s+bilmedigi\s+sir\b",
    r"\bkurumlarin\s+sakladigi\s+bilgi\b",
]

_GUARANTEE_PATTERNS = [
    r"\bgaranti\s+getiri\b",
    r"\brisksiz\s+kazanc\b",
    r"\bzarar\s+etmezsin\b",
    r"\bkesin\s+yukselir\b",
    r"\bka(c|ç)irilmayacak\s+firsat\b",
    r"\bson\s+sansi?\b",
]


def _detect_ticker_company_mismatch(text: str) -> list[str]:
    findings: list[str] = []
    normalized = _normalize_for_match(text)
    for ticker, aliases in _TICKER_TO_COMPANY.items():
        if ticker.lower() in normalized and not any(alias in normalized for alias in aliases):
            for other_ticker, other_aliases in _TICKER_TO_COMPANY.items():
                if other_ticker == ticker:
                    continue
                if any(alias in normalized for alias in other_aliases):
                    findings.append(f"ticker_company_mismatch:{ticker}:{other_ticker}")
                    break
    return findings


def _detect_unrelated_person_or_scene(prompt: str, title: str, script: str) -> list[str]:
    prompt_tokens = _keyword_set(prompt)
    ref_tokens = _keyword_set(f"{title} {script}")
    if not prompt_tokens:
        return []
    overlap = len(prompt_tokens & ref_tokens)
    ratio = overlap / max(1, len(prompt_tokens))
    if ratio >= 0.35:
        return []
    return ["thumbnail_prompt_low_relevance"]


def _detect_misleading_wealth_imagery(prompt: str, text: str) -> list[str]:
    combined = f"{prompt} {text}".lower()
    patterns = [
        r"\bluxury\b",
        r"\bprivate\s+jet\b",
        r"\binstant\s+rich\b",
        r"\bsonsuz\s+zenginlik\b",
        r"\bgaranti\s+kar\b",
    ]
    return [p for p in patterns if re.search(p, combined)]


def _detect_misleading_external_link_context(text: str) -> list[str]:
    combined = str(text or "").lower()
    if "http" not in combined and "www." not in combined:
        return []
    patterns = [
        r"\blinkte\s+garanti\b",
        r"\bkesin\s+kazanacaksiniz\b",
        r"\bsadece\s+linke\s+tiklayin\b",
    ]
    return [p for p in patterns if re.search(p, combined)]


def _short_starts_mid_sentence(short_script: str) -> bool:
    stripped = str(short_script or "").strip()
    if not stripped:
        return False
    tokens = _normalize_word_tokens(stripped)
    first = tokens[0] if tokens else ""
    # A conjunction at the beginning is common in Turkish spoken clips.
    # Mark as abrupt only when the clip is also short and context-poor.
    if first in {"ve", "ama", "fakat", "ancak", "çünkü", "cunku"}:
        return len(tokens) < 24
    if first in {"bu", "şu", "su", "o", "onlar", "bunu", "bunun"} and len(tokens) < 36:
        return True
    return stripped[0].islower()


def _short_ends_mid_sentence(short_script: str) -> bool:
    stripped = str(short_script or "").strip()
    if not stripped:
        return False
    return stripped[-1] not in ".!?"


def _short_missing_context(short_script: str) -> bool:
    tokens = _normalize_word_tokens(short_script)
    if len(tokens) < 30:
        return True
    pronoun_start = bool(tokens and tokens[0] in {"bu", "su", "şu", "o", "bunu", "onu"})
    return pronoun_start and len(tokens) < 60


def _short_missing_hook(short_script: str, short_title: str) -> bool:
    first_window = " ".join(_normalize_word_tokens(short_script)[:18])
    if "?" in short_script[:120] or any(ch.isdigit() for ch in short_script[:120]):
        return False
    hook_words = {"neden", "dikkat", "sok", "şok", "hemen", "kritik", "en"}
    if any(word in first_window for word in hook_words):
        return False
    return semantic_similarity_score(short_script, short_title) < 0.08


def _short_context_payoff_imbalance(short_script: str) -> tuple[bool, bool]:
    text = _normalize_for_match(short_script)
    context_markers = sum(text.count(token) for token in ["neden", "arka plan", "sebep", "baglam"])
    payoff_markers = sum(text.count(token) for token in ["sonuc", "cozum", "adim", "kazanc", "ozet"])
    if any(marker in text for marker in ["sonuc yok", "cozum yok", "payoff yok"]):
        payoff_markers = 0
    context_without_payoff = context_markers > 2 and payoff_markers == 0
    payoff_without_context = payoff_markers > 2 and context_markers == 0
    return context_without_payoff, payoff_without_context


def _short_duration_signal(short_script: str, target_min_words: int = 120, target_max_words: int = 420) -> tuple[float, bool]:
    words = len(_normalize_word_tokens(short_script))
    if words < target_min_words:
        return words / max(1.0, float(target_min_words)), True
    if words > target_max_words:
        return max(0.0, 1.0 - ((words - target_max_words) / float(target_max_words))), True
    return 1.0, False


def build_shadow_evaluation_context(
    *,
    run_id: str,
    content_id: str,
    channel_id: str,
    content_type: Literal["video", "short", "mixed"],
    topic: str,
    title: str,
    script: str,
    description: str,
    thumbnail_prompt: str,
    cta_text: str,
    created_at: str | None = None,
) -> ShadowEvaluationContext:
    created = str(created_at or _now_iso())
    base = f"{run_id}|{content_id}|{channel_id}|{created}"
    evaluation_id = hashlib.sha256(base.encode("utf-8")).hexdigest()[:20]
    return ShadowEvaluationContext(
        schema_version=SHADOW_CONTENT_QUALITY_SCHEMA_VERSION,
        evaluation_id=evaluation_id,
        run_id=str(run_id or "").strip(),
        content_id=str(content_id or "").strip(),
        channel_id=str(channel_id or "").strip(),
        content_type=content_type,
        created_at=created,
        topic=str(topic or "").strip(),
        title=str(title or "").strip(),
        script=str(script or "").strip(),
        description=str(description or "").strip(),
        thumbnail_prompt=str(thumbnail_prompt or "").strip(),
        cta_text=str(cta_text or "").strip(),
        topic_hash=_sha(topic),
        title_hash=_sha(title),
        script_hash=_sha(script),
        description_hash=_sha(description),
        thumbnail_prompt_hash=_sha(thumbnail_prompt),
        cta_hash=_sha(cta_text),
    )


def _severity_for_status(status: str) -> SeverityLevel:
    status_n = str(status or "").lower()
    if status_n == "fail":
        return "HIGH"
    if status_n == "warn":
        return "MEDIUM"
    return "LOW"


def _score_dict(name: str, value: float, *, warn_below: float = 0.7, fail_below: float = 0.45, details: dict[str, Any] | None = None) -> ShadowQualityScore:
    return ShadowQualityScore(
        score_name=name,
        score_value=round(float(value), 4),
        status=_status_for_score(float(value), warn_below=warn_below, fail_below=fail_below),
        details=details or {},
    )


def _build_finding(
    code: str,
    severity: SeverityLevel,
    message: str,
    *,
    confidence: ConfidenceLevel | None = None,
    details: dict[str, Any] | None = None,
    evidence_excerpt: str | None = None,
    evidence_hash: str | None = None,
) -> ShadowFinding:
    spec = get_finding_spec(code)
    return ShadowFinding(
        code=code,
        category=spec.category,
        severity=severity,
        confidence=confidence or spec.default_confidence,
        validator_version=spec.validator_version,
        message=message,
        affected_artifact=spec.affected_artifact,
        evidence_excerpt=_bounded_excerpt(evidence_excerpt, limit=180),
        evidence_hash=str(evidence_hash or ""),
        remediation_class=spec.remediation_class,
        blocking_eligible_future=bool(spec.blocking_eligible_future),
        mode="advisory",
        details=details or {},
    )


def _recent_script_snapshots(channel_id: str, limit: int = 30) -> list[dict[str, Any]]:
    try:
        from .content_quality_guard import _load_recent_scripts  # local deterministic store

        rows = _load_recent_scripts(channel_id)
        if not isinstance(rows, list):
            return []
        return rows[-limit:]
    except Exception:
        return []


def load_shadow_results(
    *,
    input_path: Path | str = SHADOW_RESULTS_PATH,
    limit: int = 200,
    checkpoint: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Load recent shadow rows.

    Returns (rows, malformed_line_count). Malformed lines are skipped safely.
    """
    path = Path(input_path)
    if not path.exists():
        return [], 0

    rows: list[dict[str, Any]] = []
    malformed = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            malformed += 1
            continue
        if checkpoint and str(row.get("checkpoint") or "") != checkpoint:
            continue
        rows.append(row)
    if limit > 0:
        rows = rows[-limit:]
    return rows, malformed


def validate_shadow_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ShadowQualityValidationError("invalid_payload")
    required = [
        "schema_version",
        "evaluation_id",
        "run_id",
        "channel_id",
        "content_type",
        "topic_hash",
        "title_hash",
        "script_hash",
        "checkpoint",
        "quality_scores",
        "findings",
        "severity",
        "validator_versions",
        "created_at",
        "shadow_mode_enabled",
    ]
    for key in required:
        value = row.get(key)
        if value is None:
            raise ShadowQualityValidationError(f"missing_field:{key}")
        if isinstance(value, str) and not value.strip():
            raise ShadowQualityValidationError(f"missing_field:{key}")

    if not isinstance(row.get("quality_scores"), list):
        raise ShadowQualityValidationError("invalid_field:quality_scores")
    if not isinstance(row.get("findings"), list):
        raise ShadowQualityValidationError("invalid_field:findings")
    if row.get("severity") not in {"none", "low", "medium", "high"}:
        raise ShadowQualityValidationError("invalid_field:severity")
    if not isinstance(row.get("validator_versions"), dict):
        raise ShadowQualityValidationError("invalid_field:validator_versions")

    schema = str(row.get("schema_version") or "")
    if schema not in {"v1", "v2"}:
        raise ShadowQualityValidationError("invalid_field:schema_version")

    for finding in row.get("findings") or []:
        if not isinstance(finding, dict):
            raise ShadowQualityValidationError("invalid_field:findings_item")
        if not str(finding.get("code") or "").strip():
            raise ShadowQualityValidationError("invalid_field:findings_item.code")
        sev = str(finding.get("severity") or "").upper()
        if sev and sev not in {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            raise ShadowQualityValidationError("invalid_field:findings_item.severity")

    created = str(row.get("created_at") or "")
    try:
        datetime.fromisoformat(created.replace("Z", "+00:00"))
    except Exception as exc:
        raise ShadowQualityValidationError("invalid_field:created_at") from exc

    normalized = dict(row)
    normalized["schema_version"] = str(normalized.get("schema_version"))
    normalized["evaluation_id"] = str(normalized.get("evaluation_id"))
    normalized["run_id"] = str(normalized.get("run_id"))
    normalized["channel_id"] = str(normalized.get("channel_id"))
    normalized["checkpoint"] = str(normalized.get("checkpoint"))
    normalized["shadow_mode_enabled"] = bool(normalized.get("shadow_mode_enabled"))
    if "pipeline_output_changed" not in normalized:
        normalized["pipeline_output_changed"] = False
    if "current_mode" not in normalized:
        normalized["current_mode"] = "advisory"
    return normalized


def append_shadow_row(row: dict[str, Any], *, output_path: Path | str = SHADOW_RESULTS_PATH) -> None:
    payload = validate_shadow_row(row)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)


def _hashes_for_payload(*, topic: str, title: str, script: str, description: str, thumbnail_text: str, short_script: str) -> dict[str, str]:
    return {
        "topic_hash": _sha(topic),
        "title_hash": _sha(title),
        "script_hash": _sha(script),
        "title_simhash": _simhash64_hex(title),
        "script_simhash": _simhash64_hex(script),
        "script_opening_hash": _sha(str(script or "")[:220]),
        "description_hash": _sha(description),
        "thumbnail_text_hash": _sha(thumbnail_text),
        "short_script_hash": _sha(short_script),
    }


def _simhash64_hex(text: str | None) -> str:
    tokens = _normalize_word_tokens(text or "")
    if not tokens:
        return "0" * 16
    bits = [0] * 64
    for token in tokens:
        h = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:16], 16)
        for idx in range(64):
            bits[idx] += 1 if (h >> idx) & 1 else -1
    out = 0
    for idx, weight in enumerate(bits):
        if weight >= 0:
            out |= (1 << idx)
    return f"{out:016x}"


def _hamming_hex(left: str, right: str) -> int:
    try:
        return int(bin(int(left, 16) ^ int(right, 16)).count("1"))
    except Exception:
        return 64


def _score_average(scores: list[ShadowQualityScore]) -> float:
    if not scores:
        return 0.0
    return round(sum(item.score_value for item in scores) / len(scores), 4)


def _serialize_scores(scores: list[ShadowQualityScore]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in scores]


def _serialize_findings(findings: list[ShadowFinding]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in findings]


def _score_family_mean(scores: list[ShadowQualityScore], families: tuple[str, ...]) -> float:
    matched = [item.score_value for item in scores if item.score_name.startswith(families)]
    if not matched:
        return 0.0
    return round(sum(matched) / len(matched), 4)


def _aggregate_metrics(scores: list[ShadowQualityScore], findings: list[ShadowFinding]) -> dict[str, Any]:
    high_conf = sum(1 for item in findings if item.confidence == "HIGH")
    max_sev = _max_severity_level(findings)
    return {
        "overall_checkpoint_score": _score_average(scores),
        "highest_severity_level": max_sev,
        "finding_count": len(findings),
        "high_confidence_finding_count": high_conf,
        "financial_risk_score": _score_family_mean(
            scores,
            (
                "unsupported_financial_claim",
                "unverifiable_insider",
                "guaranteed_return",
                "not_priced_in",
                "secret_institutional",
                "extreme_return",
                "urgent_trade_pressure",
                "specific_security_certainty",
                "fabricated_authority",
            ),
        ),
        "semantic_consistency_score": _score_family_mean(
            scores,
            (
                "title_script_",
                "script_description_",
                "title_thumbnail_",
                "script_shorts_",
                "title_description_",
                "shorts_title_content_",
                "ticker_company_",
            ),
        ),
        "duplication_score": _score_family_mean(scores, ("duplicate_",)),
        "shorts_quality_score": _score_family_mean(scores, ("shorts_",)),
    }


def _seo_discovery_observability(
    *,
    title: str,
    description: str,
    tags: list[str] | None,
    playlist_recommendation: str | None,
    card_recommendation: str | None,
    end_screen_recommendation: str | None,
) -> dict[str, Any]:
    tag_items = [str(item).strip() for item in (tags or []) if str(item).strip()]
    hashtags = re.findall(r"#[A-Za-z0-9_çğıöşüÇĞİÖŞÜ]+", str(description or ""))

    title_keywords = sorted(_keyword_set(title))[:12]
    description_keywords = sorted(_keyword_set(description))[:20]

    def _status_for_text(value: str | None) -> str:
        return "generated" if str(value or "").strip() else "absent"

    return {
        "tags": {
            "state": "generated" if tag_items else "absent",
            "count": len(tag_items),
            "values": tag_items[:15],
        },
        "hashtags": {
            "state": "generated" if hashtags else "absent",
            "count": len(hashtags),
            "values": hashtags[:20],
        },
        "playlist_recommendation": {
            "state": "recommendation_generated" if playlist_recommendation else "recommendation_absent",
            "value": str(playlist_recommendation or "")[:120],
            "applied": "unknown",
        },
        "card_recommendation": {
            "state": _status_for_text(card_recommendation) if card_recommendation else "not_implemented",
            "value": str(card_recommendation or "")[:120],
            "applied": "unknown",
        },
        "end_screen_recommendation": {
            "state": _status_for_text(end_screen_recommendation) if end_screen_recommendation else "not_implemented",
            "value": str(end_screen_recommendation or "")[:120],
            "applied": "unknown",
        },
        "title_keywords": title_keywords,
        "description_keywords": description_keywords,
        "live_youtube_state": "unknown",
    }


def infer_playlist_recommendation_from_title(title: str) -> str | None:
    """Infer playlist recommendation using existing local mapping rules only."""
    try:
        from .playlist_manager import PLAYLIST_MAP

        lower = str(title or "").lower()
        for keywords, playlist_name in PLAYLIST_MAP.items():
            if any(str(keyword).lower() in lower for keyword in keywords):
                return str(playlist_name)
    except Exception:
        return None
    return "Genel Finans Rehberi 2026"


class ShadowContentQualityEngine:
    """Single-transaction evaluator with immutable base context."""

    def __init__(
        self,
        *,
        context: ShadowEvaluationContext,
        results_path: Path | str = SHADOW_RESULTS_PATH,
        history_window: int = DEFAULT_HISTORY_WINDOW,
    ):
        self.context = context
        self.results_path = Path(results_path)
        self.history_window = max(10, int(history_window or DEFAULT_HISTORY_WINDOW))
        self._recent_script_rows = _recent_script_snapshots(context.channel_id)
        recent_rows, malformed_count = load_shadow_results(input_path=self.results_path, limit=self.history_window)
        self._recent_shadow_rows = recent_rows
        self._recent_shadow_malformed = malformed_count

    def _build_quality_input(
        self,
        *,
        description: str | None = None,
        thumbnail_text: str | None = None,
        short_script: str | None = None,
        rendered_video_text: str | None = None,
        cta_text: str | None = None,
    ) -> QualityValidationInput:
        hist_titles = [str(row.get("title") or "") for row in self._recent_script_rows if str(row.get("title") or "").strip()]
        hist_scripts = [str(row.get("script_preview") or "") for row in self._recent_script_rows if str(row.get("script_preview") or "").strip()]

        hist_thumb_texts: list[str] = []
        for row in self._recent_shadow_rows:
            hashes = row.get("hashes") or {}
            thumb_excerpt = str((hashes or {}).get("thumbnail_text_excerpt") or "").strip()
            if thumb_excerpt:
                hist_thumb_texts.append(thumb_excerpt)

        return QualityValidationInput(
            channel_id=self.context.channel_id,
            content_id=self.context.content_id,
            title=self.context.title,
            script=self.context.script,
            description=str(description if description is not None else self.context.description),
            thumbnail_prompt=self.context.thumbnail_prompt,
            thumbnail_text=str(thumbnail_text or ""),
            short_script=str(short_script or ""),
            rendered_video_text=str(rendered_video_text or ""),
            hook_text=self.context.title,
            cta_text=str(cta_text if cta_text is not None else self.context.cta_text),
            historical_titles=hist_titles,
            historical_scripts=hist_scripts,
            historical_thumbnail_texts=hist_thumb_texts,
        )

    def _from_base_validator(
        self,
        payload: QualityValidationInput,
        *,
        allow_checks: set[str],
    ) -> tuple[list[ShadowQualityScore], list[ShadowFinding]]:
        base = evaluate_quality_checkpoints(payload)
        scores: list[ShadowQualityScore] = []
        findings: list[ShadowFinding] = []
        downgraded_high_checks = {
            "title_script_semantic_consistency",
            "script_shorts_consistency",
            "title_thumbnail_consistency",
            "script_description_consistency",
            "repetitive_opening_detection",
        }
        low_priority_checks = {
            "repeated_cta_detection",
        }
        for item in base.checks:
            if item.score_name not in allow_checks:
                continue
            score = ShadowQualityScore(
                score_name=item.score_name,
                score_value=float(item.score_value),
                status=item.status,
                details=dict(item.details or {}),
            )
            scores.append(score)
            if item.status in {"warn", "fail"}:
                severity = _severity_for_status(item.status)
                confidence: ConfidenceLevel = "HIGH" if item.status == "fail" else "MEDIUM"
                if item.score_name in downgraded_high_checks and severity == "HIGH":
                    severity = "MEDIUM"
                    confidence = "MEDIUM"
                if item.score_name in low_priority_checks:
                    severity = "LOW"
                findings.append(
                    _build_finding(
                        code=item.score_name,
                        severity=severity,
                        message=f"{item.score_name} flagged {item.status}",
                        confidence=confidence,
                        details=dict(item.details or {}),
                    )
                )
        return scores, findings

    def evaluate_checkpoint(
        self,
        *,
        checkpoint: str,
        description: str | None = None,
        thumbnail_text: str | None = None,
        short_script: str | None = None,
        short_title: str | None = None,
        tags: list[str] | None = None,
        playlist_recommendation: str | None = None,
        card_recommendation: str | None = None,
        end_screen_recommendation: str | None = None,
        short_duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        payload = self._build_quality_input(
            description=description,
            thumbnail_text=thumbnail_text,
            short_script=short_script,
            rendered_video_text=description or self.context.description,
        )

        all_scores: list[ShadowQualityScore] = []
        findings: list[ShadowFinding] = []

        if checkpoint == "generation":
            allow_checks = {
                "title_script_semantic_consistency",
                "duplicate_title_detection",
                "duplicate_script_detection",
                "repetitive_opening_detection",
                "repeated_cta_detection",
            }
            base_scores, base_findings = self._from_base_validator(payload, allow_checks=allow_checks)
            all_scores.extend(base_scores)
            findings.extend(base_findings)

            full_text = f"{self.context.title} {self.context.script}"
            for code, matcher in [
                ("not_priced_in_claim_detection", _detect_not_priced_in_claims),
                ("secret_institutional_claim_detection", _detect_secret_institutional_claims),
                ("extreme_return_claim_detection", _detect_extreme_return_claims),
                ("urgent_trade_pressure_detection", _detect_urgent_trade_pressure),
                ("specific_security_certainty_detection", _detect_specific_security_certainty),
                ("fabricated_authority_detection", _detect_fabricated_authority),
            ]:
                hits = matcher(full_text)
                score = 0.0 if hits else 1.0
                all_scores.append(_score_dict(code, score, warn_below=0.8, fail_below=0.5, details={"matched_patterns": hits}))
                if hits:
                    findings.append(_build_finding(code, "HIGH", f"{code} matched", confidence="HIGH", details={"matched_patterns": hits}, evidence_excerpt=full_text, evidence_hash=self.context.script_hash))

            for code, patterns in [
                ("unsupported_financial_claim_detection", _UNSUPPORTED_CLAIM_PATTERNS),
                ("unverifiable_insider_information_detection", _INSIDER_PATTERNS),
                ("guaranteed_return_wording_detection", _GUARANTEE_PATTERNS),
            ]:
                score, severity, confidence, detail = _financial_risk_signal(full_text, patterns=patterns)
                all_scores.append(_score_dict(code, score, warn_below=0.8, fail_below=0.45, details=detail))
                if detail["assertive"] or detail["ambiguous"]:
                    findings.append(
                        _build_finding(
                            code,
                            severity,
                            f"{code} matched with contextual risk",
                            confidence=confidence,
                            details=detail,
                            evidence_excerpt=full_text,
                            evidence_hash=self.context.script_hash,
                        )
                    )

            pump_hits = _detect_pump_style_title(self.context.title)
            all_scores.append(_score_dict("pump_style_title_detection", 0.0 if pump_hits else 1.0, details={"matched_patterns": pump_hits}))
            if pump_hits:
                findings.append(_build_finding("pump_style_title_detection", "HIGH", "pump-style wording in title", confidence="HIGH", details={"matched_patterns": pump_hits}, evidence_excerpt=self.context.title, evidence_hash=self.context.title_hash))

            mismatch_hits = _detect_ticker_company_mismatch(full_text)
            all_scores.append(_score_dict("ticker_company_mismatch_detection", 0.0 if mismatch_hits else 1.0, details={"matches": mismatch_hits}))
            if mismatch_hits:
                findings.append(_build_finding("ticker_company_mismatch_detection", "HIGH", "ticker/company mismatch signal", confidence="HIGH", details={"matches": mismatch_hits}, evidence_excerpt=full_text, evidence_hash=self.context.script_hash))

            prior_generation_rows = [
                row
                for row in self._recent_shadow_rows
                if str(row.get("checkpoint") or "") == "generation"
                and str(row.get("channel_id") or "") == self.context.channel_id
                and str(row.get("evaluation_id") or "") != self.context.evaluation_id
            ]

            dup_title_exact, dup_title_exact_score = detect_duplicate_text(self.context.title, payload.historical_titles, threshold=EXACT_DUPLICATE_THRESHOLD)
            all_scores.append(_score_dict("duplicate_title_exact_detection", 1.0 - dup_title_exact_score, details={"max_similarity": dup_title_exact_score, "threshold": EXACT_DUPLICATE_THRESHOLD}))
            if dup_title_exact:
                findings.append(_build_finding("duplicate_title_detection", "HIGH", "exact duplicate title detected", confidence="HIGH", details={"max_similarity": dup_title_exact_score, "duplicate_type": "exact"}, evidence_excerpt=self.context.title, evidence_hash=self.context.title_hash))

            hash_title_match = any(str(row.get("title_hash") or "") == self.context.title_hash for row in prior_generation_rows)
            if hash_title_match:
                findings.append(_build_finding("duplicate_title_detection", "HIGH", "exact duplicate title hash match", confidence="HIGH", details={"duplicate_type": "exact_hash"}, evidence_hash=self.context.title_hash))

            title_hamming = [
                _hamming_hex(
                    str(((row.get("hashes") or {}).get("title_simhash") or "")),
                    _simhash64_hex(self.context.title),
                )
                for row in prior_generation_rows
                if str(((row.get("hashes") or {}).get("title_simhash") or "")).strip()
            ]
            near_title = min(title_hamming) if title_hamming else 64
            all_scores.append(_score_dict("duplicate_title_near_detection", 1.0 - min(1.0, near_title / 64.0), details={"min_hamming": near_title}))
            if near_title <= 20:
                findings.append(_build_finding("duplicate_title_detection", "MEDIUM", "near-duplicate title simhash", confidence="MEDIUM", details={"min_hamming": near_title, "duplicate_type": "near"}, evidence_hash=self.context.title_hash))

            dup_script_near, dup_script_near_score = detect_duplicate_text(self.context.script, payload.historical_scripts, threshold=NEAR_DUPLICATE_THRESHOLD)
            all_scores.append(_score_dict("duplicate_script_near_detection", 1.0 - dup_script_near_score, details={"max_similarity": dup_script_near_score, "threshold": NEAR_DUPLICATE_THRESHOLD}))
            if dup_script_near and dup_script_near_score < EXACT_DUPLICATE_THRESHOLD:
                findings.append(_build_finding("duplicate_script_detection", "MEDIUM", "near-duplicate script detected", confidence="HIGH", details={"max_similarity": dup_script_near_score, "duplicate_type": "near"}, evidence_hash=self.context.script_hash))

            hash_script_match = any(str(row.get("script_hash") or "") == self.context.script_hash for row in prior_generation_rows)
            if hash_script_match:
                findings.append(_build_finding("duplicate_script_detection", "HIGH", "exact duplicate script hash match", confidence="HIGH", details={"duplicate_type": "exact_hash"}, evidence_hash=self.context.script_hash))

            script_hamming = [
                _hamming_hex(
                    str(((row.get("hashes") or {}).get("script_simhash") or "")),
                    _simhash64_hex(self.context.script),
                )
                for row in prior_generation_rows
                if str(((row.get("hashes") or {}).get("script_simhash") or "")).strip()
            ]
            near_script = min(script_hamming) if script_hamming else 64
            all_scores.append(_score_dict("duplicate_script_simhash_detection", 1.0 - min(1.0, near_script / 64.0), details={"min_hamming": near_script}))
            if near_script <= 26 and not hash_script_match:
                findings.append(_build_finding("duplicate_script_detection", "MEDIUM", "near-duplicate script simhash", confidence="MEDIUM", details={"min_hamming": near_script, "duplicate_type": "near"}, evidence_hash=self.context.script_hash))

            opening_hash = _sha(str(self.context.script or "")[:220])
            opening_match = any(str(((row.get("hashes") or {}).get("script_opening_hash") or "")) == opening_hash for row in prior_generation_rows)
            if opening_match:
                findings.append(_build_finding("repetitive_opening_detection", "MEDIUM", "repetitive opening hash match", confidence="HIGH", details={"opening_hash_match": True}, evidence_hash=opening_hash))

        elif checkpoint == "description":
            allow_checks = {
                "script_description_consistency",
            }
            base_scores, base_findings = self._from_base_validator(payload, allow_checks=allow_checks)
            all_scores.extend(base_scores)
            findings.extend(base_findings)

            desc_text = str(description if description is not None else self.context.description)
            td_score = semantic_similarity_score(self.context.title, desc_text)
            all_scores.append(_score_dict("title_description_consistency", td_score))
            if td_score < 0.45:
                findings.append(_build_finding("title_description_consistency", "MEDIUM", "title/description mismatch", confidence="MEDIUM", details={"score": round(td_score, 4)}, evidence_excerpt=desc_text, evidence_hash=_sha(desc_text)))

            for code, patterns in [
                ("unsupported_financial_claim_detection", _UNSUPPORTED_CLAIM_PATTERNS),
                ("unverifiable_insider_information_detection", _INSIDER_PATTERNS),
                ("guaranteed_return_wording_detection", _GUARANTEE_PATTERNS),
            ]:
                score, severity, confidence, detail = _financial_risk_signal(desc_text, patterns=patterns)
                all_scores.append(_score_dict(f"{code}_description", score, details=detail))
                if detail["assertive"] or detail["ambiguous"]:
                    findings.append(_build_finding(code, severity, f"{code} matched in description", confidence=confidence, details=detail, evidence_excerpt=desc_text, evidence_hash=_sha(desc_text)))

            not_priced_hits = _detect_not_priced_in_claims(desc_text)
            all_scores.append(_score_dict("not_priced_in_description", 0.0 if not_priced_hits else 1.0, details={"matched_patterns": not_priced_hits}))
            if not_priced_hits:
                findings.append(_build_finding("not_priced_in_claim_detection", "HIGH", "not priced in claim in description", confidence="HIGH", details={"matched_patterns": not_priced_hits}, evidence_excerpt=desc_text, evidence_hash=_sha(desc_text)))

            urgent_hits = _detect_urgent_trade_pressure(desc_text)
            all_scores.append(_score_dict("urgent_trade_pressure_description", 0.0 if urgent_hits else 1.0, details={"matched_patterns": urgent_hits}))
            if urgent_hits:
                findings.append(_build_finding("urgent_trade_pressure_detection", "HIGH", "urgent trade pressure in description", confidence="HIGH", details={"matched_patterns": urgent_hits}, evidence_excerpt=desc_text, evidence_hash=_sha(desc_text)))

            link_hits = _detect_misleading_external_link_context(desc_text)
            all_scores.append(_score_dict("misleading_external_link_context", 0.0 if link_hits else 1.0, details={"matched_patterns": link_hits}))
            if link_hits:
                findings.append(_build_finding("misleading_external_link_context", "MEDIUM", "misleading link context detected", confidence="MEDIUM", details={"matched_patterns": link_hits}, evidence_excerpt=desc_text, evidence_hash=_sha(desc_text)))

        elif checkpoint == "thumbnail_metadata":
            allow_checks = {
                "title_thumbnail_consistency",
                "duplicate_thumbnail_text_detection",
            }
            base_scores, base_findings = self._from_base_validator(payload, allow_checks=allow_checks)
            all_scores.extend(base_scores)
            findings.extend(base_findings)

            thumb_text = str(thumbnail_text or "")
            st_score = semantic_similarity_score(self.context.script, self.context.thumbnail_prompt)
            all_scores.append(_score_dict("script_thumbnail_prompt_consistency", st_score))
            if st_score < 0.4:
                findings.append(_build_finding("script_thumbnail_prompt_consistency", "MEDIUM", "script/thumbnail prompt mismatch", confidence="MEDIUM", details={"score": round(st_score, 4)}, evidence_excerpt=self.context.thumbnail_prompt, evidence_hash=self.context.thumbnail_prompt_hash))

            tt_score = semantic_similarity_score(self.context.title, thumb_text)
            all_scores.append(_score_dict("title_thumbnail_text_consistency", tt_score))
            if thumb_text and tt_score < 0.35:
                findings.append(_build_finding("title_thumbnail_text_consistency", "MEDIUM", "title/thumbnail text mismatch", confidence="MEDIUM", details={"score": round(tt_score, 4)}, evidence_excerpt=thumb_text, evidence_hash=_sha(thumb_text)))

            related_hits = _detect_unrelated_person_or_scene(self.context.thumbnail_prompt, self.context.title, self.context.script)
            all_scores.append(_score_dict("thumbnail_prompt_relevance", 0.0 if related_hits else 1.0, details={"matches": related_hits}))
            if related_hits:
                findings.append(_build_finding("thumbnail_prompt_relevance", "MEDIUM", "thumbnail prompt may be unrelated", confidence="MEDIUM", details={"matches": related_hits}, evidence_excerpt=self.context.thumbnail_prompt, evidence_hash=self.context.thumbnail_prompt_hash))

            combined_thumb_patterns = _UNSUPPORTED_CLAIM_PATTERNS + _INSIDER_PATTERNS + _GUARANTEE_PATTERNS
            thumb_score, thumb_severity, thumb_confidence, thumb_detail = _financial_risk_signal(thumb_text, patterns=combined_thumb_patterns)
            all_scores.append(_score_dict("thumbnail_text_financial_safety", thumb_score, details=thumb_detail))
            if thumb_detail["assertive"] or thumb_detail["ambiguous"]:
                findings.append(_build_finding("thumbnail_text_financial_safety", thumb_severity, "financial safety wording in thumbnail text", confidence=thumb_confidence, details=thumb_detail, evidence_excerpt=thumb_text, evidence_hash=_sha(thumb_text)))

            wealth_hits = _detect_misleading_wealth_imagery(self.context.thumbnail_prompt, thumb_text)
            all_scores.append(_score_dict("thumbnail_wealth_imagery_signal", 0.0 if wealth_hits else 1.0, details={"matched_patterns": wealth_hits}))
            if wealth_hits:
                findings.append(_build_finding("thumbnail_wealth_imagery_signal", "LOW", "misleading wealth imagery signal", confidence="MEDIUM", details={"matched_patterns": wealth_hits}, evidence_excerpt=self.context.thumbnail_prompt, evidence_hash=self.context.thumbnail_prompt_hash))

            if thumb_text:
                text_len = len(thumb_text)
                len_score = 1.0 if 4 <= text_len <= 60 else (0.6 if 1 <= text_len <= 80 else 0.2)
                all_scores.append(_score_dict("thumbnail_text_length_convention", len_score, details={"length": text_len}))
                if len_score < 0.7:
                    findings.append(_build_finding("thumbnail_text_length_convention", "LOW", "thumbnail text length outside preferred range", confidence="HIGH", details={"length": text_len}, evidence_excerpt=thumb_text, evidence_hash=_sha(thumb_text)))

            mismatch_hits = _detect_ticker_company_mismatch(f"{self.context.title} {thumb_text} {self.context.script}")
            all_scores.append(_score_dict("thumbnail_ticker_company_mismatch", 0.0 if mismatch_hits else 1.0, details={"matches": mismatch_hits}))
            if mismatch_hits:
                findings.append(_build_finding("thumbnail_ticker_company_mismatch", "HIGH", "ticker/company mismatch in thumbnail context", confidence="HIGH", details={"matches": mismatch_hits}, evidence_excerpt=thumb_text, evidence_hash=_sha(thumb_text)))

        elif checkpoint == "shorts":
            allow_checks = {
                "script_shorts_consistency",
            }
            base_scores, base_findings = self._from_base_validator(payload, allow_checks=allow_checks)
            all_scores.extend(base_scores)
            findings.extend(base_findings)

            short_text = str(short_script or "")
            normalized_short_title = str(short_title or self.context.title)

            complete_sentences = 0.0 if (_short_starts_mid_sentence(short_text) or _short_ends_mid_sentence(short_text)) else 1.0
            all_scores.append(_score_dict("shorts_sentence_completeness", complete_sentences, warn_below=0.9, fail_below=0.5))
            if complete_sentences < 1.0:
                findings.append(_build_finding("shorts_sentence_completeness", "MEDIUM", "short may start or end mid-sentence", confidence="MEDIUM", evidence_excerpt=short_text, evidence_hash=_sha(short_text)))

            abrupt_start = _short_starts_mid_sentence(short_text)
            all_scores.append(_score_dict("shorts_abrupt_beginning", 0.0 if abrupt_start else 1.0))
            if abrupt_start:
                conf: ConfidenceLevel = "LOW" if len(_normalize_word_tokens(short_text)) >= 24 else "MEDIUM"
                findings.append(_build_finding("shorts_abrupt_beginning", "LOW" if conf == "LOW" else "MEDIUM", "short begins abruptly", confidence=conf, evidence_excerpt=short_text, evidence_hash=_sha(short_text)))

            abrupt_end = _short_ends_mid_sentence(short_text)
            all_scores.append(_score_dict("shorts_abrupt_ending", 0.0 if abrupt_end else 1.0))
            if abrupt_end:
                findings.append(_build_finding("shorts_abrupt_ending", "MEDIUM", "short ends abruptly", confidence="MEDIUM", evidence_excerpt=short_text, evidence_hash=_sha(short_text)))

            missing_context = _short_missing_context(short_text)
            all_scores.append(_score_dict("shorts_missing_context", 0.0 if missing_context else 1.0))
            if missing_context:
                findings.append(_build_finding("shorts_missing_context", "MEDIUM", "short may miss context", confidence="MEDIUM", evidence_excerpt=short_text, evidence_hash=_sha(short_text)))

            missing_hook = _short_missing_hook(short_text, normalized_short_title)
            all_scores.append(_score_dict("shorts_hook_quality", 0.0 if missing_hook else 1.0))
            if missing_hook:
                findings.append(_build_finding("shorts_hook_quality", "LOW", "short hook appears weak", confidence="MEDIUM", evidence_excerpt=short_text, evidence_hash=_sha(short_text)))

            ctx_wo_payoff, payoff_wo_ctx = _short_context_payoff_imbalance(short_text)
            if ctx_wo_payoff:
                findings.append(_build_finding("shorts_context_without_payoff", "LOW", "short has context but weak payoff", confidence="MEDIUM", evidence_excerpt=short_text, evidence_hash=_sha(short_text)))
            if payoff_wo_ctx:
                findings.append(_build_finding("shorts_payoff_without_context", "LOW", "short has payoff but weak context", confidence="MEDIUM", evidence_excerpt=short_text, evidence_hash=_sha(short_text)))
            all_scores.append(_score_dict("shorts_context_payoff_balance", 0.0 if (ctx_wo_payoff or payoff_wo_ctx) else 1.0))

            st_consistency = semantic_similarity_score(normalized_short_title, short_text)
            all_scores.append(_score_dict("shorts_title_content_consistency", st_consistency))
            if st_consistency < 0.2:
                findings.append(_build_finding("shorts_title_content_consistency", "MEDIUM", "short title/content mismatch", confidence="MEDIUM", details={"score": round(st_consistency, 4)}, evidence_excerpt=short_text, evidence_hash=_sha(short_text)))

            duration_score, duration_outside = _short_duration_signal(short_text)
            if short_duration_seconds is not None:
                if short_duration_seconds <= 0 or short_duration_seconds > 60:
                    duration_outside = True
                    duration_score = 0.0
            all_scores.append(_score_dict("shorts_duration_signal", duration_score, warn_below=0.75, fail_below=0.4, details={"duration_seconds": short_duration_seconds}))
            if duration_outside:
                findings.append(_build_finding("shorts_duration_signal", "LOW", "short duration signal outside target range", confidence="HIGH", details={"duration_seconds": short_duration_seconds}, evidence_hash=_sha(short_text)))

            historical_shorts = [
                str(((row.get("hashes") or {}).get("short_script_excerpt") or "")).strip()
                for row in self._recent_shadow_rows
                if str(row.get("checkpoint") or "") == "shorts"
            ]
            is_dup_short, dup_score = detect_duplicate_text(short_text, [item for item in historical_shorts if item], threshold=NEAR_DUPLICATE_THRESHOLD)
            all_scores.append(_score_dict("duplicate_shorts_content", 1.0 - dup_score, details={"max_similarity": dup_score}))
            if is_dup_short:
                severity: SeverityLevel = "HIGH" if dup_score >= EXACT_DUPLICATE_THRESHOLD else "MEDIUM"
                findings.append(_build_finding("duplicate_shorts_content", severity, "duplicate shorts content signal", confidence="HIGH", details={"max_similarity": dup_score}, evidence_hash=_sha(short_text)))

        elif checkpoint == "seo_discovery":
            obs = _seo_discovery_observability(
                title=self.context.title,
                description=str(description if description is not None else self.context.description),
                tags=tags,
                playlist_recommendation=playlist_recommendation,
                card_recommendation=card_recommendation,
                end_screen_recommendation=end_screen_recommendation,
            )
            coverage_components = [
                1.0 if obs["tags"]["state"] == "generated" else 0.0,
                1.0 if obs["hashtags"]["state"] == "generated" else 0.0,
                1.0 if obs["playlist_recommendation"]["state"] == "recommendation_generated" else 0.0,
                1.0 if obs["card_recommendation"]["state"] != "not_implemented" else 0.0,
                1.0 if obs["end_screen_recommendation"]["state"] != "not_implemented" else 0.0,
            ]
            coverage = sum(coverage_components) / len(coverage_components)
            all_scores.append(_score_dict("seo_discovery_observability_coverage", coverage, warn_below=0.4, fail_below=0.2, details={"observability": obs}))
            if obs["card_recommendation"]["state"] == "not_implemented":
                findings.append(_build_finding("card_recommendation_not_implemented", "INFO", "card recommendation not implemented", confidence="HIGH"))
            if obs["end_screen_recommendation"]["state"] == "not_implemented":
                findings.append(_build_finding("end_screen_recommendation_not_implemented", "INFO", "end-screen recommendation not implemented", confidence="HIGH"))
            if obs["playlist_recommendation"]["state"] == "recommendation_absent":
                findings.append(_build_finding("playlist_recommendation_absent", "LOW", "playlist recommendation absent", confidence="HIGH"))
        else:
            raise ShadowQualityValidationError(f"invalid_checkpoint:{checkpoint}")

        desc_text = str(description if description is not None else self.context.description)
        short_text = str(short_script or "")
        thumb_text = str(thumbnail_text or "")
        hashes = _hashes_for_payload(
            topic=self.context.topic,
            title=self.context.title,
            script=self.context.script,
            description=desc_text,
            thumbnail_text=thumb_text,
            short_script=short_text,
        )

        hashes["title_excerpt"] = _bounded_excerpt(self.context.title, limit=120)
        hashes["thumbnail_text_excerpt"] = _bounded_excerpt(thumb_text, limit=80)
        hashes["short_script_excerpt"] = _bounded_excerpt(short_text, limit=160)

        row = {
            "schema_version": SHADOW_CONTENT_QUALITY_SCHEMA_VERSION,
            "evaluation_id": self.context.evaluation_id,
            "run_id": self.context.run_id,
            "content_id": self.context.content_id,
            "channel_id": self.context.channel_id,
            "content_type": self.context.content_type,
            "topic_hash": self.context.topic_hash,
            "title_hash": self.context.title_hash,
            "script_hash": self.context.script_hash,
            "checkpoint": checkpoint,
            "quality_scores": _serialize_scores(all_scores),
            "overall_score": _score_average(all_scores),
            "findings": _serialize_findings(findings),
            "finding_count": len(findings),
            "severity": _max_severity(findings),
            "highest_severity_level": _max_severity_level(findings),
            "high_confidence_finding_count": sum(1 for item in findings if item.confidence == "HIGH"),
            "aggregation": _aggregate_metrics(all_scores, findings),
            "taxonomy_version": TAXONOMY_VERSION,
            "validator_versions": {
                "learning_foundation": QUALITY_SCORE_SCHEMA_VERSION,
                "shadow_content_quality": SHADOW_CONTENT_QUALITY_VALIDATOR_VERSION,
            },
            "created_at": _now_iso(),
            "shadow_mode_enabled": True,
            "current_mode": "advisory",
            "pipeline_output_changed": False,
            "shadow_context": self.context.debug_payload(),
            "hashes": hashes,
            "storage_path": str(self.results_path),
            "history_window_size": int(self.history_window),
            "history_malformed_lines": int(self._recent_shadow_malformed),
        }
        return validate_shadow_row(row)

    def evaluate_and_store(
        self,
        *,
        checkpoint: str,
        description: str | None = None,
        thumbnail_text: str | None = None,
        short_script: str | None = None,
        short_title: str | None = None,
        tags: list[str] | None = None,
        playlist_recommendation: str | None = None,
        card_recommendation: str | None = None,
        end_screen_recommendation: str | None = None,
        short_duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        row = self.evaluate_checkpoint(
            checkpoint=checkpoint,
            description=description,
            thumbnail_text=thumbnail_text,
            short_script=short_script,
            short_title=short_title,
            tags=tags,
            playlist_recommendation=playlist_recommendation,
            card_recommendation=card_recommendation,
            end_screen_recommendation=end_screen_recommendation,
            short_duration_seconds=short_duration_seconds,
        )
        append_shadow_row(row, output_path=self.results_path)
        return row


def build_human_review_items(row: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(row, dict):
        return items
    findings = row.get("findings") or []
    if not isinstance(findings, list):
        return items
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        item = build_human_review_item(
            channel_id=str(row.get("channel_id") or ""),
            run_id=str(row.get("run_id") or ""),
            content_type=str(row.get("content_type") or ""),
            finding_code=str(finding.get("code") or ""),
            severity=str(finding.get("severity") or ""),
            confidence=str(finding.get("confidence") or ""),
            affected_artifact=str(finding.get("affected_artifact") or ""),
            bounded_excerpt=str(finding.get("evidence_excerpt") or ""),
            explanation=str(finding.get("message") or ""),
            suggested_review_action=str(finding.get("remediation_class") or ""),
            evidence_hashes={
                "evidence_hash": str(finding.get("evidence_hash") or ""),
                "script_hash": str(row.get("script_hash") or ""),
                "title_hash": str(row.get("title_hash") or ""),
            },
            created_at=str(row.get("created_at") or _now_iso()),
        )
        items.append(item.to_dict())
    return items
