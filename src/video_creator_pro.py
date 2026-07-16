"""
Profesyonel Video Olusturma Modulu v2.0
- Branded intro kart (logo + baslik animasyonu)
- TV-style lower third barlar (kayarak girer/cikar)
- Netflix-style altyazi (outline, timing)
- Haber kanalı stat popup chyronlar
- Sinematik renk duzeltmesi
- Branded outro (abone CTA)
"""
import json
import logging
import random
import re
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
    vfx,
)

from .config import config

logger = logging.getLogger(__name__)

# Sistem fontlari - macOS
FONT_PATHS = {
    "bold": [
        # Linux (VPS)
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
        # macOS
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ],
    "regular": [
        # Linux (VPS)
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
        # macOS
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ],
}


def _load_font(style="regular", size=36):
    for path in FONT_PATHS.get(style, FONT_PATHS["regular"]):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


class VideoCreator:
    def __init__(self, channel_cfg=None):
        from .config import config as _cfg
        cfg = channel_cfg if channel_cfg else _cfg
        self.width = cfg.video_width
        self.height = cfg.video_height
        self.fps = 24
        self.videos_dir = getattr(cfg, "videos_dir", "output/videos")
        if channel_cfg and hasattr(channel_cfg, "color_primary"):
            self.color_primary = tuple(channel_cfg.color_primary)
            self.color_bg = tuple(channel_cfg.color_bg)
            self.channel_name = channel_cfg.name
            self.channel_tagline = getattr(channel_cfg, "tagline", "Uzmanlik Rehberi")
        else:
            self.color_primary = (212, 175, 55)   # Altın sarısı
            self.color_bg = (10, 18, 40)           # Lacivert
            self.channel_name = "Genel Kanal"
            self.channel_tagline = "Uzmanlik Rehberi"
        if channel_cfg and hasattr(channel_cfg, "base_dir"):
            wm = f"{channel_cfg.base_dir}/branding/watermark_150x150.png"
            self.watermark_path = wm if Path(wm).exists() else "assets/branding/watermark_150x150.png"
            logo = f"{channel_cfg.base_dir}/branding/logo_800x800.png"
            self.logo_path = logo if Path(logo).exists() else "assets/branding/logo_800x800.png"
        else:
            self.watermark_path = "assets/branding/watermark_150x150.png"
            self.logo_path = "assets/branding/logo_800x800.png"

    # ──────────────────────────────────────────────────────────────────────────
    # ANA METOT
    # ──────────────────────────────────────────────────────────────────────────

    def create_video(self, audio_path, title, image_paths=None, output_path=None, script=None):
        if not output_path:
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = "".join(c for c in title[:30] if c.isalnum() or c in " _").strip()
            output_path = f"{self.videos_dir}/{ts}_{safe}.mp4"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Profesyonel video oluşturuluyor: {title}")

        audio_clip = AudioFileClip(audio_path)
        duration = audio_clip.duration

        # ── KATMANLAR (alttan üste) ──────────────────────────────────────────

        # 1. Arka plan: Pexels klipleri veya gradient
        if image_paths:
            bg = self._create_slideshow(image_paths, duration)
        else:
            bg = self._create_gradient_background(duration)
        layers = [bg]

        # 2. Pexels klip modu: ust ve alt koyu seritler (okunurluk)
        if image_paths:
            layers.extend(self._get_readability_strips(duration))

        # 3. INTRO KARTI (0 → min(4.5s, %12))
        intro_dur = min(4.5, duration * 0.12)
        layers.append(self._create_intro_card(title, intro_dur))

        # 4. LOWER THIRD BARLAR (kanal kimlik barı, 3 kez kayarak girer)
        layers.extend(self._create_lower_thirds(duration, intro_dur))

        # 5. ALTYAZI (cümle zamanlamasıyla)
        timing_path = audio_path.replace(".mp3", "_timing.json")
        sentence_data = []
        if Path(timing_path).exists():
            try:
                with open(timing_path, encoding="utf-8") as f:
                    sentence_data = json.load(f)
            except Exception:
                pass
        subtitle_clips = self._create_subtitle_clips(sentence_data, duration, script)
        layers.extend(subtitle_clips)

        # 6. STAT / FACT POPUP CHYRONLAR
        if script:
            key_points = self._extract_key_points(script)
            layers.extend(self._create_stat_chyrons(key_points, duration, intro_dur))

        # 7. OUTRO KARTI (son %12, min 5s)
        outro_dur = min(6.0, duration * 0.12)
        if duration > 20:
            layers.append(self._create_outro_card(duration, outro_dur))

        # 8. WATERMARK (her zaman)
        wm = self._create_watermark_clip(duration)
        if wm:
            layers.append(wm)

        # ── RENDER ──────────────────────────────────────────────────────────
        import uuid
        tmp_audio = str(Path(output_path).parent / f"_tmp_audio_{uuid.uuid4().hex[:8]}.m4a")
        composite = CompositeVideoClip(layers, size=(self.width, self.height)).with_audio(audio_clip)
        composite.write_videofile(
            output_path,
            fps=self.fps,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=tmp_audio,
            remove_temp=True,
            logger=None,
            preset="fast",    # medium→fast: daha az RAM + daha hızlı
            bitrate="2000k",  # 3000k→2000k: YouTube için yeterli, RAM tasarrufu
            threads=1,        # Tek thread: RAM çakışmasını önle
        )
        # Temp audio temizle (MoviePy bazen bırakır)
        try:
            Path(tmp_audio).unlink(missing_ok=True)
        except Exception:
            pass
        # Dosya geçerlilik kontrolü
        out_size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        if out_size < 100_000:  # 100 KB altı kesinlikle bozuk
            raise RuntimeError(f"Render başarısız - dosya çok küçük ({out_size} bytes): {output_path}")
        logger.info(f"Video hazır ({out_size // 1024 // 1024:.1f} MB): {output_path}")
        return output_path

    # ──────────────────────────────────────────────────────────────────────────
    # BRANDED INTRO KARTI
    # ──────────────────────────────────────────────────────────────────────────

    def _create_intro_card(self, title: str, card_dur: float) -> ImageClip:
        """Markalı intro kart: logo + başlık + kanal adı, fade out ile biter."""
        W, H = self.width, self.height
        r, g, b = self.color_primary
        br, bg_, bb = self.color_bg

        # Arka plan
        img = Image.new("RGB", (W, H))
        draw = ImageDraw.Draw(img)
        for y in range(H):
            blend = y / H
            pr = int(br + blend * 10)
            pg = int(bg_ + blend * 8)
            pb = int(bb + blend * 20)
            draw.line([(0, y), (W, y)], fill=(pr, pg, pb))

        # Üst renkli şerit
        draw.rectangle([0, 0, W, 7], fill=(r, g, b))

        # Alt renkli şerit
        draw.rectangle([0, H - 7, W, H], fill=(r, g, b))

        # Orta çizgi - ince dekoratif hat
        draw.rectangle([W // 4, H // 2 - 1, W * 3 // 4, H // 2 + 1], fill=(r, g, b))

        # Logo (varsa)
        logo_placed = False
        if Path(self.logo_path).exists():
            try:
                logo = Image.open(self.logo_path).convert("RGBA")
                logo_size = 110
                logo = logo.resize((logo_size, logo_size), Image.LANCZOS)
                lx = (W - logo_size) // 2
                ly = H // 5
                tmp = Image.new("RGB", (W, H), (0, 0, 0))
                tmp.paste(img)
                tmp.paste(logo, (lx, ly), logo.split()[3])
                img = tmp
                draw = ImageDraw.Draw(img)
                logo_placed = True
            except Exception:
                pass

        # Başlık metni
        f_big = _load_font("bold", 66)
        f_med = _load_font("bold", 38)
        f_small = _load_font("regular", 28)

        y_title = H // 5 + (130 if logo_placed else 60)
        lines = textwrap.wrap(title, width=26)[:3]
        for line in lines:
            bb_box = draw.textbbox((0, 0), line, font=f_big)
            tw = bb_box[2] - bb_box[0]
            x = (W - tw) // 2
            # Gölge
            draw.text((x + 3, y_title + 3), line, font=f_big, fill=(0, 0, 0))
            draw.text((x, y_title), line, font=f_big, fill=(255, 255, 255))
            y_title += 78

        # Kanal adı (altın rengi)
        chan_bb = draw.textbbox((0, 0), self.channel_name, font=f_med)
        cx = (W - (chan_bb[2] - chan_bb[0])) // 2
        draw.text((cx + 2, y_title + 22 + 2), self.channel_name, font=f_med, fill=(0, 0, 0))
        draw.text((cx, y_title + 22), self.channel_name, font=f_med, fill=(r, g, b))

        # Tagline
        tag_bb = draw.textbbox((0, 0), self.channel_tagline, font=f_small)
        tx = (W - (tag_bb[2] - tag_bb[0])) // 2
        draw.text((tx, y_title + 72), self.channel_tagline, font=f_small, fill=(160, 160, 160))

        return (
            ImageClip(np.array(img))
            .with_duration(card_dur)
            .with_start(0)
            .with_effects([vfx.FadeOut(min(1.2, card_dur * 0.4))])
        )

    # ──────────────────────────────────────────────────────────────────────────
    # LOWER THIRD BARLAR
    # ──────────────────────────────────────────────────────────────────────────

    def _create_lower_thirds(self, total_dur: float, intro_dur: float) -> list:
        """3 adet TV-style lower third bar, soldan kayarak girer/çıkar."""
        SLIDE = 0.32   # Kayma süresi (s)
        HOLD  = 4.0    # Görünme süresi (s)
        bar_w, bar_h = 560, 74

        r, g, b = self.color_primary

        # Bar görüntüsü
        bar_img = Image.new("RGB", (bar_w, bar_h), (10, 10, 10))
        draw = ImageDraw.Draw(bar_img)
        # Sol vurgu şeridi
        draw.rectangle([0, 0, 7, bar_h], fill=(r, g, b))
        # Kanal adı
        fn = _load_font("bold", 30)
        ft = _load_font("regular", 20)
        draw.text((22, 7), self.channel_name, font=fn, fill=(255, 255, 255))
        draw.text((22, 44), self.channel_tagline, font=ft, fill=(r, g, b))

        bar_arr = np.array(bar_img)
        total_clip_dur = SLIDE * 2 + HOLD
        target_x, target_y = 55, self.height - 215

        def make_pos(t):
            if t < SLIDE:
                p = t / SLIDE
                return (int(-bar_w + (target_x + bar_w) * p), target_y)
            elif t < SLIDE + HOLD:
                return (target_x, target_y)
            else:
                p = (t - SLIDE - HOLD) / SLIDE
                return (int(target_x - (target_x + bar_w) * p), target_y)

        # Zamanlamalar: intro bittikten sonra, orta, sona yakın
        show_times = [
            intro_dur + 1.5,
            total_dur * 0.42,
            total_dur * 0.76,
        ]

        clips = []
        for st in show_times:
            if st + total_clip_dur > total_dur - 7:
                continue
            clips.append(
                ImageClip(bar_arr)
                .with_start(st)
                .with_duration(total_clip_dur)
                .with_position(make_pos)
            )
        return clips

    # ──────────────────────────────────────────────────────────────────────────
    # ALTYAZI
    # ──────────────────────────────────────────────────────────────────────────

    def _create_subtitle_clips(self, sentence_data: list, duration: float, script: str | None) -> list:
        """Netflix-style altyazı: SentenceBoundary timing veya karakter tahmini."""
        WORDS_PER = 7
        clips = []

        if sentence_data:
            for sb in sentence_data:
                text = sb.get("text", "").strip()
                if not text:
                    continue
                start = sb["start"]
                end = sb["end"]
                seg_dur = max(min(end - start, duration - start - 0.1), 0.4)
                if start >= duration - 0.5:
                    break
                words = text.split()
                n_parts = max(len(words) // WORDS_PER + 1, 1)
                part_dur = seg_dur / n_parts
                t = start
                for i in range(0, len(words), WORDS_PER):
                    chunk = " ".join(words[i:i + WORDS_PER])
                    clips.extend(self._make_subtitle(chunk, t, max(part_dur, 0.5)))
                    t += part_dur
        elif script:
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', script.strip()) if s.strip()]
            total_chars = max(sum(len(s) for s in sentences), 1)
            t = 1.0
            for sent in sentences:
                seg_dur = max((len(sent) / total_chars) * (duration - 1.5), 1.0)
                seg_dur = min(seg_dur, 8.0)
                words = sent.split()
                n_parts = max(len(words) // WORDS_PER + 1, 1)
                part_dur = seg_dur / n_parts
                for i in range(0, len(words), WORDS_PER):
                    if t >= duration - 0.5:
                        break
                    chunk = " ".join(words[i:i + WORDS_PER])
                    clips.extend(self._make_subtitle(chunk, t, max(part_dur, 0.5)))
                    t += part_dur

        return clips

    def _make_subtitle(self, text: str, start: float, dur: float) -> list:
        """Netflix-style: ince koyu bar + kalın outline metin."""
        bar_h = 62
        bar = (
            ColorClip(size=(self.width, bar_h), color=(0, 0, 0))
            .with_opacity(0.68)
            .with_start(start)
            .with_duration(dur)
            .with_position((0, self.height - bar_h - 6))
        )
        try:
            txt = (
                TextClip(
                    text=text,
                    font_size=40,
                    color="white",
                    font=next(
                        (p for p in [
                            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                            "/System/Library/Fonts/Helvetica.ttc",
                        ] if __import__('pathlib').Path(p).exists()),
                        None
                    ),
                    text_align="center",
                    stroke_color="black",
                    stroke_width=2,
                )
                .with_start(start)
                .with_duration(dur)
                .with_position(("center", self.height - bar_h + 4))
            )
            return [bar, txt]
        except Exception as e:
            logger.warning(f"Altyazı hatası: {e}")
            return [bar]

    # ──────────────────────────────────────────────────────────────────────────
    # STAT CHYRON POPUP
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_key_points(self, script: str) -> list:
        """Scriptten istatistik ve önemli noktaları çıkar."""
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', script.strip()) if s.strip()]
        key_points = []
        for s in sentences:
            if len(s) < 20:
                continue
            if re.search(r'\d+[%₺$€]|\d{4}|\d+[.,]\d+', s):
                key_points.append(s)
            elif any(kw in s.lower() for kw in ['dikkat', 'önemli', 'kritik', 'fırsat', 'kazanç', 'risk', 'uyarı']):
                key_points.append(s)
        return [p[:85] for p in key_points[:4]]

    def _create_stat_chyrons(self, key_points: list, total_dur: float, intro_dur: float) -> list:
        """Haber kanalı stil chyron kutuları - sol tarafta sürgülü."""
        if not key_points:
            return []
        SLIDE = 0.28
        HOLD  = 4.8
        clip_dur = SLIDE * 2 + HOLD
        r, g, b = self.color_primary
        clips = []
        n = len(key_points)

        for i, point in enumerate(key_points):
            show_at = intro_dur + 8 + (total_dur - intro_dur - 16) * (i / n)
            if show_at + clip_dur > total_dur - 7:
                continue

            wrapped = textwrap.wrap(point, width=44)[:2]
            line_h = 48
            box_w = 820
            box_h = len(wrapped) * line_h + 32

            # ─ Chyron görüntüsü ─
            box = Image.new("RGB", (box_w, box_h), (8, 8, 8))
            draw = ImageDraw.Draw(box)
            # Sol vurgu
            draw.rectangle([0, 0, 8, box_h], fill=(r, g, b))
            # Üst sınır çizgisi
            draw.rectangle([0, 0, box_w, 3], fill=(r, g, b))
            # Etiket metni
            f_label = _load_font("bold", 18)
            f_text  = _load_font("regular", 30)
            label = "📊 ÖNEMLİ BİLGİ"
            draw.text((18, 5), label, font=f_label, fill=(r, g, b))
            for j, line in enumerate(wrapped):
                draw.text((18, 26 + j * line_h), line, font=f_text, fill=(235, 235, 235))

            box_arr = np.array(box)
            target_x = 50
            target_y = self.height // 2 - box_h // 2

            def make_pos(t, bw=box_w, tx=target_x, ty=target_y):
                if t < SLIDE:
                    p = t / SLIDE
                    return (int(-bw + (tx + bw) * p), ty)
                elif t < SLIDE + HOLD:
                    return (tx, ty)
                else:
                    p = (t - SLIDE - HOLD) / SLIDE
                    return (int(tx - (tx + bw) * p), ty)

            clips.append(
                ImageClip(box_arr)
                .with_start(show_at)
                .with_duration(clip_dur)
                .with_position(make_pos)
            )
        return clips

    # ──────────────────────────────────────────────────────────────────────────
    # OUTRO KARTI
    # ──────────────────────────────────────────────────────────────────────────

    def _create_outro_card(self, total_dur: float, card_dur: float) -> ImageClip:
        """Branded outro: abone ol / beğen CTA, fade in ile başlar."""
        W, H = self.width, self.height
        r, g, b = self.color_primary
        br, bg_, bb = self.color_bg
        start_at = total_dur - card_dur

        img = Image.new("RGB", (W, H))
        draw = ImageDraw.Draw(img)
        for y in range(H):
            blend = y / H
            draw.line([(0, y), (W, y)], fill=(
                int(br * (1 - blend * 0.4)),
                int(bg_ * (1 - blend * 0.4)),
                int(bb * (1 - blend * 0.4)),
            ))
        draw.rectangle([0, 0, W, 7], fill=(r, g, b))
        draw.rectangle([0, H - 7, W, H], fill=(r, g, b))

        f_big   = _load_font("bold", 68)
        f_med   = _load_font("bold", 46)
        f_small = _load_font("regular", 32)
        f_tiny  = _load_font("regular", 26)

        # Kanal adı
        cn_bb = draw.textbbox((0, 0), self.channel_name, font=f_big)
        cx = (W - (cn_bb[2] - cn_bb[0])) // 2
        draw.text((cx + 3, H // 4 + 3), self.channel_name, font=f_big, fill=(0, 0, 0))
        draw.text((cx, H // 4), self.channel_name, font=f_big, fill=(r, g, b))

        # Ayırıcı çizgi
        draw.rectangle([W // 4, H // 4 + 90, W * 3 // 4, H // 4 + 93], fill=(r, g, b))

        # CTA metinler
        cta_items = [
            ("👍", "Bu videoyu beğen"),
            ("🔔", "Kanala abone ol"),
            ("💬", "Yorumlarını paylaş"),
        ]
        y_cta = H // 2 + 10
        for icon, text in cta_items:
            combined = f"{icon}  {text}"
            cb = draw.textbbox((0, 0), combined, font=f_small)
            cx2 = (W - (cb[2] - cb[0])) // 2
            draw.text((cx2, y_cta), combined, font=f_small, fill=(235, 235, 235))
            y_cta += 52

        # Alt bildirim notu
        note = "Yeni videolar için 🔔 bildirimleri açık tut!"
        nb = draw.textbbox((0, 0), note, font=f_tiny)
        draw.text(((W - (nb[2] - nb[0])) // 2, H - 90), note, font=f_tiny, fill=(140, 140, 140))

        return (
            ImageClip(np.array(img))
            .with_duration(card_dur)
            .with_start(start_at)
            .with_effects([vfx.FadeIn(min(1.0, card_dur * 0.3))])
        )

    # ──────────────────────────────────────────────────────────────────────────
    # ARKA PLAN & YARDIMCI METODLAR
    # ──────────────────────────────────────────────────────────────────────────

    def _create_slideshow(self, image_paths: list, duration: float):
        """Pexels kliplerinden arka plan - rastgele başlangıç + sinematik grade."""
        from moviepy import vfx as mvfx
        clips = []
        n = len(image_paths)
        per_clip = duration / n

        for p in image_paths:
            ext = Path(p).suffix.lower()
            if ext == ".mp4":
                try:
                    vc = VideoFileClip(p).without_audio()
                    # Rastgele başlangıç (tekrarsız)
                    if vc.duration > per_clip + 2:
                        start_off = random.uniform(0, vc.duration - per_clip - 1)
                    else:
                        start_off = 0
                    if vc.duration < per_clip:
                        vc = vc.with_effects([mvfx.Loop(duration=per_clip)])
                    else:
                        vc = vc.subclipped(start_off, start_off + per_clip)
                    vc = vc.resized((self.width, self.height))
                    # Sinematik renk düzeltmesi
                    vc = vc.image_transform(self._cinematic_grade)
                    clips.append(vc)
                    continue
                except Exception as e:
                    logger.warning(f"Klip yüklenemedi: {e}")
            try:
                arr = np.array(self._fit_image(p))
                clips.append(
                    ImageClip(arr)
                    .with_duration(per_clip)
                    .resized((self.width, self.height))
                )
            except Exception as e:
                logger.warning(f"Görsel yüklenemedi: {e}")
                clips.append(self._create_gradient_background(per_clip))

        return concatenate_videoclips(clips) if clips else self._create_gradient_background(duration)

    def _cinematic_grade(self, frame: np.ndarray) -> np.ndarray:
        """Sinematik renk düzeltmesi: kontrast artır, hafif doygunluk azalt."""
        try:
            img = Image.fromarray(frame)
            img = ImageEnhance.Contrast(img).enhance(1.14)
            img = ImageEnhance.Color(img).enhance(0.87)
            img = ImageEnhance.Sharpness(img).enhance(1.08)
            return np.array(img)
        except Exception:
            return frame

    def _get_readability_strips(self, duration: float) -> list:
        """Üst ve alt koyu şeritler - Pexels klipleri için okunabilirlik."""
        top = (
            ColorClip(size=(self.width, 160), color=(0, 0, 0))
            .with_opacity(0.52)
            .with_duration(duration)
            .with_position((0, 0))
        )
        bot = (
            ColorClip(size=(self.width, 140), color=(0, 0, 0))
            .with_opacity(0.62)
            .with_duration(duration)
            .with_position((0, self.height - 140))
        )
        return [top, bot]

    def _create_gradient_background(self, duration: float) -> ImageClip:
        r, g, b = self.color_bg
        arr = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        for y in range(self.height):
            blend = y / self.height
            arr[y, :] = [
                int(r + blend * 20),
                int(g + blend * 15),
                int(b + blend * 35),
            ]
        return ImageClip(arr).with_duration(duration)

    def _fit_image(self, path: str) -> Image.Image:
        img = Image.open(path).convert("RGB")
        bg = img.resize((self.width, self.height), Image.LANCZOS).filter(ImageFilter.GaussianBlur(18))
        ratio = min(self.width / img.width, self.height / img.height)
        nw, nh = int(img.width * ratio), int(img.height * ratio)
        fg = img.resize((nw, nh), Image.LANCZOS)
        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 100))
        bg.paste(fg, ((self.width - nw) // 2, (self.height - nh) // 2))
        return Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")

    def _create_watermark_clip(self, duration: float):
        if not Path(self.watermark_path).exists():
            return None
        try:
            wm = Image.open(self.watermark_path).convert("RGBA")
            x = self.width - wm.width - 20
            y = self.height - wm.height - 20
            # Watermark'ı RGB + siyah arka planla birleştir
            base = Image.new("RGB", wm.size, (0, 0, 0))
            base.paste(wm, mask=wm.split()[3])
            return (
                ImageClip(np.array(base))
                .with_duration(duration)
                .with_opacity(0.55)
                .with_position((x, y))
            )
        except Exception as e:
            logger.warning(f"Watermark hatası: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # PROFESYONEL THUMBNAIL SİSTEMİ  (8 stil × sonsuz parametre kombinasyonu)
    # ══════════════════════════════════════════════════════════════════════════

    def create_thumbnail(self, title: str, image_path: str | None = None, output_path: str | None = None) -> str:
        if not output_path:
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"{self.videos_dir}/{ts}_thumbnail.jpg"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        W, H = 1280, 720
        rng = random.Random(hash(title))   # Tutarlı rastgelelik: aynı başlık = aynı görünüm

        bg = self._tn_load_bg(image_path, W, H, rng)
        bg = self._tn_grade(bg)
        bg = self._tn_vignette(bg, W, H)

        stat = self._tn_extract_stat(title)
        accent = self._tn_dominant_accent(bg, rng)   # Görselden renk al

        style = rng.randint(0, 7)
        styles = [
            self._tn_style_split_panel,
            self._tn_style_dramatic_full,
            self._tn_style_banner_top,
            self._tn_style_diagonal_cut,
            self._tn_style_center_box,
            self._tn_style_magazine,
            self._tn_style_frame_border,
            self._tn_style_stat_hero,
        ]
        result = styles[style](bg.copy(), title, stat, accent, W, H, rng)
        result.save(output_path, "JPEG", quality=97)
        logger.info(f"Thumbnail stil={style} ({W}×{H}): {output_path}")
        return output_path

    # ── Arka Plan İşleme ──────────────────────────────────────────────────────

    def _tn_load_bg(self, image_path, W, H, rng) -> Image.Image:
        if image_path and Path(image_path).exists():
            try:
                ext = Path(image_path).suffix.lower()
                if ext == ".mp4":
                    vc = VideoFileClip(image_path)
                    t = rng.uniform(vc.duration * 0.15, vc.duration * 0.75)
                    frame = vc.get_frame(t)
                    vc.close()
                    return Image.fromarray(frame).resize((W, H), Image.LANCZOS)
                else:
                    return Image.open(image_path).convert("RGB").resize((W, H), Image.LANCZOS)
            except Exception:
                pass
        return self._make_thumb_gradient(W, H)

    def _tn_grade(self, img: Image.Image) -> Image.Image:
        """Sinematik renk duzeltme: kontrast, netlik, hafif doygunluk."""
        img = ImageEnhance.Contrast(img).enhance(1.25)
        img = ImageEnhance.Sharpness(img).enhance(1.15)
        img = ImageEnhance.Color(img).enhance(1.10)
        img = ImageEnhance.Brightness(img).enhance(0.88)  # hafif karar - metin okunur
        return img

    def _tn_vignette(self, img: Image.Image, W: int, H: int) -> Image.Image:
        """Kenarları karartan profesyonel vignette."""
        arr = np.array(img).astype(np.float32)
        cx, cy = W / 2, H / 2
        Y, X = np.ogrid[:H, :W]
        dist = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
        vig = 1.0 - np.clip(dist * 0.72, 0, 0.78)
        arr *= vig[:, :, np.newaxis]
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    def _tn_dominant_accent(self, img: Image.Image, rng) -> tuple:
        """Görselden baskın renk çıkar; kanal primary ile karıştır."""
        try:
            small = img.resize((40, 22), Image.LANCZOS)
            pixels = list(small.getdata())
            # Ortalama al, çok koyu/açık pikselleri atla
            filtered = [p for p in pixels if 30 < p[0] < 220 and 30 < p[1] < 220 and 30 < p[2] < 220]
            if not filtered:
                return self.color_primary
            avg_r = int(sum(p[0] for p in filtered) / len(filtered))
            avg_g = int(sum(p[1] for p in filtered) / len(filtered))
            avg_b = int(sum(p[2] for p in filtered) / len(filtered))
            # Kanal rengiyle %60-%40 karıştır (kanal kimliğini koru)
            cr, cg, cb = self.color_primary
            return (
                int(cr * 0.6 + avg_r * 0.4),
                int(cg * 0.6 + avg_g * 0.4),
                int(cb * 0.6 + avg_b * 0.4),
            )
        except Exception:
            return self.color_primary

    # ── Profesyonel Metin Efektleri ───────────────────────────────────────────

    def _tn_text(self, draw, pos, text, font, fill=(255, 255, 255),
                 shadow_layers=4, shadow_offset=3, outline=True, outline_w=2):
        """Çok katmanlı gölge + outline ile profesyonel metin."""
        x, y = pos
        # Gölge katmanları (dıştan içe doğru)
        for i in range(shadow_layers, 0, -1):
            alpha = int(200 * (i / shadow_layers))
            off = shadow_offset * i // shadow_layers + 1
            draw.text((x + off, y + off), text, font=font, fill=(0, 0, 0))
        # Outline: 8 yönde çiz
        if outline:
            for ox, oy in [(-outline_w, 0), (outline_w, 0), (0, -outline_w), (0, outline_w),
                           (-outline_w, -outline_w), (outline_w, outline_w),
                           (-outline_w, outline_w), (outline_w, -outline_w)]:
                draw.text((x + ox, y + oy), text, font=font, fill=(0, 0, 0))
        draw.text((x, y), text, font=font, fill=fill)

    def _tn_text_centered(self, draw, cy, text, font, W, fill=(255, 255, 255), **kw):
        bb = draw.textbbox((0, 0), text, font=font)
        cx = (W - (bb[2] - bb[0])) // 2
        self._tn_text(draw, (cx, cy), text, font, fill, **kw)
        return bb[3] - bb[1]

    def _tn_pill_box(self, draw, x, y, w, h, color, alpha_val=180, radius=14):
        """Yuvarlatılmış köşeli yarı-saydam kutu."""
        r2 = min(radius, h // 2, w // 2)
        box = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        bd = ImageDraw.Draw(box)
        bd.rounded_rectangle([0, 0, w, h], radius=r2, fill=(*color, alpha_val))
        # Overlay compose
        try:
            tmp = Image.new("RGBA", draw._image.size, (0, 0, 0, 0))
            tmp.paste(box, (x, y))
            draw._image.paste(Image.alpha_composite(draw._image.convert("RGBA"), tmp).convert("RGB"))
        except Exception:
            pass  # Fallback: boyama olmadan devam

    def _tn_extract_stat(self, title: str) -> str | None:
        import re
        for pat in [r'%\d+', r'\d[\d.,]+\s*TL', r'\b([2-9]|[1-9]\d)\b']:
            m = re.search(pat, title)
            if m:
                return m.group(0)
        return None

    def _tn_accent_line(self, draw, x1, y1, x2, y2, color, w=5):
        draw.line([(x1, y1), (x2, y2)], fill=color, width=w)

    # ── STİL 0: SOL PANEL ─────────────────────────────────────────────────────
    def _tn_style_split_panel(self, bg, title, stat, accent, W, H, rng):
        r, g, b = self.color_bg
        ar, ag, ab = accent
        split = int(W * rng.uniform(0.38, 0.48))

        canvas = bg.copy()
        # Sol paneli kanalın arka plan rengiyle doldur
        panel = Image.new("RGBA", (split + 40, H), (r, g, b, 230))
        canvas.paste(Image.alpha_composite(canvas.crop((0, 0, split + 40, H)).convert("RGBA"), panel).convert("RGB"), (0, 0))

        draw = ImageDraw.Draw(canvas)
        # Dikey accent çizgisi
        draw.rectangle([split, 0, split + 5, H], fill=(ar, ag, ab))

        lines = textwrap.wrap(title, width=16)[:3]
        fs = 72 if len(lines) == 1 else (62 if len(lines) == 2 else 50)
        f = _load_font("bold", fs)
        y_t = max(30, (H - len(lines) * (fs + 12)) // 2)
        for ln in lines:
            self._tn_text(draw, (28, y_t), ln, f, fill=(255, 255, 255))
            y_t += fs + 14

        if stat:
            fs2 = 52
            f2 = _load_font("bold", fs2)
            box_y = H - 135
            bb = draw.textbbox((0, 0), stat, font=f2)
            bw = bb[2] - bb[0] + 24
            draw.rounded_rectangle([20, box_y, 20 + bw, box_y + fs2 + 18], radius=8, fill=(ar, ag, ab))
            draw.text((28, box_y + 6), stat, font=f2, fill=(0, 0, 0))

        f_ch = _load_font("bold", 28)
        self._tn_text(draw, (24, H - 72), self.channel_name, f_ch, fill=(ar, ag, ab), shadow_layers=2, outline=False)
        return canvas

    # ── STİL 1: DRAMATIK FULL BLEED ──────────────────────────────────────────
    def _tn_style_dramatic_full(self, bg, title, stat, accent, W, H, rng):
        ar, ag, ab = accent
        br, bg_, bb = self.color_bg

        canvas = bg.copy()
        # Alt gradient: metin okunabilirliği için
        grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        for y in range(H // 2, H):
            alpha = int(200 * ((y - H // 2) / (H // 2)))
            gd.line([(0, y), (W, y)], fill=(br, bg_, bb, alpha))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), grad).convert("RGB")

        draw = ImageDraw.Draw(canvas)
        lines = textwrap.wrap(title, width=26)[:2]
        fs = 88 if len(lines) == 1 else 70
        f = _load_font("bold", fs)
        y_t = H - len(lines) * (fs + 16) - 75
        for ln in lines:
            self._tn_text_centered(draw, y_t, ln, f, W)
            y_t += fs + 16

        # Üst accent şerit
        draw.rectangle([0, 0, W, 8], fill=(ar, ag, ab))
        # Alt kanal adı
        f_ch = _load_font("bold", 32)
        self._tn_text_centered(draw, H - 58, self.channel_name, f_ch, W, fill=(ar, ag, ab))

        if stat:
            f_s = _load_font("bold", 100)
            bb2 = draw.textbbox((0, 0), stat, font=f_s)
            sx = W - (bb2[2] - bb2[0]) - 30
            self._tn_text(draw, (sx, 20), stat, f_s, fill=(ar, ag, ab), shadow_layers=5, shadow_offset=4)
        return canvas

    # ── STİL 2: ÜST BANNER ───────────────────────────────────────────────────
    def _tn_style_banner_top(self, bg, title, stat, accent, W, H, rng):
        ar, ag, ab = accent
        br, bg_, bb = self.color_bg
        bh = int(H * rng.uniform(0.40, 0.52))

        canvas = bg.copy()
        band = Image.new("RGBA", (W, bh), (br, bg_, bb, 235))
        canvas.paste(Image.alpha_composite(canvas.crop((0, 0, W, bh)).convert("RGBA"), band).convert("RGB"), (0, 0))

        draw = ImageDraw.Draw(canvas)
        draw.rectangle([0, bh, W, bh + 6], fill=(ar, ag, ab))

        lines = textwrap.wrap(title, width=28)[:2]
        fs = 80 if len(lines) == 1 else 65
        f = _load_font("bold", fs)
        total_h = len(lines) * (fs + 12)
        y_t = max(12, (bh - total_h) // 2)
        for ln in lines:
            self._tn_text_centered(draw, y_t, ln, f, W)
            y_t += fs + 12

        # Alt stat / kanal adı
        f_ch = _load_font("bold", 34)
        self._tn_text_centered(draw, bh + 20, self.channel_name, f_ch, W, fill=(ar, ag, ab))
        if stat:
            f_s = _load_font("bold", 88)
            self._tn_text_centered(draw, bh + 68, stat, f_s, W, fill=(255, 255, 255))
        return canvas

    # ── STİL 3: DİYAGONAL KESİŞ ─────────────────────────────────────────────
    def _tn_style_diagonal_cut(self, bg, title, stat, accent, W, H, rng):
        ar, ag, ab = accent
        br, bg_, bb = self.color_bg
        cut_x = int(W * rng.uniform(0.45, 0.62))

        canvas = bg.copy()
        skew = int(H * rng.uniform(0.12, 0.22))
        poly = [(0, 0), (cut_x, 0), (cut_x - skew, H), (0, H)]
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.polygon(poly, fill=(br, bg_, bb, 215))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

        draw = ImageDraw.Draw(canvas)
        # Diagonal accent çizgisi
        draw.line([(cut_x, 0), (cut_x - skew, H)], fill=(ar, ag, ab), width=7)

        lines = textwrap.wrap(title, width=15)[:3]
        fs = 66 if len(lines) <= 2 else 54
        f = _load_font("bold", fs)
        y_t = 38
        for ln in lines:
            self._tn_text(draw, (28, y_t), ln, f)
            y_t += fs + 12

        f_ch = _load_font("bold", 30)
        self._tn_text(draw, (28, H - 68), self.channel_name, f_ch, fill=(ar, ag, ab), shadow_layers=2, outline=False)

        if stat:
            f_s = _load_font("bold", 98)
            sb = draw.textbbox((0, 0), stat, font=f_s)
            sx = W - (sb[2] - sb[0]) - 32
            self._tn_text(draw, (sx, 22), stat, f_s, fill=(ar, ag, ab), shadow_layers=5, shadow_offset=4)
        return canvas

    # ── STİL 4: MERKEZ KUTU ──────────────────────────────────────────────────
    def _tn_style_center_box(self, bg, title, stat, accent, W, H, rng):
        ar, ag, ab = accent
        br, bg_, bb = self.color_bg

        canvas = bg.copy()
        lines = textwrap.wrap(title, width=22)[:3]
        fs = 72 if len(lines) == 1 else (58 if len(lines) == 2 else 48)
        f = _load_font("bold", fs)
        f_ch = _load_font("bold", 30)

        line_h = fs + 14
        box_h = len(lines) * line_h + 50 + (60 if stat else 0) + 54
        box_w = int(W * rng.uniform(0.72, 0.88))
        bx = (W - box_w) // 2
        by = (H - box_h) // 2

        # Kutu arka planı (RGBA)
        box_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bld = ImageDraw.Draw(box_layer)
        bld.rounded_rectangle([bx, by, bx + box_w, by + box_h], radius=20,
                               fill=(br, bg_, bb, 215), outline=(ar, ag, ab), width=4)
        canvas = Image.alpha_composite(canvas.convert("RGBA"), box_layer).convert("RGB")

        draw = ImageDraw.Draw(canvas)
        y_t = by + 22
        for ln in lines:
            self._tn_text_centered(draw, y_t, ln, f, W, outline_w=2)
            y_t += line_h

        if stat:
            f_s = _load_font("bold", 56)
            sb = draw.textbbox((0, 0), stat, font=f_s)
            sw = sb[2] - sb[0]
            sr_x = (W - sw) // 2
            draw.rounded_rectangle([sr_x - 12, y_t + 4, sr_x + sw + 12, y_t + 68], radius=10, fill=(ar, ag, ab))
            draw.text((sr_x, y_t + 6), stat, font=f_s, fill=(0, 0, 0))
            y_t += 72

        self._tn_text_centered(draw, y_t + 6, self.channel_name, f_ch, W, fill=(ar, ag, ab), shadow_layers=2, outline=False)
        return canvas

    # ── STİL 5: MAGAZİN ──────────────────────────────────────────────────────
    def _tn_style_magazine(self, bg, title, stat, accent, W, H, rng):
        ar, ag, ab = accent
        br, bg_, bb = self.color_bg

        canvas = bg.copy()
        # Üst ve alt renk bantları
        top_h = int(H * 0.18)
        bot_h = int(H * 0.22)
        top_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        tld = ImageDraw.Draw(top_layer)
        tld.rectangle([0, 0, W, top_h], fill=(ar, ag, ab, 245))
        tld.rectangle([0, H - bot_h, W, H], fill=(br, bg_, bb, 230))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), top_layer).convert("RGB")

        draw = ImageDraw.Draw(canvas)
        # Üst band: kanal adı + slogan
        f_brand = _load_font("bold", 38)
        f_slogan = _load_font("regular", 22)
        self._tn_text_centered(draw, (top_h - 42) // 2, self.channel_name, f_brand, W, fill=(0, 0, 0), shadow_layers=0, outline=False)

        # Orta: büyük başlık
        lines = textwrap.wrap(title, width=24)[:2]
        fs = 76 if len(lines) == 1 else 62
        f = _load_font("bold", fs)
        y_t = top_h + 18
        for ln in lines:
            self._tn_text_centered(draw, y_t, ln, f, W)
            y_t += fs + 14

        # Alt band: stat veya subtitle
        if stat:
            f_s = _load_font("bold", 52)
            self._tn_text_centered(draw, H - bot_h + 14, stat, f_s, W, fill=(ar, ag, ab))
        draw.rectangle([0, H - bot_h, W, H - bot_h + 4], fill=(ar, ag, ab))
        return canvas

    # ── STİL 6: ÇERÇEVE KENARI ───────────────────────────────────────────────
    def _tn_style_frame_border(self, bg, title, stat, accent, W, H, rng):
        ar, ag, ab = accent
        br, bg_, bb = self.color_bg
        border = rng.randint(14, 24)
        inner_darken = rng.uniform(0.45, 0.68)

        # Görsel hafif karartılmış iç
        canvas = bg.copy()
        dark = Image.new("RGBA", (W, H), (0, 0, 0, int(inner_darken * 255)))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), dark).convert("RGB")

        draw = ImageDraw.Draw(canvas)
        # Dış çerçeve
        draw.rectangle([0, 0, W - 1, H - 1], outline=(ar, ag, ab), width=border)
        # İç çerçeve (ince)
        inner_off = border + 6
        draw.rectangle([inner_off, inner_off, W - inner_off, H - inner_off], outline=(255, 255, 255), width=2)

        lines = textwrap.wrap(title, width=22)[:3]
        fs = 74 if len(lines) == 1 else (60 if len(lines) == 2 else 50)
        f = _load_font("bold", fs)
        total_h = len(lines) * (fs + 12)
        y_t = (H - total_h) // 2 - (30 if stat else 0)
        for ln in lines:
            self._tn_text_centered(draw, y_t, ln, f, W)
            y_t += fs + 12

        if stat:
            f_s = _load_font("bold", 60)
            self._tn_text_centered(draw, y_t + 12, stat, f_s, W, fill=(ar, ag, ab))

        f_ch = _load_font("bold", 28)
        self._tn_text_centered(draw, H - border - 52, self.channel_name, f_ch, W,
                               fill=(ar, ag, ab), shadow_layers=2, outline=False)
        return canvas

    # ── STİL 7: İSTATİSTİK KAHRAMAN ──────────────────────────────────────────
    def _tn_style_stat_hero(self, bg, title, stat, accent, W, H, rng):
        ar, ag, ab = accent
        br, bg_, bb = self.color_bg

        canvas = bg.copy()
        draw = ImageDraw.Draw(canvas)

        if stat:
            # Dev istatistik — sağ yarıda
            f_huge = _load_font("bold", 190)
            sb = draw.textbbox((0, 0), stat, font=f_huge)
            sh = sb[3] - sb[1]
            sw = sb[2] - sb[0]
            sx = W - sw - 22
            sy = (H - sh) // 2 - 20
            # Gölge efekti
            for off in range(8, 0, -1):
                draw.text((sx + off, sy + off), stat, font=f_huge, fill=(0, 0, 0))
            draw.text((sx, sy), stat, font=f_huge, fill=(ar, ag, ab))
            # İnce outline
            for ox, oy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
                draw.text((sx + ox, sy + oy), stat, font=f_huge, fill=(255, 255, 255))

            # Sol yarı: başlık
            left_w = sx - 30
            lines = textwrap.wrap(title, width=max(12, left_w // 38))[:3]
            fs = 58 if len(lines) <= 2 else 46
            f = _load_font("bold", fs)
            y_t = max(28, (H - len(lines) * (fs + 12) - 50) // 2)
            for ln in lines:
                self._tn_text(draw, (22, y_t), ln, f, shadow_layers=4)
                y_t += fs + 12

            # Dikey ayırıcı
            draw.line([(sx - 20, 30), (sx - 20, H - 30)], fill=(ar, ag, ab), width=4)
        else:
            # Stat yoksa — tam ekran büyük başlık
            lines = textwrap.wrap(title, width=22)[:3]
            fs = 82 if len(lines) == 1 else (66 if len(lines) == 2 else 54)
            f = _load_font("bold", fs)
            y_t = (H - len(lines) * (fs + 14)) // 2
            for ln in lines:
                self._tn_text_centered(draw, y_t, ln, f, W, shadow_layers=5)
                y_t += fs + 14

        draw.rectangle([0, 0, W, 7], fill=(ar, ag, ab))
        draw.rectangle([0, H - 7, W, H], fill=(ar, ag, ab))
        f_ch = _load_font("bold", 28)
        self._tn_text(draw, (22, H - 58), self.channel_name, f_ch, fill=(ar, ag, ab),
                      shadow_layers=2, outline=False)
        return canvas

    def _make_thumb_gradient(self, w: int, h: int) -> Image.Image:

        W, H = 1280, 720

        # Arkaplan görüntüsünü al (video ise rastgele frame)
        base_img = self._thumb_get_base(image_path, W, H)

        # Başlıktaki sayıyı bul (ör: %47, 25.000 TL, 3 Grafik)
        key_stat = self._thumb_extract_stat(title)

        # Şablonu belirle: başlığın hash'ine göre → her video farklı ama tutarlı
        style = hash(title) % 4
        if style == 0:
            result = self._thumb_style_bold_split(base_img, title, key_stat, W, H)
        elif style == 1:
            result = self._thumb_style_top_banner(base_img, title, key_stat, W, H)
        elif style == 2:
            result = self._thumb_style_diagonal(base_img, title, key_stat, W, H)
        else:
            result = self._thumb_style_stat_focus(base_img, title, key_stat, W, H)

        result.save(output_path, "JPEG", quality=97)
        logger.info(f"Thumbnail (style={style}): {output_path}")
        return output_path

    def _thumb_get_base(self, image_path, W, H) -> Image.Image:
        """Arkaplan görseli: video ise rastgele frame al."""
        if image_path and Path(image_path).exists():
            try:
                ext = Path(image_path).suffix.lower()
                if ext == ".mp4":
                    vc = VideoFileClip(image_path)
                    # Rastgele timestamp — her video farklı görünür
                    t = random.uniform(vc.duration * 0.15, vc.duration * 0.75)
                    frame = vc.get_frame(t)
                    vc.close()
                    return Image.fromarray(frame).resize((W, H), Image.LANCZOS)
                else:
                    return Image.open(image_path).convert("RGB").resize((W, H), Image.LANCZOS)
            except Exception:
                pass
        return self._make_thumb_gradient(W, H)

    def _thumb_extract_stat(self, title: str) -> str | None:
        """Başlıktan öne çıkarılabilecek sayı/istatistik bul."""
        import re
        # %47, %3, vs.
        m = re.search(r'%\d+', title)
        if m:
            return m.group(0)
        # 25.000 TL gibi
        m = re.search(r'\d[\d.]+\s*TL', title)
        if m:
            return m.group(0)
        # "3 Hata", "5 Yol" gibi küçük sayılar
        m = re.search(r'\b([2-9]|1[0-9])\b', title)
        if m:
            return m.group(0)
        return None

    # ── Stil 0: SOL PANEL (düz renk sol 42%, sağda görsel) ────────────────────
    def _thumb_style_bold_split(self, base: Image.Image, title: str, stat: str | None, W: int, H: int) -> Image.Image:
        r, g, b = self.color_primary
        br, bg_, bb = self.color_bg

        canvas = Image.new("RGB", (W, H))
        # Sol panel — kanalın arka plan rengi
        for y in range(H):
            blend = y / H
            pr = max(0, int(br * (1 - blend * 0.35)))
            pg = max(0, int(bg_ * (1 - blend * 0.35)))
            pb = max(0, int(bb * (1 - blend * 0.35)))
            for x in range(int(W * 0.44)):
                canvas.putpixel((x, y), (pr, pg, pb))
        # Sağ panel — orijinal görsel
        right = base.crop((int(W * 0.44), 0, W, H))
        canvas.paste(right, (int(W * 0.44), 0))
        # Geçiş: üst üste örtüşen hafif fade
        fade_w = 80
        for x in range(int(W * 0.44), int(W * 0.44) + fade_w):
            for y in range(H):
                alpha = (x - int(W * 0.44)) / fade_w
                orig = canvas.getpixel((x, y))
                overlay_c = (int(br * (1 - alpha)), int(bg_ * (1 - alpha)), int(bb * (1 - alpha)))
                canvas.putpixel((x, y), tuple(int(o * alpha + v * (1 - alpha)) for o, v in zip(orig, overlay_c)))

        draw = ImageDraw.Draw(canvas)
        # Sol üst renkli çizgi
        draw.rectangle([0, 0, int(W * 0.44), 6], fill=(r, g, b))

        # Başlık metni — sol panelde
        max_w = 22
        lines = textwrap.wrap(title, width=max_w)[:3]
        f_big = _load_font("bold", 76 if len(lines) <= 2 else 62)
        y_t = 55
        for line in lines:
            draw.text((36, y_t + 3), line, font=f_big, fill=(0, 0, 0))
            draw.text((34, y_t), line, font=f_big, fill=(255, 255, 255))
            y_t += 86 if len(lines) <= 2 else 70

        # İstatistik kutusu (varsa)
        if stat:
            f_stat = _load_font("bold", 52)
            sw = draw.textbbox((0, 0), stat, font=f_stat)[2]
            sx, sy = 34, H - 155
            draw.rectangle([sx - 8, sy - 8, sx + sw + 16, sy + 62], fill=(r, g, b))
            draw.text((sx, sy), stat, font=f_stat, fill=(0, 0, 0))

        # Kanal adı alt
        f_ch = _load_font("bold", 30)
        draw.text((36, H - 78), self.channel_name, font=f_ch, fill=(r, g, b))
        # Sağ alt köşede yıl
        f_yr = _load_font("regular", 24)
        draw.text((W - 90, H - 42), "2026", font=f_yr, fill=(200, 200, 200))
        return canvas

    # ── Stil 1: ÜST BANNER (renk şerit üstte, altı görsel) ───────────────────
    def _thumb_style_top_banner(self, base: Image.Image, title: str, stat: str | None, W: int, H: int) -> Image.Image:
        r, g, b = self.color_primary
        br, bg_, bb = self.color_bg
        banner_h = int(H * 0.46)

        # Koyu overlay ile arkaplan
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 160))
        canvas = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

        # Üst solid renk bandı (gradient)
        for y in range(banner_h):
            blend = y / banner_h
            pr = int(br + blend * (r - br) * 0.6)
            pg = int(bg_ + blend * (g - bg_) * 0.6)
            pb = int(bb + blend * (b - bb) * 0.6)
            for x in range(W):
                canvas.putpixel((x, y), (max(0, min(255, pr)), max(0, min(255, pg)), max(0, min(255, pb))))

        draw = ImageDraw.Draw(canvas)
        # Ayırıcı çizgi
        draw.rectangle([0, banner_h, W, banner_h + 5], fill=(r, g, b))

        # Başlık — banner içinde ortalı veya sola hizalı
        lines = textwrap.wrap(title, width=26)[:2]
        f_big = _load_font("bold", 82 if len(lines) == 1 else 66)
        y_t = (banner_h - len(lines) * 88) // 2
        for line in lines:
            bb2 = draw.textbbox((0, 0), line, font=f_big)
            cx = (W - (bb2[2] - bb2[0])) // 2
            draw.text((cx + 3, y_t + 3), line, font=f_big, fill=(0, 0, 0))
            draw.text((cx, y_t), line, font=f_big, fill=(255, 255, 255))
            y_t += 90

        # Alt kısım: kanal adı ve stat
        f_ch = _load_font("bold", 34)
        ch_bb = draw.textbbox((0, 0), self.channel_name, font=f_ch)
        cx_ch = (W - (ch_bb[2] - ch_bb[0])) // 2
        draw.text((cx_ch, banner_h + 25), self.channel_name, font=f_ch, fill=(r, g, b))

        if stat:
            f_stat = _load_font("bold", 80)
            sb = draw.textbbox((0, 0), stat, font=f_stat)
            cx_s = (W - (sb[2] - sb[0])) // 2
            draw.text((cx_s + 3, banner_h + 75), stat, font=f_stat, fill=(0, 0, 0))
            draw.text((cx_s, banner_h + 72), stat, font=f_stat, fill=(r, g, b))
        return canvas

    # ── Stil 2: DİYAGONAL (köşegen renk kesiş) ───────────────────────────────
    def _thumb_style_diagonal(self, base: Image.Image, title: str, stat: str | None, W: int, H: int) -> Image.Image:
        r, g, b = self.color_primary
        br, bg_, bb = self.color_bg

        # Arkaplan — görsel + ağır overlay
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 130))
        canvas = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(canvas)

        # Sol üst köşeden diagonal renk bloğu (polygon)
        poly = [(0, 0), (int(W * 0.62), 0), (int(W * 0.40), H), (0, H)]
        draw.polygon(poly, fill=(br, bg_, bb, 220))

        # Diagonal kenar vurgu çizgisi
        draw.line([(int(W * 0.62), 0), (int(W * 0.40), H)], fill=(r, g, b), width=6)

        # Başlık (diyagonal blok içinde)
        lines = textwrap.wrap(title, width=18)[:3]
        f_big = _load_font("bold", 72 if len(lines) <= 2 else 58)
        y_t = 50
        for line in lines:
            draw.text((34, y_t + 3), line, font=f_big, fill=(0, 0, 0))
            draw.text((32, y_t), line, font=f_big, fill=(255, 255, 255))
            y_t += 82 if len(lines) <= 2 else 66

        # Kanal adı
        f_ch = _load_font("bold", 32)
        draw.text((34, H - 80), self.channel_name, font=f_ch, fill=(r, g, b))

        # Stat sağ üste
        if stat:
            f_stat = _load_font("bold", 90)
            sb = draw.textbbox((0, 0), stat, font=f_stat)
            sx = W - (sb[2] - sb[0]) - 40
            draw.text((sx + 4, 30 + 4), stat, font=f_stat, fill=(0, 0, 0))
            draw.text((sx, 30), stat, font=f_stat, fill=(r, g, b))
        return canvas

    # ── Stil 3: STAT ODAKLI (büyük sayı sağda, başlık solda) ─────────────────
    def _thumb_style_stat_focus(self, base: Image.Image, title: str, stat: str | None, W: int, H: int) -> Image.Image:
        r, g, b = self.color_primary
        br, bg_, bb = self.color_bg

        overlay = Image.new("RGBA", (W, H), (br, bg_, bb, 200))
        canvas = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(canvas)

        # Üst ve alt kanal rengi şeritleri
        draw.rectangle([0, 0, W, 7], fill=(r, g, b))
        draw.rectangle([0, H - 7, W, H], fill=(r, g, b))

        if stat:
            # Büyük stat sağda
            f_stat = _load_font("bold", 160)
            sb = draw.textbbox((0, 0), stat, font=f_stat)
            stat_w = sb[2] - sb[0]
            sx = W - stat_w - 30
            sy = (H - (sb[3] - sb[1])) // 2 - 20
            draw.text((sx + 5, sy + 5), stat, font=f_stat, fill=(0, 0, 0))
            draw.text((sx, sy), stat, font=f_stat, fill=(r, g, b))

            # Başlık sol taraf (dar alana göre wrap)
            lines = textwrap.wrap(title, width=16)[:4]
            f_t = _load_font("bold", 58)
            y_t = 60
            for line in lines:
                draw.text((34, y_t + 3), line, font=f_t, fill=(0, 0, 0))
                draw.text((32, y_t), line, font=f_t, fill=(255, 255, 255))
                y_t += 68
        else:
            # Stat yok → büyük ortalı başlık
            lines = textwrap.wrap(title, width=24)[:3]
            f_big = _load_font("bold", 80 if len(lines) <= 2 else 64)
            y_t = (H - len(lines) * 92) // 2
            for line in lines:
                bb2 = draw.textbbox((0, 0), line, font=f_big)
                cx = (W - (bb2[2] - bb2[0])) // 2
                draw.text((cx + 3, y_t + 3), line, font=f_big, fill=(0, 0, 0))
                draw.text((cx, y_t), line, font=f_big, fill=(255, 255, 255))
                y_t += 92

        # Kanal adı alt orta
        f_ch = _load_font("bold", 30)
        ch_bb = draw.textbbox((0, 0), self.channel_name, font=f_ch)
        cx_ch = (W - (ch_bb[2] - ch_bb[0])) // 2
        draw.text((cx_ch, H - 75), self.channel_name, font=f_ch, fill=(r, g, b))
        return canvas

    def _make_thumb_gradient(self, w: int, h: int) -> Image.Image:
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        r, g, b = self.color_bg
        for y in range(h):
            blend = y / h
            arr[y, :] = [int(r + blend * 25), int(g + blend * 20), int(b + blend * 40)]
        return Image.fromarray(arr)
