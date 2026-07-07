"""Girisim Okulu - Kanal Gorselleri"""
import os, sys, math
sys.path.insert(0, ".")
import numpy as np
from PIL import Image, ImageDraw, ImageFont

os.makedirs("channels/girisim_okulu/branding", exist_ok=True)

BG = (40, 10, 10)
PRIMARY = (255, 80, 80)  # Kirmizi
WHITE = (255, 255, 255)

def font(size):
    for f in ["/System/Library/Fonts/Helvetica.ttc"]:
        if os.path.exists(f):
            try: return ImageFont.truetype(f, size)
            except: pass
    return ImageFont.load_default()

def gradient(w, h, top, bot):
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        t = y / h
        arr[y, :] = [int(top[i] + (bot[i] - top[i]) * t) for i in range(3)]
    return Image.fromarray(arr)

# ── LOGO 800x800 ──────────────────────────────────────────────
W, H = 800, 800
img = gradient(W, H, BG, (20, 5, 5))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle([(25,25),(775,775)], radius=70, outline=PRIMARY, width=7)

# Roket/Startup simgesi - yon oku + yildiz
cx, cy = 400, 270
# Yukari ok (roket)
arrow_pts = [(cx, cy-120), (cx-50, cy+40), (cx-20, cy+20), (cx-20, cy+80),
             (cx+20, cy+80), (cx+20, cy+20), (cx+50, cy+40)]
draw.polygon(arrow_pts, fill=PRIMARY)
# Alev
flame_pts = [(cx-20, cy+80), (cx, cy+130), (cx+20, cy+80)]
draw.polygon(flame_pts, fill=(255, 150, 0))
# Yildizlar
for sx, sy, sr in [(cx-90, cy-60, 8), (cx+100, cy-30, 6), (cx-70, cy+30, 5)]:
    draw.ellipse([(sx-sr,sy-sr),(sx+sr,sy+sr)], fill=WHITE)

for text, y, size, color in [
    ("Girisim", 450, 72, PRIMARY),
    ("Okulu", 528, 72, WHITE),
    ("Kendi Isinin Patronu Ol!", 613, 30, (255, 160, 160)),
]:
    f = font(size)
    bb = draw.textbbox((0,0), text, font=f)
    x = (W-(bb[2]-bb[0]))//2
    draw.text((x+2,y+2), text, font=f, fill=(0,0,0))
    draw.text((x,y), text, font=f, fill=color)

draw.line([(120,667),(W-120,667)], fill=PRIMARY, width=2)
img.save("channels/girisim_okulu/branding/logo_800x800.png", "PNG")
print("Logo hazir")

# ── WATERMARK 150x150 ──────────────────────────────────────────
wm = Image.new("RGBA", (150,150), (0,0,0,0))
wd = ImageDraw.Draw(wm)
wd.ellipse([(5,5),(145,145)], fill=BG+(200,))
wd.ellipse([(5,5),(145,145)], outline=PRIMARY+(255,), width=3)
# Mini roket
wd.polygon([(75,25),(65,60),(72,52),(72,80),(78,80),(78,52),(85,60)], fill=PRIMARY+(255,))
wd.polygon([(70,80),(75,95),(80,80)], fill=(255,150,0,255))
for text, y in [("Girisim", 88), ("Okulu", 106)]:
    f = font(13)
    bb = wd.textbbox((0,0), text, font=f)
    wd.text(((150-(bb[2]-bb[0]))//2, y), text, font=f, fill=PRIMARY+(255,))
wm.save("channels/girisim_okulu/branding/watermark_150x150.png", "PNG")
print("Watermark hazir")

# ── BANNER 2560x1440 ───────────────────────────────────────────
BW, BH = 2560, 1440
banner = gradient(BW, BH, (30, 8, 8), (15, 4, 4))
bd = ImageDraw.Draw(banner)

# Dekoratif yildizlar
import random
random.seed(42)
for _ in range(80):
    sx = random.randint(0, BW)
    sy = random.randint(0, BH//2)
    sr = random.randint(1, 4)
    alpha = random.randint(80, 200)
    bd.ellipse([(sx-sr,sy-sr),(sx+sr,sy+sr)], fill=(255,255,255))

for text, y, size, color in [
    ("Girisim Okulu", BH//2-140, 160, PRIMARY),
    ("Kendi Isinin Patronu Ol! | Startup • E-Ticaret • Pasif Gelir", BH//2+50, 62, WHITE),
    ("Her Gun 12:00 ve 00:00 | Girisimcilik • Pazarlama • Freelance", BH//2+140, 48, (255,160,160)),
]:
    f = font(size)
    bb = bd.textbbox((0,0), text, font=f)
    x = (BW-(bb[2]-bb[0]))//2
    bd.text((x+3,y+3), text, font=f, fill=(0,0,0))
    bd.text((x,y), text, font=f, fill=color)

bd.line([(200,BH-120),(BW-200,BH-120)], fill=PRIMARY, width=3)
footer = "#Girisim #Startup #Eticaret #PasifGelir #GirisimOkulu #Freelance #Pazarlama"
f_sm = font(44)
bb = bd.textbbox((0,0), footer, font=f_sm)
bd.text(((BW-(bb[2]-bb[0]))//2, BH-100), footer, font=f_sm, fill=(200,100,100))
banner.save("channels/girisim_okulu/branding/youtube_banner_2560x1440.png", "PNG")

print("TAMAMLANDI - Girisim Okulu gorselleri hazir")
