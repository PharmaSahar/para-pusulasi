"""Kariyer Pusulasi - Kanal Gorselleri"""
import os, sys
sys.path.insert(0, ".")
import numpy as np
from PIL import Image, ImageDraw, ImageFont

os.makedirs("channels/kariyer_pusulasi/branding", exist_ok=True)

BG = (10, 20, 50)
PRIMARY = (65, 145, 255)  # Mavi
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
img = gradient(W, H, BG, (5, 10, 35))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle([(25,25),(775,775)], radius=70, outline=PRIMARY, width=7)

# Pusula çizimi
cx, cy, r = 400, 280, 130
draw.ellipse([(cx-r,cy-r),(cx+r,cy+r)], outline=PRIMARY, width=8)
ri = r // 3
draw.ellipse([(cx-ri,cy-ri),(cx+ri,cy+ri)], fill=PRIMARY)
# Kuzey ok (beyaz)
draw.polygon([(cx, cy-r+8), (cx-12, cy), (cx+12, cy)], fill=WHITE)
# Güney ok (mavi)
draw.polygon([(cx, cy+r-8), (cx-12, cy), (cx+12, cy)], fill=PRIMARY)
# Pusula çerçevesi
for angle, label in [(0,"K"),(90,"D"),(180,"G"),(270,"B")]:
    import math
    rad = math.radians(angle - 90)
    tx = int(cx + (r+20) * math.cos(rad))
    ty = int(cy + (r+20) * math.sin(rad))
    f_sm = font(22)
    bb = draw.textbbox((0,0), label, font=f_sm)
    draw.text((tx-(bb[2]-bb[0])//2, ty-(bb[3]-bb[1])//2), label, font=f_sm, fill=PRIMARY)

for text, y, size, color in [
    ("Kariyer", 445, 70, PRIMARY),
    ("Pusulasi", 522, 70, WHITE),
    ("Kariyerinde Bir Adim One Gec!", 608, 30, (180,200,255)),
]:
    f = font(size)
    bb = draw.textbbox((0,0), text, font=f)
    x = (W-(bb[2]-bb[0]))//2
    draw.text((x+2,y+2), text, font=f, fill=(0,0,0))
    draw.text((x,y), text, font=f, fill=color)

draw.line([(120,665),(W-120,665)], fill=PRIMARY, width=2)
img.save("channels/kariyer_pusulasi/branding/logo_800x800.png", "PNG")

# ── WATERMARK 150x150 ──────────────────────────────────────────
wm = Image.new("RGBA", (150,150), (0,0,0,0))
wd = ImageDraw.Draw(wm)
wd.ellipse([(5,5),(145,145)], fill=BG+(200,))
wd.ellipse([(5,5),(145,145)], outline=PRIMARY+(255,), width=3)
wd.ellipse([(65,30),(85,50)], fill=PRIMARY+(255,))
wd.polygon([(75,25),(68,45),(82,45)], fill=WHITE+(255,))
wd.polygon([(75,65),(68,45),(82,45)], fill=PRIMARY+(255,))
for text, y in [("Kariyer", 85), ("Pusulasi", 103)]:
    f = font(13)
    bb = wd.textbbox((0,0), text, font=f)
    wd.text(((150-(bb[2]-bb[0]))//2, y), text, font=f, fill=PRIMARY+(255,))
wm.save("channels/kariyer_pusulasi/branding/watermark_150x150.png", "PNG")

# ── BANNER 2560x1440 ───────────────────────────────────────────
BW, BH = 2560, 1440
banner = gradient(BW, BH, (8, 15, 45), (4, 8, 25))
bd = ImageDraw.Draw(banner)

# Sol dekorasyon - pusula büyük
for i in range(5):
    r2 = 200 + i * 60
    bd.ellipse([(350-r2, BH//2-r2),(350+r2, BH//2+r2)],
               outline=PRIMARY+(30,) if hasattr(PRIMARY,'__len__') else PRIMARY,
               width=2)

for text, y, size, color in [
    ("Kariyer Pusulasi", BH//2-140, 155, PRIMARY),
    ("Kariyerinde Bir Adim One Gec! | Is Hayati ve Basari", BH//2+50, 62, WHITE),
    ("Her Gun 11:30 ve 23:30 | Maas • Remote • Freelance • Kariyer", BH//2+140, 48, (160,185,255)),
]:
    f = font(size)
    bb = bd.textbbox((0,0), text, font=f)
    x = (BW-(bb[2]-bb[0]))//2
    bd.text((x+3,y+3), text, font=f, fill=(0,0,0))
    bd.text((x,y), text, font=f, fill=color)

bd.line([(200,BH-120),(BW-200,BH-120)], fill=PRIMARY, width=3)
footer = "#Kariyer #Maas #Remote #Freelance #LinkedIn #IsHayati #KariyerPusulasi"
f_sm = font(44)
bb = bd.textbbox((0,0), footer, font=f_sm)
bd.text(((BW-(bb[2]-bb[0]))//2, BH-100), footer, font=f_sm, fill=(130,160,220))
banner.save("channels/kariyer_pusulasi/branding/youtube_banner_2560x1440.png", "PNG")

print("TAMAMLANDI - Kariyer Pusulasi gorselleri hazir")
