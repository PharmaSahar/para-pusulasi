"""Girişim Okulu banner ve açıklama yükle."""
import pickle
from pathlib import Path
from google.auth.transport.requests import AuthorizedSession
from src.youtube_auth import get_authenticated_service
from src.channel_manager import get_channel

cfg = get_channel('girisim_okulu')
svc = get_authenticated_service(cfg)

ch = svc.channels().list(part='id', mine=True).execute()
ch_id = ch['items'][0]['id']
print('Kanal ID:', ch_id)

with open(cfg.token_path, 'rb') as f:
    creds = pickle.load(f)

session = AuthorizedSession(creds)

# Banner yükle
banner_path = Path('channels/girisim_okulu/branding/youtube_banner_2560x1440.png')

with open(banner_path, 'rb') as f:
    banner_data = f.read()

r = session.post(
    'https://www.googleapis.com/upload/youtube/v3/channelBanners/insert?uploadType=media',
    headers={'Content-Type': 'image/png'},
    data=banner_data
)
print('Banner upload status:', r.status_code)

if r.status_code == 200:
    banner_url = r.json().get('url', '')
    svc.channels().update(
        part='brandingSettings',
        body={
            'id': ch_id,
            'brandingSettings': {
                'channel': {
                    'description': 'Girişimcilik ve startup dünyasına rehberiniz! Her gün yeni içerik:\n✅ Startup kurma rehberi\n✅ İş fikri geliştirme\n✅ Girişimci hikayeleri\n✅ Yatırım alma taktikleri\n\n#GirişimOkulu #Startup #Girişimcilik',
                    'keywords': '"girişimcilik" "startup" "iş fikri" "yatırım" "entrepreneur"',
                    'country': 'TR',
                },
                'image': {'bannerExternalUrl': banner_url}
            }
        }
    ).execute()
    print('✅ Banner ve açıklama güncellendi!')
else:
    print('Hata:', r.text[:300])
