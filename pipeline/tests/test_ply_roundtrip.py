"""PLY layout round-trip tests.

The 2026-10-18 run shipped PLYs written as "all xyz, then all rgb" while every
reader (geometry.load_cloud, trimesh/open3d in nerfstudio, three.js PLYLoader)
reads the PLY-spec per-vertex layout "x,y,z,r,g,b" per point. The nav grid came
out garbled. These tests pin the writers to the spec.

Run:  .venv\\Scripts\\python.exe pipeline\\tests\\test_ply_roundtrip.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from namma import package, sfm  # noqa: E402
from namma.geometry import load_cloud  # noqa: E402

RNG = np.random.default_rng(7)
N = 257  # odd count: catches any padding mistake
XYZ = (RNG.normal(size=(N, 3)) * 3.0).astype(np.float32)
RGB = RNG.integers(0, 256, size=(N, 3), dtype=np.uint8)


class FakePoint:
    def __init__(self, xyz, rgb):
        self.xyz = np.asarray(xyz, np.float64)
        self.color = np.asarray(rgb, np.uint8)


class FakeRec:
    """Points3DMap-like: .values() yields objects with xyz/color properties."""

    def __init__(self, xyz, rgb):
        self.points3D = {i: FakePoint(x, c) for i, (x, c) in enumerate(zip(xyz, rgb))}


def _spec_payload(xyz: np.ndarray, rgb: np.ndarray) -> bytes:
    """Independent hand-rolled reference of the PLY spec interleave."""
    out = bytearray()
    for p, c in zip(xyz, rgb):
        out += np.asarray(p, "<f4").tobytes()
        out += np.asarray(c, np.uint8).tobytes()
    return bytes(out)


def test_sfm_writer_is_spec_interleaved() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "sfm.ply"
        sfm._write_ply(FakeRec(XYZ, RGB), path)
        raw = path.read_bytes()
        head = raw.find(b"end_header\n") + len(b"end_header\n")
        assert raw[head:] == _spec_payload(XYZ, RGB), "sfm PLY payload not per-vertex interleaved"
        xyz2, rgb2 = load_cloud(path)
        np.testing.assert_array_equal(xyz2, XYZ)
        np.testing.assert_array_equal(rgb2, RGB)


def test_package_writer_round_trips() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "pkg.ply"
        package._write_ply(path, XYZ, RGB)
        raw = path.read_bytes()
        head = raw.find(b"end_header\n") + len(b"end_header\n")
        assert raw[head:] == _spec_payload(XYZ, RGB), "package PLY payload not per-vertex interleaved"
        xyz2, rgb2 = load_cloud(path)
        np.testing.assert_array_equal(xyz2, XYZ)
        np.testing.assert_array_equal(rgb2, RGB)


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok   {t.__name__}")
    print(f"OK: {len(tests)} PLY round-trip tests passed")


if __name__ == "__main__":
    main()
