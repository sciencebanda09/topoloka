"""metricize stage tests.

The frame contract: nav.json's align maps the splat's TRAINING frame -> nav.
The GPU path computes a metric scale in the depth stage; if training stays in
raw SfM units the shipped splat would be placed off by 1/scale (6.25x for the
station capture). metricize scales transforms.json camera centers + sparse.ply
points to meters, making one align correct for cloud + splat + trajectory.

Run:  .venv\\Scripts\\python.exe pipeline\\tests\\test_metricize.py
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from namma.geometry import load_cloud  # noqa: E402
from namma.metricize import run_metricize  # noqa: E402
from namma.package import _write_ply  # noqa: E402

SCALE = 0.5


def _make_capture(root: Path, scale: float = SCALE) -> dict:
    (root / "sfm").mkdir(parents=True)
    (root / "depth").mkdir()
    tf = {
        "camera_model": "SIMPLE_RADIAL",
        "w": 640,
        "h": 480,
        "fl_x": 500.0,
        "fl_y": 500.0,
        "cx": 320.0,
        "cy": 240.0,
        "ply_file_path": "sparse.ply",
        "frames": [
            {"file_path": "frames/00000.jpg",
             "transform_matrix": [[1, 0, 0, 10.0], [0, 1, 0, 20.0],
                                  [0, 0, 1, 30.0], [0, 0, 0, 1]]},
            {"file_path": "frames/00001.jpg",
             "transform_matrix": [[1, 0, 0, -4.0], [0, 1, 0, 8.0],
                                  [0, 0, 1, 2.0], [0, 0, 0, 1]]},
        ],
    }
    (root / "transforms.json").write_text(json.dumps(tf), encoding="utf-8")
    xyz = np.array([[10.0, 20.0, 30.0], [-4.0, 8.0, 2.0], [1.0, 1.0, 1.0]],
                   np.float32)
    rgb = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], np.uint8)
    _write_ply(root / "sfm" / "sparse.ply", xyz, rgb)
    (root / "depth" / "scale.json").write_text(
        json.dumps({"scale_m_per_unit": scale}), encoding="utf-8")
    return {"tf": tf, "xyz": xyz, "rgb": rgb}


def test_scales_transforms_and_cloud():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ref = _make_capture(root)
        rep = run_metricize(root)

        tf = json.loads((root / "transforms.json").read_text(encoding="utf-8"))
        for before, after in zip(ref["tf"]["frames"], tf["frames"]):
            for i in range(3):
                assert abs(after["transform_matrix"][i][3]
                           - before["transform_matrix"][i][3] * SCALE) < 1e-6
        # rotation part untouched
        assert tf["frames"][0]["transform_matrix"][0][:3] == [1, 0, 0]

        xyz, rgb = load_cloud(root / "sfm" / "sparse.ply")
        assert np.allclose(xyz, ref["xyz"] * SCALE, atol=1e-5)
        assert np.array_equal(rgb, ref["rgb"])  # colors preserved
        assert rep["scale_m_per_unit"] == SCALE
        assert rep["frames_scaled"] == 2 and rep["points_scaled"] == 3
        assert (root / "metricize.json").exists()


def test_idempotent_same_scale():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_capture(root)
        run_metricize(root)
        tf1 = (root / "transforms.json").read_text(encoding="utf-8")
        ply1 = (root / "sfm" / "sparse.ply").read_bytes()
        rep = run_metricize(root)  # must be a no-op, not a double scale
        assert (root / "transforms.json").read_text(encoding="utf-8") == tf1
        assert (root / "sfm" / "sparse.ply").read_bytes() == ply1
        assert rep["scale_m_per_unit"] == SCALE


def test_refuses_different_scale_after_metricize():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _make_capture(root)
        run_metricize(root)
        (root / "depth" / "scale.json").write_text(
            json.dumps({"scale_m_per_unit": 0.7}), encoding="utf-8")
        try:
            run_metricize(root)
        except SystemExit:
            pass
        else:
            raise AssertionError("expected SystemExit on stacking a new scale")


def test_missing_scale_is_an_error():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ref = copy.deepcopy(_make_capture(root))
        (root / "depth" / "scale.json").unlink()
        try:
            run_metricize(root)
        except SystemExit:
            pass
        else:
            raise AssertionError("expected SystemExit when depth/scale.json is missing")
        # inputs untouched
        tf = json.loads((root / "transforms.json").read_text(encoding="utf-8"))
        assert tf == ref["tf"]


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok   {t.__name__}")
    print(f"OK: {len(tests)} metricize tests passed")


if __name__ == "__main__":
    main()
