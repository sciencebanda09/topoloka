"""Build the 1920x1080 cards for the Round 2 demo video.

Run from the repo root:
    python docs/demo/build_cards_r2.py
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "cards_r2"
OUT.mkdir(parents=True, exist_ok=True)
HERO = OUT / "source" / "hero_initial.png"
NAV = OUT / "source" / "live_navigate.png"

W, H = 1920, 1080
BG = (7, 11, 16)
PANEL = (15, 22, 31)
PANEL2 = (20, 29, 40)
LINE = (44, 60, 78)
TEXT = (232, 239, 246)
MUTED = (150, 168, 186)
DIM = (112, 132, 150)
CYAN = (127, 212, 255)
GREEN = (64, 224, 138)
AMBER = (255, 190, 92)
PINK = (255, 122, 168)
VIOLET = (178, 150, 255)

SEGOE = "C:/Windows/Fonts/segoeui.ttf"
SEGOE_B = "C:/Windows/Fonts/segoeuib.ttf"
SEGOE_L = "C:/Windows/Fonts/segoeuil.ttf"
CONSOLA = "C:/Windows/Fonts/consola.ttf"
CONSOLA_B = "C:/Windows/Fonts/consolab.ttf"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def bg() -> Image.Image:
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
    d.text((W - 70, 54), "TECHFEST 2026–27  ·  ROUND 2",
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


def save(img: Image.Image, name: str) -> None:
    img.convert("RGB").save(OUT / name, quality=96)
    print("wrote", OUT / name)


def chip(d: ImageDraw.ImageDraw, x, y, text, color=CYAN, size=22):
    f = font(SEGOE_B, size)
    tw = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + tw + 40, y + 46], radius=23,
                        fill=(12, 20, 28), outline=(50, 70, 90), width=2)
    d.text((x + 20, y + 10), text, font=f, fill=color)
    return x + tw + 52


def card_title() -> None:
    img = Image.open(HERO).convert("RGB")
    img = img.resize((W, H), Image.LANCZOS)
    img = img.convert("RGBA")
    # Solid title field on the left, fading into the twin on the right.
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for x in range(W):
        t = min(1.0, max(0.0, (x - 860) / 790))
        alpha = int(255 * (1 - t) ** 1.3)
        sd.line([(x, 0), (x, H)], fill=(6, 9, 13, alpha))
    img = Image.alpha_composite(img, shade)

    d = ImageDraw.Draw(img)
    headed = spaced(d, (104, 206), "ROUND 2  ·  DUE 30 NOV 2026",
                    font(SEGOE_B, 23), CYAN, 3)
    _ = headed
    d.text((98, 258), "TOPOLOKA", font=font(SEGOE_B, 148), fill=TEXT)
    d.text((100, 446), "Search the twin.", font=font(SEGOE_L, 64), fill=TEXT)
    d.text((100, 518), "Route the walk.", font=font(SEGOE_L, 64), fill=CYAN)

    body = ("Seven authored points of interest, a real spatial index, and "
            "obstacle-aware paths on the same costmap that stops you walking "
            "through walls.")
    y = 638
    for line in wrap(d, body, font(SEGOE, 28), 820):
        d.text((102, y), line, font=font(SEGOE, 28), fill=(196, 212, 226))
        y += 40

    x = 102
    for label, col in (("7 POIs · 5 categories", CYAN),
                       ("50 web tests", GREEN),
                       ("static · no backend", AMBER)):
        x = chip(d, x, 796, label, col)
    d.text((104, 906), "sciencebanda09.github.io/topoloka",
           font=font(CONSOLA_B, 27), fill=CYAN)
    d.text((104, 950), "Round 1 free-roam is unchanged. Round 2 adds search and routing.",
           font=font(SEGOE, 22), fill=MUTED)
    save(img, "r2_01_title.png")


def card_contract() -> None:
    img = bg().convert("RGBA")
    d = ImageDraw.Draw(img)
    header(img, "THE CONTRACT")
    d.text((90, 146), "A POI is a contract,", font=font(SEGOE_B, 64), fill=TEXT)
    d.text((90, 220), "not a pin.", font=font(SEGOE_B, 64), fill=CYAN)
    d.text((94, 312), "One versioned JSON file ships beside the nav grid.",
           font=font(SEGOE, 27), fill=MUTED)

    # JSON panel
    x, y = 90, 376
    d.rounded_rectangle([x, y, x + 1000, y + 552], radius=16,
                        fill=(10, 15, 21), outline=LINE, width=2)
    d.text((x + 26, y + 18), "test/metro_v1/nav/pois.json",
           font=font(CONSOLA_B, 22), fill=DIM)
    d.text((x + 26, y + 52), "{", font=font(CONSOLA, 24), fill=MUTED)
    rows = [
        ('  "id": ', '"tunnel-walkway"', ','),
        ('  "name": ', '"Tunnel Walkway"', ','),
        ('  "category": ', '"walkway"', ','),
        ('  "aliases": ', '["tunnel", "corridor"]', ','),
        ('  "x": ', '-2.41', ',  "y": 6.02,  "z": 0'),
        ('  "radius": ', '1.4', ','),
        ('  "description": ', '"Covered pedestrian link', ',"'),
        ('                  ', '"between the platforms."', ''),
        ('  "view": ', '{ "x": -4.02, "y": 4.12,', ''),
        ('           ', '"yaw": 0.31 }', ''),
        ("}", "", ""),
    ]
    yy = y + 86
    for key, val, tail in rows:
        d.text((x + 34, yy), key, font=font(CONSOLA, 23), fill=CYAN)
        kx = x + 34 + d.textlength(key, font=font(CONSOLA, 23))
        d.text((kx, yy), val, font=font(CONSOLA, 23), fill=AMBER)
        vx = kx + d.textlength(val, font=font(CONSOLA, 23))
        d.text((vx, yy), tail, font=font(CONSOLA, 23), fill=MUTED)
        yy += 40

    # Gate panel
    gx = 1140
    d.rounded_rectangle([gx, 376, gx + 690, 928], radius=16, fill=PANEL,
                        outline=LINE, width=2)
    d.text((gx + 34, 402), "PIPELINE GATE", font=font(SEGOE_B, 22), fill=CYAN)
    checks = [
        ("Schema v1", "required fields, typed values"),
        ("Unique ids", "no duplicate names or ids"),
        ("On the floor", "x · y inside the navigable grid"),
        ("In the capture", "radius and view pose are reachable"),
        ("Deterministic", "stable order, validated before copy"),
    ]
    yy = 460
    for head, sub in checks:
        d.ellipse([gx + 36, yy + 6, gx + 50, yy + 20], fill=GREEN)
        d.text((gx + 68, yy), head, font=font(SEGOE_B, 25), fill=TEXT)
        d.text((gx + 68, yy + 34), sub, font=font(SEGOE, 21), fill=MUTED)
        yy += 82
    d.line([(gx + 34, 872), (gx + 656, 872)], fill=LINE, width=1)
    d.text((gx + 34, 886), "7 POIs · 5 categories · validated at build time",
           font=font(SEGOE, 20), fill=DIM)

    tiles = [("7", "POIs, hand-authored"), ("5", "categories"),
             ("1", "contract, reused by editor + web")]
    x = 90
    for value, label in tiles:
        d.rounded_rectangle([x, 936, x + 480, 996], radius=12, fill=PANEL,
                            outline=LINE, width=1)
        d.text((x + 22, 948), value, font=font(SEGOE_B, 30), fill=CYAN)
        d.text((x + 80, 954), label, font=font(SEGOE, 22), fill=MUTED)
        x += 520
    footer(img, "Same file feeds the browser index, the editor export, and the pipeline validator.")
    save(img, "r2_02_contract.png")


def card_index() -> None:
    img = bg().convert("RGBA")
    d = ImageDraw.Draw(img)
    header(img, "THE INDEX")
    d.text((90, 146), "Two indexes,", font=font(SEGOE_B, 64), fill=TEXT)
    d.text((90, 220), "built at load.", font=font(SEGOE_B, 64), fill=CYAN)
    d.text((94, 312), "No search server. No precomputed result list.",
           font=font(SEGOE, 27), fill=MUTED)

    # Spatial buckets
    px, py, size = 90, 376, 620
    d.rounded_rectangle([px, py, px + 830, py + 552], radius=16, fill=PANEL,
                        outline=LINE, width=2)
    d.text((px + 30, py + 22), "1 m SPATIAL BUCKETS", font=font(SEGOE_B, 21), fill=CYAN)
    ox, oy, cell = px + 42, py + 86, 46
    cols, rows = 10, 8
    near = {(4, 5), (3, 5), (5, 5), (4, 4), (4, 6)}
    for r in range(rows):
        for c in range(cols):
            x0, y0 = ox + c * cell, oy + r * cell
            fill = (20, 32, 44) if (r, c) not in near else (24, 52, 62)
            d.rectangle([x0, y0, x0 + cell - 2, y0 + cell - 2], fill=fill,
                        outline=(36, 50, 64))
    d.rectangle([ox + 4 * cell, oy + 5 * cell, ox + 5 * cell - 2,
                 oy + 6 * cell - 2], outline=CYAN, width=3)
    dots = [(4, 5, CYAN, "you"), (7, 1, GREEN, ""), (2, 2, AMBER, ""),
            (8, 5, PINK, ""), (1, 6, VIOLET, ""), (6, 6, GREEN, ""),
            (9, 2, AMBER, "")]
    for c, r, col, label in dots:
        cx = ox + c * cell + cell / 2
        cy = oy + r * cell + cell / 2
        d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=col)
    d.text((ox, oy + rows * cell + 18), "bucket = floor(x), floor(y)  ·  neighbours expand the radius",
           font=font(CONSOLA, 18), fill=DIM)
    d.text((ox, oy + rows * cell + 48), "query the player cell, then walk outward",
           font=font(SEGOE, 21), fill=MUTED)

    # Token index
    tx = 976
    d.rounded_rectangle([tx, 376, tx + 854, 928], radius=16, fill=PANEL2,
                        outline=LINE, width=2)
    d.text((tx + 34, 402), "INVERTED TOKEN INDEX", font=font(SEGOE_B, 21), fill=CYAN)
    tokens = [('"tunnel"', ["tunnel-walkway"]),
              ('"exit"', ["emergency-exit"]),
              ('"platform"', ["platforms-1-2"]),
              ('"sign"', ["town-hall-sign"]),
              ('"walkway"', ["tunnel-walkway"])]
    yy = 456
    for token, hits in tokens:
        d.text((tx + 36, yy), token, font=font(CONSOLA_B, 23), fill=AMBER)
        d.text((tx + 214, yy), "→", font=font(CONSOLA, 23), fill=DIM)
        d.text((tx + 254, yy), ", ".join(hits), font=font(CONSOLA, 22), fill=TEXT)
        yy += 44
    d.line([(tx + 34, 694), (tx + 820, 694)], fill=LINE, width=1)
    d.text((tx + 34, 714), "FUZZY FALLBACK", font=font(SEGOE_B, 21), fill=CYAN)
    d.text((tx + 36, 758), "tunel", font=font(CONSOLA_B, 28), fill=PINK)
    d.text((tx + 132, 758), "→ Tunnel Walkway", font=font(CONSOLA, 25), fill=TEXT)
    d.text((tx + 36, 800), "Levenshtein distance ≤ 2", font=font(SEGOE, 22), fill=MUTED)
    d.text((tx + 36, 850), "Ranking: exact, prefix, fuzzy, then proximity.",
           font=font(SEGOE, 20), fill=DIM)
    footer(img, "Built once at load from pois.json; every keystroke re-ranks in memory.")
    save(img, "r2_03_index.png")


def card_verified() -> None:
    img = bg().convert("RGBA")
    d = ImageDraw.Draw(img)
    header(img, "QUALITY GATE")
    d.text((90, 146), "Trust is still", font=font(SEGOE_B, 64), fill=TEXT)
    d.text((90, 220), "a deliverable.", font=font(SEGOE_B, 64), fill=CYAN)
    d.text((94, 312), "Round 2 re-runs every gate, not just the new ones.",
           font=font(SEGOE, 27), fill=MUTED)
    d.rounded_rectangle([1480, 150, 1830, 222], radius=14, fill=(18, 60, 42),
                        outline=GREEN, width=2)
    d.text((1655, 186), "QA PASS", font=font(SEGOE_B, 30), fill=GREEN,
           anchor="mm")

    tiles = [
        ("50 / 50", "web unit tests", "POIs · nav · pathfinding"),
        ("21 / 21", "pipeline tests", "schema · grid · packaging"),
        ("strict", "TypeScript check", "tsc --noEmit"),
        ("954.6 kB", "production JS", "19.6 kB CSS · built"),
        ("76 / 76", "Playwright checks", "desktop · mobile · sandbox"),
        ("27 / 27", "live Pages checks", "same build, public URL"),
    ]
    x0, y0, tw, th, gap = 90, 380, 560, 210, 40
    for i, (value, label, sub) in enumerate(tiles):
        col, row = i % 3, i // 3
        x = x0 + col * (tw + gap)
        y = y0 + row * (th + gap)
        d.rounded_rectangle([x, y, x + tw, y + th], radius=16, fill=PANEL,
                            outline=LINE, width=2)
        d.text((x + 26, y + 24), value, font=font(SEGOE_B, 46), fill=CYAN)
        d.text((x + 26, y + 96), label, font=font(SEGOE_B, 26), fill=TEXT)
        d.text((x + 26, y + 138), sub, font=font(SEGOE, 21), fill=MUTED)
        d.ellipse([x + tw - 48, y + 28, x + tw - 32, y + 44], fill=GREEN)
    d.rounded_rectangle([90, 880, 1830, 952], radius=12, fill=PANEL2,
                        outline=LINE, width=1)
    d.text((116, 900), "Every gate runs in CI. The same evidence is in docs/r2_evidence.md.",
           font=font(SEGOE, 24), fill=TEXT)
    footer(img, "Counts from the R2 branch build; live results re-checked on the public Pages URL.")
    save(img, "r2_04_verified.png")


def card_live() -> None:
    img = Image.open(NAV).convert("RGB")
    img = img.resize((W, H), Image.LANCZOS).convert("RGBA")
    bottom = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bottom)
    for y in range(H - 310, H):
        alpha = int(236 * ((y - (H - 310)) / 310) ** 1.1)
        bd.line([(0, y), (W, y)], fill=(4, 8, 12, alpha))
    img = Image.alpha_composite(img, bottom)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([52, 788, 760, 842], radius=10,
                        fill=(5, 9, 13), outline=(48, 66, 84), width=1)
    d.text((70, 802), "LIVE GITHUB PAGES", font=font(SEGOE_B, 20), fill=CYAN)
    d.text((310, 800), "sciencebanda09.github.io/topoloka",
           font=font(CONSOLA, 20), fill=TEXT)
    d.text((70, 860), "Same seven POIs · same route · same static folder",
           font=font(SEGOE_B, 34), fill=TEXT)
    d.text((70, 914), "No backend, no account, no install.",
           font=font(SEGOE, 24), fill=MUTED)
    d.text((W - 70, 870), "27 / 27 CHECKS PASSED", font=font(SEGOE_B, 24),
           fill=GREEN, anchor="ra")
    save(img, "r2_05_live.png")


def card_nav_failsafe() -> None:
    img = bg().convert("RGBA")
    d = ImageDraw.Draw(img)
    header(img, "NAVIGATION FAILSAFES")
    d.text((90, 146), "The tracker is", font=font(SEGOE_B, 64), fill=TEXT)
    d.text((90, 220), "boring on purpose.", font=font(SEGOE_B, 64), fill=CYAN)
    d.text((94, 312), "Same 5 cm costmap, three guarantees.",
           font=font(SEGOE, 27), fill=MUTED)

    tiles = [
        ("1.2 m", "off-course before reroute", "replans from the current cell"),
        ("0.7 m", "stop radius at the goal", "no overshoot, no jitter"),
        ("10 cm", "planning clearance", "unknown + obstacle cells blocked"),
    ]
    x = 90
    for value, label, sub in tiles:
        d.rounded_rectangle([x, 380, x + 560, 600], radius=16, fill=PANEL,
                            outline=LINE, width=2)
        d.text((x + 28, 404), value, font=font(SEGOE_B, 58), fill=CYAN)
        d.text((x + 28, 486), label, font=font(SEGOE_B, 24), fill=TEXT)
        d.text((x + 28, 530), sub, font=font(SEGOE, 20), fill=MUTED)
        x += 600

    # schematic route
    px, py, pw, ph = 90, 640, 1050, 300
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=16, fill=PANEL2,
                        outline=LINE, width=2)
    d.text((px + 28, py + 20), "REROUTE", font=font(SEGOE_B, 20), fill=CYAN)
    d.line([(px + 40, py + 250), (px + 820, py + 250)], fill=(48, 64, 80), width=18)
    d.line([(px + 40, py + 110), (px + 820, py + 110)], fill=(48, 64, 80), width=18)
    path = [(px + 70, py + 220), (px + 250, py + 220), (px + 370, py + 160),
            (px + 560, py + 160), (px + 660, py + 120), (px + 800, py + 120)]
    d.line(path, fill=(24, 92, 60), width=14, joint="curve")
    d.line(path, fill=GREEN, width=6, joint="curve")
    dashed = [(px + 250, py + 220), (px + 330, py + 190),
              (px + 380, py + 160), (px + 560, py + 160)]
    for i in range(0, len(dashed) - 1):
        d.line([dashed[i], dashed[i + 1]], fill=(150, 110, 70), width=3)
    d.line([(px + 250, py + 220), (px + 330, py + 250)],
           fill=(255, 120, 120), width=3)
    d.ellipse([px + 244, py + 214, px + 256, py + 226], fill=(255, 120, 120))
    d.text((px + 238, py + 178), "1.2 m off course", font=font(SEGOE, 18),
           fill=(255, 160, 150))
    d.ellipse([px + 786, py + 106, px + 814, py + 134], outline=GREEN, width=4)
    d.text((px + 748, py + 64), "goal · 0.7 m", font=font(SEGOE, 18),
           fill=GREEN)
    d.text((px + 28, py + 254), "green = new plan   orange = original heading",
           font=font(SEGOE, 18), fill=DIM)

    # overlay note
    nx, nw = 1170, 660
    d.rounded_rectangle([nx, 640, nx + nw, 940], radius=16, fill=PANEL,
                        outline=LINE, width=2)
    d.text((nx + 30, 666), "AFTER-SPLAT OVERLAY", font=font(SEGOE_B, 21), fill=CYAN)
    body = ("The ribbon and POI rings draw after the Gaussian splat pass. "
            "Without that second pass, the splat paints over every transparent "
            "3-D object.")
    y = 714
    for line in wrap(d, body, font(SEGOE, 23), nw - 60):
        d.text((nx + 30, y), line, font=font(SEGOE, 23), fill=TEXT)
        y += 36
    d.line([(nx + 30, 872), (nx + nw - 30, 872)], fill=LINE, width=1)
    d.text((nx + 30, 888), "Same path on floor and minimap.",
           font=font(SEGOE, 19), fill=MUTED)
    footer(img, "Thresholds from the shipped tracker; route drawn from nav.json waypoints.")
    save(img, "r2_04b_nav_failsafe.png")


def card_overlay_still() -> None:
    src = OUT / "source" / "nav_overlay.png"
    img = Image.open(src).convert("RGBA")
    img = img.resize((W, H), Image.LANCZOS)
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(H - 300, H):
        alpha = int(238 * ((y - (H - 300)) / 300) ** 1.1)
        sd.line([(0, y), (W, y)], fill=(4, 8, 12, alpha))
    img = Image.alpha_composite(img, shade)
    d = ImageDraw.Draw(img)
    d.text((70, 824), "AFTER-SPLAT OVERLAY", font=font(SEGOE_B, 21), fill=CYAN)
    d.text((70, 866), "Ribbon + ring, drawn after the Gaussian pass",
           font=font(SEGOE_B, 34), fill=TEXT)
    d.text((70, 918), "Same plan on the floor and on the minimap.",
           font=font(SEGOE, 23), fill=MUTED)
    d.text((W - 70, 878), "0.46 M GAUSSIANS · 315.05 m² WALKABLE",
           font=font(SEGOE_B, 20), fill=GREEN, anchor="ra")
    save(img, "r2_04c_nav_overlay.png")


def card_close() -> None:
    img = bg().convert("RGBA")
    d = ImageDraw.Draw(img)
    header(img, "CLOSE")
    d.text((90, 150), "Search. Route. Arrive.", font=font(SEGOE_B, 70), fill=TEXT)
    d.text((94, 250), "The Round 2 build is live, and Round 3 adds AR.",
           font=font(SEGOE, 30), fill=MUTED)

    d.rounded_rectangle([90, 336, 1140, 780], radius=18, fill=PANEL,
                        outline=LINE, width=2)
    links = [
        ("LIVE TWIN", "sciencebanda09.github.io/topoloka/"),
        ("SOURCE", "github.com/sciencebanda09/topoloka"),
        ("BRANCH", "tree/r2-pois-nav"),
        ("EVIDENCE", "docs/r2_evidence.md"),
        ("CONTRACT", "test/metro_v1/nav/pois.json"),
    ]
    y = 372
    for label, value in links:
        d.text((122, y + 2), label, font=font(SEGOE_B, 20), fill=DIM)
        d.text((330, y), value, font=font(CONSOLA, 24), fill=TEXT)
        y += 76

    d.rounded_rectangle([1190, 336, 1830, 780], radius=18, fill=PANEL2,
                        outline=LINE, width=2)
    d.text((1222, 372), "ROUND 3", font=font(SEGOE_B, 22), fill=GREEN)
    d.text((1222, 420), "On-site", font=font(SEGOE_B, 42), fill=TEXT)
    d.text((1222, 470), "QR-fiducial", font=font(SEGOE_B, 42), fill=TEXT)
    d.text((1222, 520), "AR tracking.", font=font(SEGOE_B, 42), fill=CYAN)
    for i, line in enumerate(["Same static pipeline", "Same POI contract",
                              "Same browser viewer"]):
        d.text((1222, 606 + i * 46), "→  " + line, font=font(SEGOE, 24),
               fill=MUTED)

    d.text((94, 846), "One video in. Google Maps for indoors out.",
           font=font(SEGOE_L, 42), fill=CYAN)
    d.text((94, 920), "Code MIT · source clip Pexels License · capture limitations documented",
           font=font(SEGOE, 21), fill=DIM)
    footer(img, "Topoloka · Techfest 2026–27 · Round 2 submission")
    save(img, "r2_06_close.png")


def main() -> None:
    if not HERO.exists() or not NAV.exists():
        raise SystemExit("missing hero/nav screenshots")
    card_title()
    card_contract()
    card_index()
    card_verified()
    card_live()
    card_nav_failsafe()
    card_overlay_still()
    card_close()


if __name__ == "__main__":
    main()
