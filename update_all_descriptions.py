"""Tüm yeni kanalların açıklamalarını doldur."""
from src.youtube_auth import get_authenticated_service
from src.channel_manager import get_channel

CHANNELS = {
    'girisim_okulu': {
        'desc': (
            "Girişim Okulu'na hoş geldiniz! Türkiye'nin girişimcilik ve startup kanalı. 🚀\n\n"
            "Her gün yeni içerik:\n"
            "✅ Sıfırdan startup kurma rehberi — adım adım\n"
            "✅ İş fikri geliştirme ve validasyon teknikleri\n"
            "✅ Melek yatırımcı ve VC fonlarından yatırım alma\n"
            "✅ Girişimci başarı hikayeleri ve dersler\n"
            "✅ Şirket kuruluşu, tescil ve hukuki süreçler\n"
            "✅ Lean Startup, MVP ve pivot stratejileri\n"
            "✅ Ekip kurma, ürün geliştirme, büyüme taktikleri\n\n"
            "Girişimci misin? Kendi işini kurmak mı istiyorsun? \n"
            "Doğru yerdesin. Her hafta gerçek girişimcilerden öğren!\n\n"
            "🔔 Bildirimleri açarak yeni videoları kaçırmayın!\n\n"
            "📌 Popüler oynatma listelerimiz:\n"
            "▶ Startup Nasıl Kurulur? (Başlangıç Serisi)\n"
            "▶ Yatırımcı Sunum Rehberi\n"
            "▶ Türkiye'de Girişimcilik Ekosistemi\n\n"
            "#GirişimOkulu #Startup #Girişimcilik #İşKur #Yatırım #Entrepreneur #MVP #AngelInvestor"
        ),
        'keywords': '"girisimcilik" "startup" "is fikri" "yatirim" "entrepreneur" "girisim" "kendi isini kur" "sirket kurma" "angel investor" "vc fon"',
    },
    'saglik_pusulasi': {
        'desc': (
            "Sağlık Pusulası — Sağlıklı yaşamın rehberi! 💚\n\n"
            "Her gün yeni içerik:\n"
            "✅ Sağlıklı beslenme rehberi — günlük pratik tavsiyeler\n"
            "✅ Evde yapılabilen egzersiz ve fitness programları\n"
            "✅ Zihinsel sağlık, stres yönetimi ve meditasyon\n"
            "✅ Hastalık önleme — doğal yöntemler ve uzman tavsiyeleri\n"
            "✅ Vitamin, mineral ve takviye rehberi\n"
            "✅ Uyku kalitesini artırma teknikleri\n"
            "✅ Kilo verme ve sağlıklı yaşam programları\n\n"
            "Sağlıklı yaşamak için doktor tavsiyesi kadar doğru kanal!\n"
            "Uzmanlardan öğren, hayatını değiştir.\n\n"
            "🔔 Bildirimleri açarak günlük sağlık ipuçlarını kaçırmayın!\n\n"
            "📌 Popüler oynatma listelerimiz:\n"
            "▶ 30 Günde Sağlıklı Beslenme\n"
            "▶ Evde Egzersiz Programları\n"
            "▶ Zihinsel Sağlık Rehberi\n\n"
            "#SağlıkPusulası #Sağlık #Wellness #Fitness #Beslenme #Egzersiz #Meditasyon #Diyet"
        ),
        'keywords': '"saglik" "wellness" "beslenme" "egzersiz" "fitness" "yasam" "diyet" "vitamin" "stres" "meditasyon" "kilo verme"',
    },
    'teknoloji_pusulasi': {
        'desc': (
            "Teknoloji Pusulası — Dijital dünyanın rehberi! 💻\n\n"
            "Her gün yeni içerik:\n"
            "✅ Yapay Zeka haberleri ve uygulamaları — ChatGPT, Gemini, Claude\n"
            "✅ Yazılım geliştirme rehberleri — Python, JavaScript, Web\n"
            "✅ Türkiye ve dünyadan teknoloji haberleri\n"
            "✅ Dijital dönüşüm — iş dünyası için AI araçları\n"
            "✅ Siber güvenlik ve kişisel veri koruma\n"
            "✅ Kripto ve blockchain teknolojileri\n"
            "✅ Yeni gadget ve ürün incelemeleri\n\n"
            "Teknoloji dünyasında kaybolmak istemiyorsanız doğru yerdesiniz!\n"
            "Her gün 5 dakikada teknoloji haberleri.\n\n"
            "🔔 Bildirimleri açarak yeni videoları kaçırmayın!\n\n"
            "📌 Popüler oynatma listelerimiz:\n"
            "▶ Yapay Zeka Başlangıç Rehberi\n"
            "▶ Python ile Kodlama\n"
            "▶ 2026 Teknoloji Trendleri\n\n"
            "#TeknolojiPusulası #Teknoloji #YapayZeka #AI #Yazılım #ChatGPT #Dijital #Kodlama"
        ),
        'keywords': '"teknoloji" "yapay zeka" "AI" "yazilim" "dijital" "inovasyon" "ChatGPT" "python" "siber guvenlik" "blockchain"',
    },
    'egitim_rehberi': {
        'desc': (
            "Eğitim Rehberi — Öğrenmek hiç bu kadar kolay olmamıştı! 📚\n\n"
            "Her gün yeni içerik:\n"
            "✅ Online eğitim tavsiyeleri — Udemy, Coursera, LinkedIn Learning\n"
            "✅ Kişisel gelişim ve öz disiplin teknikleri\n"
            "✅ Yabancı dil öğrenme yöntemleri — İngilizce, Almanca, İspanyolca\n"
            "✅ Sertifika programları rehberi — hangi sertifika kaç para kazandırır\n"
            "✅ Hafıza teknikleri ve verimli çalışma yöntemleri\n"
            "✅ Üniversite ve yüksek lisans başvuru rehberi\n"
            "✅ Çocuk eğitimi ve erken öğrenme teknikleri\n\n"
            "Kendinizi geliştirmek için en iyi yatırım eğitimdir!\n"
            "Her hafta yeni öğrenme fırsatları.\n\n"
            "🔔 Bildirimleri açarak eğitim fırsatlarını kaçırmayın!\n\n"
            "📌 Popüler oynatma listelerimiz:\n"
            "▶ Ücretsiz Online Eğitim Kaynakları\n"
            "▶ İngilizce Öğrenme Programı\n"
            "▶ Kariyer Değiştirme Rehberi\n\n"
            "#EğitimRehberi #Eğitim #OnlineEğitim #KişiselGelişim #İngilizce #Sertifika #Udemy"
        ),
        'keywords': '"egitim" "online egitim" "kisisel gelisim" "dil ogrenme" "kariyer" "sertifika" "udemy" "hafiza" "ingilizce" "yuksek lisans"',
    },
    'gayrimenkul_tv': {
        'desc': (
            "Gayrimenkul TV — Türkiye'nin gayrimenkul yatırım rehberi! 🏠\n\n"
            "Her gün yeni içerik:\n"
            "✅ Ev alma satma rehberi — doğru fiyat, doğru karar\n"
            "✅ Kira geliri ile pasif gelir oluşturma\n"
            "✅ Gayrimenkul değerleme — hangi ilçe değer kazanır?\n"
            "✅ İstanbul, Ankara, İzmir piyasa analizleri\n"
            "✅ Konut kredisi ve mortgage hesaplama\n"
            "✅ Yeni proje ve site incelemeleri\n"
            "✅ Arsa ve ticari gayrimenkul yatırımı\n"
            "✅ REIT (GYO) yatırımları — borsada gayrimenkul\n\n"
            "Ev almadan önce bu kanalı izleyin!\n"
            "Her ay milyonlarca kişi gayrimenkul yatırımı yapıyor — siz de hazır mısınız?\n\n"
            "🔔 Bildirimleri açarak piyasa analizlerini kaçırmayın!\n\n"
            "📌 Popüler oynatma listelerimiz:\n"
            "▶ İlk Evimi Alıyorum Rehberi\n"
            "▶ Kira Geliri ile Pasif Gelir\n"
            "▶ İstanbul'da Değer Kazanacak Bölgeler 2026\n\n"
            "#GayrimenkulTV #Gayrimenkul #Emlak #KonutYatırımı #Kira #EvAlmak #Mortgage #GYO"
        ),
        'keywords': '"gayrimenkul" "emlak" "konut" "kira" "ev alma" "yatirim" "daire" "arsa" "istanbul" "mortgage" "konut kredisi" "GYO"',
    },
}

success = 0
for channel_id, info in CHANNELS.items():
    try:
        cfg = get_channel(channel_id)
        from pathlib import Path
        if not Path(cfg.token_path).exists():
            print(f'[SKIP] {channel_id}: token yok')
            continue
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
        print(f'[OK] {channel_id}')
        success += 1
    except Exception as e:
        print(f'[HATA] {channel_id}: {e}')

print(f'\nToplam: {success} kanal guncellendi')
