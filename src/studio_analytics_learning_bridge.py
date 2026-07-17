from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
import csv
import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Any
import unicodedata


SCHEMA_VERSION = "v1"
CANONICAL_METRICS_VERSION = "v1"
IMPORT_MANIFEST_PATH = Path("logs/youtube_studio_import_manifest.jsonl")
CANONICAL_ANALYTICS_PATH = Path("logs/canonical_content_analytics.jsonl")


class ProviderName(str, Enum):
    STUDIO_EXPORT = "StudioExportProvider"
    EXISTING_LOCAL = "ExistingLocalAnalyticsProvider"
    FUTURE_OFFICIAL = "FutureOfficialYouTubeProvider"


class ContentType(str, Enum):
    LONG_FORM = "LONG_FORM"
    SHORT = "SHORT"
    LIVE = "LIVE"
    UNKNOWN = "UNKNOWN"


class MetricState(str, Enum):
    OBSERVED = "OBSERVED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID = "INVALID"


class JoinOutcome(str, Enum):
    LINKED = "LINKED"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"


class JoinMethod(str, Enum):
    BY_VIDEO_ID = "BY_VIDEO_ID"
    BY_UPLOAD_RESULT_VIDEO_ID = "BY_UPLOAD_RESULT_VIDEO_ID"
    BY_CANONICAL_CONTENT_ID = "BY_CANONICAL_CONTENT_ID"
    BY_OWNERSHIP_UPLOAD_MAPPING = "BY_OWNERSHIP_UPLOAD_MAPPING"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"


class SignalType(str, Enum):
    LOW_CTR_HIGH_RETENTION = "LOW_CTR_HIGH_RETENTION"
    HIGH_CTR_LOW_RETENTION = "HIGH_CTR_LOW_RETENTION"
    EARLY_RETENTION_DROP = "EARLY_RETENTION_DROP"
    STRONG_SEARCH_WEAK_BROWSE = "STRONG_SEARCH_WEAK_BROWSE"
    STRONG_BROWSE_WEAK_SEARCH = "STRONG_BROWSE_WEAK_SEARCH"
    WEAK_SUGGESTED_TRAFFIC = "WEAK_SUGGESTED_TRAFFIC"
    STRONG_SUGGESTED_TRAFFIC = "STRONG_SUGGESTED_TRAFFIC"
    SHORTS_HIGH_SWIPE_AWAY = "SHORTS_HIGH_SWIPE_AWAY"
    SHORTS_STRONG_HOOK = "SHORTS_STRONG_HOOK"
    LOW_AVERAGE_PERCENTAGE_VIEWED = "LOW_AVERAGE_PERCENTAGE_VIEWED"
    STRONG_AVERAGE_PERCENTAGE_VIEWED = "STRONG_AVERAGE_PERCENTAGE_VIEWED"
    CARD_UNDERPERFORMANCE = "CARD_UNDERPERFORMANCE"
    END_SCREEN_UNDERPERFORMANCE = "END_SCREEN_UNDERPERFORMANCE"
    PLAYLIST_OPPORTUNITY = "PLAYLIST_OPPORTUNITY"
    SUBSCRIBER_CONVERSION_STRENGTH = "SUBSCRIBER_CONVERSION_STRENGTH"
    SUBSCRIBER_CONVERSION_WEAKNESS = "SUBSCRIBER_CONVERSION_WEAKNESS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    METRIC_DEFINITION_INCOMPATIBLE = "METRIC_DEFINITION_INCOMPATIBLE"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _is_short_text(value: str) -> bool:
    text = _safe_text(value).lower()
    return "short" in text or "kisa" in text


def _is_live_text(value: str) -> bool:
    text = _safe_text(value).lower()
    return "live" in text or "canli" in text


def _parse_date(value: Any) -> str | None:
    text = _safe_text(value)
    if not text:
        return None
    date_formats = [
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
    ]
    for fmt in date_formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except Exception:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return None


def _parse_number(value: Any) -> float | None:
    text = _safe_text(value)
    if not text:
        return None

    raw = text.replace("\u00a0", " ").replace(" ", "")
    if raw.endswith("%"):
        raw = raw[:-1]

    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        parts = raw.split(",")
        if len(parts[-1]) in {1, 2, 3}:
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")

    try:
        return float(raw)
    except Exception:
        return None


def _parse_percentage_ratio(value: Any) -> float | None:
    text = _safe_text(value)
    if not text:
        return None
    has_pct = text.endswith("%")
    num = _parse_number(text)
    if num is None:
        return None
    if has_pct or num > 1.0:
        return num / 100.0
    return num


def _metric_value(state: MetricState, value: Any, *, raw_name: str | None = None) -> dict[str, Any]:
    return {
        "state": state.value,
        "value": value,
        "raw_name": _safe_text(raw_name) or None,
    }


def _ensure_metric(metrics: dict[str, dict[str, Any]], key: str) -> None:
    if key not in metrics:
        metrics[key] = _metric_value(MetricState.UNKNOWN, None)


# Canonical field aliases supporting English and Turkish export headers.
_HEADER_ALIASES: dict[str, list[str]] = {
    "youtube_video_id": [
        "video id",
        "video_id",
        "video kimligi",
        "video kimlik",
        "video",
        "video kimliği",
    ],
    "title": ["title", "baslik", "başlık", "video title", "icerik", "içerik"],
    "content_type": ["content type", "icerik turu", "içerik türü", "type", "tur", "tür"],
    "snapshot_start": ["start date", "baslangic tarihi", "başlangıç tarihi", "date", "tarih"],
    "snapshot_end": ["end date", "bitis tarihi", "bitiş tarihi"],
    "channel_id": ["channel id", "kanal id", "kanal kimligi", "kanal kimliği"],
    "content_id": ["content id", "icerik id", "içerik id"],
    "views": ["views", "goruntuleme", "görüntüleme", "izlenme"],
    "impressions": ["impressions", "gosterim", "gösterim"],
    "impressions_ctr": ["impressions ctr", "ctr", "gosterim tiklama orani", "gösterim tıklama oranı"],
    "watch_time": ["watch time", "watch time hours", "izlenme suresi", "izlenme süresi", "izlenme suresi saat"],
    "average_view_duration": ["average view duration", "ortalama goruntuleme suresi", "ortalama görüntüleme süresi"],
    "average_percentage_viewed": ["average percentage viewed", "ortalama izlenme yuzdesi", "ortalama izlenme yüzdesi"],
    "likes": ["likes", "begeni", "beğeni"],
    "comments": ["comments", "yorum"],
    "shares": ["shares", "paylasim", "paylaşım"],
    "subscribers_gained": ["subscribers gained", "aboneler kazanildi", "kazanilan aboneler", "kazanılan aboneler"],
    "subscribers_lost": ["subscribers lost", "aboneler kaybedildi", "kaybedilen aboneler"],
    "first_30_second_retention": ["first 30 second retention", "ilk 30 saniye tutma", "ilk 30 sn"],
    "relative_retention": ["relative retention", "goreli tutma", "göreli tutma"],
    "intro_retention": ["intro retention", "giris tutma", "giriş tutma"],
    "top_moments": ["top moments", "zirve anlar"],
    "spikes": ["spikes", "zirveler"],
    "dips": ["dips", "dususler", "düşüşler"],
    "browse_features": ["browse features", "gozatma ozellikleri", "göz atma özellikleri"],
    "suggested_videos": ["suggested videos", "onerilen videolar", "önerilen videolar"],
    "youtube_search": ["youtube search", "youtube arama"],
    "shorts_feed": ["shorts feed", "shorts akisi", "shorts akışı"],
    "external": ["external", "harici"],
    "channel_pages": ["channel pages", "kanal sayfalari", "kanal sayfaları"],
    "playlists": ["playlists", "oynatma listeleri", "playlist"],
    "notifications": ["notifications", "bildirimler"],
    "other_traffic": ["other traffic", "diger trafik", "diğer trafik"],
    "search_terms": ["search terms", "arama terimleri"],
    "suggested_source_videos": ["suggested source videos", "onerilen kaynak videolar", "önerilen kaynak videolar"],
    "playlist_starts": ["playlist starts", "playlist baslangiclari", "playlist başlangıçları"],
    "playlist_watch_time": ["playlist watch time", "playlist izlenme suresi", "playlist izlenme süresi"],
    "cards_shown": ["cards shown", "kart gosterimleri", "kart gösterimleri"],
    "card_clicks": ["card clicks", "kart tiklamalari", "kart tıklamaları"],
    "card_click_rate": ["card click rate", "kart tiklama orani", "kart tıklama oranı"],
    "end_screen_impressions": ["end-screen impressions", "end screen impressions", "bitis ekrani gosterimleri", "bitiş ekranı gösterimleri"],
    "end_screen_clicks": ["end-screen clicks", "end screen clicks", "bitis ekrani tiklamalari", "bitiş ekranı tıklamaları"],
    "end_screen_click_rate": ["end-screen click rate", "end screen click rate", "bitis ekrani tiklama orani", "bitiş ekranı tıklama oranı"],
    "shown_in_feed": ["shown in feed", "feedde gosterildi", "akista gosterildi", "akışta gösterildi"],
    "viewed": ["viewed", "izlendi"],
    "swiped_away": ["swiped away", "kaydirilip gecildi", "kaydırılıp geçildi"],
    "viewed_vs_swiped_away": ["viewed vs swiped away", "izlendi ve kaydirildi", "izlendi vs kaydırıldı"],
    "engaged_views": ["engaged views", "etkilesimli izlenme", "etkileşimli izlenme"],
    "loops": ["loops", "tekrar izleme", "repeat views"],
}


def _normalize_header(header: str) -> str:
    text = _safe_text(header).lower().replace("_", " ")
    folded = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return plain


def _canonical_column_map(headers: list[str]) -> dict[str, str]:
    normalized = {_normalize_header(h): h for h in headers}
    mapping: dict[str, str] = {}
    for canonical, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            alias_norm = _normalize_header(alias)
            if alias_norm in normalized:
                mapping[canonical] = normalized[alias_norm]
                break
    return mapping


def _row_value(row: dict[str, Any], mapping: dict[str, str], key: str) -> Any:
    real = mapping.get(key)
    if not real:
        return None
    return row.get(real)


def _is_aggregate_row(row: dict[str, Any], mapping: dict[str, str]) -> bool:
    title = _safe_text(_row_value(row, mapping, "title")).lower()
    if title in {"total", "toplam", "all", "genel"}:
        return True
    vid = _safe_text(_row_value(row, mapping, "youtube_video_id"))
    if not vid and title in {"summary", "ozet", "özet"}:
        return True
    return False


def _infer_content_type(raw: dict[str, Any], mapping: dict[str, str]) -> ContentType:
    ct_text = _safe_text(_row_value(raw, mapping, "content_type"))
    if _is_short_text(ct_text):
        return ContentType.SHORT
    if _is_live_text(ct_text):
        return ContentType.LIVE

    if ct_text:
        return ContentType.LONG_FORM

    shorts_feed = _row_value(raw, mapping, "shorts_feed")
    shown_in_feed = _row_value(raw, mapping, "shown_in_feed")
    if _safe_text(shorts_feed) or _safe_text(shown_in_feed):
        return ContentType.SHORT
    return ContentType.UNKNOWN


def _window_type(snapshot_start: str | None, snapshot_end: str | None) -> str:
    if not snapshot_start and not snapshot_end:
        return "lifetime"
    if snapshot_start and snapshot_end:
        if snapshot_start == snapshot_end:
            return "daily"
        return "date_range"
    return "point_in_time"


@dataclass(frozen=True)
class MetricValue:
    state: str
    value: Any
    raw_name: str | None


@dataclass(frozen=True)
class CanonicalAnalyticsRecord:
    schema_version: str
    analytics_record_id: str
    provider: str
    source_file_hash: str | None
    source_row_number: int
    canonical_channel_id: str | None
    content_id: str | None
    youtube_video_id: str | None
    content_type: str
    snapshot_start: str | None
    snapshot_end: str | None
    imported_at: str
    metrics_version: str
    provenance: dict[str, Any]
    advisory_only: bool
    pipeline_output_changed: bool
    metrics: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return validate_canonical_record(
            {
                "schema_version": self.schema_version,
                "analytics_record_id": self.analytics_record_id,
                "provider": self.provider,
                "source_file_hash": self.source_file_hash,
                "source_row_number": int(self.source_row_number),
                "canonical_channel_id": self.canonical_channel_id,
                "content_id": self.content_id,
                "youtube_video_id": self.youtube_video_id,
                "content_type": self.content_type,
                "snapshot_start": self.snapshot_start,
                "snapshot_end": self.snapshot_end,
                "imported_at": self.imported_at,
                "metrics_version": self.metrics_version,
                "provenance": dict(self.provenance),
                "advisory_only": bool(self.advisory_only),
                "pipeline_output_changed": bool(self.pipeline_output_changed),
                "metrics": dict(self.metrics),
            }
        )


@dataclass(frozen=True)
class LearningSignal:
    signal_id: str
    channel_id: str | None
    content_id: str | None
    youtube_video_id: str | None
    content_type: str
    metric_window: str
    signal_type: str
    evidence_metrics: dict[str, Any]
    confidence: float
    explanation: str
    affected_component: str
    recommended_future_action: str
    advisory_only: bool
    created_at: str
    supporting_metrics: dict[str, Any]
    alternative_explanations: list[str]
    data_limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "channel_id": self.channel_id,
            "content_id": self.content_id,
            "youtube_video_id": self.youtube_video_id,
            "content_type": self.content_type,
            "metric_window": self.metric_window,
            "signal_type": self.signal_type,
            "evidence_metrics": dict(self.evidence_metrics),
            "confidence": float(self.confidence),
            "explanation": self.explanation,
            "affected_component": self.affected_component,
            "recommended_future_action": self.recommended_future_action,
            "advisory_only": bool(self.advisory_only),
            "created_at": self.created_at,
            "supporting_metrics": dict(self.supporting_metrics),
            "alternative_explanations": list(self.alternative_explanations),
            "data_limitations": list(self.data_limitations),
            "pipeline_output_changed": False,
        }


def validate_canonical_record(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("invalid_payload")

    required = [
        "schema_version",
        "analytics_record_id",
        "provider",
        "source_row_number",
        "content_type",
        "imported_at",
        "metrics_version",
        "provenance",
        "advisory_only",
        "pipeline_output_changed",
        "metrics",
    ]
    for key in required:
        if key not in row:
            raise ValueError(f"missing_field:{key}")

    if _safe_text(row.get("schema_version")) != SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")

    ProviderName(_safe_text(row.get("provider")))
    ContentType(_safe_text(row.get("content_type")))

    if not isinstance(row.get("provenance"), dict):
        raise ValueError("invalid_field:provenance")
    if not isinstance(row.get("metrics"), dict):
        raise ValueError("invalid_field:metrics")

    for metric_name, payload in dict(row.get("metrics") or {}).items():
        if not isinstance(payload, dict):
            raise ValueError(f"invalid_field:metric:{metric_name}")
        MetricState(_safe_text(payload.get("state")))

    if not bool(row.get("advisory_only")):
        raise ValueError("invalid_field:advisory_only")
    if bool(row.get("pipeline_output_changed")):
        raise ValueError("invalid_field:pipeline_output_changed")

    imported_at = _safe_text(row.get("imported_at"))
    try:
        datetime.fromisoformat(imported_at.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError("invalid_field:imported_at") from exc

    normalized = dict(row)
    for field in [
        "source_file_hash",
        "canonical_channel_id",
        "content_id",
        "youtube_video_id",
        "snapshot_start",
        "snapshot_end",
    ]:
        normalized[field] = _safe_text(row.get(field)) or None
    normalized["source_row_number"] = int(row.get("source_row_number") or 0)
    return normalized


def _compute_source_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _build_record_id(
    *,
    provider: ProviderName,
    source_file_hash: str | None,
    source_row_number: int,
    youtube_video_id: str | None,
    snapshot_start: str | None,
    snapshot_end: str | None,
    metrics_version: str,
) -> str:
    parts = [
        provider.value,
        _safe_text(source_file_hash),
        str(source_row_number),
        _safe_text(youtube_video_id),
        _safe_text(snapshot_start),
        _safe_text(snapshot_end),
        _safe_text(metrics_version),
    ]
    return "car_" + _sha("|".join(parts))[:24]


def build_canonical_record_id(
    *,
    provider: str,
    source_file_hash: str | None,
    source_row_number: int,
    youtube_video_id: str | None,
    snapshot_start: str | None,
    snapshot_end: str | None,
    metrics_version: str,
) -> str:
    """Public stable seam for canonical analytics record id generation."""
    resolved_provider = ProviderName(_safe_text(provider))
    return _build_record_id(
        provider=resolved_provider,
        source_file_hash=source_file_hash,
        source_row_number=source_row_number,
        youtube_video_id=youtube_video_id,
        snapshot_start=snapshot_start,
        snapshot_end=snapshot_end,
        metrics_version=metrics_version,
    )


def _build_metric_map(raw: dict[str, Any], mapping: dict[str, str]) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}

    numeric_ratio_fields = {
        "impressions_ctr",
        "average_percentage_viewed",
        "first_30_second_retention",
        "relative_retention",
        "intro_retention",
        "card_click_rate",
        "end_screen_click_rate",
        "viewed_vs_swiped_away",
    }
    numeric_fields = {
        "views",
        "impressions",
        "watch_time",
        "average_view_duration",
        "likes",
        "comments",
        "shares",
        "subscribers_gained",
        "subscribers_lost",
        "top_moments",
        "spikes",
        "dips",
        "browse_features",
        "suggested_videos",
        "youtube_search",
        "shorts_feed",
        "external",
        "channel_pages",
        "playlists",
        "notifications",
        "other_traffic",
        "playlist_starts",
        "playlist_watch_time",
        "cards_shown",
        "card_clicks",
        "end_screen_impressions",
        "end_screen_clicks",
        "shown_in_feed",
        "viewed",
        "swiped_away",
        "engaged_views",
        "loops",
    }
    text_fields = {"audience_retention_summary", "retention_curve_reference", "search_terms", "suggested_source_videos"}

    supported = sorted(set(numeric_ratio_fields) | set(numeric_fields) | set(text_fields))

    for key in supported:
        raw_val = _row_value(raw, mapping, key)
        raw_name = mapping.get(key)
        if raw_name is None:
            metrics[key] = _metric_value(MetricState.UNKNOWN, None)
            continue

        if raw_val is None or _safe_text(raw_val) == "":
            metrics[key] = _metric_value(MetricState.UNAVAILABLE, None, raw_name=raw_name)
            continue

        if key in numeric_ratio_fields:
            val = _parse_percentage_ratio(raw_val)
            if val is None:
                metrics[key] = _metric_value(MetricState.INVALID, None, raw_name=raw_name)
            else:
                metrics[key] = _metric_value(MetricState.OBSERVED, val, raw_name=raw_name)
            continue

        if key in numeric_fields:
            val = _parse_number(raw_val)
            if val is None:
                metrics[key] = _metric_value(MetricState.INVALID, None, raw_name=raw_name)
            else:
                metrics[key] = _metric_value(MetricState.OBSERVED, val, raw_name=raw_name)
            continue

        if key in text_fields:
            metrics[key] = _metric_value(MetricState.OBSERVED, _safe_text(raw_val), raw_name=raw_name)
            continue

    return metrics


def parse_studio_export_file(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    content = path.read_text(encoding="utf-8-sig")
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    rows: list[dict[str, Any]] = []

    reader = csv.DictReader(content.splitlines(), delimiter=delimiter)
    headers = list(reader.fieldnames or [])
    mapping = _canonical_column_map(headers)

    inventory = {
        "file": str(path),
        "format": path.suffix.lower().lstrip("."),
        "headers": headers,
        "canonical_columns": sorted(mapping.keys()),
        "rows_read": 0,
        "rows_kept": 0,
        "rows_aggregate_excluded": 0,
    }

    for idx, raw_row in enumerate(reader, start=2):
        inventory["rows_read"] += 1
        if _is_aggregate_row(raw_row, mapping):
            inventory["rows_aggregate_excluded"] += 1
            continue

        snapshot_start = _parse_date(_row_value(raw_row, mapping, "snapshot_start"))
        snapshot_end = _parse_date(_row_value(raw_row, mapping, "snapshot_end"))
        if snapshot_start and not snapshot_end:
            snapshot_end = snapshot_start

        provider = ProviderName.STUDIO_EXPORT
        source_file_hash = _compute_source_file_hash(path)
        youtube_video_id = _safe_text(_row_value(raw_row, mapping, "youtube_video_id")) or None
        content_id = _safe_text(_row_value(raw_row, mapping, "content_id")) or None
        channel_id = _safe_text(_row_value(raw_row, mapping, "channel_id")) or None
        content_type = _infer_content_type(raw_row, mapping)

        metrics = _build_metric_map(raw_row, mapping)
        record_id = _build_record_id(
            provider=provider,
            source_file_hash=source_file_hash,
            source_row_number=idx,
            youtube_video_id=youtube_video_id,
            snapshot_start=snapshot_start,
            snapshot_end=snapshot_end,
            metrics_version=CANONICAL_METRICS_VERSION,
        )

        row = CanonicalAnalyticsRecord(
            schema_version=SCHEMA_VERSION,
            analytics_record_id=record_id,
            provider=provider.value,
            source_file_hash=source_file_hash,
            source_row_number=idx,
            canonical_channel_id=channel_id,
            content_id=content_id,
            youtube_video_id=youtube_video_id,
            content_type=content_type.value,
            snapshot_start=snapshot_start,
            snapshot_end=snapshot_end,
            imported_at=_now_iso(),
            metrics_version=CANONICAL_METRICS_VERSION,
            provenance={
                "source_type": "studio_export",
                "source_file": str(path),
                "title": _safe_text(_row_value(raw_row, mapping, "title")) or None,
                "window_type": _window_type(snapshot_start, snapshot_end),
                "header_mapping": {k: mapping.get(k) for k in sorted(mapping.keys())},
            },
            advisory_only=True,
            pipeline_output_changed=False,
            metrics=metrics,
        ).to_dict()
        rows.append(row)
        inventory["rows_kept"] += 1

    return rows, inventory


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    malformed = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
            else:
                malformed += 1
        except Exception:
            malformed += 1
    return rows, malformed


def _load_runtime_upload_index(runtime_dir: Path) -> dict[str, list[dict[str, Any]]]:
    idx: dict[str, list[dict[str, Any]]] = {}
    if not runtime_dir.exists():
        return idx
    for path in sorted(runtime_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        upload_metadata = payload.get("upload_metadata") if isinstance(payload.get("upload_metadata"), dict) else {}
        video_id = _safe_text(payload.get("video_id") or upload_metadata.get("video_id"))
        if not video_id:
            continue
        row = {
            "content_id": _safe_text(payload.get("content_id")) or None,
            "run_id": _safe_text(payload.get("run_id")) or None,
            "channel_id": _safe_text(payload.get("channel")) or None,
            "ownership_manifest_path": _safe_text(upload_metadata.get("ownership_manifest_path")) or None,
        }
        idx.setdefault(video_id, []).append(row)
    return idx


def _load_ownership_index(ownership_dir: Path) -> dict[str, list[dict[str, Any]]]:
    idx: dict[str, list[dict[str, Any]]] = {}
    if not ownership_dir.exists():
        return idx
    for path in sorted(ownership_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        key = _safe_text(payload.get("content_id"))
        if not key:
            continue
        idx.setdefault(key, []).append(
            {
                "content_id": _safe_text(payload.get("content_id")) or None,
                "run_id": _safe_text(payload.get("run_id")) or None,
                "channel_id": _safe_text(payload.get("channel_id")) or None,
                "ownership_id": path.stem,
            }
        )
    return idx


def _load_upload_id_to_ownership(ownership_dir: Path, runtime_dir: Path) -> dict[str, list[dict[str, Any]]]:
    idx: dict[str, list[dict[str, Any]]] = {}
    runtime_idx = _load_runtime_upload_index(runtime_dir)
    for video_id, rows in runtime_idx.items():
        for row in rows:
            ownership_id = None
            omp = _safe_text(row.get("ownership_manifest_path"))
            if omp:
                ownership_id = Path(omp).stem
            idx.setdefault(video_id, []).append(
                {
                    "content_id": row.get("content_id"),
                    "run_id": row.get("run_id"),
                    "channel_id": row.get("channel_id"),
                    "ownership_id": ownership_id,
                }
            )
    return idx


def join_canonical_record_identity(
    *,
    record: dict[str, Any],
    runtime_dir: Path,
    ownership_dir: Path,
) -> dict[str, Any]:
    provider_content_id = _safe_text(record.get("content_id"))
    provider_video_id = _safe_text(record.get("youtube_video_id"))

    if not record.get("provider"):
        return {
            "join_outcome": JoinOutcome.INVALID.value,
            "join_method": JoinMethod.INVALID.value,
            "content_id": None,
            "run_id": None,
            "canonical_channel_id": record.get("canonical_channel_id"),
            "youtube_video_id": provider_video_id or None,
            "provenance": {"reason": "missing_provider"},
        }

    runtime_idx = _load_runtime_upload_index(runtime_dir)
    ownership_idx = _load_ownership_index(ownership_dir)
    upload_own_idx = _load_upload_id_to_ownership(ownership_dir, runtime_dir)

    # 1) exact video id
    if provider_video_id:
        matches = runtime_idx.get(provider_video_id, [])
        if len(matches) == 1:
            m = matches[0]
            return {
                "join_outcome": JoinOutcome.LINKED.value,
                "join_method": JoinMethod.BY_VIDEO_ID.value,
                "content_id": m.get("content_id"),
                "run_id": m.get("run_id"),
                "canonical_channel_id": m.get("channel_id") or record.get("canonical_channel_id"),
                "youtube_video_id": provider_video_id,
                "provenance": {"match_count": 1},
            }
        if len(matches) > 1:
            return {
                "join_outcome": JoinOutcome.AMBIGUOUS.value,
                "join_method": JoinMethod.AMBIGUOUS.value,
                "content_id": None,
                "run_id": None,
                "canonical_channel_id": record.get("canonical_channel_id"),
                "youtube_video_id": provider_video_id,
                "provenance": {"match_count": len(matches), "reason": "video_id_multi_match"},
            }

    # 2) upload result video id (provider maybe sets alternative field)
    upload_id = _safe_text(record.get("youtube_video_id"))
    if upload_id:
        matches = upload_own_idx.get(upload_id, [])
        if len(matches) == 1:
            m = matches[0]
            return {
                "join_outcome": JoinOutcome.LINKED.value,
                "join_method": JoinMethod.BY_UPLOAD_RESULT_VIDEO_ID.value,
                "content_id": m.get("content_id"),
                "run_id": m.get("run_id"),
                "canonical_channel_id": m.get("channel_id") or record.get("canonical_channel_id"),
                "youtube_video_id": upload_id,
                "provenance": {"match_count": 1},
            }
        if len(matches) > 1:
            return {
                "join_outcome": JoinOutcome.AMBIGUOUS.value,
                "join_method": JoinMethod.AMBIGUOUS.value,
                "content_id": None,
                "run_id": None,
                "canonical_channel_id": record.get("canonical_channel_id"),
                "youtube_video_id": upload_id,
                "provenance": {"match_count": len(matches), "reason": "upload_id_multi_match"},
            }

    # 3) explicit canonical content id
    if provider_content_id:
        matches = ownership_idx.get(provider_content_id, [])
        if len(matches) == 1:
            m = matches[0]
            return {
                "join_outcome": JoinOutcome.LINKED.value,
                "join_method": JoinMethod.BY_CANONICAL_CONTENT_ID.value,
                "content_id": m.get("content_id"),
                "run_id": m.get("run_id"),
                "canonical_channel_id": m.get("channel_id") or record.get("canonical_channel_id"),
                "youtube_video_id": provider_video_id or None,
                "provenance": {"match_count": 1},
            }
        if len(matches) > 1:
            return {
                "join_outcome": JoinOutcome.AMBIGUOUS.value,
                "join_method": JoinMethod.AMBIGUOUS.value,
                "content_id": None,
                "run_id": None,
                "canonical_channel_id": record.get("canonical_channel_id"),
                "youtube_video_id": provider_video_id or None,
                "provenance": {"match_count": len(matches), "reason": "content_id_multi_match"},
            }

    # 4) ownership/upload mapping fallback already covered via runtime-owned mapping
    if provider_video_id:
        matches = upload_own_idx.get(provider_video_id, [])
        if len(matches) == 1:
            m = matches[0]
            return {
                "join_outcome": JoinOutcome.LINKED.value,
                "join_method": JoinMethod.BY_OWNERSHIP_UPLOAD_MAPPING.value,
                "content_id": m.get("content_id"),
                "run_id": m.get("run_id"),
                "canonical_channel_id": m.get("channel_id") or record.get("canonical_channel_id"),
                "youtube_video_id": provider_video_id,
                "provenance": {"match_count": 1},
            }

    return {
        "join_outcome": JoinOutcome.UNRESOLVED.value,
        "join_method": JoinMethod.UNRESOLVED.value,
        "content_id": None,
        "run_id": None,
        "canonical_channel_id": record.get("canonical_channel_id"),
        "youtube_video_id": provider_video_id or None,
        "provenance": {"reason": "deterministic_keys_missing"},
    }


class BaseAnalyticsProvider:
    name: ProviderName

    def collect_records(self, **kwargs: Any) -> list[dict[str, Any]]:
        raise NotImplementedError()


class StudioExportProvider(BaseAnalyticsProvider):
    name = ProviderName.STUDIO_EXPORT

    def collect_records(self, *, input_files: list[Path]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for file_path in input_files:
            parsed, _inventory = parse_studio_export_file(file_path)
            rows.extend(parsed)
        return rows


class ExistingLocalAnalyticsProvider(BaseAnalyticsProvider):
    name = ProviderName.EXISTING_LOCAL

    def collect_records(self, *, channel_performance_path: Path) -> list[dict[str, Any]]:
        payloads, _malformed = _load_jsonl(channel_performance_path)
        rows: list[dict[str, Any]] = []
        for idx, row in enumerate(payloads, start=1):
            if not isinstance(row, dict):
                continue
            content_type = ContentType.SHORT if _safe_text(row.get("short_video_id")) else ContentType.LONG_FORM
            source_file_hash = _compute_source_file_hash(channel_performance_path)
            youtube_video_id = _safe_text(row.get("video_id")) or None
            snapshot_start = _parse_date(row.get("day"))
            snapshot_end = snapshot_start
            metrics: dict[str, dict[str, Any]] = {}
            for key in [
                "impressions",
                "click_through_rate",
                "average_view_duration_seconds",
                "average_view_percentage",
                "watch_time_hours",
                "views",
                "likes",
                "comments",
                "shares",
                "subscribers_gained",
            ]:
                if key in row:
                    value = row.get(key)
                    parsed = _parse_number(value) if key != "click_through_rate" else _parse_percentage_ratio(value)
                    if parsed is None:
                        metrics[key] = _metric_value(MetricState.INVALID, None, raw_name=key)
                    else:
                        metrics[key] = _metric_value(MetricState.OBSERVED, parsed, raw_name=key)
                else:
                    metrics[key] = _metric_value(MetricState.UNKNOWN, None)

            record_id = _build_record_id(
                provider=self.name,
                source_file_hash=source_file_hash,
                source_row_number=idx,
                youtube_video_id=youtube_video_id,
                snapshot_start=snapshot_start,
                snapshot_end=snapshot_end,
                metrics_version=CANONICAL_METRICS_VERSION,
            )

            rows.append(
                CanonicalAnalyticsRecord(
                    schema_version=SCHEMA_VERSION,
                    analytics_record_id=record_id,
                    provider=self.name.value,
                    source_file_hash=source_file_hash,
                    source_row_number=idx,
                    canonical_channel_id=_safe_text(row.get("channel_id")) or None,
                    content_id=_safe_text(row.get("content_id")) or None,
                    youtube_video_id=youtube_video_id,
                    content_type=content_type.value,
                    snapshot_start=snapshot_start,
                    snapshot_end=snapshot_end,
                    imported_at=_now_iso(),
                    metrics_version=CANONICAL_METRICS_VERSION,
                    provenance={
                        "source_type": "existing_local_analytics",
                        "source_file": str(channel_performance_path),
                        "window_type": "daily",
                    },
                    advisory_only=True,
                    pipeline_output_changed=False,
                    metrics=metrics,
                ).to_dict()
            )
        return rows


class FutureOfficialYouTubeProvider(BaseAnalyticsProvider):
    name = ProviderName.FUTURE_OFFICIAL

    def collect_records(self, **kwargs: Any) -> list[dict[str, Any]]:
        raise NotImplementedError("FutureOfficialYouTubeProvider is interface-only in this phase")


def provider_priority() -> list[str]:
    return [
        ProviderName.FUTURE_OFFICIAL.value,
        ProviderName.STUDIO_EXPORT.value,
        ProviderName.EXISTING_LOCAL.value,
        "UNAVAILABLE",
    ]


def load_import_manifest(*, path: Path | str = IMPORT_MANIFEST_PATH) -> tuple[list[dict[str, Any]], int]:
    return _load_jsonl(Path(path))


def load_canonical_records(*, path: Path | str = CANONICAL_ANALYTICS_PATH) -> tuple[list[dict[str, Any]], int]:
    rows, malformed = _load_jsonl(Path(path))
    valid: list[dict[str, Any]] = []
    for row in rows:
        try:
            valid.append(validate_canonical_record(row))
        except Exception:
            malformed += 1
    return valid, malformed


def _manifest_key(provider: str, file_hash: str | None) -> str:
    return _sha(f"{_safe_text(provider)}|{_safe_text(file_hash)}")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")


def append_canonical_record_row(*, output_path: Path | str, row: dict[str, Any]) -> None:
    """Public stable seam for deterministic canonical row append."""
    normalized = validate_canonical_record(dict(row or {}))
    _append_jsonl(Path(output_path), normalized)


def import_records_append_only(
    *,
    provider: str,
    source_file: Path | None,
    candidate_rows: list[dict[str, Any]],
    manifest_path: Path | str = IMPORT_MANIFEST_PATH,
    canonical_store_path: Path | str = CANONICAL_ANALYTICS_PATH,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    canonical_file = Path(canonical_store_path)

    source_hash = _compute_source_file_hash(source_file) if source_file is not None and source_file.exists() else None

    manifest_rows, manifest_malformed = load_import_manifest(path=manifest_file)
    existing_manifest_keys = {
        _safe_text(item.get("manifest_key"))
        for item in manifest_rows
        if isinstance(item, dict) and _safe_text(item.get("manifest_key"))
    }

    key = _manifest_key(provider, source_hash)
    if key in existing_manifest_keys:
        return {
            "status": "duplicate_file_skipped",
            "provider": provider,
            "source_file": str(source_file) if source_file else None,
            "source_file_hash": source_hash,
            "rows_read": len(candidate_rows),
            "rows_appended": 0,
            "duplicate_rows": 0,
            "invalid_rows": 0,
            "manifest_malformed": manifest_malformed,
            "advisory_only": True,
            "pipeline_output_changed": False,
        }

    existing_rows, canonical_malformed = load_canonical_records(path=canonical_file)
    existing_ids = {_safe_text(r.get("analytics_record_id")) for r in existing_rows if _safe_text(r.get("analytics_record_id"))}

    appended = 0
    invalid = 0
    duplicate_rows = 0

    for row in candidate_rows:
        try:
            normalized = validate_canonical_record(row)
        except Exception:
            invalid += 1
            continue

        record_id = _safe_text(normalized.get("analytics_record_id"))
        if record_id in existing_ids:
            duplicate_rows += 1
            continue

        _append_jsonl(canonical_file, normalized)
        existing_ids.add(record_id)
        appended += 1

    manifest_row = {
        "schema_version": SCHEMA_VERSION,
        "manifest_key": key,
        "provider": provider,
        "source_file": str(source_file) if source_file else None,
        "source_file_hash": source_hash,
        "rows_read": len(candidate_rows),
        "rows_appended": appended,
        "invalid_rows": invalid,
        "duplicate_rows": duplicate_rows,
        "imported_at": _now_iso(),
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
    _append_jsonl(manifest_file, manifest_row)

    return {
        **manifest_row,
        "status": "imported",
        "manifest_malformed": manifest_malformed,
        "canonical_malformed": canonical_malformed,
    }


def reconstruct_metric_history(*, rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        content_key = _safe_text(row.get("content_id")) or _safe_text(row.get("youtube_video_id"))
        if not content_key:
            content_key = "UNRESOLVED::" + _safe_text(row.get("analytics_record_id"))
        grouped.setdefault(content_key, []).append(row)

    timelines: dict[str, dict[str, Any]] = {}

    for key, bucket in grouped.items():
        ordered = sorted(
            bucket,
            key=lambda r: (
                _safe_text(r.get("snapshot_start")) or "9999-99-99",
                _safe_text(r.get("snapshot_end")) or "9999-99-99",
                _safe_text(r.get("analytics_record_id")),
            ),
        )

        duplicate_snapshots = 0
        seen_windows: set[str] = set()
        for row in ordered:
            window = f"{_safe_text(row.get('snapshot_start'))}|{_safe_text(row.get('snapshot_end'))}|{_safe_text(row.get('metrics_version'))}|{_safe_text(row.get('provider'))}"
            if window in seen_windows:
                duplicate_snapshots += 1
            seen_windows.add(window)

        first = ordered[0]
        latest = ordered[-1]

        deltas: dict[str, Any] = {}
        incompatible_metrics: list[str] = []

        if _safe_text(first.get("metrics_version")) == _safe_text(latest.get("metrics_version")) and _window_type(first.get("snapshot_start"), first.get("snapshot_end")) == _window_type(latest.get("snapshot_start"), latest.get("snapshot_end")):
            for metric in ["views", "impressions", "watch_time", "average_view_duration", "average_percentage_viewed"]:
                m1 = ((first.get("metrics") or {}).get(metric) or {})
                m2 = ((latest.get("metrics") or {}).get(metric) or {})
                if _safe_text(m1.get("state")) == MetricState.OBSERVED.value and _safe_text(m2.get("state")) == MetricState.OBSERVED.value:
                    try:
                        deltas[metric] = float(m2.get("value")) - float(m1.get("value"))
                    except Exception:
                        pass
        else:
            incompatible_metrics = ["views", "impressions", "watch_time", "average_view_duration", "average_percentage_viewed"]

        missing_periods = 0
        last_day: date | None = None
        for row in ordered:
            day = _parse_date(row.get("snapshot_start"))
            if day is None:
                continue
            current = datetime.strptime(day, "%Y-%m-%d").date()
            if last_day is not None and (current - last_day).days > 1:
                missing_periods += 1
            last_day = current

        provider_transitions = 0
        prev_provider = None
        for row in ordered:
            p = _safe_text(row.get("provider"))
            if prev_provider is not None and p != prev_provider:
                provider_transitions += 1
            prev_provider = p

        timelines[key] = {
            "content_key": key,
            "content_id": first.get("content_id") or latest.get("content_id"),
            "youtube_video_id": first.get("youtube_video_id") or latest.get("youtube_video_id"),
            "content_type": latest.get("content_type"),
            "first_snapshot": first,
            "latest_snapshot": latest,
            "observation_count": len(ordered),
            "duplicate_snapshots": duplicate_snapshots,
            "missing_periods": missing_periods,
            "provider_transitions": provider_transitions,
            "metric_deltas": deltas,
            "incompatible_metric_definitions": incompatible_metrics,
            "advisory_only": True,
            "pipeline_output_changed": False,
        }

    return timelines


def compute_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    linked = 0
    unresolved = 0
    ambiguous = 0
    invalid = 0

    channels = set()
    long_form = 0
    shorts = 0

    metric_presence = {
        "retention": 0,
        "traffic": 0,
        "cards": 0,
        "end_screens": 0,
        "playlists": 0,
    }

    min_date = None
    max_date = None

    for row in rows:
        provenance = dict(row.get("provenance") or {})
        join_outcome = _safe_text(provenance.get("join_outcome"))
        if join_outcome == JoinOutcome.LINKED.value:
            linked += 1
        elif join_outcome == JoinOutcome.UNRESOLVED.value:
            unresolved += 1
        elif join_outcome == JoinOutcome.AMBIGUOUS.value:
            ambiguous += 1
        elif join_outcome == JoinOutcome.INVALID.value:
            invalid += 1

        channel_id = _safe_text(row.get("canonical_channel_id"))
        if channel_id:
            channels.add(channel_id)

        ctype = _safe_text(row.get("content_type"))
        if ctype == ContentType.SHORT.value:
            shorts += 1
        elif ctype == ContentType.LONG_FORM.value:
            long_form += 1

        metrics = dict(row.get("metrics") or {})

        if _safe_text(((metrics.get("first_30_second_retention") or {}).get("state"))) == MetricState.OBSERVED.value:
            metric_presence["retention"] += 1
        if _safe_text(((metrics.get("youtube_search") or {}).get("state"))) == MetricState.OBSERVED.value or _safe_text(((metrics.get("browse_features") or {}).get("state"))) == MetricState.OBSERVED.value:
            metric_presence["traffic"] += 1
        if _safe_text(((metrics.get("cards_shown") or {}).get("state"))) == MetricState.OBSERVED.value:
            metric_presence["cards"] += 1
        if _safe_text(((metrics.get("end_screen_impressions") or {}).get("state"))) == MetricState.OBSERVED.value:
            metric_presence["end_screens"] += 1
        if _safe_text(((metrics.get("playlist_watch_time") or {}).get("state"))) == MetricState.OBSERVED.value:
            metric_presence["playlists"] += 1

        for field in ["snapshot_start", "snapshot_end"]:
            d = _parse_date(row.get(field))
            if not d:
                continue
            if min_date is None or d < min_date:
                min_date = d
            if max_date is None or d > max_date:
                max_date = d

    denom = max(1, total)

    return {
        "files_discovered": None,
        "files_imported": None,
        "rows_read": total,
        "valid_rows": total - invalid,
        "invalid_rows": invalid,
        "duplicate_rows": None,
        "content_linked_rows": linked,
        "unresolved_rows": unresolved,
        "ambiguous_rows": ambiguous,
        "videos_covered": long_form,
        "shorts_covered": shorts,
        "channels_covered": len(channels),
        "retention_coverage": round(100.0 * metric_presence["retention"] / denom, 2),
        "traffic_source_coverage": round(100.0 * metric_presence["traffic"] / denom, 2),
        "cards_coverage": round(100.0 * metric_presence["cards"] / denom, 2),
        "end_screens_coverage": round(100.0 * metric_presence["end_screens"] / denom, 2),
        "playlist_coverage": round(100.0 * metric_presence["playlists"] / denom, 2),
        "date_coverage": {"start": min_date, "end": max_date},
        "long_form_rows": long_form,
        "short_rows": shorts,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def build_baselines(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for row in rows:
        channel = _safe_text(row.get("canonical_channel_id")) or "unknown"
        ctype = _safe_text(row.get("content_type")) or ContentType.UNKNOWN.value
        buckets.setdefault((channel, ctype), []).append(row)

    baselines: dict[str, Any] = {}

    for (channel, ctype), bucket in buckets.items():
        ctr_vals: list[float] = []
        apv_vals: list[float] = []

        for row in bucket:
            metrics = dict(row.get("metrics") or {})
            ctr = (metrics.get("impressions_ctr") or metrics.get("click_through_rate") or {})
            apv = (metrics.get("average_percentage_viewed") or {})

            if _safe_text(ctr.get("state")) == MetricState.OBSERVED.value:
                try:
                    ctr_vals.append(float(ctr.get("value")))
                except Exception:
                    pass
            if _safe_text(apv.get("state")) == MetricState.OBSERVED.value:
                try:
                    apv_vals.append(float(apv.get("value")))
                except Exception:
                    pass

        def _pct(values: list[float], q: float) -> float | None:
            if not values:
                return None
            ordered = sorted(values)
            if len(ordered) == 1:
                return ordered[0]
            pos = q * (len(ordered) - 1)
            lo = int(pos)
            hi = min(lo + 1, len(ordered) - 1)
            frac = pos - lo
            return ordered[lo] * (1.0 - frac) + ordered[hi] * frac

        baselines[f"{channel}::{ctype}"] = {
            "channel_id": channel,
            "content_type": ctype,
            "sample_count": len(bucket),
            "ctr_median": median(ctr_vals) if ctr_vals else None,
            "ctr_p25": _pct(ctr_vals, 0.25),
            "ctr_p75": _pct(ctr_vals, 0.75),
            "apv_median": median(apv_vals) if apv_vals else None,
            "apv_p25": _pct(apv_vals, 0.25),
            "apv_p75": _pct(apv_vals, 0.75),
            "advisory_only": True,
            "pipeline_output_changed": False,
        }

    return baselines


def _obs(metrics: dict[str, Any], key: str) -> float | None:
    payload = dict(metrics.get(key) or {})
    if _safe_text(payload.get("state")) != MetricState.OBSERVED.value:
        return None
    try:
        return float(payload.get("value"))
    except Exception:
        return None


def _signal(
    *,
    signal_type: SignalType,
    row: dict[str, Any],
    window: str,
    evidence: dict[str, Any],
    confidence: float,
    explanation: str,
    component: str,
    action: str,
    alternatives: list[str],
    limitations: list[str],
) -> dict[str, Any]:
    sid = "sig_" + _sha(
        f"{signal_type.value}|{_safe_text(row.get('content_id'))}|{_safe_text(row.get('youtube_video_id'))}|{window}|{json.dumps(evidence, sort_keys=True)}"
    )[:24]

    return LearningSignal(
        signal_id=sid,
        channel_id=_safe_text(row.get("canonical_channel_id")) or None,
        content_id=_safe_text(row.get("content_id")) or None,
        youtube_video_id=_safe_text(row.get("youtube_video_id")) or None,
        content_type=_safe_text(row.get("content_type")) or ContentType.UNKNOWN.value,
        metric_window=window,
        signal_type=signal_type.value,
        evidence_metrics=evidence,
        confidence=confidence,
        explanation=explanation,
        affected_component=component,
        recommended_future_action=action,
        advisory_only=True,
        created_at=_now_iso(),
        supporting_metrics=evidence,
        alternative_explanations=alternatives,
        data_limitations=limitations,
    ).to_dict()


def derive_learning_signals(
    *,
    rows: list[dict[str, Any]],
    baselines: dict[str, Any],
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []

    for row in rows:
        metrics = dict(row.get("metrics") or {})
        ctype = _safe_text(row.get("content_type")) or ContentType.UNKNOWN.value
        channel = _safe_text(row.get("canonical_channel_id")) or "unknown"
        key = f"{channel}::{ctype}"
        baseline = dict(baselines.get(key) or {})

        ctr = _obs(metrics, "impressions_ctr")
        apv = _obs(metrics, "average_percentage_viewed")
        r30 = _obs(metrics, "first_30_second_retention")
        search = _obs(metrics, "youtube_search")
        browse = _obs(metrics, "browse_features")
        suggested = _obs(metrics, "suggested_videos")
        swipe = _obs(metrics, "swiped_away")
        viewed_ratio = _obs(metrics, "viewed_vs_swiped_away")
        cards = _obs(metrics, "cards_shown")
        card_rate = _obs(metrics, "card_click_rate")
        end_impr = _obs(metrics, "end_screen_impressions")
        end_rate = _obs(metrics, "end_screen_click_rate")
        playlist_watch = _obs(metrics, "playlist_watch_time")
        subs_gained = _obs(metrics, "subscribers_gained")
        views = _obs(metrics, "views")

        window = _window_type(row.get("snapshot_start"), row.get("snapshot_end"))

        baseline_ctr = baseline.get("ctr_median")
        baseline_apv = baseline.get("apv_median")

        insufficient = []
        if baseline.get("sample_count", 0) < 3:
            insufficient.append("low_channel_sample")
        if ctr is None and apv is None:
            insufficient.append("missing_ctr_and_apv")
        if insufficient:
            signals.append(
                _signal(
                    signal_type=SignalType.INSUFFICIENT_DATA,
                    row=row,
                    window=window,
                    evidence={"reasons": insufficient},
                    confidence=0.2,
                    explanation="Insufficient comparable observations for stable recommendation.",
                    component="learning_foundation",
                    action="Collect more snapshots before applying directional guidance.",
                    alternatives=["Date-range mismatch", "Metric not exported"],
                    limitations=insufficient,
                )
            )

        if baseline_ctr is not None and baseline_apv is not None and ctr is not None and apv is not None:
            if ctr < baseline_ctr and apv > baseline_apv:
                signals.append(
                    _signal(
                        signal_type=SignalType.LOW_CTR_HIGH_RETENTION,
                        row=row,
                        window=window,
                        evidence={"ctr": ctr, "ctr_baseline": baseline_ctr, "apv": apv, "apv_baseline": baseline_apv},
                        confidence=0.72,
                        explanation="Discovery efficiency appears weak while post-click satisfaction appears strong.",
                        component="title_thumbnail_discovery",
                        action="Prioritize packaging review while preserving core narrative quality.",
                        alternatives=["Seasonality", "Distribution mix shift"],
                        limitations=["Correlation is not causation"],
                    )
                )

            if ctr > baseline_ctr and apv < baseline_apv:
                signals.append(
                    _signal(
                        signal_type=SignalType.HIGH_CTR_LOW_RETENTION,
                        row=row,
                        window=window,
                        evidence={"ctr": ctr, "ctr_baseline": baseline_ctr, "apv": apv, "apv_baseline": baseline_apv},
                        confidence=0.72,
                        explanation="Click acquisition appears strong but watch satisfaction appears weak.",
                        component="opening_promise_alignment",
                        action="Review opening structure and promise-delivery alignment.",
                        alternatives=["Audience mismatch", "Outlier event"],
                        limitations=["Correlation is not causation"],
                    )
                )

            if apv < baseline_apv * 0.75:
                signals.append(
                    _signal(
                        signal_type=SignalType.LOW_AVERAGE_PERCENTAGE_VIEWED,
                        row=row,
                        window=window,
                        evidence={"apv": apv, "apv_baseline": baseline_apv},
                        confidence=0.66,
                        explanation="Average percentage viewed is materially below comparable baseline.",
                        component="narrative_pacing",
                        action="Test tighter early pacing and earlier value delivery.",
                        alternatives=["Topic fatigue"],
                        limitations=["Needs repeated observations"],
                    )
                )
            if apv > baseline_apv * 1.15:
                signals.append(
                    _signal(
                        signal_type=SignalType.STRONG_AVERAGE_PERCENTAGE_VIEWED,
                        row=row,
                        window=window,
                        evidence={"apv": apv, "apv_baseline": baseline_apv},
                        confidence=0.68,
                        explanation="Average percentage viewed is above comparable baseline.",
                        component="narrative_structure",
                        action="Preserve structure patterns that sustain attention.",
                        alternatives=["Topic novelty"],
                        limitations=["Needs holdout validation"],
                    )
                )

        if r30 is not None and r30 < 0.35:
            signals.append(
                _signal(
                    signal_type=SignalType.EARLY_RETENTION_DROP,
                    row=row,
                    window=window,
                    evidence={"first_30_second_retention": r30},
                    confidence=0.7,
                    explanation="Early retention suggests first moments lose viewers quickly.",
                    component="hook_timing",
                    action="Strengthen first 1-3 second payoff clarity.",
                    alternatives=["Traffic quality variance"],
                    limitations=["Retention curve detail unavailable"],
                )
            )

        if search is not None and browse is not None:
            if search > browse * 1.5:
                signals.append(
                    _signal(
                        signal_type=SignalType.STRONG_SEARCH_WEAK_BROWSE,
                        row=row,
                        window=window,
                        evidence={"youtube_search": search, "browse_features": browse},
                        confidence=0.62,
                        explanation="Search discovery outperforms browse discovery.",
                        component="seo_vs_browse_balance",
                        action="Keep SEO strengths; test broader packaging for browse contexts.",
                        alternatives=["Channel audience shift"],
                        limitations=["Traffic attribution granularity"],
                    )
                )
            if browse > search * 1.5:
                signals.append(
                    _signal(
                        signal_type=SignalType.STRONG_BROWSE_WEAK_SEARCH,
                        row=row,
                        window=window,
                        evidence={"youtube_search": search, "browse_features": browse},
                        confidence=0.62,
                        explanation="Browse distribution outperforms search distribution.",
                        component="seo_vs_browse_balance",
                        action="Retain browse packaging; improve searchable intent clarity.",
                        alternatives=["Trending feed support"],
                        limitations=["Search term exports may be partial"],
                    )
                )

        if suggested is not None:
            if suggested < 0.05:
                signals.append(
                    _signal(
                        signal_type=SignalType.WEAK_SUGGESTED_TRAFFIC,
                        row=row,
                        window=window,
                        evidence={"suggested_videos": suggested},
                        confidence=0.58,
                        explanation="Suggested traffic share appears weak.",
                        component="suggested_ecosystem_fit",
                        action="Review topic adjacency and sequence continuity for recommendations.",
                        alternatives=["Low sample window"],
                        limitations=["Share may fluctuate by age"],
                    )
                )
            if suggested > 0.25:
                signals.append(
                    _signal(
                        signal_type=SignalType.STRONG_SUGGESTED_TRAFFIC,
                        row=row,
                        window=window,
                        evidence={"suggested_videos": suggested},
                        confidence=0.58,
                        explanation="Suggested traffic share appears strong.",
                        component="suggested_ecosystem_fit",
                        action="Preserve content adjacency patterns that drive suggestion uptake.",
                        alternatives=["One-off external boost"],
                        limitations=["Requires longitudinal confirmation"],
                    )
                )

        if ctype == ContentType.SHORT.value:
            if swipe is not None and viewed_ratio is not None and swipe > viewed_ratio:
                signals.append(
                    _signal(
                        signal_type=SignalType.SHORTS_HIGH_SWIPE_AWAY,
                        row=row,
                        window=window,
                        evidence={"swiped_away": swipe, "viewed_vs_swiped_away": viewed_ratio},
                        confidence=0.69,
                        explanation="Shorts swipe-away pressure appears high.",
                        component="shorts_first_second_hook",
                        action="Test stronger first-frame and first-second hook contrast.",
                        alternatives=["Cold audience reach"],
                        limitations=["Viewer intent may vary by feed source"],
                    )
                )
            if viewed_ratio is not None and viewed_ratio > 0.65:
                signals.append(
                    _signal(
                        signal_type=SignalType.SHORTS_STRONG_HOOK,
                        row=row,
                        window=window,
                        evidence={"viewed_vs_swiped_away": viewed_ratio},
                        confidence=0.66,
                        explanation="Shorts viewed ratio suggests strong early hook behavior.",
                        component="shorts_hook_pattern",
                        action="Retain early frame and opening rhythm characteristics.",
                        alternatives=["Temporary trend alignment"],
                        limitations=["Need repeated uploads"],
                    )
                )

        if cards is not None and card_rate is not None and cards >= 100 and card_rate < 0.01:
            signals.append(
                _signal(
                    signal_type=SignalType.CARD_UNDERPERFORMANCE,
                    row=row,
                    window=window,
                    evidence={"cards_shown": cards, "card_click_rate": card_rate},
                    confidence=0.55,
                    explanation="Card interactions underperform for shown volume.",
                    component="card_strategy",
                    action="Revisit card timing and contextual relevance.",
                    alternatives=["Cards shown in low-intent segments"],
                    limitations=["Card placement metadata unavailable"],
                )
            )

        if end_impr is not None and end_rate is not None and end_impr >= 100 and end_rate < 0.01:
            signals.append(
                _signal(
                    signal_type=SignalType.END_SCREEN_UNDERPERFORMANCE,
                    row=row,
                    window=window,
                    evidence={"end_screen_impressions": end_impr, "end_screen_click_rate": end_rate},
                    confidence=0.55,
                    explanation="End-screen click efficiency appears weak.",
                    component="end_screen_strategy",
                    action="Review end-screen relevance and timing.",
                    alternatives=["Low end reach"],
                    limitations=["End-screen creative variants unavailable"],
                )
            )

        if playlist_watch is not None and playlist_watch > 0:
            signals.append(
                _signal(
                    signal_type=SignalType.PLAYLIST_OPPORTUNITY,
                    row=row,
                    window=window,
                    evidence={"playlist_watch_time": playlist_watch},
                    confidence=0.52,
                    explanation="Playlist watch time indicates sequence-consumption opportunity.",
                    component="playlist_strategy",
                    action="Consider strengthening playlist continuity cues.",
                    alternatives=["Single playlist outlier"],
                    limitations=["Playlist start attribution may be incomplete"],
                )
            )

        if subs_gained is not None and views is not None and views > 0:
            conversion = subs_gained / views
            if conversion > 0.02:
                signals.append(
                    _signal(
                        signal_type=SignalType.SUBSCRIBER_CONVERSION_STRENGTH,
                        row=row,
                        window=window,
                        evidence={"subscribers_gained": subs_gained, "views": views, "conversion": conversion},
                        confidence=0.57,
                        explanation="Subscriber conversion appears stronger than typical thresholds.",
                        component="cta_timing",
                        action="Preserve CTA cadence patterns while monitoring consistency.",
                        alternatives=["External campaign traffic"],
                        limitations=["Subscriber source granularity unavailable"],
                    )
                )
            if conversion < 0.002:
                signals.append(
                    _signal(
                        signal_type=SignalType.SUBSCRIBER_CONVERSION_WEAKNESS,
                        row=row,
                        window=window,
                        evidence={"subscribers_gained": subs_gained, "views": views, "conversion": conversion},
                        confidence=0.57,
                        explanation="Subscriber conversion appears weak relative to view volume.",
                        component="cta_timing",
                        action="Test clearer subscription value framing.",
                        alternatives=["Low-intent traffic mix"],
                        limitations=["Conversion lag effects"],
                    )
                )

    return signals


def build_advisory_recommendations(*, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for sig in signals:
        recommendations.append(
            {
                "recommendation_id": "rec_" + _sha(_safe_text(sig.get("signal_id")))[:24],
                "signal_id": sig.get("signal_id"),
                "affected_component": sig.get("affected_component"),
                "evidence": sig.get("evidence_metrics"),
                "expected_direction": "improve" if _safe_text(sig.get("signal_type")) not in {
                    SignalType.STRONG_AVERAGE_PERCENTAGE_VIEWED.value,
                    SignalType.STRONG_SUGGESTED_TRAFFIC.value,
                    SignalType.SUBSCRIBER_CONVERSION_STRENGTH.value,
                    SignalType.SHORTS_STRONG_HOOK.value,
                } else "preserve",
                "confidence": float(sig.get("confidence") or 0.0),
                "minimum_sample_size": 3,
                "rollback_requirement": "Required before any production activation",
                "human_approval_required": True,
                "advisory_only": True,
                "pipeline_output_changed": False,
                "applied": False,
            }
        )
    return recommendations


def build_review_payloads(*, signals: list[dict[str, Any]], recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_signal = {_safe_text(r.get("signal_id")): r for r in recommendations}
    payloads: list[dict[str, Any]] = []

    for sig in signals:
        rec = by_signal.get(_safe_text(sig.get("signal_id")), {})
        payloads.append(
            {
                "review_id": "rev_" + _sha(_safe_text(sig.get("signal_id")))[:24],
                "signal": sig,
                "supporting_metrics": sig.get("supporting_metrics"),
                "hypothesis": {
                    "explanation": sig.get("explanation"),
                    "confidence": sig.get("confidence"),
                    "alternative_explanations": sig.get("alternative_explanations"),
                    "data_limitations": sig.get("data_limitations"),
                },
                "recommended_action": rec.get("affected_component"),
                "affected_channel": sig.get("channel_id"),
                "affected_content_type": sig.get("content_type"),
                "confidence": sig.get("confidence"),
                "sample_size": rec.get("minimum_sample_size", 0),
                "data_limitations": sig.get("data_limitations"),
                "advisory_only": True,
                "pipeline_output_changed": False,
                "auto_submit": False,
            }
        )

    return payloads


def run_phase4b_local_assessment(
    *,
    studio_files: list[Path],
    channel_performance_path: Path,
    runtime_dir: Path,
    ownership_dir: Path,
    manifest_path: Path,
    canonical_store_path: Path,
) -> dict[str, Any]:
    format_inventory: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []

    studio_provider = StudioExportProvider()
    local_provider = ExistingLocalAnalyticsProvider()

    for file_path in studio_files:
        parsed_rows, inventory = parse_studio_export_file(file_path)
        format_inventory.append(inventory)
        joined_rows: list[dict[str, Any]] = []
        for row in parsed_rows:
            join = join_canonical_record_identity(record=row, runtime_dir=runtime_dir, ownership_dir=ownership_dir)
            merged = dict(row)
            merged["content_id"] = join.get("content_id") or row.get("content_id")
            merged["canonical_channel_id"] = join.get("canonical_channel_id") or row.get("canonical_channel_id")
            merged["provenance"] = dict(merged.get("provenance") or {})
            merged["provenance"]["join_outcome"] = join.get("join_outcome")
            merged["provenance"]["join_method"] = join.get("join_method")
            merged["provenance"]["join_details"] = join.get("provenance")
            joined_rows.append(merged)

        imports.append(
            import_records_append_only(
                provider=studio_provider.name.value,
                source_file=file_path,
                candidate_rows=joined_rows,
                manifest_path=manifest_path,
                canonical_store_path=canonical_store_path,
            )
        )
        all_records.extend(joined_rows)

    local_rows = local_provider.collect_records(channel_performance_path=channel_performance_path)
    local_joined: list[dict[str, Any]] = []
    for row in local_rows:
        join = join_canonical_record_identity(record=row, runtime_dir=runtime_dir, ownership_dir=ownership_dir)
        merged = dict(row)
        merged["content_id"] = join.get("content_id") or row.get("content_id")
        merged["canonical_channel_id"] = join.get("canonical_channel_id") or row.get("canonical_channel_id")
        merged["provenance"] = dict(merged.get("provenance") or {})
        merged["provenance"]["join_outcome"] = join.get("join_outcome")
        merged["provenance"]["join_method"] = join.get("join_method")
        merged["provenance"]["join_details"] = join.get("provenance")
        local_joined.append(merged)

    imports.append(
        import_records_append_only(
            provider=local_provider.name.value,
            source_file=channel_performance_path,
            candidate_rows=local_joined,
            manifest_path=manifest_path,
            canonical_store_path=canonical_store_path,
        )
    )
    all_records.extend(local_joined)

    canonical_rows, canonical_malformed = load_canonical_records(path=canonical_store_path)
    history = reconstruct_metric_history(rows=canonical_rows)
    coverage = compute_coverage(canonical_rows)
    baselines = build_baselines(canonical_rows)
    signals = derive_learning_signals(rows=canonical_rows, baselines=baselines)
    recommendations = build_advisory_recommendations(signals=signals)
    review_payloads = build_review_payloads(signals=signals, recommendations=recommendations)

    signal_counts: dict[str, int] = {}
    for sig in signals:
        st = _safe_text(sig.get("signal_type"))
        signal_counts[st] = signal_counts.get(st, 0) + 1

    summary = {
        "generated_at": _now_iso(),
        "provider_priority": provider_priority(),
        "format_inventory": format_inventory,
        "imports": imports,
        "canonical_rows": len(canonical_rows),
        "canonical_malformed": canonical_malformed,
        "coverage": coverage,
        "history_count": len(history),
        "baselines": baselines,
        "signal_count": len(signals),
        "signal_counts": signal_counts,
        "recommendation_count": len(recommendations),
        "review_payload_count": len(review_payloads),
        "future_official_provider": {
            "implemented": False,
            "interface_only": True,
            "api_calls_made": False,
            "oauth_implemented": False,
        },
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    return {
        "summary": summary,
        "canonical_rows": canonical_rows,
        "history": history,
        "signals": signals,
        "recommendations": recommendations,
        "review_payloads": review_payloads,
    }
