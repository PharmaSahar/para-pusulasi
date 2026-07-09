"""
YouTube OAuth 2.0 Kimlik Doğrulama
Credentials token'ı oluşturup kaydeder.
Tek seferlik çalıştırılır: python src/youtube_auth.py
"""
import os
import pickle
from pathlib import Path

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import google.auth.transport.requests
import requests as req_lib

from .config import config

UPLOAD_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
ANALYTICS_SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]
TOKEN_PATH = "youtube_token.pickle"
ANALYTICS_TOKEN_PATH = "youtube_analytics_token.pickle"
CLIENT_SECRETS_PATH = "client_secrets.json"


def get_authenticated_service(channel_cfg=None):
    """YouTube API servisi döndür. channel_cfg varsa o kanalin token'ini kullanir."""
    credentials = _get_credentials(
        scopes=UPLOAD_SCOPES,
        token_path=_resolve_token_path(channel_cfg, TOKEN_PATH, "token_path"),
        secrets_path=_resolve_secrets_path(channel_cfg),
        channel_cfg=channel_cfg,
    )
    return build("youtube", "v3", credentials=credentials, cache_discovery=False, static_discovery=False)


def get_authenticated_analytics_service(channel_cfg=None):
    """YouTube Analytics servisi döndür."""
    credentials = _get_credentials(
        scopes=ANALYTICS_SCOPES,
        token_path=_resolve_token_path(channel_cfg, ANALYTICS_TOKEN_PATH, "youtube_analytics_token_path"),
        secrets_path=_resolve_secrets_path(channel_cfg),
        channel_cfg=channel_cfg,
    )
    return build("youtubeAnalytics", "v2", credentials=credentials, cache_discovery=False, static_discovery=False)


def _resolve_token_path(channel_cfg, default_path: str, attr_name: str) -> str:
    if channel_cfg and hasattr(channel_cfg, attr_name):
        value = getattr(channel_cfg, attr_name)
        if value:
            return value
    return default_path


def _resolve_secrets_path(channel_cfg) -> str:
    if channel_cfg and hasattr(channel_cfg, "client_secrets_path"):
        return getattr(channel_cfg, "client_secrets_path")
    return CLIENT_SECRETS_PATH


def _get_credentials(*, scopes: list[str], token_path: str, secrets_path: str, channel_cfg=None):
    credentials = None

    if Path(token_path).exists():
        with open(token_path, "rb") as f:
            credentials = pickle.load(f)

    if credentials is not None:
        try:
            has_required_scopes = credentials.has_scopes(scopes)
        except Exception:
            has_required_scopes = False
        if not has_required_scopes:
            channel_name = channel_cfg.name if channel_cfg else "Ana Kanal"
            print(f"[{channel_name}] Token scope yetersiz, yeniden yetkilendirme gerekiyor: {token_path}")
            credentials = None

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not Path(secrets_path).exists():
                _create_client_secrets(secrets_path, channel_cfg)

            flow = InstalledAppFlow.from_client_secrets_file(secrets_path, scopes)
            channel_name = channel_cfg.name if channel_cfg else "Ana Kanal"
            print(f"\n[{channel_name}] Tarayici aciliyor...")
            print(f"[{channel_name}] Acilmazsa asagidaki URL'yi kopyalayin ve tarayicida acin.\n")
            credentials = flow.run_local_server(
                port=8080,
                open_browser=True,
                authorization_prompt_message=f"[{channel_name}] Tarayicida acin: {{url}}",
                success_message="Izin verildi! Bu sekmeyi kapatabilirsiniz.",
            )

        with open(token_path, "wb") as f:
            pickle.dump(credentials, f)

    return credentials


def _create_client_secrets(path: str, channel_cfg=None):
    """client_secrets.json olustur."""
    import json
    from .config import config
    client_id = channel_cfg.youtube_client_id if channel_cfg else config.youtube_client_id
    client_secret = channel_cfg.youtube_client_secret if channel_cfg else config.youtube_client_secret
    secrets = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(secrets, indent=2))


if __name__ == "__main__":
    print("YouTube kimlik doğrulama başlatılıyor...")
    service = get_authenticated_service()
    print("✅ Başarıyla kimlik doğrulandı! Token kaydedildi.")
