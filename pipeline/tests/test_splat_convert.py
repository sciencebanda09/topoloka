"""Splat converter round-trip test (runs locally, no GPU).

Builds a synthetic 3DGS PLY with the standard 59 per-gaussian properties,
converts it, and checks the .splat records against the exact layout the web
renderer expects (validated against @mkkellogg/gaussian-splats-3d's parser:
32-byte rows, float32 pos, float32 linear scale, uint8 rgba, uint8 wxyz).

Run:  .venv\\Scripts\\python.exe pipeline\\tests\\test_splat_convert.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from namma import splat_convert  # noqa: E402

PROPS = (["x", "y", "z"]
         + [f"f_dc_{i}" for i in range(3)]
         + [f"f_rest_{i}" for i in range(45)]
         + ["opacity"]
         + [f"scale_{i}" for i in range(3)]
         + [f"rot_{i}" for i in range(4)])


def make_ply(path: Path, n: int = 1000) -> None:
    dt = np.dtype([(p, "<f4") for p in PROPS])
    arr = np.zeros(n, dt)
    rng = np.random.default_rng(3)
    arr["x"] = rng.normal(0, 2, n)
    arr["y"] = rng.normal(0, 2, n)
    arr["z"] = rng.uniform(0, 2.5, n)
    arr["f_dc_0"] = rng.normal(0, 0.5, n)
    arr["f_dc_1"] = rng.normal(0, 0.5, n)
    arr["f_dc_2"] = rng.normal(0, 0.5, n)
    arr["opacity"] = rng.normal(4, 2, n)       # sigmoid -> mostly ~0.98
    arr["opacity"][::10] = -6.0                # every 10th: alpha ~0.002 (prunable)
    arr["scale_0"] = arr["scale_1"] = arr["scale_2"] = np.log(0.05)
    arr["rot_0"] = 1.0
    header = ("ply\nformat binary_little_endian 1.0\n"
              f"element vertex {n}\n"
              + "".join(f"property float {p}\n" for p in PROPS)
              + "end_header\n").encode("ascii")
    with open(path, "wb") as f:
        f.write(header)
        f.write(arr.tobytes())


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ply = Path(tmp) / "splat.ply"
        out = Path(tmp) / "splat.splat"
        make_ply(ply, 1000)

        report = splat_convert.convert_splat(ply, out, max_gaussians=600)
        assert report.gaussians_in == 1000, report.gaussians_in
        # 100 low-alpha dropped; 900 eligible pruned to budget 600
        assert report.dropped_alpha == 100, report.dropped_alpha
        assert report.dropped_budget == 300, report.dropped_budget
        assert report.gaussians_out == 600, report.gaussians_out
        assert out.stat().st_size == 600 * 32, out.stat().st_size

        raw = out.read_bytes()
        first = np.frombuffer(raw[:32], dtype=np.uint8)
        pos = first[0:12].view("<f4")
        scl = first[12:24].view("<f4")
        col = first[24:28]
        rot = first[28:32]
        assert abs(float(scl[0]) - 0.05) < 1e-5, scl           # linear scale, not log
        assert abs(float(rot[0]) - 255) <= 1 or rot[0] == 255  # w ~ 1.0 mapped
        assert col[3] > 200                                     # vivid alpha
        print(f"OK: {report.gaussians_out} gaussians, "
              f"pos0=({pos[0]:.2f},{pos[1]:.2f},{pos[2]:.2f}), scale={float(scl[0]):.3f}")


if __name__ == "__main__":
    main()
