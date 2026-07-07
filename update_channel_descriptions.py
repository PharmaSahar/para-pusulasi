"""Yeni kanalların açıklamalarını doldur ve VPS'e sync et."""
from src.youtube_auth import get_authenticated_service
from src.channel_manager import get_channel
import json
from pathlib import Path

CHANNEL_INFO = {
    'girisim_okulu': {
        'desc': (
            'Girişimcilik ve startup dünyasına rehberiniz!\n\n'
            'Her gün yeni içerik:\n'
            'Startup kurma rehberi\n'
            'Is fikri gelistirme\n'
            'Yatirim alma taktikleri\n'
            'Girisimci hikayeleri\n\n'
            'Bildirimleri acin!\n\n'
            '#GirisimOkulu #Startup #Girisimcilik'
        ),
        'keywords': '"girisimcilik" "startup" "is fikri" "yatirim" "entrepreneur"',
    },
    'saglik_pusulasi': {
        'desc': (
            'Saglikli yasamin pusulasi!\n\n'
            'Her gun yeni icerik:\n'
            'Saglikli beslenme rehberi\n'
            'Egzersiz ve fitness\n'
            'Zihinsel saglik\n'
            'Hastalik onleme tuyolari\n\n'
            'Bildirimleri acin!\n\n'
            '#SaglikPusulasi #Saglik #Wellness #Fitness'
        ),
        'keywords': '"saglik" "wellness" "beslenme" "egzersiz" "fitness" "yasam"',
    },
}

for channel_id, info in CHANNEL_INFO.items():
    try:
        cfg = get_channel(channel_id)
        svc = get_authenticated_service(cfg)
        ch_id = svc.channels().list(part='id', mine=True).execute()['items'][0]['id']
        svc.channels().update(
            part='brandingSettings',
            body={
                'id': ch_id,
                'brandingSettings': {
                    'channel': {
                        'description': info['desc'],
                        'keywords': info['keywords'],
                        'country': 'TR',
                    }
                }
            }
        ).execute()
        print(f'[OK] {channel_id}: aciklama guncellendi')
    except Exception as e:
        print(f'[HATA] {channel_id}: {e}')

print('Tamamlandi.')
