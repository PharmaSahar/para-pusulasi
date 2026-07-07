"""
Kanal Branding API Yukleyici
Requests transport kullanarak banner ve thumbnail yukler.
Kullanim:
  python upload_branding.py                  # Tum kanallar
  python upload_branding.py para_pusulasi    # Tek kanal
"""
import os, sys, pickle
sys.path.insert(0, ".")
import requests as req_lib
from google.auth.transport.requests import AuthorizedSession, Request

CHANNEL_IDS = {
    "para_pusulasi":   "UC6tU7UqYylfSA75pj3rEY_Q",
    "borsa_akademi":   "UCwQERXHCUOngXXTnJ9goBSQ",
    "kripto_rehber":   "UCyFK7LdIPM01fAf3f0W2x9Q",
    "kariyer_pusulasi": "UC-LxyfIrfqWDfFCzJLVBwEg",
}


def get_session(token_path):
    with open(token_path, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return AuthorizedSession(creds)


def upload_banner(session, channel_id, banner_path):
    """Channel banner yukle ve kanala ata."""
    # 1. Banner'i yukle
    with open(banner_path, "rb") as f:
        data = f.read()
    resp = session.post(
        "https://www.googleapis.com/upload/youtube/v3/channelBanners/insert?uploadType=media",
        data=data,
        headers={"Content-Type": "image/png"},
    )
    if resp.status_code not in (200, 201):
        print(f"  Banner yuklenemedi: {resp.status_code} - {resp.text[:200]}")
        return False

    banner_url = resp.json().get("url", "")

    # 2. Mevcut kanal branding bilgilerini al
    ch_resp = session.get(
        "https://www.googleapis.com/youtube/v3/channels?part=brandingSettings,snippet&mine=true"
    )
    ch_items = ch_resp.json().get("items", [])
    if not ch_items:
        print("  Kanal bilgisi alinamadi")
        return False
    ch = ch_items[0]
    channel_branding = ch.get("brandingSettings", {}).get("channel", {})
    channel_branding["title"] = ch["snippet"]["title"]

    # 3. Banner'i kanala ata
    update_resp = session.put(
        "https://www.googleapis.com/youtube/v3/channels?part=brandingSettings",
        json={
            "id": channel_id,
            "brandingSettings": {
                "channel": channel_branding,
                "image": {"bannerExternalUrl": banner_url},
            },
        },
    )
    if update_resp.status_code in (200, 201):
        print(f"  ✅ Banner yuklendi: {ch['snippet']['title']}")
        return True
    else:
        print(f"  Banner atama basarisiz: {update_resp.status_code} - {update_resp.text[:150]}")
        return False


def upload_channel_branding(channel_id):
    token_path = f"channels/{channel_id}/youtube_token.pickle"
    if not os.path.exists(token_path):
        print(f"[{channel_id}] Token bulunamadi, atlaniyor.")
        return

    channel_uid = CHANNEL_IDS.get(channel_id)
    if not channel_uid:
        print(f"[{channel_id}] Channel ID bilinmiyor, atlaniyor.")
        return

    branding_dir = f"channels/{channel_id}/branding"
    banner_path = f"{branding_dir}/youtube_banner_2560x1440.png"

    if not os.path.exists(banner_path):
        print(f"[{channel_id}] Banner dosyasi yok: {banner_path}")
        return

    print(f"\n[{channel_id}] Banner yukleniyor...")
    session = get_session(token_path)
    upload_banner(session, channel_uid, banner_path)


if __name__ == "__main__":
    from src.channel_manager import list_channels

    if len(sys.argv) > 1:
        channels = sys.argv[1:]
    else:
        channels = [c for c in list_channels() if c in CHANNEL_IDS]

    print(f"{len(channels)} kanal icin banner yuklenecek...")
    for cid in channels:
        upload_channel_branding(cid)

    print("\nTamamlandi!")
