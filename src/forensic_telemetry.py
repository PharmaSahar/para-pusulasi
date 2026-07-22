from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from PIL import Image


FORENSIC_SCHEMA_VERSION = "forensic.generation.v1"
FORENSIC_COMPONENT = "production_quality_platform.write_immutable_generation_forensic_record"
PERCEPTUAL_HASH_ALGORITHM = "average_hash_8x8.v1"

_REQUIRED_TOP_LEVEL_FIELDS = {
    "forensic_schema_version",
    "timestamp_utc",
    "release_sha",
    "run_id",
    "content_id",
    "channel_id",
    "topic",
    "provider",
    "media_queries",
    "provider_asset_ids",
    "asset_urls_sanitized",
    "asset_fingerprints",
    "perceptual_hashes",
    "selected_visuals",
    "scene_order",
    "thumbnail_prompt",
    "thumbnail_hash",
    "render_hash",
    "video_id",
    "youtube_url",
    "qa_result",
    "generation_result",
    "record_hash",
    "created_by_component",
    "cache_provenance",
}

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|token|secret|password|authorization|cookie|session|bearer|access[_-]?token|refresh[_-]?token)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(bearer\s+[a-z0-9._-]+|sk-[a-z0-9]+|AIza[0-9A-Za-z_-]{20,}|xox[baprs]-[0-9A-Za-z-]+|ghp_[0-9A-Za-z]{20,}|ya29\.[0-9A-Za-z._-]+)",
    re.IGNORECASE,
)
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str | None:
    p = Path(str(path or "").strip())
    if not p.exists() or not p.is_file():
        return None
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_url(url: str | None) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except Exception:
        return ""
    netloc = parsed.netloc.split("@")[-1]
    sanitized = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    return sanitized


def average_hash_8x8(image_path: str | Path) -> dict[str, Any]:
    path = Path(str(image_path or "").strip())
    if not path.exists() or not path.is_file():
        return {
            "value": None,
            "status": "missing_file",
            "algorithm": PERCEPTUAL_HASH_ALGORITHM,
        }

    suffix = path.suffix.lower()
    if suffix not in _IMAGE_EXTENSIONS:
        return {
            "value": None,
            "status": "unsupported_media_type",
            "algorithm": PERCEPTUAL_HASH_ALGORITHM,
        }

    try:
        with Image.open(path) as img:
            gray = img.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
            pixels = list(gray.getdata())
    except Exception as exc:
        return {
            "value": None,
            "status": f"error:{exc.__class__.__name__}",
            "algorithm": PERCEPTUAL_HASH_ALGORITHM,
        }

    avg = sum(pixels) / 64.0
    bits = "".join("1" if px >= avg else "0" for px in pixels)
    return {
        "value": f"{int(bits, 2):016x}",
        "status": "ok",
        "algorithm": PERCEPTUAL_HASH_ALGORITHM,
    }


def _contains_secret_like_data(value: Any, parent_key: str = "") -> bool:
    if isinstance(value, dict):
        for key, val in value.items():
            if _SECRET_KEY_RE.search(str(key)):
                return True
            if _contains_secret_like_data(val, parent_key=str(key)):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_secret_like_data(item, parent_key=parent_key) for item in value)
    text = str(value or "")
    return bool(_SECRET_VALUE_RE.search(text))


def _validate_hash_field(name: str, value: Any, *, nullable: bool = True, allow_short_hash: bool = False) -> None:
    if value is None:
        if nullable:
            return
        raise ValueError(f"forensic_invalid_{name}:null")
    text = str(value).strip().lower()
    if not text:
        if nullable:
            return
        raise ValueError(f"forensic_invalid_{name}:empty")
    if allow_short_hash and re.fullmatch(r"[0-9a-f]{16}", text):
        return
    if not _HEX64_RE.fullmatch(text):
        raise ValueError(f"forensic_invalid_{name}:format")


def validate_forensic_record(record: dict[str, Any]) -> None:
    if not isinstance(record, dict):
        raise ValueError("forensic_invalid_payload:type")

    missing = sorted(_REQUIRED_TOP_LEVEL_FIELDS - set(record.keys()))
    if missing:
        raise ValueError(f"forensic_invalid_payload:missing={missing}")

    if str(record.get("forensic_schema_version") or "") != FORENSIC_SCHEMA_VERSION:
        raise ValueError("forensic_invalid_schema_version")

    for field in ("timestamp_utc", "run_id", "content_id", "channel_id", "created_by_component"):
        if not str(record.get(field) or "").strip():
            raise ValueError(f"forensic_invalid_{field}:empty")

    for field in (
        "media_queries",
        "provider_asset_ids",
        "asset_urls_sanitized",
        "asset_fingerprints",
        "perceptual_hashes",
        "selected_visuals",
        "scene_order",
        "cache_provenance",
    ):
        if not isinstance(record.get(field), list):
            raise ValueError(f"forensic_invalid_{field}:not_list")

    if _contains_secret_like_data(record):
        raise ValueError("forensic_invalid_secret_like_data")

    for url in record.get("asset_urls_sanitized", []):
        text = str(url or "")
        if "?" in text or "#" in text:
            raise ValueError("forensic_invalid_asset_urls_sanitized:query_or_fragment")

    for value in record.get("asset_fingerprints", []):
        _validate_hash_field("asset_fingerprint", value, nullable=False)

    _validate_hash_field("thumbnail_hash", record.get("thumbnail_hash"), nullable=True)
    _validate_hash_field("render_hash", record.get("render_hash"), nullable=True)

    scene_order = record.get("scene_order") or []
    for index, item in enumerate(scene_order):
        if not isinstance(item, dict):
            raise ValueError("forensic_invalid_scene_order:item_type")
        scene_index = item.get("scene_index")
        if int(scene_index) != index:
            raise ValueError("forensic_invalid_scene_order:index")
        if item.get("asset_fingerprint"):
            _validate_hash_field("scene_asset_fingerprint", item.get("asset_fingerprint"), nullable=False)
        if item.get("local_asset_hash"):
            _validate_hash_field("scene_local_asset_hash", item.get("local_asset_hash"), nullable=False)

    raw_hash = str(record.get("record_hash") or "").lower()
    if not _HEX64_RE.fullmatch(raw_hash):
        raise ValueError("forensic_invalid_record_hash:format")

    expected_hash = compute_record_hash(record)
    if raw_hash != expected_hash:
        raise ValueError("forensic_invalid_record_hash:mismatch")


def compute_record_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_hash", None)
    return sha256_text(canonical_json(payload))


def atomic_create_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"forensic_record_exists:{target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)

    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(blob)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        if target.exists():
            raise FileExistsError(f"forensic_record_exists:{target}")
        os.replace(tmp_path, target)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def build_forensic_record_path(*, root_dir: str | Path, channel_id: str, run_id: str, content_id: str) -> Path:
    return Path(root_dir) / str(channel_id) / str(run_id) / f"{content_id}.forensic.v1.json"


def write_immutable_forensic_record(*, root_dir: str | Path, record: dict[str, Any]) -> Path:
    validate_forensic_record(record)
    path = build_forensic_record_path(
        root_dir=root_dir,
        channel_id=str(record.get("channel_id") or ""),
        run_id=str(record.get("run_id") or ""),
        content_id=str(record.get("content_id") or ""),
    )
    atomic_create_json(path, record)
    return path
