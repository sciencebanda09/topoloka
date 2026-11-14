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

from namma.geometry import CHEST_HEIGHT_M, FREE, OBSTACLE, align_scene, build_costmap  # noqa: E402


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


def test_build_costmap_carves_walked_corridor_without_erasing_distant_walls():
    # Floor around origin + a wall 1.5 m away + noisy obstacle 0.2 m from trajectory
    xs = np.linspace(-2.0, 2.0, 41)
    gx, gy = np.meshgrid(xs, xs)
    floor = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)])
    noisy = np.array([[0.20, 0.0, 0.6], [0.20, 0.5, 0.6]])
    wall = np.column_stack([np.full(61, 1.5), np.linspace(-1.5, 1.5, 61), np.full(61, 0.8)])
    pts = np.vstack([floor, noisy, wall])
    traj = np.column_stack([np.zeros(21), np.linspace(-1.0, 1.0, 21), np.full(21, 1.4)])

    grid, lo, cell = build_costmap(pts, traj)
    c_noisy = (int((0.20 - lo[0]) / cell), int((0.0 - lo[1]) / cell))
    c_wall = (int((1.5 - lo[0]) / cell), int((0.0 - lo[1]) / cell))
    assert grid[c_noisy[1], c_noisy[0]] == FREE
    assert grid[c_wall[1], c_wall[0]] == OBSTACLE


def test_build_costmap_continuous_carving_bridges_strided_poses():
    xs = np.linspace(-3.0, 3.0, 61)
    gx, gy = np.meshgrid(xs, xs)
    floor = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)])
    # Spaced keyframes (~1.2 m apart) with spurious obstacle noise on the straight line between them
    mid_noise = np.column_stack([np.full(13, 0.0), np.linspace(-1.8, 1.8, 13), np.full(13, 0.7)])
    pts = np.vstack([floor, mid_noise])
    traj = np.array([[0.0, -2.4, 1.4], [0.0, -1.2, 1.4], [0.0, 0.0, 1.4], [0.0, 1.2, 1.4], [0.0, 2.4, 1.4]])

    grid, lo, cell = build_costmap(pts, traj)
    col_x = int(round((0.0 - lo[0]) / cell))
    for y in (-1.8, -0.6, 0.6, 1.8):
        row_y = int(round((y - lo[1]) / cell))
        assert grid[row_y, col_x] == FREE


def test_align_scene_gravity_ransac_survives_dominant_vertical_walls():
    rng = np.random.default_rng(7)
    # Wall has 5x more points than the horizontal floor (mimics masonry-heavy hallways like guildhall-v2)
    wall = np.column_stack([rng.uniform(-4, 4, 2500), np.full(2500, 1.5), rng.uniform(0.1, 3.0, 2500)])
    floor = np.column_stack([rng.uniform(-4, 4, 500), rng.uniform(-2, 2, 500), np.zeros(500)])
    pts = np.vstack([wall, floor]).astype(np.float32)
    cams = np.column_stack([np.linspace(-2, 2, 12), np.zeros(12), np.full(12, 1.4)])
    down = np.array([0.0, 0.0, -1.0])

    R, _origin, scale, info = align_scene(pts, cams, down)
    assert info["floor_inliers"] >= 450
    assert abs(scale - 1.35 / 1.4) < 0.05
    assert R[2, 2] > 0.99


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok   {t.__name__}")
    print(f"OK: {len(tests)} geometry-align tests passed")


if __name__ == "__main__":
    main()
