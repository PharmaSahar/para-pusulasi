"""
Kanal Yoneticisi - Cok Kanalli Sistem
Her kanalin konfigürasyonunu, token yolunu ve ayarlarini yonetir.
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REGISTRY_PATH = "channels/channel_registry.json"
CHANNELS_DIR = "channels"
ANALYTICS_TOKEN_POLICY_ENV = "ANALYTICS_TOKEN_POLICY"
MARKET_LANGUAGE_NICHES = frozenset({"kisisel_finans", "borsa", "kripto", "gayrimenkul"})


def _normalize_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def resolve_allow_market_language(*, niche: str | None, explicit_value: object = None) -> bool:
    """Resolve channel market-language policy with deterministic niche fallback."""
    explicit = _normalize_bool(explicit_value)
    if explicit is not None:
        return explicit
    normalized_niche = str(niche or "").strip().lower()
    return normalized_niche in MARKET_LANGUAGE_NICHES


@dataclass
class ChannelConfig:
    channel_id: str
    name: str
    niche: str
    language: str
    upload_times: list[str]
    color_primary: list[int]
    color_bg: list[int]
    youtube_channel_id: str = ""

    # Opsiyonel alanlar (yeni kanallar için default)
    slogan: str = ""
    category_id: str = "27"
    pexels_query: str = "business office planning"
    persona: str = ""
    topics: list = field(default_factory=list)
    tone: str = ""
    audience: str = ""
    voice_archetype: str = ""
    evidence_style: str = ""
    forbidden_patterns: list = field(default_factory=list)
    signature_structure: list = field(default_factory=list)
    channel_dna_version: str = "v1"
    allow_market_language: bool = False

    # API anahtarlari (channels/{id}/.env'den yuklenir)
    anthropic_api_key: str = ""
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_analytics_token_path: str = ""
    pexels_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""  # Her kanala özel ses — boşsa global .env'den alınır
    elevenlabs_enabled: bool = False  # True = ElevenLabs, False = Edge TTS (ücretsiz)

    # Klasorler
    base_dir: str = ""
    output_dir: str = ""
    scripts_dir: str = ""
    audio_dir: str = ""
    videos_dir: str = ""
    token_path: str = ""
    client_secrets_path: str = ""

    def __post_init__(self):
        self.base_dir = f"{CHANNELS_DIR}/{self.channel_id}"
        self.output_dir = f"{self.base_dir}/output"
        self.scripts_dir = f"{self.base_dir}/output/scripts"
        self.audio_dir = f"{self.base_dir}/output/audio"
        self.videos_dir = f"{self.base_dir}/output/videos"
        self.token_path = f"{self.base_dir}/youtube_token.pickle"
        self.client_secrets_path = f"{self.base_dir}/client_secrets.json"

        # .env dosyasindan API anahtarlarini yukle
        env_path = f"{self.base_dir}/.env"
        if Path(env_path).exists():
            self._load_env(env_path)
        else:
            # Ana .env'den yukle (ilk kanal icin)
            self._load_env(".env")

        # Analytics token topolojisini tek policy ile belirle.
        if not str(self.youtube_analytics_token_path or "").strip():
            policy = str(os.getenv(ANALYTICS_TOKEN_POLICY_ENV, "channel_local") or "").strip().lower()
            if policy == "shared":
                self.youtube_analytics_token_path = "youtube_analytics_token.pickle"
            else:
                self.youtube_analytics_token_path = f"{self.base_dir}/youtube_analytics_token.pickle"

    def _load_env(self, path: str):
        from dotenv import dotenv_values
        env = dotenv_values(path)
        self.anthropic_api_key = env.get("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
        self.youtube_client_id = env.get("YOUTUBE_CLIENT_ID", os.getenv("YOUTUBE_CLIENT_ID", ""))
        self.youtube_client_secret = env.get("YOUTUBE_CLIENT_SECRET", os.getenv("YOUTUBE_CLIENT_SECRET", ""))
        self.youtube_analytics_token_path = env.get("YOUTUBE_ANALYTICS_TOKEN_PATH", os.getenv("YOUTUBE_ANALYTICS_TOKEN_PATH", ""))
        self.pexels_api_key = env.get("PEXELS_API_KEY", os.getenv("PEXELS_API_KEY", ""))
        self.elevenlabs_api_key = env.get("ELEVENLABS_API_KEY", os.getenv("ELEVENLABS_API_KEY", ""))
        self.elevenlabs_voice_id = env.get("ELEVENLABS_VOICE_ID", os.getenv("ELEVENLABS_VOICE_ID", ""))

    def ensure_directories(self):
        for d in [self.output_dir, self.scripts_dir, self.audio_dir, self.videos_dir,
                  f"{self.base_dir}/branding"]:
            Path(d).mkdir(parents=True, exist_ok=True)

    @property
    def video_width(self) -> int:
        return 1920

    @property
    def video_height(self) -> int:
        return 1080

    @property
    def default_category_id(self) -> str:
        return self.category_id

    @property
    def channel_language(self) -> str:
        return self.language


def load_registry() -> dict[str, Any]:
    """Channel registry JSON'unu yukle."""
    path = Path(REGISTRY_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Registry bulunamadi: {REGISTRY_PATH}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_channel(channel_id: str) -> ChannelConfig:
    """Belirli bir kanalin konfigurasyonunu dondur."""
    registry = load_registry()
    channels = registry.get("channels", {})
    if channel_id not in channels:
        available = list(channels.keys())
        raise ValueError(f"Kanal bulunamadi: '{channel_id}'. Mevcut: {available}")
    data = dict(channels[channel_id])  # kopya al
    data.pop("channel_id", None)  # cift gelmesin
    data["allow_market_language"] = resolve_allow_market_language(
        niche=data.get("niche"),
        explicit_value=data.get("allow_market_language"),
    )
    # ChannelConfig'in kabul etmediği extra alanları temizle
    import dataclasses
    known = {f.name for f in dataclasses.fields(ChannelConfig)}
    data = {k: v for k, v in data.items() if k in known}
    return ChannelConfig(channel_id=channel_id, **data)


def list_channels() -> list[str]:
    """Tum kanal ID'lerini listele."""
    registry = load_registry()
    return list(registry.get("channels", {}).keys())


def get_all_channels() -> list[ChannelConfig]:
    """Tum kanallarin konfigurasyonlarini dondur."""
    return [get_channel(cid) for cid in list_channels()]
