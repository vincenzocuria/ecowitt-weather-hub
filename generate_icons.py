"""
Genera le icone dell'app (PWA, Apple, badge notifiche, ntfy) in stile flat:
sfondo pieno a gradiente cielo (il sistema operativo applica da sé gli angoli arrotondati),
un sole caldo parzialmente coperto da una nuvola morbida, margini ampi per la "safe zone" maskable.

Uso: python generate_icons.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ICONS_DIR = Path(__file__).resolve().parent / "backend" / "static" / "icons"
SS = 4  # supersampling per bordi morbidi

SKY_TOP = (56, 189, 248)      # sky-400
SKY_BOTTOM = (29, 78, 216)    # blue-700
SUN_LIGHT = (253, 224, 71)    # yellow-300
SUN_DARK = (245, 158, 11)     # amber-500
CLOUD = (255, 255, 255)
CLOUD_SHADE = (219, 234, 254)  # blue-100


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def vertical_gradient(size, top, bottom):
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        draw.line([(0, y), (size, y)], fill=lerp(top, bottom, y / (size - 1)))
    return img


def radial_sun(size, cx, cy, r):
    """Disco del sole con leggero gradiente radiale (centro più chiaro)."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    steps = 48
    for i in range(steps, 0, -1):
        t = i / steps
        rr = r * t
        color = lerp(SUN_LIGHT, SUN_DARK, t ** 1.6)
        draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=color + (255,))
    return layer


def cloud_mask(size, ox, oy, w):
    """Silhouette di nuvola: tre cerchi + base arrotondata, larghezza w con origine (ox, oy) in basso a sinistra."""
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    h = w * 0.30                                   # altezza della base
    base_top = oy - h
    d.rounded_rectangle([ox, base_top, ox + w, oy], radius=h / 2, fill=255)
    for cx, cy, r in (
        (ox + w * 0.30, base_top + h * 0.15, w * 0.20),
        (ox + w * 0.56, base_top - h * 0.30, w * 0.27),
        (ox + w * 0.80, base_top + h * 0.25, w * 0.17),
    ):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return mask


def draw_artwork(size, with_background=True):
    s = size * SS
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    if with_background:
        canvas.paste(vertical_gradient(s, SKY_TOP, SKY_BOTTOM), (0, 0))

    # Sole in alto a destra, dentro la safe zone (cerchio centrale dell'80%)
    sun = radial_sun(s, s * 0.60, s * 0.43, s * 0.20)
    canvas.alpha_composite(sun)

    # Nuvola: ombra morbida + corpo bianco con leggera sfumatura in basso
    cw = s * 0.62
    ox, oy = s * 0.19, s * 0.745
    mask = cloud_mask(s, ox, oy, cw)

    shadow = Image.new("RGBA", (s, s), (15, 23, 42, 0))
    shadow.putalpha(mask.point(lambda v: int(v * 0.22)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(s * 0.025))
    canvas.alpha_composite(shadow, (0, int(s * 0.02)))

    # Leggera sfumatura azzurrina solo nella parte bassa della nuvola
    top_px, bottom_px = int(oy - cw * 0.30 - cw * 0.57), int(oy)
    grad = Image.new("RGBA", (s, s), CLOUD + (255,))
    gd = ImageDraw.Draw(grad)
    for y in range(top_px, bottom_px):
        t = (y - top_px) / max(1, bottom_px - top_px)
        gd.line([(0, y), (s, y)], fill=lerp(CLOUD, CLOUD_SHADE, max(0.0, t - 0.35) / 0.65 if t > 0.35 else 0.0) + (255,))
    for y in range(bottom_px, s):
        gd.line([(0, y), (s, y)], fill=CLOUD_SHADE + (255,))
    grad.putalpha(mask)
    canvas.alpha_composite(grad)

    return canvas.resize((size, size), Image.LANCZOS)


def draw_badge(size=96):
    """Badge monocromatico per le notifiche Android: silhouette bianca su trasparente."""
    s = size * SS
    mask = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(mask)
    cx, cy, r = s * 0.62, s * 0.36, s * 0.22
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    cloud = cloud_mask(s, s * 0.08, s * 0.84, s * 0.80)
    # Stacco trasparente tra sole e nuvola, così le due forme restano distinguibili
    halo = cloud.filter(ImageFilter.MaxFilter(int(s * 0.05) | 1))
    mask.paste(0, (0, 0), halo)
    mask.paste(255, (0, 0), cloud)
    img = Image.new("RGBA", (s, s), (255, 255, 255, 0))
    img.putalpha(mask)
    return img.resize((size, size), Image.LANCZOS)


def main():
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    full = draw_artwork(1024)
    for name, px in (("icon-512.png", 512), ("icon-192.png", 192), ("apple-touch-icon.png", 180), ("ntfy-icon.png", 256)):
        full.resize((px, px), Image.LANCZOS).convert("RGB" if name == "apple-touch-icon.png" else "RGBA").save(ICONS_DIR / name, optimize=True)
    # Favicon piccola: stessa grafica
    full.resize((48, 48), Image.LANCZOS).save(ICONS_DIR / "favicon-48.png", optimize=True)
    draw_badge(96).save(ICONS_DIR / "badge-96.png", optimize=True)
    print("Icone generate in", ICONS_DIR)


if __name__ == "__main__":
    main()
