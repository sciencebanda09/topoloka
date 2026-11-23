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

Optionally prunes to a gaussian budget (--max-gaussians): drops low-alpha
gaussians first, then keeps the most visually important ones (alpha x scale),
because web payload and viewer load time are first-class product constraints.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SH_C0 = 0.28209479177387814
ALPHA_MIN = 0.02            # gaussians this transparent are never worth their bytes
FLOATER_MAX_SCALE = 0.35    # oversized semi-transparent blobs (meters in metricized runs)
FLOATER_ALPHA_CEIL = 0.35
NEEDLE_MAX_SCALE = 0.15     # elongated spiky streak splats
NEEDLE_MAX_ASPECT = 25.0
NEEDLE_ALPHA_CEIL = 0.85
SPIKE_ELONGATION = 6.0      # cigar-shaped spike ratio (s_max / s_mid), preserves flat wall surfels
SPIKE_MIN_SCALE = 0.04      # meters (scaled adaptively to scene median)


@dataclass
class SplatReport:
    stage: str = "splat_convert"
    ply: str = ""
    out: str = ""
    gaussians_in: int = 0
    gaussians_out: int = 0
    dropped_alpha: int = 0
    dropped_floaters: int = 0
    dropped_budget: int = 0
    splat_bytes: int = 0
    source_bytes: int = 0
    dropped_sh_bands: int = 0
    max_gaussians: int = 0

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


def convert_splat(ply_path: Path, out_path: Path,
                  max_gaussians: int = 0,
                  prune_floaters: bool = True) -> SplatReport:
    ply_path, out_path = Path(ply_path), Path(out_path)
    data, names = _read_ply_props(ply_path)
    need = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
            "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    missing = [n for n in need if n not in names]
    if missing:
        raise SystemExit(f"PLY lacks gaussian properties: {missing} (found {len(names)})")

    n_in = len(data)
    pos = np.stack([data["x"], data["y"], data["z"]], axis=1).astype(np.float32)

    # color: SH DC -> [0,1]; alpha: sigmoid(opacity)
    rgb = 0.5 + SH_C0 * np.stack([data["f_dc_0"], data["f_dc_1"], data["f_dc_2"]], axis=1)
    rgb = np.clip(rgb, 0.0, 1.0)
    raw_opacity = np.clip(np.asarray(data["opacity"], np.float64), -60.0, 60.0)
    alpha = 1.0 / (1.0 + np.exp(-raw_opacity))

    # scale: exp(); clamp wild values so a viewer never explodes
    raw_scale = np.stack([data["scale_0"], data["scale_1"], data["scale_2"]], axis=1).astype(np.float64)
    finite_mask = np.isfinite(pos).all(axis=1) & np.isfinite(raw_scale).all(axis=1) & np.isfinite(alpha)
    scale = np.exp(np.clip(raw_scale, -20.0, 5.0))
    scale = np.clip(scale, 1e-5, 1.0).astype(np.float32)

    # rotation: (w,x,y,z) normalized -> uint8
    quat = np.stack([data["rot_0"], data["rot_1"], data["rot_2"], data["rot_3"]], axis=1).astype(np.float64)
    finite_mask &= np.isfinite(quat).all(axis=1)
    norm = np.linalg.norm(quat, axis=1, keepdims=True)
    quat = np.where(norm > 1e-12, quat / norm, np.array([1.0, 0.0, 0.0, 0.0]))
    quat_u8 = np.clip(quat * 128 + 128, 0, 255).astype(np.uint8)

    color_u8 = np.empty((n_in, 4), np.uint8)
    color_u8[:, :3] = np.round(np.nan_to_num(rgb, nan=0.0) * 255).astype(np.uint8)
    color_u8[:, 3] = np.round(np.nan_to_num(alpha, nan=0.0) * 255).astype(np.uint8)

    # -- pruning: bytes, load time, and floater clarity are product constraints --
    keep_alpha = finite_mask & (alpha >= ALPHA_MIN)
    dropped_alpha = int(n_in - keep_alpha.sum())
    dropped_floaters = 0
    keep = keep_alpha
    if prune_floaters:
        sorted_s = np.sort(scale, axis=1)
        min_s = np.maximum(sorted_s[:, 0], 1e-5)
        mid_s = np.maximum(sorted_s[:, 1], 1e-5)
        max_s = sorted_s[:, 2]
        aspect = max_s / min_s
        elongation = max_s / mid_s
        s_med = float(np.median(max_s[keep_alpha])) if keep_alpha.any() else 0.02
        # 1) Volumetric semi-transparent fog blobs (adaptive to room scale + global ceiling)
        fog_thresh = min(FLOATER_MAX_SCALE, max(0.08, 10.0 * s_med))
        is_fog_floater = ((max_s > FLOATER_MAX_SCALE) & (alpha < FLOATER_ALPHA_CEIL)) | (
            (max_s > fog_thresh) & (alpha < 0.65)
        )
        # 2) Elongated needle/cigar spikes (s_max >> s_mid), preserving flat wall pancake surfels
        spike_thresh = max(SPIKE_MIN_SCALE, 4.5 * s_med)
        is_needle = (
            ((aspect > NEEDLE_MAX_ASPECT) & (max_s > NEEDLE_MAX_SCALE) & (alpha < NEEDLE_ALPHA_CEIL))
            | ((elongation > SPIKE_ELONGATION) & (max_s > spike_thresh))
        )
        keep = keep_alpha & ~(is_fog_floater | is_needle)
        dropped_floaters = int(keep_alpha.sum() - keep.sum())

    idx = np.flatnonzero(keep)
    dropped_budget = 0
    if max_gaussians and len(idx) > max_gaussians:
        sorted_k = np.sort(scale[idx].astype(np.float64), axis=1)
        max_k = sorted_k[:, 2]
        mid_k = np.maximum(sorted_k[:, 1], 1e-5)
        elong_k = max_k / mid_k
        # Favor opaque, compact surface splats over bloated blobs and elongated streaks
        importance = alpha[idx] / (
            (1.0 + np.maximum(0.0, elong_k - 3.0) * 0.4)
            * (1.0 + np.maximum(0.0, max_k - 0.04) * 25.0)
        )
        sel = np.argpartition(importance, -max_gaussians)[-max_gaussians:]
        dropped_budget = len(idx) - max_gaussians
        idx = idx[sel]

    n = len(idx)
    pos, scale, color_u8, quat_u8 = pos[idx], scale[idx], color_u8[idx], quat_u8[idx]

    records = np.empty((n, 32), np.uint8)
    records[:, 0:12] = pos.view(np.uint8).reshape(n, 12)
    records[:, 12:24] = scale.view(np.uint8).reshape(n, 12)
    records[:, 24:28] = color_u8
    records[:, 28:32] = quat_u8

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        # raw records only -- no header: this is the .splat format
        f.write(records.tobytes())

    report = SplatReport(
        ply=str(ply_path), out=str(out_path),
        gaussians_in=n_in, gaussians_out=n,
        dropped_alpha=dropped_alpha, dropped_floaters=dropped_floaters,
        dropped_budget=dropped_budget,
        splat_bytes=out_path.stat().st_size, source_bytes=ply_path.stat().st_size,
        dropped_sh_bands=len(names) - 14, max_gaussians=max_gaussians,
    )
    (out_path.parent / "splat_convert_report.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(f"[splat_convert] {n_in} gaussians -> {n} kept ({dropped_alpha} low-alpha, "
          f"{dropped_floaters} floaters/needles, {dropped_budget} over budget) -> "
          f"{report.splat_bytes / 1e6:.1f} MB (from {report.source_bytes / 1e6:.1f} MB)")
    return report
