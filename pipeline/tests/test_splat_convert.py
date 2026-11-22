"""Splat converter round-trip & floater-pruning tests (runs locally, no GPU).

Builds synthetic 3DGS PLYs with the standard 59 per-gaussian properties,
converts them, and checks the .splat records against the exact layout the web
renderer expects (32-byte rows, float32 pos, float32 linear scale, uint8 rgba,
uint8 wxyz), plus fog-floater, spiky-needle, and non-finite pruning.
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


def _write_ply(path: Path, arr: np.ndarray) -> None:
    header = ("ply\nformat binary_little_endian 1.0\n"
              f"element vertex {len(arr)}\n"
              + "".join(f"property float {p}\n" for p in PROPS)
              + "end_header\n").encode("ascii")
    with open(path, "wb") as f:
        f.write(header)
        f.write(arr.tobytes())


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
    _write_ply(path, arr)


def test_splat_convert_roundtrip(tmp_path: Path) -> None:
    ply = tmp_path / "splat.ply"
    out = tmp_path / "splat.splat"
    make_ply(ply, 1000)

    report = splat_convert.convert_splat(ply, out, max_gaussians=600)
    assert report.gaussians_in == 1000
    assert report.dropped_alpha == 100
    assert report.dropped_floaters == 0
    assert report.dropped_budget == 300
    assert report.gaussians_out == 600
    assert out.stat().st_size == 600 * 32

    raw = out.read_bytes()
    first = np.frombuffer(raw[:32], dtype=np.uint8)
    scl = first[12:24].view("<f4")
    col = first[24:28]
    rot = first[28:32]
    assert abs(float(scl[0]) - 0.05) < 1e-5
    assert abs(float(rot[0]) - 255) <= 1 or rot[0] == 255
    assert col[3] > 200


def test_splat_convert_prunes_floaters_needles_and_nonfinite(tmp_path: Path) -> None:
    dt = np.dtype([(p, "<f4") for p in PROPS])
    arr = np.zeros(10, dt)
    arr["opacity"] = 3.0  # alpha ~0.95
    arr["scale_0"] = arr["scale_1"] = arr["scale_2"] = np.log(0.04)
    arr["rot_0"] = 1.0

    # Index 0: foggy oversized floater (scale=0.6 m, alpha~0.18)
    arr["opacity"][0] = -1.5
    arr["scale_0"][0] = arr["scale_1"][0] = arr["scale_2"][0] = np.log(0.6)

    # Index 1: spiky needle (0.4 m x 0.005 m -> aspect 80, alpha~0.5)
    arr["opacity"][1] = 0.0
    arr["scale_0"][1] = np.log(0.4)
    arr["scale_1"][1] = arr["scale_2"][1] = np.log(0.005)

    # Index 2: NaN position
    arr["x"][2] = np.nan

    # Index 3: solid wall panel (large opaque splat, alpha~0.98) -> must be KEPT
    arr["opacity"][3] = 4.0
    arr["scale_0"][3] = arr["scale_1"][3] = np.log(0.45)
    arr["scale_2"][3] = np.log(0.05)

    ply = tmp_path / "noisy.ply"
    out = tmp_path / "clean.splat"
    _write_ply(ply, arr)

    rep = splat_convert.convert_splat(ply, out)
    assert rep.gaussians_in == 10
    assert rep.dropped_alpha == 1       # NaN entry
    assert rep.dropped_floaters == 2    # fog floater + spiky needle
    assert rep.gaussians_out == 7       # wall panel & 6 normal splats preserved

    # When prune_floaters=False, floaters and needles remain
    out_raw = tmp_path / "unpruned.splat"
    rep_raw = splat_convert.convert_splat(ply, out_raw, prune_floaters=False)
    assert rep_raw.dropped_floaters == 0
    assert rep_raw.gaussians_out == 9


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        test_splat_convert_roundtrip(Path(tmp))
        test_splat_convert_prunes_floaters_needles_and_nonfinite(Path(tmp))
        print("OK: all splat_convert checks passed")


if __name__ == "__main__":
    main()
