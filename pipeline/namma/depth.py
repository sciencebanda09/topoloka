"""Stage 4 (GPU) -- metric depth fusion: dense colored point cloud in meters.

Input:  <capture>/sfm/poses.json + sparse_txt/ + frames/
Output: <capture>/depth/
    map.npz          dense cloud in METERS: points (N,3) float32 + colors (N,3) uint8
    scale.json       metric scale estimate (scene-units-per-meter) + method + stats
    depth_report.json

The hard part is scale: monocular SfM has arbitrary scale, the depth model is
metric. We align them directly instead of guessing --

  for every visible sparse SfM point in a frame, the depth model's value at
  that pixel (meters) divided by the point's camera-z (scene units) gives a
  scale candidate; the median over hundreds of points/frames is the scale.

That single number makes every downstream artifact metric: real distances,
real ETAs, real obstacle inflation radius.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

import cv2
import numpy as np

MODEL_ID = "depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf"
DEPTH_MAX_M = 12.0     # beyond this the model is unreliable indoors
DEPTH_MIN_M = 0.15
PIXEL_STRIDE = 3       # fuse every 3rd pixel
VOXEL_M = 0.03         # output cloud voxel size (fine enough for a 5 cm grid)
SCALE_SAMPLE_FRAMES = 40


@dataclass
class DepthReport:
    stage: str = "depth"
    status: str = "ok"
    model: str = MODEL_ID
    frames: int = 0
    frames_fused: int = 0
    points_raw: int = 0
    points_voxel: int = 0
    scale_m_per_unit: float = 0.0
    scale_samples: int = 0
    scale_mad_rel: float = 0.0
    timing_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _load_model(device: str):
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    processor = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForDepthEstimation.from_pretrained(MODEL_ID).to(device).eval()
    return torch, processor, model


def _parse_sparse_txt(sfm_dir: Path):
    """images.txt + points3D.txt -> {image_name: (uv (K,2), point_ids (K,))} and points."""
    points: dict[int, np.ndarray] = {}
    for line in (sfm_dir / "points3D.txt").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        points[int(parts[0])] = np.array([float(parts[1]), float(parts[2]), float(parts[3])])
    per_image: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    lines = (sfm_dir / "images.txt").read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        if not lines[i] or lines[i].startswith("#"):
            i += 1
            continue
        name = lines[i].split()[-1]
        i += 1
        if i >= len(lines):
            break
        uv, ids = [], []
        parts = lines[i].split()
        for k in range(0, len(parts), 3):
            x, y, pid = float(parts[k]), float(parts[k + 1]), int(parts[k + 2])
            if pid != -1:
                uv.append((x, y))
                ids.append(pid)
        per_image[name] = (np.asarray(uv, np.float64), np.asarray(ids, np.int64))
        i += 1
    return per_image, points


def _infer_depth(torch, processor, model, bgr: np.ndarray, device: str, max_side: int = 518):
    """Metric depth (meters) at the frame's original resolution."""
    h0, w0 = bgr.shape[:2]
    scale = max_side / max(h0, w0)
    resized = cv2.resize(bgr, (max(1, round(w0 * scale)), max(1, round(h0 * scale))))
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    inputs = processor(images=rgb, return_tensors="pt").to(device)
    with torch.inference_mode():
        pred = model(**inputs).predicted_depth  # (1, h, w)
    depth = pred.squeeze(0).float().cpu().numpy().astype(np.float32)
    up = cv2.resize(depth, (w0, h0), interpolation=cv2.INTER_LINEAR)
    return up


def estimate_scale(capture_dir: Path) -> tuple[float, int, float]:
    """Median ratio (depth_meters / sparse camera-z) over sampled frames."""
    import torch

    sfm = capture_dir / "sfm"
    frames = capture_dir / "frames"
    poses = json.loads((sfm / "poses.json").read_text(encoding="utf-8"))
    per_image, points = _parse_sparse_txt(sfm / "sparse_txt")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch_m, processor, model = _load_model(device)

    names = [f["name"] for f in poses["frames"] if f["name"] in per_image]
    if not names:
        raise SystemExit("no frames with sparse observations; sparse_txt incomplete?")
    pick = np.linspace(0, len(names) - 1, min(SCALE_SAMPLE_FRAMES, len(names))).astype(int)

    ratios: list[float] = []
    for idx in pick:
        fr = next(f for f in poses["frames"] if f["name"] == names[idx])
        bgr = cv2.imread(str(frames / fr["name"]))
        if bgr is None:
            continue
        depth = _infer_depth(torch_m, processor, model, bgr, device)
        w2c = np.asarray(fr["w2c"], np.float64)
        R, t = w2c[:3, :3], w2c[:3, 3]
        uv, ids = per_image[fr["name"]]
        for (u, v), pid in zip(uv, ids):
            p = points.get(int(pid))
            if p is None:
                continue
            z_cam = float((R @ p + t)[2])         # scene units
            dm = float(depth[int(round(v)), int(round(u))])  # meters
            if z_cam > 1e-6 and DEPTH_MIN_M < dm < DEPTH_MAX_M:
                ratios.append(dm / z_cam)
    if len(ratios) < 50:
        raise SystemExit(f"too few scale samples ({len(ratios)})")
    ratios_arr = np.asarray(ratios)
    scale = float(np.median(ratios_arr))
    mad_rel = float(np.median(np.abs(ratios_arr - scale)) / max(scale, 1e-9))
    return scale, len(ratios), mad_rel


def fuse(capture_dir: Path, scale: float) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Back-project every frame's depth into a metric world cloud.

    Returns (points, colors, raw_point_count, frames_used).
    """
    import torch

    sfm = capture_dir / "sfm"
    frames = capture_dir / "frames"
    poses = json.loads((sfm / "poses.json").read_text(encoding="utf-8"))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch_m, processor, model = _load_model(device)

    all_pts, all_cols = [], []
    frames_used = 0
    for i, fr in enumerate(poses["frames"]):
        bgr = cv2.imread(str(frames / fr["name"]))
        if bgr is None:
            continue
        depth = _infer_depth(torch_m, processor, model, bgr, device)
        h, w = depth.shape
        u = np.arange(0, w, PIXEL_STRIDE)
        v = np.arange(0, h, PIXEL_STRIDE)
        uu, vv = np.meshgrid(u, v)
        d = depth[vv, uu]
        valid = (d > DEPTH_MIN_M) & (d < DEPTH_MAX_M)
        if not valid.any():
            continue
        uu, vv, d = uu[valid], vv[valid], d[valid]
        x = (uu - fr["cx"]) / fr["fl_x"] * d
        y = (vv - fr["cy"]) / fr["fl_y"] * d
        z = d
        cam_pts = np.stack([x, y, z], axis=1)          # meters, camera frame
        w2c = np.asarray(fr["w2c"], np.float64)
        R, t = w2c[:3, :3], w2c[:3, 3]
        world_units = (cam_pts - t) @ R                 # = R^T (p_cam - t), scene units
        world_m = world_units * scale
        cols = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)[vv, uu]
        all_pts.append(world_m.astype(np.float32))
        all_cols.append(cols.astype(np.uint8))
        frames_used += 1
        if (i + 1) % 25 == 0:
            print(f"[depth] fused {i + 1}/{len(poses['frames'])} frames", flush=True)

    pts = np.concatenate(all_pts)
    cols = np.concatenate(all_cols).astype(np.float64)
    n_raw = len(pts)
    out_pts, out_cols = _voxel_downsample(pts, cols)
    return out_pts, out_cols, n_raw, frames_used


def _voxel_downsample(pts: np.ndarray, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean of points/colors per VOXEL_M cube. Vectorized (bincount), no Python loop."""
    keys = np.floor(pts / VOXEL_M).astype(np.int64)
    packed = ((keys[:, 0] + (1 << 20)) << 42) | ((keys[:, 1] + (1 << 20)) << 21) | (keys[:, 2] + (1 << 20))
    _, inverse, counts = np.unique(packed, return_inverse=True, return_counts=True)
    n = len(counts)
    out_pts = np.empty((n, 3), np.float32)
    out_cols = np.empty((n, 3), np.uint8)
    for c in range(3):
        out_pts[:, c] = np.bincount(inverse, weights=pts[:, c], minlength=n) / counts
        out_cols[:, c] = np.round(np.bincount(inverse, weights=cols[:, c], minlength=n) / counts)
    return out_pts, out_cols


def run_depth(capture_dir: Path) -> DepthReport:
    capture_dir = Path(capture_dir)
    out = capture_dir / "depth"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    report = DepthReport()

    scale, n_samples, mad = estimate_scale(capture_dir)
    report.scale_m_per_unit = round(scale, 6)
    report.scale_samples = n_samples
    report.scale_mad_rel = round(mad, 4)
    (out / "scale.json").write_text(json.dumps({
        "scale_m_per_unit": scale, "method": "median(depth_m / sparse_camera_z)",
        "samples": n_samples, "mad_rel": mad,
    }, indent=2), encoding="utf-8")

    # metric copy of the poses: translations scaled to meters, so the fused
    # metric cloud and the camera trajectory live in the SAME frame.
    poses_path = capture_dir / "sfm" / "poses.json"
    poses = json.loads(poses_path.read_text(encoding="utf-8"))
    for fr in poses["frames"]:
        w2c = np.asarray(fr["w2c"], np.float64)
        w2c[:3, 3] *= scale
        fr["w2c"] = w2c.tolist()
    poses["note"] = f"translations scaled by depth-derived metric scale {scale:.6f}"
    (capture_dir / "sfm" / "poses_m.json").write_text(json.dumps(poses), encoding="utf-8")

    pts, cols, n_raw, frames_used = fuse(capture_dir, scale)
    report.points_raw = n_raw
    report.points_voxel = len(pts)
    np.savez_compressed(out / "map.npz", points=pts, colors=cols)

    report.frames = len(json.loads((capture_dir / "sfm" / "poses.json")
                                    .read_text(encoding="utf-8"))["frames"])
    report.frames_fused = frames_used
    if mad > 0.25:
        report.warnings.append(f"scale estimate unstable (relative MAD {mad:.2f})")
    report.timing_seconds = round(time.time() - t0, 1)
    (out / "depth_report.json").write_text(json.dumps(report.to_dict(), indent=2),
                                           encoding="utf-8")
    print(f"[depth] scale {scale:.5f} m/unit ({n_samples} samples, MAD {mad:.2%}), "
          f"{n_raw} pts -> {len(pts)} voxels, {report.timing_seconds}s")
    return report
