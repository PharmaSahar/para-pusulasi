"""Pexels Stok Video ve Gorsel Indirici"""
import logging
import os
from pathlib import Path

import requests

from .config import config

logger = logging.getLogger(__name__)

PEXELS_PHOTOS_URL = "https://api.pexels.com/v1/search"
PEXELS_VIDEOS_URL = "https://api.pexels.com/videos/search"

KEYWORD_MAP = {
    # Kişisel Finans
    "yatirim": "investment growth financial success",
    "portfoy": "investment portfolio stock chart",
    "para": "money cash wealth abundance",
    "birikim": "savings piggy bank coins",
    "tasarruf": "saving money budget planning",
    "butce": "budget finance planning spreadsheet",
    "emeklilik": "retirement elderly happy sunset",
    "maas": "salary paycheck income professional",
    "gelir": "income money earning business",
    "harcama": "shopping spending money purchase",
    # Borsa
    "borsa": "stock market trading charts bull",
    "hisse": "stock trading financial market",
    "teknik analiz": "stock chart analysis trading",
    "temetu": "dividend investment stocks profit",
    "bist": "stock exchange trading finance",
    # Kripto
    "kripto": "cryptocurrency bitcoin blockchain digital",
    "bitcoin": "bitcoin cryptocurrency trading chart",
    "blockchain": "blockchain technology digital network",
    "nft": "digital art nft technology",
    "altcoin": "cryptocurrency exchange trading",
    # Makro / Ekonomi
    "enflasyon": "inflation economy prices rising",
    "faiz": "interest rate bank central bank",
    "dolar": "dollar currency exchange money",
    "doviz": "currency exchange forex trading",
    "altin": "gold bullion investment precious metal",
    "ekonomi": "economy business financial news",
    "merkez bankasi": "central bank finance economy",
    # Gayrimenkul
    "gayrimenkul": "real estate luxury property modern",
    "konut": "house modern home real estate",
    "kira": "apartment rental property urban",
    # Kariyer
    "kariyer": "career professional success business",
    "is hayati": "business professional office meeting",
    "girisim": "startup entrepreneur innovation office",
    "liderlik": "leadership business team meeting",
    # Genel Finans
    "finans": "finance business money professional",
    "teknoloji": "technology innovation digital future",
    "yapay zeka": "artificial intelligence technology robot",
    "egitim": "education learning university student",
    "psikoloji": "psychology mind mental health",
    "saglik": "health wellness medical fitness",
}


class ImageFetcher:
    def __init__(self, channel_cfg=None):
        from .config import config as _cfg
        cfg = channel_cfg if channel_cfg else _cfg
        self.api_key = os.getenv("PEXELS_API_KEY", "") if not channel_cfg else getattr(cfg, "pexels_api_key", os.getenv("PEXELS_API_KEY", ""))
        self.has_api = bool(self.api_key) and not self.api_key.startswith("your_")

    def fetch_video_clips(self, title: str, count: int = 6, output_dir: str = "", query_override: str = None) -> list:
        """Konuyla ilgili Pexels video klibi indir."""
        if not self.has_api:
            logger.warning("Pexels API anahtari yok! Statik arka plan kullanilacak.")
            return []

        query = query_override if query_override else self._extract_query(title)
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
        query = self._extract_query(title)
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
        query = self._extract_thumbnail_query(title)
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
