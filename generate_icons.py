import math
from PIL import Image, ImageDraw

def create_weather_icon(size=512):
    # Draw at 4x for smooth antialiasing
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Background Rounded Rectangle with Gradient
    r = int(s * 0.22)
    # Background gradient from deep dark navy to vibrant azure
    for y in range(s):
        ratio = y / s
        r_c = int(15 * (1 - ratio) + 2 * ratio)
        g_c = int(23 * (1 - ratio) + 132 * ratio)
        b_c = int(42 * (1 - ratio) + 199 * ratio)
        draw.line([(0, y), (s, y)], fill=(r_c, g_c, b_c, 255))

    # Mask with rounded corners
    mask = Image.new("L", (s, s), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, s, s], radius=r, fill=255)
    img.putalpha(mask)

    draw = ImageDraw.Draw(img)

    # Subtle inner border
    draw.rounded_rectangle([scale * 3, scale * 3, s - scale * 3, s - scale * 3], radius=r - scale * 2, outline=(56, 189, 248, 80), width=scale * 4)

    # 2. Golden Sun in the upper-right
    sun_cx, sun_cy = int(s * 0.65), int(s * 0.38)
    sun_radius = int(s * 0.18)

    # Sun glow
    for glow_r in range(sun_radius + int(s * 0.08), sun_radius, -int(scale * 2)):
        alpha = int(30 * (1 - (glow_r - sun_radius) / (s * 0.08)))
        draw.ellipse([sun_cx - glow_r, sun_cy - glow_r, sun_cx + glow_r, sun_cy + glow_r], fill=(251, 191, 36, alpha))

    # Sun rays
    num_rays = 8
    ray_len = int(s * 0.06)
    ray_dist = sun_radius + int(s * 0.03)
    for i in range(num_rays):
        angle = i * (2 * math.pi / num_rays)
        x1 = sun_cx + int(ray_dist * math.cos(angle))
        y1 = sun_cy + int(ray_dist * math.sin(angle))
        x2 = sun_cx + int((ray_dist + ray_len) * math.cos(angle))
        y2 = sun_cy + int((ray_dist + ray_len) * math.sin(angle))
        draw.line([(x1, y1), (x2, y2)], fill=(245, 158, 11, 230), width=scale * 6)

    # Sun body gradient / solid
    draw.ellipse([sun_cx - sun_radius, sun_cy - sun_radius, sun_cx + sun_radius, sun_cy + sun_radius], fill=(251, 191, 36, 255))

    # 3. Fluffy stylized Cloud in the center-left
    cloud_color = (255, 255, 255, 250)
    cloud_shadow = (203, 213, 225, 255)

    # Base cloud circles
    c1 = (int(s * 0.32), int(s * 0.62), int(s * 0.16)) # left
    c2 = (int(s * 0.48), int(s * 0.50), int(s * 0.22)) # center top
    c3 = (int(s * 0.68), int(s * 0.63), int(s * 0.15)) # right

    # Bottom pill base
    cloud_bottom_y = int(s * 0.76)
    draw.rounded_rectangle([int(s * 0.20), int(s * 0.58), int(s * 0.80), cloud_bottom_y], radius=int(s * 0.08), fill=cloud_color)

    # Circles for cloud puffs
    draw.ellipse([c1[0] - c1[2], c1[1] - c1[2], c1[0] + c1[2], c1[1] + c1[2]], fill=cloud_color)
    draw.ellipse([c3[0] - c3[2], c3[1] - c3[2], c3[0] + c3[2], c3[1] + c3[2]], fill=cloud_color)
    draw.ellipse([c2[0] - c2[2], c2[1] - c2[2], c2[0] + c2[2], c2[1] + c2[2]], fill=cloud_color)

    # 4. Weather Station Signals / Lightning / Raindrop accent
    # Lightning bolt or rain droplet accent
    drop_x, drop_y = int(s * 0.40), int(s * 0.84)
    draw.line([(drop_x, drop_y), (drop_x - int(s*0.02), drop_y + int(s*0.04))], fill=(56, 189, 248, 240), width=scale * 5)
    
    drop_x2, drop_y2 = int(s * 0.55), int(s * 0.83)
    draw.line([(drop_x2, drop_y2), (drop_x2 - int(s*0.02), drop_y2 + int(s*0.04))], fill=(56, 189, 248, 240), width=scale * 5)

    drop_x3, drop_y3 = int(s * 0.70), int(s * 0.84)
    draw.line([(drop_x3, drop_y3), (drop_x3 - int(s*0.02), drop_y3 + int(s*0.04))], fill=(56, 189, 248, 240), width=scale * 5)

    # Downsample with Lanczos for ultra-crisp output
    final_img = img.resize((size, size), Image.Resampling.LANCZOS)
    return final_img

def create_monochrome_badge(size=96):
    # Android Chrome Notification Badge must be transparent with solid white shape
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Sun rays & circle
    sun_cx, sun_cy = int(s * 0.65), int(s * 0.35)
    sun_r = int(s * 0.16)
    draw.ellipse([sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r], fill=(255, 255, 255, 255))

    # Cloud shape
    c1 = (int(s * 0.35), int(s * 0.60), int(s * 0.17))
    c2 = (int(s * 0.52), int(s * 0.48), int(s * 0.22))
    c3 = (int(s * 0.70), int(s * 0.60), int(s * 0.16))

    draw.rounded_rectangle([int(s * 0.20), int(s * 0.56), int(s * 0.82), int(s * 0.76)], radius=int(s * 0.08), fill=(255, 255, 255, 255))
    draw.ellipse([c1[0] - c1[2], c1[1] - c1[2], c1[0] + c1[2], c1[1] + c1[2]], fill=(255, 255, 255, 255))
    draw.ellipse([c3[0] - c3[2], c3[1] - c3[2], c3[0] + c3[2], c3[1] + c3[2]], fill=(255, 255, 255, 255))
    draw.ellipse([c2[0] - c2[2], c2[1] - c2[2], c2[0] + c2[2], c2[1] + c2[2]], fill=(255, 255, 255, 255))

    return img.resize((size, size), Image.Resampling.LANCZOS)

if __name__ == "__main__":
    icon_512 = create_weather_icon(512)
    icon_512.save("backend/static/icons/icon-512.png", "PNG")
    icon_512.save("backend/static/icons/ntfy-icon.png", "PNG")

    icon_192 = create_weather_icon(192)
    icon_192.save("backend/static/icons/icon-192.png", "PNG")

    badge_96 = create_monochrome_badge(96)
    badge_96.save("backend/static/icons/badge-96.png", "PNG")

    print("Icons generated successfully!")
