"""
YouTube Playlist Yoneticisi
Konuya gore otomatik playlist olusturur ve videolari ekler.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Anahtar kelime -> Playlist adı eşleşmesi
PLAYLIST_MAP = {
    ("yatirim", "portfoy", "borsa", "hisse", "fon"): "Yatirim Rehberi 2026",
    ("birikim", "tasarruf", "butce", "harcama"): "Birikim ve Tasarruf",
    ("kripto", "bitcoin", "ethereum", "blockchain"): "Kripto Para",
    ("gayrimenkul", "kira", "konut", "emlak"): "Gayrimenkul Yatirimi",
    ("girisim", "startup", "is", "serbest"): "Girisimcilik",
    ("vergi", "sgk", "sigorta", "emeklilik"): "Finans ve Hukuk",
    ("teknoloji", "yapay zeka", "ai", "yazilim"): "Teknoloji ve Gelecek",
    ("kariyer", "maas", "is hayati", "freelance"): "Kariyer ve Gelir",
}

PLAYLIST_CACHE_FILE = "youtube_playlists.json"


class PlaylistManager:
    def __init__(self, youtube_service):
        self.svc = youtube_service
        self._cache: dict[str, str] = self._load_cache()

    def get_or_create_playlist(self, title: str) -> str | None:
        """
        Video basligina gore uygun playlist'i bul veya olustur.
        Playlist ID dondurur. Esleme yoksa None.
        """
        playlist_name = self._match_playlist(title)
        if not playlist_name:
            logger.info("Uygun playlist bulunamadi, atlanıyor.")
            return None

        if playlist_name in self._cache:
            logger.info(f"Mevcut playlist kullaniliyor: '{playlist_name}'")
            return self._cache[playlist_name]

        playlist_id = self._create_playlist(playlist_name)
        self._cache[playlist_name] = playlist_id
        self._save_cache()
        logger.info(f"Yeni playlist olusturuldu: '{playlist_name}' ({playlist_id})")
        return playlist_id

    def add_video_to_playlist(self, video_id: str, playlist_id: str):
        """Videoyu playlist'e ekle."""
        try:
            self.svc.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            ).execute()
            logger.info(f"Video playlist'e eklendi: {video_id} -> {playlist_id}")
        except Exception as e:
            logger.warning(f"Playlist'e eklenemedi: {e}")

    def _match_playlist(self, title: str) -> str | None:
        title_lower = title.lower()
        for keywords, playlist_name in PLAYLIST_MAP.items():
            if any(kw in title_lower for kw in keywords):
                return playlist_name
        # Hicbir esleme yoksa genel playlist
        return "Genel Bilgi Rehberi 2026"

    def _create_playlist(self, name: str) -> str:
        response = self.svc.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": name,
                    "description": f"AI destekli otomatik olusturulmus playlist: {name}",
                    "defaultLanguage": "tr",
                },
                "status": {"privacyStatus": "public"},
            },
        ).execute()
        return response["id"]

    def _load_cache(self) -> dict:
        if Path(PLAYLIST_CACHE_FILE).exists():
            try:
                return json.loads(Path(PLAYLIST_CACHE_FILE).read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_cache(self):
        Path(PLAYLIST_CACHE_FILE).write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
