"""
Twitter/X Otomatik Tweet Modülü
Her YouTube videosu yüklendiğinde otomatik tweet atar.
tweepy kütüphanesi kullanır (pip install tweepy).
"""
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_client():
    """Tweepy v2 Client oluştur."""
    try:
        import tweepy
    except ImportError:
        raise ImportError("tweepy kurulu değil. Kur: pip install tweepy")

    api_key     = os.getenv("TWITTER_API_KEY", "")
    api_secret  = os.getenv("TWITTER_API_SECRET", "")
    acc_token   = os.getenv("TWITTER_ACCESS_TOKEN", "")
    acc_secret  = os.getenv("TWITTER_ACCESS_SECRET", "")

    if not all([api_key, api_secret, acc_token, acc_secret]):
        raise ValueError("Twitter API key'leri .env'de eksik!")

    return tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=acc_token,
        access_token_secret=acc_secret,
    )


def generate_tweet(title: str, youtube_url: str, channel_name: str,
                   script: str = "", short_url: str = "") -> str:
    """
    Video başlığından ve scriptinden AI ile tweet metni üret.
    Claude API yoksa basit format kullanır.
    """
    # Script'ten en çarpıcı cümleyi bul
    hook = ""
    if script:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', script.strip()) if s.strip()]
        # İstatistik veya soru içeren ilk cümleyi seç
        for s in sentences[:5]:
            if re.search(r'\d+[%₺$]|\?|!', s) and len(s) < 120:
                hook = s
                break
        if not hook and sentences:
            hook = sentences[0][:100]

    # Hashtag'leri başlıktan çıkar
    keywords = re.findall(r'\b(borsa|kripto|bitcoin|dolar|finans|yatırım|emeklilik|maaş|BES|BIST)\b',
                          title, re.IGNORECASE)
    hashtags = " ".join(f"#{kw.capitalize()}" for kw in list(dict.fromkeys(keywords))[:3])
    if not hashtags:
        hashtags = "#Finans #Yatırım"

    # Tweet formatı (280 karakter max)
    if hook:
        tweet = f"{hook}\n\n🎬 {title[:60]}{'...' if len(title) > 60 else ''}\n\n{youtube_url}\n\n{hashtags} #ParaPusulasi"
    else:
        tweet = f"🎬 Yeni video: {title[:80]}{'...' if len(title) > 80 else ''}\n\n{youtube_url}\n\n{hashtags} #ParaPusulasi"

    if short_url:
        tweet += f"\n📱 Short: {short_url}"

    return tweet[:280]


def post_tweet(title: str, youtube_url: str, channel_name: str,
               script: str = "", short_url: str = "") -> str | None:
    """
    Tweet at. Başarılıysa tweet URL'sini döndür, hata olursa None.
    TWITTER_API_KEY .env'de yoksa sessizce atla.
    """
    if not os.getenv("TWITTER_API_KEY"):
        logger.debug("Twitter API key yok, tweet atlanıyor.")
        return None

    try:
        client = _get_client()
        tweet_text = generate_tweet(title, youtube_url, channel_name, script, short_url)
        response = client.create_tweet(text=tweet_text)
        tweet_id = response.data["id"]
        tweet_url = f"https://x.com/mehresahar/status/{tweet_id}"
        logger.info(f"Tweet atıldı: {tweet_url}")
        return tweet_url
    except Exception as e:
        logger.warning(f"Tweet gönderilemedi: {e}")
        return None
