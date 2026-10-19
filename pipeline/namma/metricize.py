"""Scale the training inputs to meters, using the depth stage's scale estimate.

The splat frame contract:
    The depth stage writes a METRIC cloud (depth/map.npz) and metric poses
    (sfm/poses_m.json); geometry then builds nav.json's align against that
    metric frame (align.scale_m_per_unit = 1.0, source "metric-input"). The
    splat, however, trains from transforms.json + sparse.ply, which stay in
    raw SfM units (arbitrary scale). nav.json's align maps the SPLAT'S
    TRAINING FRAME -> nav, so training in SfM units while align says "metric"
    would place the splat off by 1/scale (2.29x for the house capture).

    This stage multiplies camera centers in transforms.json and points in
    sparse.ply by the depth scale. A uniform world scaling leaves rotations,
    intrinsics and the image files untouched. Afterwards the training frame
    is metric and one align serves cloud + splat + trajectory.

    If the depth stage did not run, skip this stage: geometry then built the
    align against the SfM cloud, and SfM-frame training is consistent.

Writes metricize.json (scale, counts). Re-running with the same scale is a
no-op; a different scale after one was applied refuses (it would stack).
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

import numpy as np

from .geometry import load_cloud
from .package import _write_ply


def _read_scale(capture_dir: Path) -> float:
    scale_path = capture_dir / "depth" / "scale.json"
    if not scale_path.exists():
        raise SystemExit(f"missing {scale_path} (run `depth` first, or stay in SfM units)")
    scale = float(json.loads(scale_path.read_text(encoding="utf-8"))["scale_m_per_unit"])
    if not (0 < scale < 1e6):
        raise SystemExit(f"implausible depth scale {scale!r}")
    return scale


def _scale_transforms(capture_dir: Path, scale: float) -> int:
    """Multiply the camera-center (translation) column of every c2w matrix."""
    tf_path = capture_dir / "transforms.json"
    if not tf_path.exists():
        raise SystemExit(f"missing {tf_path}")
    tf = json.loads(tf_path.read_text(encoding="utf-8"))
    for fr in tf["frames"]:
        m = fr["transform_matrix"]
        for i in range(3):
            m[i][3] *= scale
    tmp = tf_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tf), encoding="utf-8")
    os.replace(tmp, tf_path)
    return len(tf["frames"])


def _scale_cloud(capture_dir: Path, scale: float) -> int:
    """Scale sparse.ply points (interleaved PLY, colors preserved)."""
    ply_path = capture_dir / "sfm" / "sparse.ply"
    if not ply_path.exists():
        raise SystemExit(f"missing {ply_path}")
    xyz, rgb = load_cloud(ply_path)
    xyz = (xyz.astype(np.float64) * scale).astype(np.float32)
    tmp = ply_path.with_suffix(".ply.tmp")
    _write_ply(tmp, xyz, rgb)
    os.replace(tmp, ply_path)
    return len(xyz)


def run_metricize(capture_dir: Path) -> dict:
    capture_dir = Path(capture_dir)
    t0 = time.time()
    scale = _read_scale(capture_dir)

    marker = capture_dir / "metricize.json"
    if marker.exists():
        prev = json.loads(marker.read_text(encoding="utf-8"))
        if math.isclose(float(prev.get("scale_m_per_unit", -1)), scale, rel_tol=1e-9):
            print(f"[metricize] already metric at scale {scale:.6f}; no-op")
            return prev
        raise SystemExit("capture was metricized with a different scale "
                         f"({prev.get('scale_m_per_unit')} vs {scale}); refusing to stack scales")

    n_frames = _scale_transforms(capture_dir, scale)
    n_points = _scale_cloud(capture_dir, scale)

    report = {
        "stage": "metricize",
        "status": "ok",
        "scale_m_per_unit": scale,
        "frames_scaled": n_frames,
        "points_scaled": n_points,
        "timing_seconds": round(time.time() - t0, 2),
        "note": "transforms.json camera centers + sfm/sparse.ply points *= depth scale",
    }
    marker.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[metricize] {n_frames} cameras + {n_points} points x {scale:.6f} "
          f"({report['timing_seconds']}s)")
    return report
