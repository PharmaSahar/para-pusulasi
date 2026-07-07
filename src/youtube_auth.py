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

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube",
          "https://www.googleapis.com/auth/youtube.force-ssl"]
TOKEN_PATH = "youtube_token.pickle"
CLIENT_SECRETS_PATH = "client_secrets.json"


def get_authenticated_service(channel_cfg=None):
    """YouTube API servisi döndür. channel_cfg varsa o kanalin token'ini kullanir."""
    if channel_cfg and hasattr(channel_cfg, "token_path"):
        token_path = channel_cfg.token_path
        secrets_path = channel_cfg.client_secrets_path
    else:
        token_path = TOKEN_PATH
        secrets_path = CLIENT_SECRETS_PATH

    credentials = None

    if Path(token_path).exists():
        with open(token_path, "rb") as f:
            credentials = pickle.load(f)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not Path(secrets_path).exists():
                _create_client_secrets(secrets_path, channel_cfg)

            flow = InstalledAppFlow.from_client_secrets_file(secrets_path, SCOPES)
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

    return build("youtube", "v3", credentials=credentials, cache_discovery=False,
                  static_discovery=False)


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
