"""Pexels Stok Video ve Gorsel Indirici"""
import logging
import os
import re
from pathlib import Path

import requests

from .config import config
from .forensic_telemetry import sanitize_url
from .visual_safety_policy import evaluate_visual_query

logger = logging.getLogger(__name__)

PEXELS_PHOTOS_URL = "https://api.pexels.com/v1/search"
PEXELS_VIDEOS_URL = "https://api.pexels.com/videos/search"

KEYWORD_MAP = {
    # Kişisel Finans
    "yatirim": "investment portfolio chart graph documents desk",
    "portfoy": "investment portfolio chart analysis spreadsheet",
    "para": "money cash coins banknotes wallet finance",
    "birikim": "savings jar coins piggy bank desk finance",
    "tasarruf": "savings budget spreadsheet calculator finance desk",
    "butce": "budget spreadsheet calculator finance planning desk",
    "emeklilik": "retirement savings pension fund documents planning office",
    "maas": "paycheck salary income documents finance desk",
    "gelir": "income finance earnings chart graph",
    "harcama": "budget expenses spreadsheet finance planning",
    # Borsa
    "borsa": "stock market chart trading screen analysis desk",
    "hisse": "stock chart trading screen monitor finance",
    "teknik analiz": "stock chart technical analysis graph screen",
    "temetu": "dividend stocks chart income finance documents",
    "bist": "stock exchange chart trading screen monitor",
    # Kripto
    "kripto": "cryptocurrency bitcoin coin chart screen technology",
    "bitcoin": "bitcoin coin chart cryptocurrency technology screen",
    "blockchain": "blockchain technology network digital nodes",
    "nft": "digital technology art blockchain screen",
    "altcoin": "cryptocurrency coin chart trading screen",
    # Makro / Ekonomi
    "enflasyon": "inflation price rising chart economy graph",
    "faiz": "interest rate bank finance chart graph",
    "dolar": "dollar currency exchange chart finance banknote",
    "doviz": "currency exchange forex chart trading screen",
    "altin": "gold bullion coin bar precious metal finance",
    "ekonomi": "economy finance chart graph analysis desk",
    "merkez bankasi": "central bank finance economy building",
    # Gayrimenkul
    "gayrimenkul": "real estate house building property architecture exterior",
    "konut": "house building property architecture exterior",
    "kira": "apartment building property exterior architecture",
    # Kariyer
    "kariyer": "career office laptop desk planning professional",
    "is hayati": "office workspace desk laptop planning",
    "girisim": "startup office workspace desk laptop planning",
    "liderlik": "office meeting room whiteboard planning",
    # Genel
    "finans": "finance chart money desk office planning",
    "teknoloji": "technology computer screen code software digital",
    "yapay zeka": "artificial intelligence technology computer circuit digital",
    "egitim": "education books library desk classroom learning notebook",
    "psikoloji": "psychology books desk therapy journal notebook",
    "saglik": "health medical clinic equipment nutrition food",
}

# Pexels fotoğraf alt-text filtresi — insan/lifestyle içerenleri at
# Legacy broad regex — now replaced by image_relevance_guard policies.
# Kept for backward-compat with _photo_is_safe / _video_is_safe helpers below.
PHOTO_REJECT_RE = re.compile(
    r'\b(bikini|swimsuit|swimwear|lingerie|beachwear|'
    r'nude|naked|topless|explicit|erotic|'
    r'nightclub|nightlife)\b',
    re.IGNORECASE,
)


def _photo_is_safe(photo: dict) -> bool:
    """Hard-block filter — kept for legacy callers; guard handles full policy."""
    from .image_relevance_guard import _HARD_BLOCK_RE
    alt = str(photo.get("alt", "") or "")
    url = str(photo.get("url", "") or "")
    return not bool(_HARD_BLOCK_RE.search(f"{alt} {url}"))


def _video_is_safe(video: dict) -> bool:
    """Hard-block filter — kept for legacy callers; guard handles full policy."""
    from .image_relevance_guard import _HARD_BLOCK_RE
    url = str(video.get("url", "") or "")
    tags = " ".join(str(t) for t in (video.get("tags") or []))
    return not bool(_HARD_BLOCK_RE.search(f"{url} {tags}"))


RISKY_QUERY_PATTERNS = (
    "bikini",
    "swimsuit",
    "lingerie",
    "beachwear",
    "sensual",
    "sexy",
    "glamour",
    "nightlife",
    "party girl",
    "fashion model",
)

NICHE_RELEVANCE_KEYWORDS = {
    "egitim": {"education", "learning", "study", "student", "teacher", "classroom", "school", "library", "book", "books", "notebook", "desk", "exam", "course"},
    "kisisel_finans": {"finance", "money", "budget", "saving", "savings", "planning", "documents", "desk", "office", "calculator", "chart"},
    "borsa": {"finance", "trading", "chart", "market", "investment", "stock", "office", "desk", "analysis"},
    "kripto": {"crypto", "cryptocurrency", "bitcoin", "blockchain", "trading", "chart", "technology", "screen"},
    "kariyer": {"career", "professional", "office", "work", "team", "meeting", "laptop", "planning", "presentation"},
    "girisim": {"startup", "entrepreneur", "office", "team", "pitch", "laptop", "workspace", "planning", "innovation"},
    "teknoloji": {"technology", "computer", "coding", "software", "digital", "device", "workspace", "screen", "innovation"},
    "gayrimenkul": {"real", "estate", "property", "home", "house", "apartment", "interior", "architecture", "building"},
    "saglik": {"health", "medical", "wellness", "clinic", "doctor", "fitness", "nutrition", "hospital", "therapy"},
    "psikoloji": {"psychology", "mental", "mind", "therapy", "meditation", "journal", "wellness", "reflection", "counseling", "emotion"},
}

NICHE_ALIASES = {
    "girisimcilik": "girisim",
}

SAFE_DEFAULT_QUERY_BY_NICHE = {
    "kisisel_finans": "personal finance budgeting savings desk",
    "borsa": "stock market analysis charts desk",
    "kripto": "cryptocurrency blockchain trading screens",
    "kariyer": "career professional office laptop planning",
    "girisim": "startup entrepreneur team workspace planning",
    "teknoloji": "technology software digital workspace screens",
    "egitim": "education learning study books classroom",
    "gayrimenkul": "real estate home interior property",
    "saglik": "health wellness nutrition clinic fitness",
    "psikoloji": "psychology mental wellness reflection journal",
}


def _normalize_niche(niche: str | None) -> str:
    raw = str(niche or "").strip().lower()
    return NICHE_ALIASES.get(raw, raw)


class ImageFetcher:
    def __init__(self, channel_cfg=None):
        from .config import config as _cfg
        cfg = channel_cfg if channel_cfg else _cfg
        self.channel_cfg = cfg
        self.api_key = os.getenv("PEXELS_API_KEY", "") if not channel_cfg else getattr(cfg, "pexels_api_key", os.getenv("PEXELS_API_KEY", ""))
        self.has_api = bool(self.api_key) and not self.api_key.startswith("your_")
        self.last_forensic_trace = {
            "provider": "pexels",
            "query_attempts": [],
            "selected_assets": [],
            "asset_metadata_by_local_path": {},
            "deterministic_inputs": {},
            "cache_provenance": [],
        }

    def _record_forensic_trace(self, trace: dict) -> None:
        if not isinstance(trace, dict):
            return
        self.last_forensic_trace = {
            "provider": "pexels",
            "query_attempts": list(trace.get("query_attempts") or []),
            "selected_assets": list(trace.get("selected_assets") or []),
            "asset_metadata_by_local_path": dict(trace.get("asset_metadata_by_local_path") or {}),
            "deterministic_inputs": dict(trace.get("deterministic_inputs") or {}),
            "cache_provenance": list(trace.get("cache_provenance") or []),
        }

    def _fallback_query(self, title: str) -> str:
        niche = _normalize_niche(getattr(self.channel_cfg, "niche", ""))
        canonical = SAFE_DEFAULT_QUERY_BY_NICHE.get(niche, "business office planning desk")
        configured = str(getattr(self.channel_cfg, "pexels_query", "") or "").strip()
        if configured and self._is_query_allowed_for_niche(configured, niche=niche):
            return configured
        extracted = self._extract_query(title)
        if self._is_query_allowed_for_niche(extracted, niche=niche):
            return extracted
        return canonical

    def _is_query_allowed_for_niche(self, query: str | None, *, niche: str | None = None) -> bool:
        raw = str(query or "").strip()
        if not raw:
            return False

        normalized = re.sub(r"[^a-z0-9\s-]", " ", raw.lower())
        normalized = " ".join(normalized.split())
        if not normalized:
            return False

        if any(pattern in normalized for pattern in RISKY_QUERY_PATTERNS):
            return False

        normalized_niche = _normalize_niche(niche if niche is not None else getattr(self.channel_cfg, "niche", ""))
        relevance_keywords = NICHE_RELEVANCE_KEYWORDS.get(normalized_niche)
        if relevance_keywords:
            tokens = set(normalized.split())
            return bool(tokens.intersection(relevance_keywords))
        return True

    def _sanitize_query(self, query: str | None, title: str) -> str:
        raw = str(query or "").strip()
        fallback = self._fallback_query(title)
        if not raw:
            return fallback

        decision = evaluate_visual_query(
            query=raw,
            channel_id=str(getattr(self.channel_cfg, "channel_id", "unknown") or "unknown"),
            niche=getattr(self.channel_cfg, "niche", ""),
            topic=title,
        )
        if not decision.allowed:
            logger.warning(
                "Visual safety query rejected; fallback applied: channel=%s reason=%s query=%s rewrite=%s",
                getattr(self.channel_cfg, "channel_id", "unknown"),
                decision.reason,
                raw,
                decision.rewritten_query or fallback,
            )
            return fallback

        if not self._is_query_allowed_for_niche(raw):
            niche = _normalize_niche(getattr(self.channel_cfg, "niche", ""))
            logger.warning("Unsafe or off-niche Pexels query rejected; fallback applied: niche=%s query=%s", niche, raw)
            return fallback

        return raw

    def _channel_context(self) -> tuple[str, str]:
        """Return (channel_id, niche) for observability."""
        cid = str(getattr(self.channel_cfg, "channel_id", "") or "unknown")
        niche = str(getattr(self.channel_cfg, "niche", "") or "")
        return cid, niche

    def fetch_video_clips(self, title: str, count: int = 6, output_dir: str = "", query_override: str = None) -> list:
        """Konuyla ilgili Pexels video klibi indir — relevance guard uygulanır."""
        from .image_relevance_guard import (
            build_safe_search_queries,
            select_safe_assets,
            SearchObservability,
            record_search_observability,
        )

        if not self.has_api:
            logger.warning("Pexels API anahtari yok! Statik arka plan kullanilacak.")
            return []

        channel_id, niche = self._channel_context()
        original_query = self._sanitize_query(
            query_override if query_override else self._extract_query(title), title
        )
        output_dir = output_dir or "output/clips"
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Build query candidates: primary + safe fallbacks
        query_candidates = [original_query] + build_safe_search_queries(title, niche, channel_id)
        forensic_trace = {
            "provider": "pexels",
            "query_attempts": [],
            "selected_assets": [],
            "asset_metadata_by_local_path": {},
            "deterministic_inputs": {
                "title_hash": hash(title),
                "query_override": str(query_override or ""),
            },
            "cache_provenance": [],
        }

        obs = SearchObservability(
            channel_id=channel_id,
            topic=title[:60],
            niche=niche,
            original_query=original_query,
            effective_query=original_query,
            media_type="video",
        )

        paths: list[str] = []
        for attempt, query in enumerate(query_candidates):
            if len(paths) >= count:
                break
            forensic_trace["query_attempts"].append(
                {
                    "attempt": int(attempt),
                    "query": str(query),
                    "media_type": "video",
                }
            )
            obs.effective_query = query
            if attempt > 0:
                obs.fallback_used = True
                obs.fallback_reason = f"attempt_{attempt}: insufficient safe results"

            logger.info(f"Pexels video aranıyor [{attempt+1}]: {query}")
            try:
                resp = requests.get(
                    PEXELS_VIDEOS_URL,
                    headers={"Authorization": self.api_key},
                    params={"query": query, "per_page": max(count * 3, 15), "orientation": "landscape"},
                    timeout=15,
                )
                resp.raise_for_status()
                raw_videos = resp.json().get("videos", [])
                obs.total_candidates += len(raw_videos)

                need = count - len(paths)
                safe_videos, classifications = select_safe_assets(
                    raw_videos, "video", title, niche, query, max_count=need
                )
                obs.classifications.extend(classifications)
                obs.accepted += len(safe_videos)
                obs.rejected += len(raw_videos) - len(safe_videos)
                obs.hard_blocked += sum(1 for c in classifications if c.hard_blocked)
                obs.low_relevance += sum(
                    1 for c in classifications
                    if c.rejection_reason and "low_relevance" in c.rejection_reason
                )

                for video in safe_videos:
                    files = sorted(
                        video.get("video_files", []),
                        key=lambda x: x.get("width", 0),
                        reverse=True,
                    )
                    best = next(
                        (f for f in files if f.get("width", 0) >= 1280 and f.get("file_type") == "video/mp4"),
                        files[0] if files else None,
                    )
                    if not best:
                        continue
                    clip_path = f"{output_dir}/clip_{len(paths):02d}.mp4"
                    self._download_file(best["link"], clip_path)
                    paths.append(clip_path)
                    provider_asset_id = str(video.get("id") or "")
                    provider_url = str(video.get("url") or "")
                    forensic_trace["selected_assets"].append(
                        {
                            "candidate_asset_id": provider_asset_id,
                            "provider_asset_id": provider_asset_id,
                            "provider": "pexels",
                            "source_url": sanitize_url(provider_url),
                            "local_path": clip_path,
                            "media_type": "video",
                            "query": str(query),
                        }
                    )
                    forensic_trace["asset_metadata_by_local_path"][clip_path] = {
                        "provider_asset_id": provider_asset_id,
                        "source_url": sanitize_url(provider_url),
                        "provider": "pexels",
                        "media_type": "video",
                        "query": str(query),
                    }
                    obs.selected_asset_urls.append(str(video.get("url", "")))
                    logger.info(f"Klip indirildi [{query[:40]}]: {clip_path}")

            except Exception as exc:
                logger.warning(f"Video klip indirme başarısız (attempt {attempt+1}): {exc}")

        # Final fallback: photos if no videos found
        if not paths:
            logger.warning("Tüm video sorguları başarısız — fotoğrafa geçiliyor")
            obs.fallback_used = True
            obs.fallback_reason = "all_video_queries_failed_using_photos"
            paths = self.fetch_images(title, count, output_dir)
            inherited = dict(getattr(self, "last_forensic_trace", {}) or {})
            if inherited:
                forensic_trace["query_attempts"].extend(list(inherited.get("query_attempts") or []))
                forensic_trace["selected_assets"].extend(list(inherited.get("selected_assets") or []))
                forensic_trace["asset_metadata_by_local_path"].update(dict(inherited.get("asset_metadata_by_local_path") or {}))
                for key, value in dict(inherited.get("deterministic_inputs") or {}).items():
                    forensic_trace["deterministic_inputs"][key] = value

        record_search_observability(obs)
        self._record_forensic_trace(forensic_trace)
        logger.info(f"Toplam {len(paths)} medya dosyasi hazir. "
                    f"[accepted={obs.accepted} rejected={obs.rejected} hard_blocked={obs.hard_blocked}]")
        return paths

    def fetch_images(self, title: str, count: int = 8, output_dir: str = "") -> list:
        """Yedek fotoğrafları indir — relevance guard uygulanır."""
        from .image_relevance_guard import (
            build_safe_search_queries,
            select_safe_assets,
            SearchObservability,
            record_search_observability,
        )

        if not self.has_api:
            return []

        channel_id, niche = self._channel_context()
        original_query = self._sanitize_query(self._extract_query(title), title)
        output_dir = output_dir or f"{config.output_dir}/images"
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        query_candidates = [original_query] + build_safe_search_queries(title, niche, channel_id)
        forensic_trace = {
            "provider": "pexels",
            "query_attempts": [],
            "selected_assets": [],
            "asset_metadata_by_local_path": {},
            "deterministic_inputs": {
                "title_hash": hash(title),
            },
            "cache_provenance": [],
        }

        obs = SearchObservability(
            channel_id=channel_id,
            topic=title[:60],
            niche=niche,
            original_query=original_query,
            effective_query=original_query,
            media_type="photo",
        )

        paths: list[str] = []
        for attempt, query in enumerate(query_candidates):
            if len(paths) >= count:
                break
            forensic_trace["query_attempts"].append(
                {
                    "attempt": int(attempt),
                    "query": str(query),
                    "media_type": "photo",
                }
            )
            obs.effective_query = query
            if attempt > 0:
                obs.fallback_used = True
                obs.fallback_reason = f"attempt_{attempt}: insufficient safe results"

            try:
                resp = requests.get(
                    PEXELS_PHOTOS_URL,
                    headers={"Authorization": self.api_key},
                    params={"query": query, "per_page": max(count * 3, 15), "orientation": "landscape"},
                    timeout=15,
                )
                resp.raise_for_status()
                raw_photos = resp.json().get("photos", [])
                obs.total_candidates += len(raw_photos)

                need = count - len(paths)
                safe_photos, classifications = select_safe_assets(
                    raw_photos, "photo", title, niche, query, max_count=need
                )
                obs.classifications.extend(classifications)
                obs.accepted += len(safe_photos)
                obs.rejected += len(raw_photos) - len(safe_photos)
                obs.hard_blocked += sum(1 for c in classifications if c.hard_blocked)

                for photo in safe_photos:
                    img_path = f"{output_dir}/img_{len(paths):02d}.jpg"
                    self._download_file(photo["src"]["large2x"], img_path)
                    paths.append(img_path)
                    provider_asset_id = str(photo.get("id") or "")
                    provider_url = str(photo.get("url") or "")
                    forensic_trace["selected_assets"].append(
                        {
                            "candidate_asset_id": provider_asset_id,
                            "provider_asset_id": provider_asset_id,
                            "provider": "pexels",
                            "source_url": sanitize_url(provider_url),
                            "local_path": img_path,
                            "media_type": "photo",
                            "query": str(query),
                        }
                    )
                    forensic_trace["asset_metadata_by_local_path"][img_path] = {
                        "provider_asset_id": provider_asset_id,
                        "source_url": sanitize_url(provider_url),
                        "provider": "pexels",
                        "media_type": "photo",
                        "query": str(query),
                    }
                    obs.selected_asset_urls.append(str(photo.get("url", "")))
            except Exception as exc:
                logger.warning(f"Fotoğraf indirme başarısız (attempt {attempt+1}): {exc}")

        record_search_observability(obs)
        self._record_forensic_trace(forensic_trace)
        return paths

    def fetch_thumbnail_photo(self, title: str, output_path: str = "") -> str | None:
        """Thumbnail için konuya özel fotoğraf indir — relevance guard uygulanır."""
        from .image_relevance_guard import select_safe_assets

        if not self.has_api:
            return None
        query = self._sanitize_query(self._extract_thumbnail_query(title), title)
        if not output_path:
            import tempfile
            output_path = tempfile.mktemp(suffix="_thumb_bg.jpg")

        _, niche = self._channel_context()

        try:
            resp = requests.get(
                PEXELS_PHOTOS_URL,
                headers={"Authorization": self.api_key},
                params={"query": query, "per_page": 30, "orientation": "landscape"},
                timeout=12,
            )
            resp.raise_for_status()
            photos = resp.json().get("photos", [])
            if not photos:
                return None

            safe_photos, _ = select_safe_assets(photos, "photo", title, niche, query, max_count=20)
            if not safe_photos:
                logger.warning(f"Thumbnail: tüm fotoğraflar filtrelendi — sorgu: {query}")
                return None

            # Hash-tabanlı seçim: tutarlı ama her video farklı
            idx = hash(title) % len(safe_photos)
            photo = safe_photos[idx]
            url = photo["src"].get("large2x") or photo["src"]["large"]
            self._download_file(url, output_path)
            trace = dict(getattr(self, "last_forensic_trace", {}) or {})
            trace.setdefault("provider", "pexels")
            trace.setdefault("query_attempts", [])
            trace.setdefault("selected_assets", [])
            trace.setdefault("asset_metadata_by_local_path", {})
            trace.setdefault("deterministic_inputs", {})
            trace.setdefault("cache_provenance", [])
            trace["query_attempts"].append(
                {
                    "attempt": 0,
                    "query": str(query),
                    "media_type": "thumbnail_photo",
                }
            )
            provider_asset_id = str(photo.get("id") or "")
            provider_url = str(photo.get("url") or "")
            trace["selected_assets"].append(
                {
                    "candidate_asset_id": provider_asset_id,
                    "provider_asset_id": provider_asset_id,
                    "provider": "pexels",
                    "source_url": sanitize_url(provider_url),
                    "local_path": output_path,
                    "media_type": "thumbnail_photo",
                    "query": str(query),
                }
            )
            trace["asset_metadata_by_local_path"][output_path] = {
                "provider_asset_id": provider_asset_id,
                "source_url": sanitize_url(provider_url),
                "provider": "pexels",
                "media_type": "thumbnail_photo",
                "query": str(query),
            }
            trace["deterministic_inputs"]["thumbnail_selection"] = {
                "title_hash": hash(title),
                "candidate_count": len(safe_photos),
                "selected_index": idx,
            }
            self._record_forensic_trace(trace)
            logger.info(f"Thumbnail fotoğrafı indirildi: {query}")
            return output_path
        except Exception as exc:
            logger.warning(f"Thumbnail fotoğrafı alınamadı: {exc}")
            return None

    def _extract_thumbnail_query(self, title: str) -> str:
        """Thumbnail için daha sinematik / görsel odaklı sorgu."""
        base = self._extract_query(title)
        # Thumbnail için daha dramatik, atmosferik kelimeler ekle
        atmospheric = ["dramatic lighting", "cinematic", "professional", "vibrant"]
        import random
        rng = random.Random(hash(title))
        suffix = rng.choice(atmospheric)
        return f"{base} {suffix}"

    def _extract_query(self, title: str) -> str:
        """Başlık/script'ten en iyi Pexels arama sorgusunu çıkar (çoklu eşleşme)."""
        title_lower = title.lower()
        matches = []
        for tr_word, en_query in KEYWORD_MAP.items():
            if tr_word in title_lower:
                matches.append(en_query)
        if matches:
            # Birden fazla eşleşme varsa en spesifikini döndür (en uzun)
            return max(matches, key=len)
        return "business finance success professional"

    def _download_file(self, url: str, path: str):
        resp = requests.get(url, timeout=60, stream=True)
        resp.raise_for_status()
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
