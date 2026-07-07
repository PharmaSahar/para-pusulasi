"""Kanal Description'larini gunceller."""
import os, sys, pickle
sys.path.insert(0, ".")
from google.auth.transport.requests import AuthorizedSession, Request

DESCRIPTIONS = {
    "para_pusulasi": {
        "id": "UC6tU7UqYylfSA75pj3rEY_Q",
        "token": "channels/para_pusulasi/youtube_token.pickle",
        "description": """Turkiye'nin en pratik kisisel finans kanali: Para Pusulasi

Her gun 2 yeni video ile:
✅ Birikim ve yatirim rehberleri
✅ Guncel ekonomi analizleri (BIST, doviz, faiz)
✅ Butce yonetimi ve tasarruf stratejileri
✅ Herkesin anlayabilecegi finans egitimi
✅ Gercek rakamlar, gercek hesaplamalar

Abone olun, para konusunda bir adim onde olun!
Her gun 08:00 ve 20:00'da yeni video

#KisiselFinans #Borsa #Yatirim #ParaPusulasi #FinansEgitimi #BIST #Tasarruf #Birikim""",
    },
    "borsa_akademi": {
        "id": "UCwQERXHCUOngXXTnJ9goBSQ",
        "token": "channels/borsa_akademi/youtube_token.pickle",
        "description": """Turkiye borsasi BIST'e odaklanmis en kapsamli analiz kanali: Borsa Akademi

Her gun 2 yeni video ile:
📊 BIST 100 hisse analizi ve yorumlari
💰 Temettü hisseleri ve pasif gelir stratejileri
🔍 Teknik ve temel analiz egitimleri
📉 Risk yonetimi ve portfoy cesitlendirme
⚡ Guncel piyasa haberleri

Abone olun, hicbir analizi kacirmayin!
Her gun 08:30 ve 20:30'da yeni video

⚠️ Bu kanal yatirim tavsiyesi vermez. Egitim amaclidir.
#Borsa #BIST #Hisse #Temettü #TeknikAnaliz #BorsaAkademi #BIST100""",
    },
    "kripto_rehber": {
        "id": "UCyFK7LdIPM01fAf3f0W2x9Q",
        "token": "channels/kripto_rehber/youtube_token.pickle",
        "description": """Kriptoda Kaybolma! Turkiye'nin en guncel kripto para analiz kanali: Kripto Rehber

Her gun 2 yeni video ile:
₿ Bitcoin, Ethereum ve altcoin analizleri
📊 Guncel fiyat hareketleri ve teknik analiz
🔍 DeFi, NFT, Web3 gelismeleri
⚠️ Risk yonetimi ve yatirim stratejileri
📰 Kripto dunyanin son haberleri

Abone olun, bildirimleri acin!
Her gun 09:00 ve 21:00'da yeni video

⚠️ Bu kanal yatirim tavsiyesi vermez. Egitim amaclidir.
#Kripto #Bitcoin #Ethereum #KriptoRehber #BTC #ETH #Blockchain #DeFi""",
    },
    "kariyer_pusulasi": {
        "id": "UC-LxyfIrfqWDfFCzJLVBwEg",
        "token": "channels/kariyer_pusulasi/youtube_token.pickle",
        "description": """Kariyerinde Bir Adim One Gec! Turkiye'nin en pratik kariyer kanali: Kariyer Pusulasi

Her gun 2 yeni video ile:
💼 Maas muzakeresi ve zam alma taktikleri
📈 Kariyer planlama ve terfi stratejileri
🏠 Remote calisma ve freelance firsatlari
💡 LinkedIn optimizasyonu ve is bulma
🚀 Girisimcilik ve yan gelir kaynaklari

Abone olun, kariyerinizde one gecin!
Her gun 09:30 ve 21:30'da yeni video

#Kariyer #IsHayati #Maas #Remote #Freelance #LinkedIn #KariyerPusulasi""",
    },
}


def update_description(channel_id, token_path, description, yt_channel_id):
    with open(token_path, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    session = AuthorizedSession(creds)

    # Mevcut kanal snippet'ini al
    ch_resp = session.get(
        "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"
    )
    ch_items = ch_resp.json().get("items", [])
    if not ch_items:
        print(f"  [{channel_id}] Kanal bulunamadi")
        return

    snippet = ch_items[0]["snippet"]
    snippet["description"] = description

    resp = session.put(
        "https://www.googleapis.com/youtube/v3/channels?part=snippet",
        json={
            "id": yt_channel_id,
            "snippet": {
                "title": snippet.get("title", ""),
                "description": description,
                "defaultLanguage": snippet.get("defaultLanguage", "tr"),
                "country": snippet.get("country", "TR"),
            },
        },
    )
    if resp.status_code == 200:
        print(f"  ✅ [{channel_id}] Description guncellendi")
    else:
        print(f"  [{channel_id}] Hata {resp.status_code}: {resp.text[:150]}")


if __name__ == "__main__":
    print("Kanal description'lari guncelleniyor...\n")
    for cid, cfg in DESCRIPTIONS.items():
        if os.path.exists(cfg["token"]):
            update_description(cid, cfg["token"], cfg["description"], cfg["id"])
        else:
            print(f"  [{cid}] Token yok, atlaniyor")
    print("\nTamamlandi!")
