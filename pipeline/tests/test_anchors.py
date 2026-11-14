"""QR anchor PnP localization -> metric nav frame tests."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from namma.anchors import solve_qr_pose_nav  # noqa: E402


def test_solve_qr_pose_nav_recovers_metric_marker_position():
    # Camera at scene origin looking down +Z (camera frame == scene frame)
    # Scale = 2.0 m/unit, identity rotation R, origin = [0, 0, 0].
    # Place a 0.20 m square marker at z_cam = 2.0 m (which is 1.0 scene unit -> 2.0 m nav).
    K = np.array([[800.0, 0.0, 400.0], [0.0, 800.0, 300.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    half = 0.10
    pts_3d = np.array([
        [-half, -half, 2.0],
        [half, -half, 2.0],
        [half, half, 2.0],
        [-half, half, 2.0],
    ], dtype=np.float64)
    proj, _ = cv2.projectPoints(pts_3d, np.zeros(3), np.zeros(3), K, None)
    corners_px = proj.reshape(4, 2)

    w2c = np.eye(4, dtype=np.float64)
    align = {
        "R_row_major": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "origin": [0.0, 0.0, 0.0],
        "scale_m_per_unit": 2.0,
    }
    solved = solve_qr_pose_nav(corners_px, K, w2c, align, marker_size_m=0.20)
    assert solved is not None
    pos_nav, normal_nav = solved
    assert np.allclose(pos_nav, [0.0, 0.0, 2.0], atol=0.03), pos_nav
    assert abs(abs(normal_nav[2]) - 1.0) < 0.05, normal_nav
