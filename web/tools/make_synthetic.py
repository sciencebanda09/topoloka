"""Generate a synthetic artifact bundle for viewer smoke tests.

Writes web/public/artifacts/synthetic/:
    nav.json       room 6x2 m, walls + furniture as obstacles, walk loop
    cloud.ply      sparse points in the NAV frame (what package.py emits)
    splat.splat    gaussians in a DELIBERATELY different "scene frame"
    meta.json

The scene frame is the nav frame rotated 90 deg about z, scaled x2, and
offset -- exactly what nav.json's `align` block then undoes. If the viewer's
splat placement math is wrong, the splat will visibly sit in the wrong spot
relative to the floor grid / outline / cloud.

Run:  ..\.venv\Scripts\python.exe web\tools\make_synthetic.py
"""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "public" / "artifacts" / "synthetic"

ROOM = (-3.0, 3.0, -2.0, 2.0)   # x0, x1, y0, y1 (meters)
CEIL = 2.5
CELL = 0.05
FREE, OBSTACLE, UNKNOWN = 0, 1, 2

# scene frame: p_scene = origin + R @ p_nav / scale
R_Z90 = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
SCALE = 2.0
ORIGIN = np.array([10.0, -5.0, 0.7])


def nav_to_scene(p: np.ndarray) -> np.ndarray:
    return ORIGIN + (p @ R_Z90.T) / SCALE


def main() -> None:
    rng = np.random.default_rng(7)
    x0, x1, y0, y1 = ROOM
    w = int(round((x1 - x0) / CELL))
    h = int(round((y1 - y0) / CELL))
    grid = np.full((h, w), UNKNOWN, np.uint8)

    def cell(px: float, py: float) -> tuple[int, int]:
        return int((py - y0) / CELL), int((px - x0) / CELL)

    # interior + walls
    for gy in range(h):
        for gx in range(w):
            px = x0 + (gx + 0.5) * CELL
            py = y0 + (gy + 0.5) * CELL
            on_wall = (abs(px - x0) < 0.1 or abs(px - x1) < 0.1
                       or abs(py - y0) < 0.1 or abs(py - y1) < 0.1)
            doorway = (abs(py - 0.0) < 0.6 and abs(px - x1) < 0.2)
            furniture = (-1.6 < px < -0.4 and 0.4 < py < 1.6) or (0.8 < px < 1.8 and -1.2 < py < -0.4)
            if on_wall and not doorway:
                grid[gy, gx] = OBSTACLE
            elif furniture:
                grid[gy, gx] = OBSTACLE
            else:
                grid[gy, gx] = FREE

    # walk loop trajectory (free space), staying clear of furniture
    loop_xy = [(0.0, -1.4), (1.4, -1.4), (2.2, -0.5), (2.2, 1.2), (0.6, 1.6),
               (-0.8, 1.6), (-2.2, 0.8), (-2.4, -0.8), (-1.6, -1.4), (0.0, -1.4)]
    traj = []
    for i in range(len(loop_xy) - 1):
        ax, ay = loop_xy[i]
        bx, by = loop_xy[i + 1]
        for t in np.linspace(0, 1, 20, endpoint=False):
            px, py = ax + (bx - ax) * t, ay + (by - ay) * t
            traj.append([px, py, 1.6])
            gy, gx = cell(px, py)
            if 0 <= gy < h and 0 <= gx < w:
                grid[max(0, gy - 2):gy + 3, max(0, gx - 2):gx + 3] = FREE

    outline = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]

    png_ok, png = cv2.imencode(".png", grid, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    assert png_ok
    nav = {
        "version": 1,
        "units": "meters",
        "cell_m": CELL,
        "origin": [x0, y0],
        "grid": {"w": w, "h": h, "encoding": "uint8-png-base64",
                 "legend": {"0": "free", "1": "obstacle", "2": "unknown"},
                 "data_b64": base64.b64encode(png.tobytes()).decode("ascii")},
        "outline": outline,
        "trajectory": traj,
        "scale_m_per_unit": SCALE,
        "scale_source": "synthetic",
        "cam_height_units": 1.6 / SCALE,
        "down_axis_source": "synthetic",
        "align": {"R_row_major": R_Z90.tolist(), "origin": ORIGIN.tolist(),
                  "scale_m_per_unit": SCALE,
                  "formula": "p_nav_m = scale * R^T @ (p_scene_units - origin)"},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "nav.json").write_text(json.dumps(nav), encoding="utf-8")

    # ---- point cloud in NAV frame (like package.py output) -----------------
    pts, cols = [], []
    for _ in range(6000):
        px = rng.uniform(x0 + 0.1, x1 - 0.1)
        py = rng.uniform(y0 + 0.1, y1 - 0.1)
        z = rng.uniform(0.0, CEIL)
        on_wall = (abs(px - x0) < 0.15 or abs(px - x1) < 0.15
                   or abs(py - y0) < 0.15 or abs(py - y1) < 0.15)
        if not on_wall and z > 0.25:
            continue
        # push near-wall points onto the wall
        if abs(px - x0) < 0.15: px = x0 + 0.02
        if abs(px - x1) < 0.15: px = x1 - 0.02
        if abs(py - y0) < 0.15: py = y0 + 0.02
        if abs(py - y1) < 0.15: py = y1 - 0.02
        pts.append([px, py, z])
        cols.append([180, 180, 175] if z < 0.25 else [90 + rng.integers(0, 60), 95, 110])
    pts = np.asarray(pts, np.float32)
    cols = np.asarray(cols, np.uint8)
    _write_ply(OUT / "cloud.ply", pts, cols)

    # ---- splat in SCENE frame ---------------------------------------------
    # gaussians on walls + floor of the room, expressed in the scene frame
    splat_pts, splat_cols = [], []
    for _ in range(12000):
        face = rng.integers(0, 6)
        if face == 0:   # floor
            p = [rng.uniform(x0, x1), rng.uniform(y0, y1), 0.02]
            c = [120, 110, 100]
        elif face == 1:  # ceiling
            p = [rng.uniform(x0, x1), rng.uniform(y0, y1), CEIL - 0.02]
            c = [230, 230, 225]
        elif face == 2:
            p = [x0 + 0.02, rng.uniform(y0, y1), rng.uniform(0, CEIL)]
            c = [150, 120, 110]
        elif face == 3:
            p = [x1 - 0.02, rng.uniform(y0, y1), rng.uniform(0, CEIL)]
            c = [110, 130, 150]
        elif face == 4:
            p = [rng.uniform(x0, x1), y0 + 0.02, rng.uniform(0, CEIL)]
            c = [130, 140, 120]
        else:
            p = [rng.uniform(x0, x1), y1 - 0.02, rng.uniform(0, CEIL)]
            c = [140, 125, 135]
        splat_pts.append(nav_to_scene(np.asarray(p, np.float64)))
        splat_cols.append(c)
    _write_splat(OUT / "splat.splat", np.asarray(splat_pts, np.float32),
                 np.asarray(splat_cols, np.uint8))

    (OUT / "meta.json").write_text(json.dumps({
        "capture": "synthetic",
        "note": "viewer smoke-test fixture (not pipeline output)",
        "cloud_points": int(len(pts)),
        "blocks": True,
        "timing_seconds": 0,
        "walkable_area_m2": round(float((grid == FREE).sum()) * CELL * CELL, 1),
        "qa_overall": "SYNTHETIC",
        "splat": {"present": True, "gaussians": 12000},
    }, indent=2), encoding="utf-8")
    print(f"[synthetic] wrote {OUT}")


def _write_ply(path: Path, xyz: np.ndarray, rgb: np.ndarray) -> None:
    header = ("ply\nformat binary_little_endian 1.0\n"
              f"element vertex {len(xyz)}\n"
              "property float x\nproperty float y\nproperty float z\n"
              "property uchar red\nproperty uchar green\nproperty uchar blue\n"
              "end_header\n").encode("ascii")
    with open(path, "wb") as f:
        f.write(header)
        f.write(xyz.astype("<f4").tobytes())
        f.write(rgb.astype(np.uint8).tobytes())


def _write_splat(path: Path, xyz: np.ndarray, rgb: np.ndarray) -> None:
    """32-byte records: pos f32x3, scale f32x3 (linear), rgba u8x4, rot u8x4 (w,x,y,z)."""
    n = len(xyz)
    rec = np.zeros((n, 32), np.uint8)
    scale = np.full((n, 3), 0.06, np.float32)  # 6 cm gaussians
    color = np.ones((n, 4), np.uint8) * 255
    color[:, :3] = rgb
    rot = np.zeros((n, 4), np.uint8)
    rot[:, 0] = 255  # w=~1, normalized by the parser anyway
    rec[:, 0:12] = xyz.astype("<f4").view(np.uint8).reshape(n, 12)
    rec[:, 12:24] = scale.astype("<f4").view(np.uint8).reshape(n, 12)
    rec[:, 24:28] = color
    rec[:, 28:32] = rot
    path.write_bytes(rec.tobytes())


if __name__ == "__main__":
    main()
