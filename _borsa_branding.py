"""Borsa Akademi - Kanal Gorselleri"""
import os, sys
sys.path.insert(0, ".")
import numpy as np
from PIL import Image, ImageDraw, ImageFont

os.makedirs("channels/borsa_akademi/branding", exist_ok=True)

BG = (10, 30, 20)
PRIMARY = (0, 200, 100)
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

W, H = 800, 800
img = gradient(W, H, BG, (5, 15, 10))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle([(25,25),(775,775)], radius=70, outline=PRIMARY, width=7)

# Grafik çubuğu (borsa bar chart)
bars = [(300,180,60),(370,120,60),(440,200,60),(510,90,60),(580,150,60)]
for bx, bh, bw in bars:
    draw.rectangle([(bx, 380-bh),(bx+bw, 380)], fill=PRIMARY)
# Trend çizgisi
pts = [(300,280),(370,220),(440,300),(510,190),(580,250),(640,170)]
for i in range(len(pts)-1):
    draw.line([pts[i], pts[i+1]], fill=WHITE, width=4)
    draw.ellipse([(pts[i][0]-5,pts[i][1]-5),(pts[i][0]+5,pts[i][1]+5)], fill=PRIMARY)

for text, y, size, color in [
    ("Borsa", 435, 72, PRIMARY),
    ("Akademi", 513, 72, WHITE),
    ("BIST'te Kazanmanin Yolu!", 600, 30, (150,255,180)),
]:
    f = font(size)
    bb = draw.textbbox((0,0), text, font=f)
    x = (W-(bb[2]-bb[0]))//2
    draw.text((x+2,y+2), text, font=f, fill=(0,0,0))
    draw.text((x,y), text, font=f, fill=color)

draw.line([(120,655),(W-120,655)], fill=PRIMARY, width=2)
img.save("channels/borsa_akademi/branding/logo_800x800.png", "PNG")

# WATERMARK
wm = Image.new("RGBA", (150,150), (0,0,0,0))
wd = ImageDraw.Draw(wm)
wd.ellipse([(5,5),(145,145)], fill=BG+(200,))
wd.ellipse([(5,5),(145,145)], outline=PRIMARY+(255,), width=3)
mini_bars = [(45,30),(65,20),(85,35),(105,15)]
for bx, bh in mini_bars:
    wd.rectangle([(bx,75-bh),(bx+15,75)], fill=PRIMARY+(255,))
wd.line([(40,60),(60,50),(80,65),(100,40),(120,52)], fill=WHITE+(255,), width=2)
for text, y in [("Borsa", 88), ("Akademi", 106)]:
    f = font(13)
    bb = wd.textbbox((0,0), text, font=f)
    wd.text(((150-(bb[2]-bb[0]))//2, y), text, font=f, fill=PRIMARY+(255,))
wm.save("channels/borsa_akademi/branding/watermark_150x150.png", "PNG")

# BANNER
BW, BH = 2560, 1440
banner = gradient(BW, BH, (8, 22, 14), (4, 10, 7))
bd = ImageDraw.Draw(banner)
# Büyük grafik dekorasyonu
big_pts = [(100,BH//2+200),(400,BH//2-100),(700,BH//2+300),(1000,BH//2-200),(1300,BH//2+100)]
for i in range(len(big_pts)-1):
    bd.line([big_pts[i], big_pts[i+1]], fill=(0,200,100,30), width=3)

for text, y, size, color in [
    ("Borsa Akademi", BH//2-140, 160, PRIMARY),
    ("BIST'te Kazanmanin Yolu! | Hisse • Temettü • Teknik Analiz", BH//2+50, 62, WHITE),
    ("Her Gun 10:30 ve 22:30 | BIST100 • Portfoy • Temettü Stratejisi", BH//2+140, 48, (150,255,180)),
]:
    f = font(size)
    bb = bd.textbbox((0,0), text, font=f)
    x = (BW-(bb[2]-bb[0]))//2
    bd.text((x+3,y+3), text, font=f, fill=(0,0,0))
    bd.text((x,y), text, font=f, fill=color)

bd.line([(200,BH-120),(BW-200,BH-120)], fill=PRIMARY, width=3)
footer = "#Borsa #BIST #Hisse #Temettü #TeknikAnaliz #BorsaAkademi #Portfoy"
f_sm = font(44)
bb = bd.textbbox((0,0), footer, font=f_sm)
bd.text(((BW-(bb[2]-bb[0]))//2, BH-100), footer, font=f_sm, fill=(100,200,130))
banner.save("channels/borsa_akademi/branding/youtube_banner_2560x1440.png", "PNG")
print("TAMAMLANDI - Borsa Akademi gorselleri hazir")
