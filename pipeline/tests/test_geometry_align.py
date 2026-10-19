"""Floor alignment / metric scale tests.

2026-10-19 bug: align_scene() negated the camera height above the floor plane,
so cam_height_units was always <= -0.4 -> clamped to 0.2 -> every heuristic
run (fixed_scale=None) got scale = CHEST_HEIGHT_M / 0.2 = 6.75 no matter how
high the phone actually was. These tests pin the sign and the recovered scale.

Run:  .venv\\Scripts\\python.exe pipeline\\tests\\test_geometry_align.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from namma.geometry import CHEST_HEIGHT_M, align_scene  # noqa: E402


def _scene(cam_z: float, seed: int = 3):
    """Floor at z=0 (world z up), cameras around cam_z, one vertical wall."""
    rng = np.random.default_rng(seed)
    floor = np.column_stack([rng.uniform(-3, 3, 500), rng.uniform(-3, 3, 500),
                             np.zeros(500)])
    wall = np.column_stack([rng.uniform(-3, 3, 120), np.full(120, 3.0),
                            rng.uniform(0.0, 2.0, 120)])
    points = np.vstack([floor, wall])
    cam_centers = np.array([[0.0, 0.0, cam_z], [0.5, 0.0, cam_z + 0.05],
                            [0.0, 1.0, cam_z - 0.05]])
    down = np.array([0.0, 0.0, -1.0])
    return points, cam_centers, down


def test_cam_height_sign_and_scale():
    points, cams, down = _scene(1.5)
    R, origin, scale, info = align_scene(points, cams, down)
    assert abs(info["cam_height_units"] - 1.5) < 0.05, info
    assert abs(scale - CHEST_HEIGHT_M / 1.5) < 0.02, scale


def test_floor_maps_to_z0_and_camera_reads_chest_height():
    points, cams, down = _scene(1.2)
    R, origin, scale, info = align_scene(points, cams, down)
    # a floor point lands on z=0 in the aligned metric frame
    p = ((np.array([2.0, -1.0, 0.0]) - origin) @ R) * scale
    assert abs(p[2]) < 0.02, p
    # camera mean height reads back as CHEST_HEIGHT_M (that's the heuristic)
    cam_m = ((cams.mean(axis=0) - origin) @ R) * scale
    assert abs(cam_m[2] - CHEST_HEIGHT_M) < 0.05, cam_m


def test_fixed_scale_skips_the_heuristic():
    points, cams, down = _scene(1.5)
    _, _, scale, _ = align_scene(points, cams, down, fixed_scale=2.0)
    assert scale == 2.0


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok   {t.__name__}")
    print(f"OK: {len(tests)} geometry-align tests passed")


if __name__ == "__main__":
    main()
