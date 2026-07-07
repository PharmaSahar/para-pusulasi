"""Girişim Okulu açıklamasını güncelle."""
from src.youtube_auth import get_authenticated_service
from src.channel_manager import get_channel

cfg = get_channel('girisim_okulu')
svc = get_authenticated_service(cfg)

desc = (
    "Girisim Okulu'na hos geldiniz! Turkiye'nin girisimcilik ve startup kanali.\n\n"
    "Her gun yeni icerik:\n"
    "Sifirdan startup kurma rehberi - adim adim\n"
    "Is fikri gelistirme ve validasyon teknikleri\n"
    "Melek yatirimci ve VC fonlarindan yatirim alma\n"
    "Girisimci basari hikayeleri ve dersler\n"
    "Lean Startup, MVP ve pivot stratejileri\n"
    "Ekip kurma, urun gelistirme, buyume taktikleri\n\n"
    "Girisimci misin? Kendi isini kurmak mi istiyorsun?\n"
    "Dogru yerdesin. Her hafta gercek girisimcilerden ogren!\n\n"
    "Bildirimleri acarak yeni videolari kacirmayin!\n\n"
    "#GirisimOkulu #Startup #Girisimcilik #IsKur #Yatirim #Entrepreneur #MVP"
)

ch_id = 'UCvfuE893JTeSJx72j3eq3hQ'  # Girişim Okulu gerçek ID
print('Kanal ID:', ch_id)

result = svc.channels().update(
    part='brandingSettings',
    body={
        'id': ch_id,
        'brandingSettings': {
            'channel': {
                'description': desc,
                'keywords': '"girisimcilik" "startup" "is fikri" "yatirim" "entrepreneur" "girisim"',
                'country': 'TR',
            }
        }
    }
).execute()
saved = result['brandingSettings']['channel'].get('description', '')
print('Kaydedildi, ilk 100 karakter:', saved[:100])
