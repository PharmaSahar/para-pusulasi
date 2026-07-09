"""
YouTube Video Yükleyici
YouTube Data API v3 ile video ve thumbnail yükler.
"""
import logging
import os
import re
import socket
import time
from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from httplib2 import ServerNotFoundError

from .config import config
from .content_generator import VideoContent
from .youtube_auth import get_authenticated_service

logger = logging.getLogger(__name__)

# YouTube API yeniden deneme ayarları
MAX_RETRIES = 3
RETRY_EXCEPTIONS = (IOError, ServerNotFoundError, socket.timeout, TimeoutError)
YOUTUBE_API_HOST = "youtube.googleapis.com"


class YouTubeUploader:
    def __init__(self, channel_cfg=None):
        self.service = None
        self.channel_cfg = channel_cfg
        self._can_upload_thumbnail = True
        self._can_add_comment = True

    def _resolve_default_language(self) -> str:
        """Kanal dili -> global config -> güvenli default sırasıyla çöz."""
        lang = None
        if self.channel_cfg is not None:
            lang = (
                getattr(self.channel_cfg, "channel_language", None)
                or getattr(self.channel_cfg, "language", None)
            )
        if not lang:
            lang = getattr(config, "channel_language", None)

        normalized = str(lang or "").strip().replace("_", "-")
        if re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z]{2,4})?", normalized):
            return normalized
        return "en"

    def _classify_http_error(self, err: HttpError) -> tuple[str, bool]:
        """HTTP hatasını sınıflandır: (reason, retryable)."""
        status = int(getattr(getattr(err, "resp", None), "status", 0) or 0)
        content = getattr(err, "content", b"")
        if isinstance(content, bytes):
            detail = content.decode("utf-8", errors="ignore").lower()
        else:
            detail = str(content).lower()

        if 500 <= status <= 599:
            return "server_error", True

        if status == 408:
            return "request_timeout", True

        if status == 409:
            # Resumable upload state/session çakışmaları transient olabilir.
            if any(k in detail for k in ("resumable", "upload", "session", "state")):
                return "resumable_conflict", True
            return "conflict", False

        if status == 429:
            return "rate_limited", True

        # 4xx'lerde kör retry kapalı: credential/quota/validation kalıcı sayılır.
        if status in {401, 403}:
            if "quota" in detail or "ratelimit" in detail or "rate_limit" in detail:
                return "quota_or_rate_limit", False
            return "credential_or_permission", False
        if status == 400:
            return "validation_error", False
        if 400 <= status <= 499:
            return "client_error", False

        # Beklenmeyen durumda güvenli taraf: retry etme.
        return "unknown_http_error", False

    def _get_service(self):
        if not self.service:
            from .youtube_auth import get_authenticated_service
            self.service = get_authenticated_service(channel_cfg=self.channel_cfg)
        return self.service

    def upload_video(
        self,
        video_path: str,
        content: VideoContent,
        thumbnail_path: str | None = None,
        privacy: str = "public",
        publish_at: str | None = None,  # ISO 8601: "2026-07-07T20:00:00+03:00"
    ) -> str:
        """Video yukle. publish_at verilirse YouTube otomatik o saatte yayınlar."""
        # Upload öncesi dosya kontrolü
        vp = Path(video_path)
        if not vp.exists():
            raise FileNotFoundError(f"Video dosyası bulunamadı: {video_path}")
        file_size = vp.stat().st_size
        if file_size < 100_000:
            raise ValueError(f"Video dosyası çok küçük ({file_size} bytes) - bozuk render: {video_path}")
        logger.info(f"YouTube'a yukleniyor: '{content.title}' ({file_size // 1024 // 1024:.1f} MB)")
        self._log_dns_resolution(YOUTUBE_API_HOST)
        self._ensure_dns_resolution(YOUTUBE_API_HOST)

        status = {"selfDeclaredMadeForKids": False}
        if publish_at:
            # Scheduled: private olarak yükle, YouTube zamanında public yapar
            status["privacyStatus"] = "private"
            status["publishAt"] = publish_at
            logger.info(f"Zamanlanmış yükleme: {publish_at}")
        else:
            status["privacyStatus"] = privacy

        clean_tags = self._sanitize_tags(content.tags)
        body = {
            "snippet": {
                "title": content.title[:100],
                "description": content.seo_description()[:5000],
                "tags": clean_tags,
                "categoryId": content.category_id,
                "defaultLanguage": self._resolve_default_language(),
            },
            "status": status,
        }

        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=1024 * 1024 * 5,
        )

        request = self._get_service().videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )

        video_id = self._resumable_upload(request)
        logger.info(f"Video yuklendi: https://youtube.com/watch?v={video_id}")

        if self._can_upload_thumbnail and thumbnail_path and Path(thumbnail_path).exists():
            self._upload_thumbnail(video_id, thumbnail_path)

        # Playlist ve yorum: quota koruma için devre dışı
        # Her upload 1600 birim, günlük limit 10000 — playlist/yorum ekstra birim yiyor
        # Kanala göre quota kalmışsa yorum ekle
        if self._can_add_comment:
            try:
                self._add_pinned_comment(video_id, content.title)
            except Exception:
                pass  # Quota aşılmışsa sessizce atla

        return video_id

    def _add_pinned_comment(self, video_id: str, title: str):
        """Video yukledikten hemen sonra sabitlenecek yorum ekle."""
        try:
            comment_text = (
                f"📌 Bu videoda ne ogrendik? Asagiya yazin! 👇\n\n"
                f"💡 '{title}' konusunu faydalı buldunuz mu?\n"
                f"🔔 Abone olun, her gun 2 yeni video!\n\n"
                f"❓ Sorulariniz var mi? Yorumda sorun, cevapliyorum!"
            )
            response = self._get_service().commentThreads().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": video_id,
                        "topLevelComment": {
                            "snippet": {"textOriginal": comment_text}
                        },
                    }
                },
            ).execute()

            comment_id = response["snippet"]["topLevelComment"]["id"]

            # Yorumu sabitle
            self._get_service().comments().setModerationStatus(
                id=comment_id,
                moderationStatus="published",
            ).execute()
            logger.info(f"Sabitlenecek yorum eklendi: {comment_id}")
        except Exception as e:
            if isinstance(e, HttpError) and getattr(e, "resp", None) and e.resp.status == 403:
                self._can_add_comment = False
                logger.info("Yorum izni yok (403) -> yorum ekleme bu oturum için devre dışı.")
            else:
                logger.warning(f"Yorum eklenemedi: {e}")

    def _sanitize_tags(self, tags: list) -> list:
        """YouTube tag kurallarına uygun hale getir: emoji yok, max 500 karakter toplam."""
        import re
        clean = []
        total_len = 0
        for tag in (tags or []):
            # Emoji ve özel karakterleri kaldır (ASCII + Türkçe harfler kalsın)
            t = re.sub(r'[^\w\s\-.,&\'\u00C0-\u024F]', '', str(tag), flags=re.UNICODE)
            t = t.strip()[:50]  # Tek tag max 50 karakter
            if not t:
                continue
            if total_len + len(t) + 1 > 500:
                break
            clean.append(t)
            total_len += len(t) + 1
        return clean[:15]  # Max 15 tag

    def _resumable_upload(self, request) -> str:
        """Yeniden başlatılabilir yükleme ile video yükle."""
        response = None
        retry = 0

        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"Yükleniyor... %{progress}")
            except HttpError as e:
                reason, retryable = self._classify_http_error(e)
                if retryable and retry < MAX_RETRIES:
                    retry += 1
                    wait = 2 ** retry
                    logger.warning(
                        "Transient upload HTTP hatası (%s), %ss sonra yeniden denenecek (%s/%s)",
                        reason,
                        wait,
                        retry,
                        MAX_RETRIES,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "Kalıcı upload HTTP hatası (%s, status=%s) - retry yok",
                        reason,
                        getattr(getattr(e, "resp", None), "status", "unknown"),
                    )
                    raise
            except ServerNotFoundError as e:
                if retry < MAX_RETRIES:
                    retry += 1
                    wait = 2 ** retry
                    self._log_dns_resolution(YOUTUBE_API_HOST)
                    logger.warning(f"DNS/ağ hatası, {wait}s sonra yeniden denenecek ({retry}/{MAX_RETRIES}): {e}")
                    time.sleep(wait)
                else:
                    raise
            except RETRY_EXCEPTIONS as e:
                if retry < MAX_RETRIES:
                    retry += 1
                    wait = 2 ** retry
                    logger.warning(
                        "Transient upload hatası (%s), %ss sonra yeniden denenecek (%s/%s)",
                        type(e).__name__,
                        wait,
                        retry,
                        MAX_RETRIES,
                    )
                    time.sleep(wait)
                else:
                    raise

        return response["id"]

    def _ensure_dns_resolution(self, host: str) -> None:
        try:
            socket.getaddrinfo(host, 443)
        except socket.gaierror as e:
            raise ServerNotFoundError(str(e)) from e

    def _log_dns_resolution(self, host: str) -> None:
        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
            ips = []
            seen = set()
            for info in infos:
                ip = info[4][0]
                if ip not in seen:
                    seen.add(ip)
                    ips.append(ip)
            if ips:
                logger.info("DNS resolution for %s -> %s", host, ", ".join(ips))
        except socket.gaierror as e:
            logger.warning("DNS resolution failed for %s: %s", host, e)

    def _upload_thumbnail(self, video_id: str, thumbnail_path: str):
        """Video thumbnail'ini yükle."""
        try:
            self._get_service().thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            logger.info(f"Thumbnail yüklendi: {thumbnail_path}")
        except HttpError as e:
            if getattr(e, "resp", None) and e.resp.status == 403:
                self._can_upload_thumbnail = False
                logger.info("Thumbnail yükleme izni yok (403) -> thumbnail yükleme bu oturum için devre dışı.")
            else:
                logger.warning(f"Thumbnail yüklenemedi: {e}")

    def get_channel_stats(self) -> dict:
        """Kanal istatistiklerini getir."""
        response = self._get_service().channels().list(
            part="statistics,snippet",
            mine=True,
        ).execute()

        if response.get("items"):
            item = response["items"][0]
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            return {
                "channel_name": snippet.get("title", ""),
                "subscribers": stats.get("subscriberCount", 0),
                "total_views": stats.get("viewCount", 0),
                "video_count": stats.get("videoCount", 0),
            }
        return {}
