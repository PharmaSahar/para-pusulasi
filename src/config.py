"""
Yapılandırma Yöneticisi
Ortam değişkenlerini yükler ve doğrular.
"""
import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # API Anahtarları
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    youtube_client_id: str = field(default_factory=lambda: os.getenv("YOUTUBE_CLIENT_ID", ""))
    youtube_client_secret: str = field(default_factory=lambda: os.getenv("YOUTUBE_CLIENT_SECRET", ""))
    youtube_redirect_uri: str = field(default_factory=lambda: os.getenv("YOUTUBE_REDIRECT_URI", "http://localhost:8080/callback"))
    youtube_analytics_token_path: str = field(default_factory=lambda: os.getenv("YOUTUBE_ANALYTICS_TOKEN_PATH", "youtube_analytics_token.pickle"))
    elevenlabs_api_key: str = field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY", ""))
    elevenlabs_voice_id: str = field(default_factory=lambda: os.getenv("ELEVENLABS_VOICE_ID", ""))

    # Kanal Ayarları
    # Channel-neutral default for startup paths where CHANNEL_NICHE is not set.
    channel_niche: str = field(default_factory=lambda: os.getenv("CHANNEL_NICHE", "general"))
    channel_language: str = field(default_factory=lambda: os.getenv("CHANNEL_LANGUAGE", "tr"))
    default_category_id: str = field(default_factory=lambda: os.getenv("DEFAULT_CATEGORY_ID", "22"))

    # Video Ayarları
    video_resolution: str = field(default_factory=lambda: os.getenv("VIDEO_RESOLUTION", "1920x1080"))
    videos_per_week: int = field(default_factory=lambda: int(os.getenv("VIDEOS_PER_WEEK", "3")))
    upload_time: str = field(default_factory=lambda: os.getenv("UPLOAD_TIME", "10:00"))

    # Zamanlayıcı
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Europe/Istanbul"))
    schedule_enabled: bool = field(default_factory=lambda: os.getenv("SCHEDULE_ENABLED", "true").lower() == "true")

    # Klasörler
    output_dir: str = "output"
    scripts_dir: str = "output/scripts"
    audio_dir: str = "output/audio"
    videos_dir: str = "output/videos"
    assets_dir: str = "assets"
    logs_dir: str = "logs"

    def validate(self) -> List[str]:
        """Eksik API anahtarlarını döndür."""
        missing = []
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if not self.youtube_client_id:
            missing.append("YOUTUBE_CLIENT_ID")
        if not self.youtube_client_secret:
            missing.append("YOUTUBE_CLIENT_SECRET")
        return missing

    def ensure_directories(self):
        """Gerekli klasörleri oluştur."""
        dirs = [
            self.output_dir, self.scripts_dir, self.audio_dir,
            self.videos_dir, self.assets_dir, self.logs_dir,
            "assets/backgrounds", "assets/music", "assets/fonts",
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)

    @property
    def video_width(self) -> int:
        return int(self.video_resolution.split("x")[0])

    @property
    def video_height(self) -> int:
        return int(self.video_resolution.split("x")[1])

    @property
    def upload_days(self) -> List[str]:
        days = os.getenv("UPLOAD_DAYS", "Monday,Wednesday,Friday")
        return [d.strip() for d in days.split(",")]

    @property
    def niche(self) -> str:
        """Backward-compatible alias expected by legacy pipeline paths."""
        return self.channel_niche

    @niche.setter
    def niche(self, value: str) -> None:
        self.channel_niche = value


# Tek örnek (singleton)
config = Config()
