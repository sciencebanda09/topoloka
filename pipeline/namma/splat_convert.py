"""Splat export -- convert a 3DGS .ply into the compact web .splat format.

3DGS training (splatfacto / gsplat) exports a PLY where each gaussian carries
59 floats (xyz, 3 SH-DC, 45 SH-rest, opacity, 3 scales, 4 rotation). For the
web we keep the DC term only (higher SH bands are dropped -- a deliberate
size/quality tradeoff) and pack each gaussian into the 32-byte ".splat" record
used by antimatter15-style web viewers:

    position  3 x float32
    scale     3 x float32   (linear, already exp()'d)
    color     4 x uint8     (r, g, b, alpha)
    rotation  4 x uint8     (w, x, y, z; mapped from [-1,1] to [0,255])

A 1M-gaussian scene lands at ~32 MB (vs ~240 MB as PLY).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SH_C0 = 0.28209479177387814


@dataclass
class SplatReport:
    stage: str = "splat_convert"
    ply: str = ""
    out: str = ""
    gaussians: int = 0
    splat_bytes: int = 0
    source_bytes: int = 0
    dropped_sh_bands: int = 0

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _read_ply_props(path: Path) -> tuple[np.ndarray, list[str]]:
    """Read a binary little-endian PLY with named scalar float/uchar properties."""
    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise SystemExit(f"not a PLY: {path}")
        fmt, count = "", 0
        props: list[tuple[str, str]] = []
        while True:
            line = f.readline()
            if not line:
                raise SystemExit("PLY header truncated")
            parts = line.split()
            if parts[:1] == [b"format"]:
                fmt = parts[1].decode()
            elif parts[:1] == [b"element"] and parts[1:2] == [b"vertex"]:
                count = int(parts[2])
            elif parts[:1] == [b"property"] and len(parts) >= 3:
                props.append((parts[2].decode(), parts[1].decode()))
            elif parts[:1] == [b"end_header"]:
                break
        if fmt != "binary_little_endian":
            raise SystemExit(f"unsupported PLY format: {fmt}")
        np_types = {
            "float": "<f4", "float32": "<f4", "double": "<f8", "float64": "<f8",
            "uchar": "u1", "uint8": "u1",
        }
        names = [p[0] for p in props]
        dtype = np.dtype([(p[0], np_types[p[1]]) for p in props])
        data = np.frombuffer(f.read(count * dtype.itemsize), dtype=dtype, count=count)
    return data, names


def convert_splat(ply_path: Path, out_path: Path) -> SplatReport:
    ply_path, out_path = Path(ply_path), Path(out_path)
    data, names = _read_ply_props(ply_path)
    need = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
            "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    missing = [n for n in need if n not in names]
    if missing:
        raise SystemExit(f"PLY lacks gaussian properties: {missing} (found {len(names)})")

    n = len(data)
    pos = np.stack([data["x"], data["y"], data["z"]], axis=1).astype(np.float32)

    # color: SH DC -> [0,1]; alpha: sigmoid(opacity)
    rgb = 0.5 + SH_C0 * np.stack([data["f_dc_0"], data["f_dc_1"], data["f_dc_2"]], axis=1)
    rgb = np.clip(rgb, 0.0, 1.0)
    alpha = 1.0 / (1.0 + np.exp(-np.asarray(data["opacity"], np.float64)))

    # scale: exp(); clamp wild values so a viewer never explodes
    scale = np.exp(np.stack([data["scale_0"], data["scale_1"], data["scale_2"]], axis=1))
    scale = np.clip(scale, 1e-5, 1.0).astype(np.float32)

    # rotation: (w,x,y,z) normalized -> uint8
    quat = np.stack([data["rot_0"], data["rot_1"], data["rot_2"], data["rot_3"]], axis=1).astype(np.float64)
    norm = np.linalg.norm(quat, axis=1, keepdims=True)
    quat = np.where(norm > 1e-12, quat / norm, np.array([1.0, 0.0, 0.0, 0.0]))
    quat_u8 = np.clip(quat * 128 + 128, 0, 255).astype(np.uint8)

    color_u8 = np.empty((n, 4), np.uint8)
    color_u8[:, :3] = np.round(rgb * 255).astype(np.uint8)
    color_u8[:, 3] = np.round(alpha * 255).astype(np.uint8)

    records = np.empty((n, 32), np.uint8)
    records[:, 0:12] = pos.view(np.uint8).reshape(n, 12)
    records[:, 12:24] = scale.view(np.uint8).reshape(n, 12)
    records[:, 24:28] = color_u8
    records[:, 28:32] = quat_u8

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        # header written by the JS viewers' expectation: none -- raw records only
        f.write(records.tobytes())

    report = SplatReport(
        ply=str(ply_path), out=str(out_path), gaussians=n,
        splat_bytes=out_path.stat().st_size, source_bytes=ply_path.stat().st_size,
        dropped_sh_bands=len(names) - 14,
    )
    (out_path.parent / "splat_convert_report.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(f"[splat_convert] {n} gaussians -> {report.splat_bytes / 1e6:.1f} MB "
          f"(from {report.source_bytes / 1e6:.1f} MB)")
    return report
