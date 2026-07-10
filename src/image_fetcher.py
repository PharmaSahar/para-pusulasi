"""Pexels Stok Video ve Gorsel Indirici"""
import logging
import os
import re
from pathlib import Path

import requests

from .config import config

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
PHOTO_REJECT_RE = re.compile(
    r'\b(bikini|swimsuit|swimwear|lingerie|beachwear|'
    r'woman|man|girl|boy|lady|female|male|person|people|portrait|'
    r'model|fashion|glamour|sexy|sensual|beauty|attractive|'
    r'vacation|holiday|resort|tropical|beach|pool|'
    r'influencer|lifestyle|selfie|dating)\b',
    re.IGNORECASE,
)


def _photo_is_safe(photo: dict) -> bool:
    """Alt text veya URL'den uygunsuz/alakasız fotoğrafı filtrele."""
    alt = str(photo.get("alt", "") or "")
    url = str(photo.get("url", "") or "")
    return not bool(PHOTO_REJECT_RE.search(f"{alt} {url}"))


def _video_is_safe(video: dict) -> bool:
    """Video metaverisinden uygunsuz içeriği filtrele."""
    url = str(video.get("url", "") or "")
    tags = " ".join(str(t) for t in (video.get("tags") or []))
    return not bool(PHOTO_REJECT_RE.search(f"{url} {tags}"))


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

        if not self._is_query_allowed_for_niche(raw):
            niche = _normalize_niche(getattr(self.channel_cfg, "niche", ""))
            logger.warning("Unsafe or off-niche Pexels query rejected; fallback applied: niche=%s query=%s", niche, raw)
            return fallback

        return raw

    def fetch_video_clips(self, title: str, count: int = 6, output_dir: str = "", query_override: str = None) -> list:
        """Konuyla ilgili Pexels video klibi indir."""
        if not self.has_api:
            logger.warning("Pexels API anahtari yok! Statik arka plan kullanilacak.")
            return []

        query = self._sanitize_query(query_override if query_override else self._extract_query(title), title)
        output_dir = output_dir or "output/clips"
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        logger.info("Pexels video klipleri aranıyor: " + query)
        paths = []
        try:
            resp = requests.get(
                PEXELS_VIDEOS_URL,
                headers={"Authorization": self.api_key},
                params={"query": query, "per_page": count, "orientation": "landscape"},
                timeout=15,
            )
            resp.raise_for_status()
            videos = resp.json().get("videos", [])

            for i, video in enumerate(videos):
                # Uygunsuz/alakasız video filtresi
                if not _video_is_safe(video):
                    logger.debug(f"Video filtrelendi (içerik): {video.get('url', '')}")
                    continue
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
                clip_path = f"{output_dir}/clip_{i:02d}.mp4"
                self._download_file(best["link"], clip_path)
                paths.append(clip_path)
                logger.info(f"Klip indirildi: {clip_path}")

        except Exception as e:
            logger.warning("Video klip indirme basarisiz: " + str(e))
            paths = self.fetch_images(title, count, output_dir)

        logger.info(f"Toplam {len(paths)} medya dosyasi hazir.")
        return paths

    def fetch_images(self, title: str, count: int = 8, output_dir: str = "") -> list:
        """Yedek: fotograflari indir."""
        if not self.has_api:
            return []
        query = self._sanitize_query(self._extract_query(title), title)
        output_dir = output_dir or f"{config.output_dir}/images"
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        paths = []
        try:
            resp = requests.get(
                PEXELS_PHOTOS_URL,
                headers={"Authorization": self.api_key},
                params={"query": query, "per_page": count, "orientation": "landscape"},
                timeout=15,
            )
            resp.raise_for_status()
            for i, photo in enumerate(resp.json().get("photos", [])):
                # Uygunsuz/alakasız fotoğraf filtresi
                if not _photo_is_safe(photo):
                    logger.debug(f"Fotoğraf filtrelendi (içerik): {photo.get('alt', '')}")
                    continue
                img_path = f"{output_dir}/img_{i:02d}.jpg"
                self._download_file(photo["src"]["large2x"], img_path)
                paths.append(img_path)
        except Exception as e:
            logger.warning("Fotograf indirme basarisiz: " + str(e))
        return paths

    def fetch_thumbnail_photo(self, title: str, output_path: str = "") -> str | None:
        """Thumbnail için konuya özel yüksek çözünürlüklü fotoğraf indir."""
        if not self.has_api:
            return None
        query = self._sanitize_query(self._extract_thumbnail_query(title), title)
        if not output_path:
            import tempfile
            output_path = tempfile.mktemp(suffix="_thumb_bg.jpg")
        try:
            resp = requests.get(
                PEXELS_PHOTOS_URL,
                headers={"Authorization": self.api_key},
                params={"query": query, "per_page": 20, "orientation": "landscape"},
                timeout=12,
            )
            resp.raise_for_status()
            photos = resp.json().get("photos", [])
            if not photos:
                return None
            # Title hash ile tutarlı ama her video farklı fotoğraf
            idx = hash(title) % len(photos)
            photo = photos[idx]
            url = photo["src"].get("large2x") or photo["src"]["large"]
            self._download_file(url, output_path)
            logger.info(f"Thumbnail fotoğrafı indirildi: {query}")
            return output_path
        except Exception as e:
            logger.warning(f"Thumbnail fotoğrafı alınamadı: {e}")
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
