"""
Topluluk Gonderi Otomasyonu
Video yukledikten sonra YouTube Community tab'ına anket/gonderi atar.
"""
import logging
from google.auth.transport.requests import AuthorizedSession, Request
import pickle

logger = logging.getLogger(__name__)


def post_community_poll(session: AuthorizedSession, channel_id: str, video_title: str, video_url: str):
    """Video hakkinda anket/gonderi paylas."""
    # YouTube Community posts API henüz public değil, ama post yapabiliriz
    # Alternatif: ilk yorumu sabitleyip, community post benzeri bir yorum yaz
    pass  # YouTube Community API hala beta/kısıtlı


def post_video_announcement(
    channel_cfg,
    video_id: str,
    title: str,
    next_topic: str = "",
) -> bool:
    """
    Video yüklendikten sonra gelişmiş sabitlenmiş yorum ekle.
    Algorithmanın engagement olarak sayması için CTA içerir.
    """
    token_path = getattr(channel_cfg, "token_path", "youtube_token.pickle")
    try:
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        session = AuthorizedSession(creds)

        channel_name = getattr(channel_cfg, "name", "Para Pusulasi")

        comment_lines = [
            f"📌 Bu videoda ne ogrendim? Asagiya yorumunuzu yazin!",
            f"",
            f"💬 Soru? Direkt buraya yazin — cevapliyorum!",
            f"🔔 Bildirimleri acin, her gun yeni video!",
        ]
        if next_topic:
            comment_lines += [
                f"",
                f"👉 SIRADAKI VIDEO: '{next_topic[:50]}' — yakinda!",
            ]
        comment_lines += [
            f"",
            f"💪 {channel_name} ile her gun bir adim ileri!",
        ]
        comment_text = "\n".join(comment_lines)

        resp = session.post(
            "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet",
            json={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": comment_text}
                    },
                }
            },
        )
        if resp.status_code in (200, 201):
            logger.info(f"Topluluk yorumu eklendi: {video_id}")
            return True
        else:
            logger.warning(f"Yorum eklenemedi: {resp.status_code}")
            return False
    except Exception as e:
        logger.warning(f"Topluluk yorumu hatasi: {e}")
        return False
