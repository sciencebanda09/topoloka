"""Build the 1920x1080 title and metric cards for the R1 demo video.

Run from the repo root:
    python docs/demo/build_cards.py

Only Pillow is used; no browser and no pipeline compute.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "cards"
OUT.mkdir(parents=True, exist_ok=True)
TMP = Path.home() / "AppData" / "Local" / "Temp"

W, H = 1920, 1080
BG = (7, 11, 16)
PANEL = (15, 22, 31)
PANEL2 = (20, 29, 40)
LINE = (44, 60, 78)
TEXT = (232, 239, 246)
MUTED = (150, 168, 186)
CYAN = (127, 212, 255)
GREEN = (64, 224, 138)
AMBER = (255, 190, 92)

SEGOE = "C:/Windows/Fonts/segoeui.ttf"
SEGOE_B = "C:/Windows/Fonts/segoeuib.ttf"
SEGOE_L = "C:/Windows/Fonts/segoeuil.ttf"
CONSOLA = "C:/Windows/Fonts/consola.ttf"
CONSOLA_B = "C:/Windows/Fonts/consolab.ttf"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def bg() -> Image.Image:
    """Vertical gradient plus a faint grid and vignette."""
    base = Image.new("RGB", (W, H), BG)
    px = base.load()
    top = (9, 14, 21)
    bottom = (4, 7, 11)
    for y in range(H):
        t = y / (H - 1)
        c = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        for x in range(W):
            px[x, y] = c
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, W, 80):
        gd.line([(x, 0), (x, H)], fill=(90, 130, 170, 12), width=1)
    for y in range(0, H, 80):
        gd.line([(0, y), (W, y)], fill=(90, 130, 170, 12), width=1)
    base = Image.alpha_composite(base.convert("RGBA"), grid)
    # vignette
    vig = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-W * 0.25, -H * 0.35, W * 1.25, H * 1.35], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(180))
    black = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    black.putalpha(Image.eval(vig, lambda v: 110 - int(v * 0.43)))
    return Image.alpha_composite(base, black).convert("RGB")


def spaced(draw: ImageDraw.ImageDraw, xy, text: str, fnt, fill, spacing: int):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + spacing
    return x


def header(img: Image.Image, chapter: str) -> None:
    d = ImageDraw.Draw(img)
    d.text((70, 48), "TOPOLOKA", font=font(SEGOE_B, 26), fill=CYAN)
    d.text((70, 82), chapter, font=font(SEGOE, 22), fill=MUTED)
    d.text((W - 70, 54), "TECHFEST 2026–27  ·  ROUND 1",
           font=font(SEGOE_B, 20), fill=MUTED, anchor="ra")


def footer(img: Image.Image, text: str) -> None:
    d = ImageDraw.Draw(img)
    d.line([(70, H - 74), (W - 70, H - 74)], fill=(40, 54, 70), width=1)
    d.text((70, H - 54), text, font=font(SEGOE, 20), fill=MUTED)


def wrap(draw, text, fnt, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=fnt) <= max_width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def dotted_cloud(img: Image.Image, cx, cy, rx, ry, n=2600, seed=7) -> None:
    rnd = random.Random(seed)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for _ in range(n):
        a = rnd.random() * math.tau
        r = math.sqrt(rnd.random())
        x = cx + math.cos(a) * rx * r
        y = cy + math.sin(a) * ry * r
        # denser toward the middle, dimmer at the rim
        alpha = int(20 + 115 * (1 - r) ** 1.6)
        size = 1 if rnd.random() < 0.7 else 2
        col = (140, 215, 255, alpha) if rnd.random() < 0.8 else (220, 245, 255, alpha)
        ld.ellipse([x, y, x + size, y + size], fill=col)
    img.alpha_composite(layer)


def save(img: Image.Image, name: str) -> None:
    img.convert("RGB").save(OUT / name, quality=96)
    print("wrote", OUT / name)


def card_title() -> None:
    img = bg().convert("RGBA")
    dotted_cloud(img, 1450, 500, 430, 330, n=3400, seed=11)
    d = ImageDraw.Draw(img)
    d.text((100, 250), "A 3D twin from", font=font(SEGOE_L, 64), fill=MUTED)
    d.text((100, 322), "one walk-through.", font=font(SEGOE_L, 64), fill=MUTED)
    spaced(d, (96, 416), "TOPOLOKA", font(SEGOE_B, 158), TEXT, 10)
    d.text((104, 630), "One video in. A navigable place out.",
           font=font(SEGOE, 46), fill=CYAN)
    body = ("Metric Gaussian-splat twin, collision, minimap, and A* routing "
            "from a single indoor clip — hosted as a static link.")
    y = 706
    for line in wrap(d, body, font(SEGOE, 30), 980):
        d.text((104, y), line, font=font(SEGOE, 30), fill=MUTED)
        y += 44
    d.text((104, 852), "Source: Modern Melbourne Metro Walkway Urban Design",
           font=font(SEGOE, 22), fill=(120, 140, 158))
    d.text((104, 882), "Joolsmagool · Pexels License · trimmed to 86.07 s",
           font=font(SEGOE, 22), fill=(120, 140, 158))
    save(img, "01_title.png")


def card_problem() -> None:
    img = bg().convert("RGBA")
    d = ImageDraw.Draw(img)
    header(img, "THE GAP")
    d.text((100, 190), "Google Maps stops", font=font(SEGOE_B, 84), fill=TEXT)
    d.text((100, 286), "at the door.", font=font(SEGOE_B, 84), fill=TEXT)
    d.text((104, 414), "Floor-plan kiosks are static. LiDAR twins need hardware.",
           font=font(SEGOE, 32), fill=MUTED)
    d.text((104, 458), "Topoloka asks a narrower question:",
           font=font(SEGOE, 32), fill=MUTED)
    quote = ("What is the shortest path from one walk-through to a stranger "
             "navigating that space?")
    y = 540
    for line in wrap(d, quote, font(SEGOE_L, 52), 1240):
        d.text((104, y), line, font=font(SEGOE_L, 52), fill=CYAN)
        y += 70
    tiles = [
        ("NO LIDAR", "one ordinary camera clip"),
        ("NO FLOOR PLAN", "geometry from the frames"),
        ("NO SERVER", "a folder of static files"),
    ]
    x = 100
    for i, (title, sub) in enumerate(tiles):
        d.rounded_rectangle([x, 800, x + 520, 940], radius=16, fill=PANEL,
                            outline=LINE, width=2)
        d.text((x + 28, 826), title, font=font(SEGOE_B, 24), fill=GREEN)
        d.text((x + 28, 870), sub, font=font(SEGOE, 25), fill=TEXT)
        x += 560
    footer(img, "Problem framing; no product claims beyond the shipped artifact.")
    save(img, "02_problem.png")


def card_pipeline() -> None:
    img = bg().convert("RGB")
    d = ImageDraw.Draw(img)
    header(img, "THE PIPELINE")
    d.text((90, 150), "One video in. Static twin out.",
           font=font(SEGOE_B, 62), fill=TEXT)
    fig = Image.open(ROOT / "docs" / "fig" / "pipeline.png").convert("RGB")
    fw = 1740
    fh = int(fig.height * fw / fig.width)
    fig = fig.resize((fw, fh), Image.LANCZOS)
    # white figure on a light panel
    px, py = 90, 280
    d.rounded_rectangle([px - 20, py - 20, px + fw + 20, py + fh + 20],
                        radius=18, fill=(246, 248, 250))
    img.paste(fig, (px, py))
    tiles = [
        ("216", "frames registered", "pycolmap 4.2.1"),
        ("10.28 M", "depth points fused", "metric scale 6.2505"),
        ("510 K", "gaussians exported", "25 K Splatfacto iters"),
    ]
    x = 90
    for value, label, sub in tiles:
        d.rounded_rectangle([x, 760, x + 560, 928], radius=16, fill=PANEL,
                            outline=LINE, width=2)
        d.text((x + 28, 786), value, font=font(SEGOE_B, 56), fill=CYAN)
        d.text((x + 28, 854), label, font=font(SEGOE, 25), fill=TEXT)
        d.text((x + 28, 888), sub, font=font(CONSOLA, 20), fill=MUTED)
        x += 600
    footer(img, "CPU kernel: SfM + depth + nav.  GPU kernel: metric splat training.")
    save(img, "03_pipeline.png")


def card_artifacts() -> None:
    img = bg().convert("RGBA")
    d = ImageDraw.Draw(img)
    header(img, "THE ARTIFACT")
    d.text((90, 150), "What ships is a folder,", font=font(SEGOE_B, 60), fill=TEXT)
    d.text((90, 222), "not a service.", font=font(SEGOE_B, 60), fill=TEXT)
    tree = [
        ("test/metro_v1/", TEXT),
        ("  web/splat.splat", MUTED),
        ("      14.63 MB  ·  510,336 gaussians", CYAN),
        ("  web/cloud.ply", MUTED),
        ("       3.75 MB  ·  250,000 points", CYAN),
        ("  web/nav.json", MUTED),
        ("      40.1 KB  ·  grid + path + align", CYAN),
        ("  web/occupancy.png", MUTED),
        ("      23.6 KB  ·  minimap", CYAN),
        ("  sfm/sfm_report.json", MUTED),
        ("  depth/scale.json", MUTED),
        ("  nav/nav_report.json", MUTED),
        ("  capture_qa.md", MUTED),
    ]
    x, y = 100, 360
    d.rounded_rectangle([x - 20, y - 24, x + 1020, y + 500], radius=16,
                        fill=(10, 15, 21), outline=LINE, width=2)
    for line, col in tree:
        f = font(CONSOLA_B if line.startswith("test/") else CONSOLA, 27)
        d.text((x, y), line, font=f, fill=col)
        y += 35
    # right side callouts
    bx = 1120
    d.rounded_rectangle([bx, 360, bx + 700, 860], radius=16, fill=PANEL,
                        outline=LINE, width=2)
    d.text((bx + 36, 392), "24.7 MB", font=font(SEGOE_B, 72), fill=GREEN)
    d.text((bx + 38, 480), "complete sample folder", font=font(SEGOE, 26), fill=TEXT)
    facts = [
        "no server",
        "no database",
        "no account",
        "no build step on the host",
    ]
    yy = 550
    for fact in facts:
        d.ellipse([bx + 40, yy + 9, bx + 52, yy + 21], fill=GREEN)
        d.text((bx + 70, yy), fact, font=font(SEGOE, 28), fill=MUTED)
        yy += 56
    d.text((bx + 38, 790), "index.html + fetch()", font=font(CONSOLA, 22), fill=CYAN)
    footer(img, "The 139 MB training PLY never goes to the web.")
    save(img, "03b_artifacts.png")


def card_qa() -> None:
    img = bg().convert("RGBA")
    d = ImageDraw.Draw(img)
    header(img, "QUALITY GATE")
    d.text((90, 150), "Trust is a deliverable.", font=font(SEGOE_B, 66), fill=TEXT)
    d.rounded_rectangle([90, 248, 470, 318], radius=12, fill=(18, 60, 42),
                        outline=GREEN, width=2)
    d.text((280, 283), "QA 6 / 6 PASS", font=font(SEGOE_B, 28), fill=GREEN,
           anchor="mm")
    rows = [
        ("Frames registered", "216 / 216"),
        ("Median reprojection error", "0.403 px"),
        ("Scale", "6.2505 m / unit"),
        ("Scale MAD", "7.54 %"),
        ("Walkable area", "315.05 m²"),
        ("Depth points fused", "10,281,709"),
        ("Export", "510,336 gaussians"),
    ]
    x0, y0 = 90, 370
    d.rounded_rectangle([x0 - 16, y0 - 20, x0 + 1120, y0 + 7 * 78 + 8],
                        radius=16, fill=PANEL, outline=LINE, width=2)
    y = y0
    for i, (label, value) in enumerate(rows):
        if i % 2 == 0:
            d.rectangle([x0 - 16, y - 10, x0 + 1100, y + 58], fill=(18, 26, 36))
        d.text((x0 + 20, y + 12), label, font=font(SEGOE, 28), fill=MUTED)
        d.text((x0 + 1070, y + 8), value, font=font(CONSOLA_B, 34), fill=TEXT,
               anchor="ra")
        y += 78
    bx = 1260
    d.rounded_rectangle([bx, 370, bx + 560, 814], radius=16, fill=PANEL2,
                        outline=LINE, width=2)
    d.text((bx + 32, 400), "SHIPPED IN THE SAMPLE", font=font(SEGOE_B, 22), fill=CYAN)
    d.text((bx + 32, 448), "capture_qa.md", font=font(CONSOLA_B, 26), fill=TEXT)
    d.text((bx + 32, 492), "sfm_report.json", font=font(CONSOLA, 24), fill=MUTED)
    d.text((bx + 32, 530), "depth_report.json", font=font(CONSOLA, 24), fill=MUTED)
    d.text((bx + 32, 568), "scale.json", font=font(CONSOLA, 24), fill=MUTED)
    d.text((bx + 32, 606), "nav_report.json", font=font(CONSOLA, 24), fill=MUTED)
    d.text((bx + 32, 668), "No projected or", font=font(SEGOE, 26), fill=TEXT)
    d.text((bx + 32, 704), "invented numbers.", font=font(SEGOE, 26), fill=TEXT)
    d.text((bx + 32, 760), "Failures must name", font=font(SEGOE, 22), fill=MUTED)
    d.text((bx + 32, 788), "their compensation.", font=font(SEGOE, 22), fill=MUTED)
    footer(img, "Values from test/metro_v1/capture_qa.md and the report JSONs.")
    save(img, "04_qa.png")


def card_nav() -> None:
    img = bg().convert("RGB")
    d = ImageDraw.Draw(img)
    header(img, "METRIC NAVIGATION")
    d.text((90, 150), "The floor is measured, not guessed.", font=font(SEGOE_B, 56),
           fill=TEXT)
    nav = Image.open(ROOT / "docs" / "fig" / "nav.png").convert("RGB")
    nh = 700
    nw = int(nav.width * nh / nav.height)
    nav = nav.resize((nw, nh), Image.LANCZOS)
    px, py = 80, 240
    d.rounded_rectangle([px - 14, py - 14, px + nw + 14, py + nh + 14],
                        radius=14, fill=(230, 232, 235))
    img.paste(nav, (px, py))
    x = 900
    d.text((x, 262), "5 cm grid", font=font(SEGOE_B, 30), fill=CYAN)
    stats = [
        ("1188 × 1259", "cells"),
        ("126,020", "free cells"),
        ("315.05 m²", "walkable floor"),
        ("1,272,609", "unknown cells blocked"),
        ("0.5 m", "free corridor carved"),
    ]
    y = 330
    for value, label in stats:
        d.text((x, y), value, font=font(SEGOE_B, 52), fill=TEXT)
        d.text((x, y + 58), label, font=font(SEGOE, 26), fill=MUTED)
        y += 128
    footer(img, "Camera height 1.588 m. Floor inliers: 929,436. Nav build: 61.0 s.")
    save(img, "04b_nav.png")


def caption_still(src: Path, dst: str, text: str) -> None:
    img = Image.open(src).convert("RGBA")
    if img.size != (W, H):
        img = img.resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(img, "RGBA")
    f = font(SEGOE_B, 27)
    tw = d.textlength(text, font=f)
    x = (W - tw) / 2
    d.rounded_rectangle([x - 24, 28, x + tw + 24, 78], radius=12,
                        fill=(5, 9, 14, 210), outline=(80, 110, 140, 180), width=1)
    d.text((x, 41), text, font=f, fill=TEXT)
    save(img, dst)


def card_limits() -> None:
    img = bg().convert("RGBA")
    d = ImageDraw.Draw(img)
    header(img, "LIMITS, NEXT TO THE NUMBERS")
    d.text((90, 150), "Where it is weak.", font=font(SEGOE_B, 66), fill=TEXT)
    items = [
        ("SPECULAR WALLS", "Soft at ~1.5 K gaussians/m².\nThe web .splat is DC-only."),
        ("DEPTH RANGE", "Degrades past 8–12 m.\nThe ceiling is under-observed."),
        ("PORTAL GAPS", "Unknown cells are blocked.\nCarved 1 m walked corridor."),
    ]
    x = 90
    for title, body in items:
        d.rounded_rectangle([x, 330, x + 550, 700], radius=18, fill=PANEL,
                            outline=LINE, width=2)
        d.text((x + 30, 366), title, font=font(SEGOE_B, 26), fill=AMBER)
        yy = 440
        for line in body.split("\n"):
            d.text((x + 30, yy), line, font=font(SEGOE, 28), fill=TEXT)
            yy += 52
        x += 590
    d.rounded_rectangle([90, 780, 1830, 920], radius=16, fill=PANEL2,
                        outline=LINE, width=2)
    d.text((120, 808), "These are in docs/abstract.pdf — not hidden in a footnote.",
           font=font(SEGOE, 30), fill=TEXT)
    d.text((120, 858), "No second capture is claimed: two public candidates failed SfM "
                       "(54% and 2% registered).",
           font=font(SEGOE, 24), fill=MUTED)
    footer(img, "Metro capture is the only hosted twin in Round 1.")
    save(img, "07_limits.png")


def card_close() -> None:
    img = bg().convert("RGBA")
    d = ImageDraw.Draw(img)
    header(img, "ROADMAP")
    d.text((90, 150), "Round 2 and Round 3.", font=font(SEGOE_B, 62), fill=TEXT)
    d.rounded_rectangle([90, 270, 910, 610], radius=18, fill=PANEL,
                        outline=LINE, width=2)
    d.text((120, 300), "R2  ·  DUE NOV 30", font=font(SEGOE_B, 24), fill=CYAN)
    r2 = ["Open-vocabulary POIs", "Search over the twin", "End-to-end routing"]
    for i, t in enumerate(r2):
        d.text((120, 360 + i * 64), "→  " + t, font=font(SEGOE, 32), fill=TEXT)
    d.rounded_rectangle([960, 270, 1830, 610], radius=18, fill=PANEL,
                        outline=LINE, width=2)
    d.text((990, 300), "R3  ·  DEC 16–17", font=font(SEGOE_B, 24), fill=GREEN)
    r3 = ["On-site IIT Bombay capture", "QR-anchored AR", "Same static pipeline"]
    for i, t in enumerate(r3):
        d.text((990, 360 + i * 64), "→  " + t, font=font(SEGOE, 32), fill=TEXT)
    d.text((90, 690), "One video in. A navigable place out.",
           font=font(SEGOE_L, 58), fill=CYAN)
    links = [
        ("Live twin", "sciencebanda09.github.io/topoloka/?v=20261031-clean"),
        ("Repository", "github.com/sciencebanda09/topoloka"),
        ("Abstract", "docs/abstract.pdf"),
    ]
    y = 796
    for label, value in links:
        d.text((90, y), label, font=font(SEGOE_B, 22), fill=MUTED)
        d.text((300, y - 2), value, font=font(CONSOLA, 24), fill=TEXT)
        y += 48
    footer(img, "MIT code. Source clip: Pexels License. No house footage in this video.")
    save(img, "08_close.png")


def credit_overlay() -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    lines = [
        "Source: Modern Melbourne Metro Walkway Urban Design",
        "Joolsmagool  ·  Pexels License  ·  trimmed to 86.07 s",
    ]
    f1 = font(SEGOE_B, 22)
    f2 = font(SEGOE, 20)
    width = max(d.textlength(lines[0], font=f1), d.textlength(lines[1], font=f2)) + 36
    x, y = 48, 940
    d.rounded_rectangle([x, y, x + width, y + 84], radius=10,
                        fill=(4, 8, 13, 205), outline=(110, 140, 165, 120), width=1)
    d.text((x + 18, y + 12), lines[0], font=f1, fill=(240, 246, 252, 245))
    d.text((x + 18, y + 46), lines[1], font=f2, fill=(185, 202, 218, 240))
    img.save(OUT / "source_credit.png")
    print("wrote", OUT / "source_credit.png")


def main() -> None:
    card_title()
    card_problem()
    card_pipeline()
    card_artifacts()
    card_qa()
    card_nav()
    card_limits()
    card_close()
    caption_still(TMP / "live_default_walk.png", "05b_default.png",
                  "DEFAULT SPAWN  ·  51.0 fps idle / 60.1 fps walking")
    caption_still(TMP / "live_t90_walk.png", "05c_t90.png",
                  "MID-CAPTURE  ?t=90  ·  43.0 fps idle / 40.2 fps walking")
    caption_still(TMP / "live_route.png", "06a_route.png",
                  "A* ROUTE  ·  350 waypoints  ·  20.3 m")
    caption_still(TMP / "live_route_walk.png", "06b_route_walk.png",
                  "WALKING THE ROUTE  ·  47.5 / 55.9 fps")
    credit_overlay()


if __name__ == "__main__":
    main()
