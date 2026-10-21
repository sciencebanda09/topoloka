"""Render the abstract figures from pipeline artifacts.

    docs/fig/nav.png       occupancy grid + floor outline + camera path
                           (from <out>/nav.json; the shipped occupancy.png is a
                           debug dump with values 0..2, unreadable at print size)
    docs/fig/pipeline.png  stage diagram (what runs where)

Usage (repo root, venv python):
    .venv\\Scripts\\python.exe tools\\make_figures.py
    .venv\\Scripts\\python.exe tools\\make_figures.py --nav kaggle/out/namma_splat/out/nav.json
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "fig"

FREE, OBSTACLE, UNKNOWN = 0, 1, 2
COLORS = np.array(
    [
        [255, 255, 255],  # free
        [192, 57, 43],    # obstacle
        [236, 239, 242],  # unknown
    ],
    dtype=np.uint8,
)


def load_grid(nav: dict) -> np.ndarray:
    raw = base64.b64decode(nav["grid"]["data_b64"])
    img = Image.open(io.BytesIO(raw))
    return np.array(img)


def in_bounds(grid: np.ndarray, cells: np.ndarray) -> np.ndarray:
    h, w = grid.shape
    return ((cells[:, 0] >= 0) & (cells[:, 0] < w)
            & (cells[:, 1] >= 0) & (cells[:, 1] < h))


def pick_row_direction(grid: np.ndarray, origin, cell, traj2d: np.ndarray) -> int:
    """Return +1 if row 0 is at y=origin (bottom-up), -1 if row 0 is the top row.

    Decided by which reading lands the camera path on free cells; the transform
    is then at least self-consistent with the artifacts it draws.
    """
    h = grid.shape[0]
    best, best_score = 1, -1
    for direction in (1, -1):
        rows = np.rint((traj2d[:, 1] - origin[1]) / cell).astype(int)
        rows = rows if direction == 1 else (h - 1 - rows)
        cols = np.rint((traj2d[:, 0] - origin[0]) / cell).astype(int)
        cells = np.stack([cols, rows], axis=1)
        ok = in_bounds(grid, cells)
        score = int((grid[cells[ok, 1], cells[ok, 0]] == FREE).sum())
        if score > best_score:
            best, best_score = direction, score
    return best


def render_nav(nav_path: Path, out_path: Path) -> dict:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    nav = json.loads(nav_path.read_text(encoding="utf-8"))
    grid = load_grid(nav)
    h, w = grid.shape
    cell = float(nav["cell_m"])
    ox, oy = (float(v) for v in nav["origin"])

    traj = np.asarray(nav["trajectory"], dtype=float)
    traj2d = traj[:, :2]
    direction = pick_row_direction(grid, (ox, oy), cell, traj2d)

    rgb = COLORS[np.clip(grid.astype(int), 0, 2)]
    # Viewer convention (web/src/minimap.ts): row 0 is at y = origin[1], rows
    # increasing with y. With matplotlib origin='lower' that is the raster as-is.
    rgb_plot = rgb if direction == 1 else rgb[::-1]
    extent = (ox, ox + w * cell, oy, oy + h * cell)

    fig, ax = plt.subplots(figsize=(6.4, 5.6))
    ax.imshow(rgb_plot, origin="lower", extent=extent,
              interpolation="nearest", zorder=1)

    outline = np.asarray(nav["outline"], dtype=float)
    if len(outline):
        closed = np.vstack([outline, outline[:1]])
        ax.plot(closed[:, 0], closed[:, 1], color="#0d2b45", lw=1.2, zorder=3)

    ax.plot(traj2d[:, 0], traj2d[:, 1], color="#0b5fa5", lw=1.4, zorder=4)
    ax.scatter(*traj2d[0], s=32, color="#2e7d32", zorder=5)
    ax.scatter(*traj2d[-1], s=32, color="#0b5fa5", marker="s", zorder=5)

    from matplotlib.lines import Line2D
    handles = [
        Patch(facecolor="#ffffff", edgecolor="#c9ced6", label="free (visited)"),
        Patch(facecolor="#c0392b", label="obstacle (0.1-1.5 m)"),
        Patch(facecolor="#eceff3", label="unobserved"),
        Line2D([], [], color="#0d2b45", lw=1.2, label="floor outline"),
        Line2D([], [], color="#0b5fa5", lw=1.4, label="camera path"),
        Line2D([], [], marker="o", ls="", color="#2e7d32", label="start"),
        Line2D([], [], marker="s", ls="", color="#0b5fa5", label="end"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=7.0,
              framealpha=0.95, borderpad=0.4, labelspacing=0.3)

    report = json.loads((nav_path.parent / "nav_report.json").read_text(encoding="utf-8")) \
        if (nav_path.parent / "nav_report.json").exists() else {}
    area = report.get("walkable_area_m2")
    title = "House capture: metric occupancy grid"
    if area:
        title += f" -- {area:.2f} m² walkable"
    ax.set_title(title, fontsize=10.5)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_aspect("equal")
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return {"grid": [w, h], "cell_m": cell, "row_direction": direction,
            "walkable_area_m2": area, "out": str(out_path)}


def render_pipeline(out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    stages = [
        ("phone capture\n(SOP: slow walk)", "capture"),
        ("frames\nsharpest @ 2.5 Hz", "cpu"),
        ("SfM\npycolmap 4.2.1", "cpu"),
        ("metric depth\nDepth Anything V2", "gpu"),
        ("geometry\nfloor + 5 cm costmap", "gpu"),
        ("metricize\n(SfM -> metres)", "gpu"),
        ("splatfacto\n20k it, 1.5 M caps", "gpu"),
        ("package\ntwin + nav.json", "local"),
        ("web viewer\nstatic link", "web"),
    ]
    tints = {
        "capture": "#e8f1f8",
        "cpu": "#eef3ee",
        "gpu": "#efeaf6",
        "local": "#fdf1e3",
        "web": "#e6f4f1",
    }
    edges = {
        "capture": "#2d6a9f",
        "cpu": "#4b7a4b",
        "gpu": "#6a4b9f",
        "local": "#b0722d",
        "web": "#2d8a7a",
    }

    fig, ax = plt.subplots(figsize=(13.0, 2.9))
    ax.set_xlim(0, len(stages) * 2.5)
    ax.set_ylim(0, 2.2)
    ax.axis("off")

    width, height = 2.1, 0.95
    centers = []
    for i, (label, kind) in enumerate(stages):
        x = 0.15 + i * 2.5
        y = 0.65
        box = FancyBboxPatch(
            (x, y), width, height,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            linewidth=1.3, edgecolor=edges[kind], facecolor=tints[kind], zorder=2,
        )
        ax.add_patch(box)
        ax.text(x + width / 2, y + height / 2, label, ha="center", va="center",
                fontsize=8.0, color="#16222e", zorder=3)
        centers.append((x, y, width, height))
        if i:
            px, py, pw, ph = centers[i - 1]
            ax.add_patch(FancyArrowPatch(
                (px + pw + 0.02, py + ph / 2), (x - 0.02, py + ph / 2),
                arrowstyle="-|>", mutation_scale=11, linewidth=1.1,
                color="#6b7785", zorder=2,
            ))

    groups = [
        ("phone", 0, 0, "capture"),
        ("Kaggle CPU kernel", 1, 2, "cpu"),
        ("Kaggle GPU kernel", 3, 6, "gpu"),
        ("repo tooling", 7, 7, "local"),
        ("any static host", 8, 8, "web"),
    ]
    for label, a, b, kind in groups:
        x0, y0, w0, h0 = centers[a]
        x1 = centers[b][0] + centers[b][2]
        ax.plot([x0, x1], [1.86, 1.86], color=edges[kind], lw=1.0, alpha=0.55)
        ax.plot([x0, x0], [1.86, 1.80], color=edges[kind], lw=1.0, alpha=0.55)
        ax.plot([x1, x1], [1.86, 1.80], color=edges[kind], lw=1.0, alpha=0.55)
        ax.text((x0 + x1) / 2, 1.98, label, ha="center", va="bottom",
                fontsize=8.0, color=edges[kind])

    ax.text(len(stages) * 2.5 / 2, 0.22,
            "one phone video in  ->  splat + metric nav graph out  ->  a link anyone can open",
            ha="center", va="center", fontsize=9.0, color="#33424f", style="italic")

    fig.tight_layout(pad=0.2)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nav", type=Path,
                    default=ROOT / "kaggle/out/namma_splat/out/nav.json")
    ap.add_argument("--out-dir", type=Path, default=FIG)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if not args.nav.exists():
        raise SystemExit(f"nav.json not found: {args.nav}")

    info = render_nav(args.nav, args.out_dir / "nav.png")
    print("nav figure:", json.dumps(info))
    render_pipeline(args.out_dir / "pipeline.png")
    print(f"pipeline figure: {args.out_dir / 'pipeline.png'}")


if __name__ == "__main__":
    sys.exit(main())
