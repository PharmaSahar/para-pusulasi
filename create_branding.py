"""
Para Pusulasi - Kanal Gorsel Uretici
Logo (800x800) ve YouTube Banner (2560x1440) olusturur.
"""
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = "assets/branding"
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

# Renk paleti
NAVY = (15, 25, 60)
GOLD = (212, 175, 55)
WHITE = (255, 255, 255)
LIGHT_GOLD = (255, 215, 80)
DARK_OVERLAY = (0, 0, 30, 200)


def get_font(size: int, bold: bool = False):
    fonts = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for f in fonts:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                pass
    return ImageFont.load_default()


def draw_compass(draw: ImageDraw, cx: int, cy: int, r: int, color=GOLD):
    """Minimalist pusula simgesi ciz."""
    # Dis cember
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=color, width=max(2, r // 20))

    # Ic cember
    ri = r // 3
    draw.ellipse([(cx - ri, cy - ri), (cx + ri, cy + ri)], fill=color)

    # Kuzey ok (beyaz)
    tip_n = (cx, cy - r + r // 8)
    base_l = (cx - r // 8, cy)
    base_r = (cx + r // 8, cy)
    draw.polygon([tip_n, base_l, base_r], fill=WHITE)

    # Guney ok (altin)
    tip_s = (cx, cy + r - r // 8)
    draw.polygon([tip_s, base_l, base_r], fill=color)

    # Kardinal yonler
    tick = r // 10
    for angle_deg, label in [(0, "K"), (90, "D"), (180, "G"), (270, "B")]:
        angle = math.radians(angle_deg - 90)
        ox = int(cx + (r - tick * 2) * math.cos(angle))
        oy = int(cy + (r - tick * 2) * math.sin(angle))
        ex = int(cx + (r - 4) * math.cos(angle))
        ey = int(cy + (r - 4) * math.sin(angle))
        draw.line([(ox, oy), (ex, ey)], fill=color, width=max(1, r // 25))


def make_gradient(w: int, h: int, top=NAVY, bottom=(5, 10, 40)) -> Image.Image:
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        t = y / h
        arr[y, :] = [
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
        ]
    return Image.fromarray(arr)


# ─────────────────────────────────────────────────────────
# LOGO 800x800
# ─────────────────────────────────────────────────────────
def create_logo(path: str = f"{OUTPUT_DIR}/logo_800x800.png"):
    W, H = 800, 800
    img = make_gradient(W, H)
    draw = ImageDraw.Draw(img)

    # Altin cerceve
    margin = 30
    draw.rounded_rectangle(
        [(margin, margin), (W - margin, H - margin)],
        radius=60,
        outline=GOLD,
        width=6,
    )

    # Pusula
    draw_compass(draw, W // 2, 310, 170)

    # Kanal adi
    font_title = get_font(72)
    font_sub = get_font(34)

    title = "Para Pusulasi"
    bb = draw.textbbox((0, 0), title, font=font_title)
    tx = (W - (bb[2] - bb[0])) // 2
    draw.text((tx + 2, 522), title, font=font_title, fill=(0, 0, 0))
    draw.text((tx, 520), title, font=font_title, fill=GOLD)

    sub = "Paranizi Calistirin!"
    bb2 = draw.textbbox((0, 0), sub, font=font_sub)
    sx = (W - (bb2[2] - bb2[0])) // 2
    draw.text((sx, 610), sub, font=font_sub, fill=WHITE)

    # Alt cizgi
    draw.line([(120, 670), (W - 120, 670)], fill=GOLD, width=2)

    img.save(path, "PNG")
    print(f"Logo kaydedildi: {path}")
    return path


# ─────────────────────────────────────────────────────────
# YOUTUBE BANNER 2560x1440
# ─────────────────────────────────────────────────────────
def create_banner(path: str = f"{OUTPUT_DIR}/youtube_banner_2560x1440.png"):
    W, H = 2560, 1440
    img = make_gradient(W, H, top=(10, 20, 55), bottom=(5, 10, 35))
    draw = ImageDraw.Draw(img)

    # Sol pusula (buyuk)
    draw_compass(draw, 420, H // 2, 280, color=GOLD)

    # Kanal adi (ortada buyuk)
    font_big = get_font(160)
    font_med = get_font(70)
    font_small = get_font(50)

    title = "Para Pusulasi"
    bb = draw.textbbox((0, 0), title, font=font_big)
    tx = (W - (bb[2] - bb[0])) // 2
    # Golgeli
    draw.text((tx + 4, H // 2 - 160 + 4), title, font=font_big, fill=(0, 0, 0))
    draw.text((tx, H // 2 - 160), title, font=font_big, fill=GOLD)

    # Slogan
    slogan = "Paranizi Calistirin | Finansal Ozgurluge Giden Yolunuz"
    bb2 = draw.textbbox((0, 0), slogan, font=font_med)
    sx = (W - (bb2[2] - bb2[0])) // 2
    draw.text((sx, H // 2 + 30), slogan, font=font_med, fill=WHITE)

    # Yayin programi
    schedule = "Her Gun Sabah 10:00 ve Aksam 20:00"
    bb3 = draw.textbbox((0, 0), schedule, font=font_small)
    scx = (W - (bb3[2] - bb3[0])) // 2
    draw.text((scx, H // 2 + 130), schedule, font=font_small, fill=LIGHT_GOLD)

    # Alt cizgi
    draw.line([(200, H - 120), (W - 200, H - 120)], fill=GOLD, width=3)

    # Alt bilgi
    info = "#KisiselFinans  #Borsa  #Yatirim  #ParaPusulasi"
    bb4 = draw.textbbox((0, 0), info, font=font_small)
    ix = (W - (bb4[2] - bb4[0])) // 2
    draw.text((ix, H - 100), info, font=font_small, fill=(180, 180, 180))

    img.save(path, "PNG", optimize=True)
    print(f"Banner kaydedildi: {path}")
    return path


# ─────────────────────────────────────────────────────────
# KANAL ACIKLAMASI
# ─────────────────────────────────────────────────────────
CHANNEL_ABOUT = """Turkiye'nin en pratik kisisel finans kanali: Para Pusulasi 🧭

Her gun 2 yeni video ile:
✅ Borsa ve yatirim rehberleri
✅ Guncel ekonomi analizleri (BIST, doviz, faiz)
✅ Birikim ve tasarruf stratejileri
✅ Herkesin anlayabilecegi finans egitimi
✅ Gercek rakamlar, gercek hesaplamalar

📌 Abone olun, para konusunda bir adim onde olun!
🔔 Bildirimleri acin, hicbir videoyu kacirmayin!

Yayın Programi: Her gun sabah 10:00 ve aksam 20:00

#KisiselFinans #Borsa #Yatirim #ParaPusulasi #FinansEgitimi #BIST #Kripto #Tasarruf #Birikim #FinansalOzgurluk
"""


def print_channel_about():
    print("\n" + "="*60)
    print("KANAL ACIKLAMASI (YouTube Studio > About'a yapistirin):")
    print("="*60)
    print(CHANNEL_ABOUT)
    print("="*60)


if __name__ == "__main__":
    print("Para Pusulasi kanal gorselleri olusturuluyor...")
    logo_path = create_logo()
    banner_path = create_banner()
    print_channel_about()
    print(f"\nDosyalar:")
    print(f"  Logo:   {logo_path}")
    print(f"  Banner: {banner_path}")
    print("\nYouTube Studio > Customization > Branding'e yukleyin.")
