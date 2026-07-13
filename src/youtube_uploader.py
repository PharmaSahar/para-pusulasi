"""
YouTube Video Yükleyici
YouTube Data API v3 ile video ve thumbnail yükler.
"""
import logging
import os
import re
import socket
import time
import json
import unicodedata
from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from httplib2 import ServerNotFoundError

from .config import config
from .chapter_validator import remove_chapter_lines, render_chapter_block, validate_and_fix_chapters
from .content_generator import VideoContent
from .channel_capabilities import capability_gating_enabled, get_default_channel_capability_resolver
from .youtube_auth import get_authenticated_service
from .quality_scoring import build_quality_scores
from .chapter_validation_trail import (
    append_chapter_validation_event,
    write_latest_chapter_validator_artifact,
)

logger = logging.getLogger(__name__)

# YouTube API yeniden deneme ayarları
MAX_RETRIES = 3
RETRY_EXCEPTIONS = (IOError, ServerNotFoundError, socket.timeout, TimeoutError)
YOUTUBE_API_HOST = "youtube.googleapis.com"
THUMBNAIL_PERMISSION_CACHE = Path("logs/thumbnail_permission_cache.json")


class YouTubeUploader:
    def __init__(self, channel_cfg=None):
        self.service = None
        self.channel_cfg = channel_cfg
        self._capability_gating_enabled = capability_gating_enabled()
        self._capability_resolution = get_default_channel_capability_resolver().resolve(self._channel_id())
        self._capability_profile = self._capability_resolution.profile
        self._can_upload_thumbnail = True
        self._can_add_comment = True
        self._thumbnail_permission_state = self._load_thumbnail_permission_state()
        if self._thumbnail_permission_state is False:
            self._can_upload_thumbnail = False

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

    def _http_error_detail(self, err: HttpError) -> str:
        content = getattr(err, "content", b"")
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="ignore")[:600]
        return str(content)[:600]

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

        if self._capability_gating_enabled:
            duration_seconds = self._get_video_duration_seconds(video_path)
            if duration_seconds > 15 * 60 and not self._capability_profile.supports_long_form_over_15_minutes():
                raise RuntimeError(
                    f"capability_guard_long_form_over_15m_not_allowed: channel={self._channel_id()} source={self._capability_profile.source}"
                )

        status = {"selfDeclaredMadeForKids": False}
        if publish_at:
            # Scheduled: private olarak yükle, YouTube zamanında public yapar
            status["privacyStatus"] = "private"
            status["publishAt"] = publish_at
            logger.info(f"Zamanlanmış yükleme: {publish_at}")
        else:
            status["privacyStatus"] = privacy

        upload_description = self._build_upload_description(content=content, video_path=video_path)
        clean_tags = self._ensure_minimum_tags(content=content, tags=self._sanitize_tags(content.tags))

        try:
            seo_meta = build_quality_scores(
                title=str(content.title or ""),
                description=upload_description,
                script=str(getattr(content, "script", "") or ""),
                tags=clean_tags,
                thumbnail_prompt=str(getattr(content, "thumbnail_prompt", "") or ""),
            )
            logger.info(
                "Upload metadata quality: seo=%s overall=%s tags=%s desc_len=%s",
                seo_meta.get("seo_score"),
                seo_meta.get("overall_quality_score"),
                len(clean_tags),
                len(upload_description),
            )
        except Exception:
            pass

        safe_description = upload_description
        if self._capability_gating_enabled and not self._capability_profile.supports_external_links():
            safe_description = self._strip_external_links(upload_description)

        body = {
            "snippet": {
                "title": content.title[:100],
                "description": safe_description[:5000],
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

        try:
            video_id = self._resumable_upload(request)
        except Exception as exc:
            append_chapter_validation_event(
                {
                    "artifact_version": "v1",
                    "channel_id": self._channel_id(),
                    "title": str(getattr(content, "title", "") or "")[:180],
                    "upload_stage_failed": True,
                    "post_upload_edit": None,
                    "error_type": exc.__class__.__name__,
                    "event_type": "upload_outcome",
                }
            )
            raise

        append_chapter_validation_event(
            {
                "artifact_version": "v1",
                "channel_id": self._channel_id(),
                "title": str(getattr(content, "title", "") or "")[:180],
                "upload_stage_failed": False,
                "post_upload_edit": False,
                "event_type": "upload_outcome",
            }
        )
        logger.info(f"Video yuklendi: https://youtube.com/watch?v={video_id}")

        thumbnail_allowed_by_capability = True
        if self._capability_gating_enabled:
            thumbnail_allowed_by_capability = self._capability_profile.supports_custom_thumbnails()

        if self._can_upload_thumbnail and thumbnail_allowed_by_capability and thumbnail_path and Path(thumbnail_path).exists():
            self._upload_thumbnail(video_id, thumbnail_path)
        elif thumbnail_path and Path(thumbnail_path).exists() and self._capability_gating_enabled and not thumbnail_allowed_by_capability:
            logger.info(
                "Thumbnail upload skipped by capability gate (channel=%s source=%s)",
                self._channel_id(),
                self._capability_profile.source,
            )
        elif thumbnail_path and Path(thumbnail_path).exists() and not self._can_upload_thumbnail:
            logger.info("Thumbnail upload skipped by cached permission state (channel=%s)", self._channel_id())

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

    def _build_upload_description(self, content: VideoContent, video_path: str) -> str:
        """Normalize description for chapter safety and minimum SEO quality."""
        raw = str(content.seo_description() or "").strip()
        base = self._strip_chapters(raw)
        summary = self._build_summary_line(content)
        discussion = self._build_discussion_line(content)
        duration = self._get_video_duration_seconds(video_path)
        proposed_chapters = self._build_chapters_for_duration(duration)
        chapter_candidate = base
        if proposed_chapters:
            chapter_candidate = f"{base}\n\n{proposed_chapters}".strip()
        try:
            chapter_preflight = validate_and_fix_chapters(
                description=chapter_candidate,
                video_duration_seconds=duration,
                is_short=bool(int(duration or 0) < 60),
            )
        except Exception as exc:
            logger.warning("Chapter validator failed-open: %s", exc)
            chapter_preflight = {
                "schema_version": "2.0",
                "validator_version": "1.1.0",
                "final_chapters": [],
                "chapter_contract_pass": False,
                "input_chapter_count": 0,
                "shorts_bypass": bool(int(duration or 0) < 60),
                "issue_codes": [],
                "issue_labels": ["validator_error"],
                "auto_fix_actions": ["validator_fail_open"],
                "fix_counts": {
                    "cta_removed_count": 0,
                    "merge_count": 0,
                    "ending_trim_count": 0,
                    "duplicate_removed_count": 0,
                },
                "bypass_reason": "validator_error",
                "min_gap_seconds": 10,
                "min_gap_ok": False,
                "ending_guard_pass": False,
                "short_segment_merges": 0,
                "cta_removed_count": 0,
            }
        chapters = render_chapter_block(chapter_preflight.get("final_chapters", []))
        chapter_lines = [line for line in chapters.splitlines()[1:] if line.strip()] if chapters else []
        chapter_count = len(chapter_lines)
        chapter_contract_pass = bool(chapter_preflight.get("chapter_contract_pass", False))

        auto_fix_actions = []
        if raw != base:
            auto_fix_actions.append("strip_static_chapters")
        auto_fix_actions.extend(chapter_preflight.get("auto_fix_actions", []))
        auto_fix_applied = bool(auto_fix_actions)

        append_chapter_validation_event(
            {
                "artifact_version": "v1",
                "channel_id": self._channel_id(),
                "title": str(getattr(content, "title", "") or "")[:180],
                "duration_seconds": int(max(0, duration)),
                "validate_before": {
                    "raw_has_static_chapter_block": bool(raw != base),
                    "generated_chapter_count": int(chapter_preflight.get("input_chapter_count", 0)),
                    "shorts_bypass": bool(chapter_preflight.get("shorts_bypass", False)),
                },
                "auto_fix": {
                    "applied": bool(auto_fix_applied),
                    "action": ",".join(auto_fix_actions) if auto_fix_actions else "none",
                },
                "revalidate": {
                    "chapter_count": int(chapter_count),
                    "chapter_contract_pass": bool(chapter_contract_pass),
                    "bypass_reason": chapter_preflight.get("bypass_reason"),
                    "min_gap_seconds": int(chapter_preflight.get("min_gap_seconds", 10)),
                    "min_gap_ok": bool(chapter_preflight.get("min_gap_ok", False)),
                    "ending_guard_pass": bool(chapter_preflight.get("ending_guard_pass", False)),
                    "short_segment_merges": int(chapter_preflight.get("short_segment_merges", 0)),
                    "cta_removed_count": int(chapter_preflight.get("cta_removed_count", 0)),
                },
                "upload_stage_failed": None,
                "post_upload_edit": None,
            }
        )

        write_latest_chapter_validator_artifact(
            channel_id=self._channel_id(),
            title=str(getattr(content, "title", "") or ""),
            duration_seconds=int(max(0, duration)),
            chapter_result=chapter_preflight,
            input_description=chapter_candidate,
        )

        keywords = self._build_keyword_line(content)
        hashtags = self._build_hashtags(content)

        parts = [summary]
        if base:
            parts.append(base)
        if chapters:
            parts.append(chapters)
        parts.append(discussion)
        parts.append(keywords)
        if hashtags:
            parts.append(hashtags)

        description = "\n\n".join(part.strip() for part in parts if part and part.strip())
        if len(description) < 220:
            description = (
                f"{description}\n\n"
                "Bu icerik egitim amaclidir. Risk yonetimi, uygulama adimlari ve pratik kontrol listesiyle ilerliyoruz."
            )
        return description

    def _strip_chapters(self, text: str) -> str:
        return remove_chapter_lines(text)

    def _build_summary_line(self, content: VideoContent) -> str:
        hook = str(getattr(content, "hook", "") or "").strip()
        title = str(getattr(content, "title", "") or "").strip()
        if hook:
            return f"📌 Bu videoda: {hook}"
        return f"📌 Bu videoda: {title}"

    def _build_discussion_line(self, content: VideoContent) -> str:
        title = str(getattr(content, "title", "") or "").strip()
        return f"💬 Yorum sorusu: {title} konusunda en cok hangi adimda zorlaniyorsun?"

    def _build_keyword_line(self, content: VideoContent) -> str:
        tags = self._ensure_minimum_tags(content=content, tags=self._sanitize_tags(getattr(content, "tags", [])))
        return "Anahtar kelimeler: " + ", ".join(tags[:10]) + "."

    def _build_hashtags(self, content: VideoContent) -> str:
        tags = self._ensure_minimum_tags(content=content, tags=self._sanitize_tags(getattr(content, "tags", [])))
        hashtag_tokens = []
        for tag in tags[:8]:
            token = "".join(ch for ch in tag if ch.isalnum())
            if token:
                hashtag_tokens.append(f"#{token}")
        return " ".join(hashtag_tokens)

    def _strip_external_links(self, text: str) -> str:
        return re.sub(r"https?://\S+", "", str(text or "")).strip()

    def _get_video_duration_seconds(self, video_path: str) -> int:
        try:
            from moviepy import VideoFileClip

            clip = VideoFileClip(video_path)
            try:
                duration = int(float(getattr(clip, "duration", 0) or 0))
            finally:
                clip.close()
            return max(0, duration)
        except Exception as e:
            logger.warning("Video duration okunamadi, chapter blok atlanacak: %s", e)
            return 0

    def _build_chapters_for_duration(self, duration_sec: int) -> str:
        if duration_sec < 45:
            return ""

        available = duration_sec - 10
        if available < 30:
            return ""

        target_count = min(6, max(3, duration_sec // 120 + 2))
        points: list[int] = [0]
        for i in range(1, target_count):
            candidate = int(round((available * i) / (target_count - 1)))
            candidate = max(10, min(available, candidate))
            if candidate - points[-1] < 10:
                candidate = points[-1] + 10
            if candidate > available:
                break
            points.append(candidate)

        while len(points) >= 2 and (available - points[-1]) < 10:
            points.pop()

        if len(points) < 3:
            return ""

        titles = [
            "Giris ve Hook",
            "Temel Kavramlar",
            "Ornekler ve Veri",
            "Adim Adim Uygulama",
            "Kritik Hatalar",
            "Ozet ve Sonraki Adim",
        ]
        chapter_lines = ["⏱️ BOLUMLER:"]
        for idx, sec in enumerate(points):
            minute = sec // 60
            second = sec % 60
            title = titles[min(idx, len(titles) - 1)]
            chapter_lines.append(f"{minute:02d}:{second:02d} {title}")
        return "\n".join(chapter_lines)

    def _ensure_minimum_tags(self, content: VideoContent, tags: list[str]) -> list[str]:
        normalized = [t for t in tags if t]
        seen = {t.lower() for t in normalized}

        fallbacks = self._fallback_tags_from_content(content)
        for tag in fallbacks:
            key = tag.lower()
            if key in seen:
                continue
            normalized.append(tag)
            seen.add(key)
            if len(normalized) >= 15:
                break

        while len(normalized) < 8:
            candidate = f"anahtar konu {len(normalized) + 1}"
            if candidate.lower() not in seen:
                normalized.append(candidate)
                seen.add(candidate.lower())

        return normalized[:15]

    def _fallback_tags_from_content(self, content: VideoContent) -> list[str]:
        title = str(getattr(content, "title", "") or "")
        niche = str(getattr(content, "niche", "") or "")
        ascii_title = "".join(
            ch for ch in unicodedata.normalize("NFKD", title) if not unicodedata.combining(ch)
        ).lower()
        words = [w for w in re.findall(r"[a-z0-9ığüşöç]+", ascii_title) if len(w) >= 3]
        defaults = [
            niche.strip() or "egitim",
            "finans",
            "strateji",
            "analiz",
            "risk yonetimi",
            "turkiye",
            "yatirim",
        ]
        merged = defaults + words
        out: list[str] = []
        seen: set[str] = set()
        for item in merged:
            token = str(item).strip()[:50]
            if not token:
                continue
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(token)
            if len(out) >= 15:
                break
        return out

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
                status = getattr(getattr(e, "resp", None), "status", "unknown")
                detail = self._http_error_detail(e)
                if retryable and retry < MAX_RETRIES:
                    retry += 1
                    wait = 2 ** retry
                    logger.warning(
                        "Transient upload HTTP hatası (%s, status=%s), %ss sonra yeniden denenecek (%s/%s). detail=%s",
                        reason,
                        status,
                        wait,
                        retry,
                        MAX_RETRIES,
                        detail,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "Kalıcı upload HTTP hatası (%s, status=%s) - retry yok. detail=%s",
                        reason,
                        status,
                        detail,
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
        if not isinstance(response, dict):
            logger.error("Upload yanıtı geçersiz tipte: %s", type(response).__name__)
            raise RuntimeError("upload_response_invalid_type")

        video_id = str(response.get("id") or "").strip()
        if not video_id:
            logger.error(
                "Upload yanıtında video ID yok. keys=%s response=%s",
                sorted(response.keys()),
                json.dumps(response, ensure_ascii=False)[:600],
            )
            raise RuntimeError("upload_response_missing_id")

        return video_id

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
            self._set_thumbnail_permission_state(True)
            logger.info(f"Thumbnail yüklendi: {thumbnail_path}")
        except HttpError as e:
            if getattr(e, "resp", None) and e.resp.status == 403:
                self._can_upload_thumbnail = False
                token_path = getattr(self.channel_cfg, "token_path", "youtube_token.pickle")
                channel_id = getattr(self.channel_cfg, "channel_id", "default")
                content = getattr(e, "content", b"")
                detail = content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else str(content)
                reason = self._classify_thumbnail_403_reason(detail)
                logger.warning(
                    "Thumbnail yükleme izni yok (403) -> devre dışı. channel=%s token=%s reason=%s detail=%s remediation=thumbnail_only_probe",
                    channel_id,
                    token_path,
                    reason,
                    detail[:400],
                )
                self._set_thumbnail_permission_state(False, reason=reason)
            else:
                logger.warning(f"Thumbnail yüklenemedi: {e}")

    def _channel_id(self) -> str:
        return str(getattr(self.channel_cfg, "channel_id", "default"))

    def _load_thumbnail_permission_state(self) -> bool | None:
        path = THUMBNAIL_PERMISSION_CACHE
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            state = (payload.get("channels") or {}).get(self._channel_id(), {}).get("can_upload_thumbnail")
            if isinstance(state, bool):
                return state
        except Exception:
            return None
        return None

    def _set_thumbnail_permission_state(self, can_upload: bool, reason: str | None = None) -> None:
        path = THUMBNAIL_PERMISSION_CACHE
        try:
            existing = {}
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))
            channels = dict(existing.get("channels") or {})
            prev = channels.get(self._channel_id(), {})
            prev_streak = int(prev.get("success_streak", 0) or 0)
            success_streak = (prev_streak + 1) if can_upload else 0
            channels[self._channel_id()] = {
                "can_upload_thumbnail": bool(can_upload),
                "success_streak": success_streak,
                "last_reason": reason,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            data = {"channels": channels}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _classify_thumbnail_403_reason(self, detail: str) -> str:
        text = (detail or "").lower()
        if "insufficientpermissions" in text or "forbidden" in text and "permission" in text:
            return "ownership_or_brand_permission"
        if "channel" in text and "not found" in text:
            return "token_channel_mismatch"
        if "thumbnail" in text and "disabled" in text:
            return "custom_thumbnail_eligibility"
        if "policy" in text or "verification" in text:
            return "api_policy_or_verification"
        return "forbidden_unknown"

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
