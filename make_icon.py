"""Draws the Aether Lite icon (Liquid-Glass look) and builds assets/AetherLite.icns."""
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

N = 2048  # supersampled canvas, downscaled to 1024
A = Path(__file__).parent / "assets"
A.mkdir(exist_ok=True)


def lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def squircle_mask(size, inset, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([inset, inset, size - inset, size - inset], radius, fill=255)
    return m


def sparkle(size, cx, cy, r):
    """Slim 4-point star (astroid) with a slightly filled core, drawn as a dense polygon."""
    m = Image.new("L", (size, size), 0)
    pts = []
    for i in range(1440):
        t = 2 * math.pi * i / 1440
        k = 0.12
        x = math.cos(t) ** 3 * (1 - k) + k * 0.5 * math.cos(t)
        y = math.sin(t) ** 3 * (1 - k) + k * 0.5 * math.sin(t)
        pts.append((cx + r * x, cy + r * y))
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return m


inset, radius = int(N * 0.09), int(N * 0.205)
mask = squircle_mask(N, inset, radius)

c1, c2, c3 = (46, 92, 255), (139, 92, 246), (30, 190, 200)
base = Image.new("RGB", (N, N))
px = base.load()
for y in range(N):
    for x in range(N):
        t = (x * 0.55 + y * 0.9) / (N * 1.45)
        px[x, y] = lerp(c1, c2, t / 0.65) if t < 0.65 else lerp(c2, c3, (t - 0.65) / 0.35)
tile = Image.new("RGBA", (N, N), (0, 0, 0, 0))
tile.paste(base, (0, 0), mask)

shadow = Image.new("RGBA", (N, N), (0, 0, 0, 0))
shadow.paste((10, 14, 40, 120), (0, int(N * 0.018)), mask)
shadow = shadow.filter(ImageFilter.GaussianBlur(N * 0.02))
out = Image.alpha_composite(shadow, tile)

sheen = Image.new("RGBA", (N, N), (255, 255, 255, 0))
sp = sheen.load()
for y in range(N):
    t = max(0.0, 1 - (y - inset) / (N * 0.6))
    a = int(90 * t * t)
    for x in range(N):
        sp[x, y] = (255, 255, 255, a)
sheen.putalpha(ImageChops.multiply(sheen.getchannel("A"), mask))
out = Image.alpha_composite(out, sheen)

rim = Image.new("RGBA", (N, N), (0, 0, 0, 0))
ImageDraw.Draw(rim).rounded_rectangle(
    [inset, inset, N - inset, N - inset], radius, outline=(255, 255, 255, 150), width=int(N * 0.006))
rim.putalpha(ImageChops.multiply(rim.getchannel("A"), mask))
out = Image.alpha_composite(out, rim)

cx = cy = N * 0.5
glow = Image.new("RGBA", (N, N), (255, 255, 255, 0))
glow.putalpha(sparkle(N, cx, cy, N * 0.38).filter(ImageFilter.GaussianBlur(N * 0.04)).point(lambda v: int(v * 0.75)))
out = Image.alpha_composite(out, glow)

body = Image.new("RGBA", (N, N), (255, 255, 255, 255))
bp = body.load()
for y in range(N):
    col = lerp((255, 255, 255), (206, 216, 255), (y - N * 0.2) / (N * 0.6)) + (255,)
    for x in range(N):
        bp[x, y] = col
body.putalpha(sparkle(N, cx, cy, N * 0.34))
out = Image.alpha_composite(out, body)

small = Image.new("RGBA", (N, N), (255, 255, 255, 0))
small.putalpha(sparkle(N, N * 0.71, N * 0.29, N * 0.12))
out = Image.alpha_composite(out, small)

master = out.resize((1024, 1024), Image.LANCZOS)
master.save(A / "icon_1024.png")
iconset = A / "AetherLite.iconset"
shutil.rmtree(iconset, ignore_errors=True)
iconset.mkdir()
for s in (16, 32, 128, 256, 512):
    master.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
    master.resize((s * 2, s * 2), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(A / "AetherLite.icns")], check=True)
shutil.rmtree(iconset)
print("done")
