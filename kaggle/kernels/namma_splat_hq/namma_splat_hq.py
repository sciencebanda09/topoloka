"""Kaggle GPU kernel (v3 HQ): Anti-blur, anti-spike 3DGS for indoor multi-room twins.

Upgrades over baseline namma_splat.py:
  1. Continuous loop filtering: drops disconnected/outlier tail frames before depth & 3DGS.
  2. Edge-filtered indoor metric depth (Depth-Anything-V2-Metric-Indoor-Small-hf, Apache 2.0):
     - Per-frame robust Huber alignment (a*d + b) to COLMAP sparse points
     - Depth-discontinuity flying-pixel mask (|grad D| / D < 0.055)
     - Indoor depth cap (0.20 m .. 5.2 m) -> zero starburst rays on 2D minimap!
  3. Dense metric depth + sparse SfM combined seed cloud (~230k surface seeds).
  4. High-sharpness anti-spike `splatfacto-big` (nerfstudio 1.1.5 + gsplat, Apache 2.0):
     - camera_optimizer.mode = "SO3xR3"   (fixes 1.57 px DISK pose jitter!)
     - use_scale_regularization = True, max_gauss_ratio = 3.5 (suppresses spikes!)
     - sh_degree = 0                      (exact 1:1 match with DC .ksplat!)
     - rasterize_mode = "antialiased"     (Mip-Splatting anti-aliasing!)
     - use_absgrad = True                 (splits blurry under-reconstructed walls!)
     - cull_alpha_thresh = 0.025, cull_scale_thresh = 0.06 (6 cm max metric scale!)
     - num_downscales = 0, eval_mode = "all" (100% of continuous frames @ native res!)
     - 30,000 iterations.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import time
import traceback
import zipfile
from pathlib import Path

import cv2
import numpy as np

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")
SCRATCH = Path("/tmp/namma_hq")
OUT = WORK / "out"
CODE = SCRATCH / "code"
RUN = SCRATCH / "run"
NS_OUT = SCRATCH / "ns"

MODEL_ID = "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"  # Apache 2.0
ITERS = int(os.environ.get("NM_ITERS", "30000"))
DEPTH_MIN_M = 0.20
DEPTH_MAX_M = 5.20
GRAD_REL_MAX = 0.055
VOXEL_M = 0.025
SEED_MAX_PTS = 200_000


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def stage_code() -> None:
    tar = next(INPUT.glob("**/code.tar"), None)
    if tar:
        CODE.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar) as t:
            t.extractall(CODE)
    else:
        cli = next(INPUT.glob("**/namma/cli.py"), None)
        if not cli:
            raise SystemExit("namma/cli.py not found under /kaggle/input")
        shutil.copytree(cli.parents[1], CODE, dirs_exist_ok=True)
    log(f"code staged: {sorted(p.name for p in CODE.iterdir())}")


def stage_capture() -> None:
    root = None
    for marker in ("**/transforms.json", "**/frames.zip", "**/poses.json"):
        for p in sorted(INPUT.glob(marker)):
            cand = p.parent
            if (cand / "transforms.json").exists() and (cand / "poses.json").exists():
                root = cand
                break
        if root:
            break
    if root is None:
        raise SystemExit("capture dataset not found under /kaggle/input")
    log(f"capture root: {root}")

    RUN.mkdir(parents=True, exist_ok=True)

    def stage_archive(stem: str, dst: Path) -> None:
        z = root / f"{stem}.zip"
        d = root / stem
        if z.exists():
            with zipfile.ZipFile(z) as zf:
                zf.extractall(dst)
        elif d.is_dir():
            shutil.copytree(d, dst, dirs_exist_ok=True)
        else:
            raise SystemExit(f"missing {stem}.zip or {stem}/")

    stage_archive("frames", RUN / "frames")
    for f in ("transforms.json", "sparse.ply"):
        shutil.copy2(root / f, RUN / f)
    sfm = RUN / "sfm"
    sfm.mkdir(exist_ok=True)
    shutil.copy2(root / "poses.json", sfm / "poses.json")
    shutil.copy2(root / "sparse.ply", sfm / "sparse.ply")
    for name, dst in (("frames_meta.json", RUN / "frames_meta.json"),
                      ("sfm_report.json", sfm / "sfm_report.json")):
        if (root / name).exists():
            shutil.copy2(root / name, dst)
    stage_archive("sparse_txt", sfm / "sparse_txt")
    log(f"staged {len(list((RUN / 'frames').glob('*.jpg')))} frames")


def filter_continuous_loop() -> int:
    """Keep only the largest temporally continuous pose segment (drops disconnected outlier tail frames)."""
    poses_p = RUN / "sfm" / "poses.json"
    tf_p = RUN / "transforms.json"
    poses = json.loads(poses_p.read_text(encoding="utf-8"))
    frames = sorted(poses["frames"], key=lambda f: f["name"])

    # Extract integer frame index from filename (e.g. 00000.jpg -> 0)
    def fidx(name: str) -> int:
        stem = Path(name).stem
        digits = "".join(ch for ch in stem if ch.isdigit())
        return int(digits) if digits else 0

    # Split into continuous runs wherever frame index jumps by > 15 frames (~3 s gap)
    runs: list[list[dict]] = []
    cur: list[dict] = []
    for fr in frames:
        if cur and (fidx(fr["name"]) - fidx(cur[-1]["name"])) > 15:
            runs.append(cur)
            cur = [fr]
        else:
            cur.append(fr)
    if cur:
        runs.append(cur)

    best = max(runs, key=len)
    kept_names = {fr["name"] for fr in best}
    dropped = len(frames) - len(best)
    log(f"continuous loop filter: kept {len(best)}/{len(frames)} frames (dropped {dropped} disconnected frames across {len(runs)} segments)")

    poses["frames"] = best
    poses_p.write_text(json.dumps(poses, indent=2), encoding="utf-8")

    tf = json.loads(tf_p.read_text(encoding="utf-8"))
    tf["frames"] = [fr for fr in tf["frames"] if Path(fr["file_path"]).name in kept_names]
    tf_p.write_text(json.dumps(tf, indent=2), encoding="utf-8")
    return len(best)


def ensure_deps() -> None:
    for pkg in ("transformers", "nerfstudio==1.1.5"):
        mod = pkg.split("==")[0]
        try:
            __import__(mod)
        except ImportError:
            log(f"pip install {pkg}...")
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise SystemExit(f"pip install {pkg} failed:\n{(r.stderr or '')[-2000:]}")
    import importlib
    importlib.invalidate_caches()


def parse_sparse_txt(sfm_dir: Path):
    points: dict[int, np.ndarray] = {}
    for line in (sfm_dir / "points3D.txt").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        points[int(parts[0])] = np.array([float(parts[1]), float(parts[2]), float(parts[3])], dtype=np.float64)
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
            if pid != -1 and pid in points:
                uv.append((x, y))
                ids.append(pid)
        per_image[name] = (np.asarray(uv, np.float64), np.asarray(ids, np.int64))
        i += 1
    return per_image, points


def robust_scale_shift(d_pred: np.ndarray, z_true: np.ndarray) -> tuple[float, float]:
    """Fit z_true ~= a * d_pred + b with IRLS Huber, falling back to median scale."""
    valid = (d_pred > 0.15) & (d_pred < 7.0) & (z_true > 0.15) & (z_true < 7.0)
    if valid.sum() < 20:
        return 1.0, 0.0
    x = d_pred[valid]
    y = z_true[valid]
    a = float(np.clip(np.median(y / np.maximum(x, 1e-6)), 0.70, 1.40))
    b = 0.0
    if len(x) >= 35:
        for _ in range(8):
            res = (a * x + b) - y
            w = 1.0 / np.maximum(np.abs(res), 0.06)
            A = np.column_stack([x, np.ones_like(x)])
            Aw = A * w[:, None]
            lhs = Aw.T @ A + np.diag([10.0, 25.0])
            rhs = Aw.T @ y + np.array([10.0 * a, 0.0])
            sol = np.linalg.solve(lhs, rhs)
            a = float(np.clip(sol[0], 0.72, 1.38))
            b = float(np.clip(sol[1], -0.25, 0.25))
    return a, b


def run_clean_depth_and_seed() -> dict:
    """Compute global metric scale, fuse edge-filtered dense depth, and write combined SfM+depth seed PLY."""
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    t0 = time.time()
    sfm = RUN / "sfm"
    frames_dir = RUN / "frames"
    poses = json.loads((sfm / "poses.json").read_text(encoding="utf-8"))
    per_image, sparse_pts = parse_sparse_txt(sfm / "sparse_txt")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForDepthEstimation.from_pretrained(MODEL_ID).to(device).eval()

    def infer(bgr: np.ndarray) -> np.ndarray:
        h0, w0 = bgr.shape[:2]
        sc = 518.0 / max(h0, w0)
        small = cv2.resize(bgr, (max(1, round(w0 * sc)), max(1, round(h0 * sc))))
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        inp = processor(images=rgb, return_tensors="pt").to(device)
        with torch.inference_mode():
            pred = model(**inp).predicted_depth
        d = pred.squeeze(0).float().cpu().numpy().astype(np.float32)
        return cv2.resize(d, (w0, h0), interpolation=cv2.INTER_LINEAR)

    # 1. Global metric scale from 45 evenly spaced loop frames
    f_list = poses["frames"]
    pick = np.linspace(0, len(f_list) - 1, min(45, len(f_list))).astype(int)
    ratios: list[float] = []
    cached_depths: dict[str, np.ndarray] = {}
    for idx in pick:
        fr = f_list[idx]
        nm = fr["name"]
        if nm not in per_image:
            continue
        bgr = cv2.imread(str(frames_dir / nm))
        if bgr is None:
            continue
        d_map = infer(bgr)
        cached_depths[nm] = d_map
        w2c = np.asarray(fr["w2c"], np.float64)
        R, t = w2c[:3, :3], w2c[:3, 3]
        uv, ids = per_image[nm]
        h0, w0 = d_map.shape
        for (u, v), pid in zip(uv, ids):
            ui, vi = int(round(u)), int(round(v))
            if not (0 <= ui < w0 and 0 <= vi < h0):
                continue
            z_cam = float((R @ sparse_pts[int(pid)] + t)[2])
            dm = float(d_map[vi, ui])
            if z_cam > 1e-6 and DEPTH_MIN_M < dm < DEPTH_MAX_M:
                ratios.append(dm / z_cam)

    ratios_arr = np.asarray(ratios, dtype=np.float64)
    scale = float(np.median(ratios_arr))
    mad_rel = float(np.median(np.abs(ratios_arr - scale)) / max(scale, 1e-9))
    log(f"global metric scale: {scale:.5f} m/unit (samples={len(ratios)}, MAD={mad_rel*100:.2f}%)")

    # 2. Fuse all 293 loop frames with per-frame Huber alignment + edge discontinuity mask
    all_pts, all_cols = [], []
    frames_fused = 0
    stride = 3
    for fr in f_list:
        nm = fr["name"]
        bgr = cv2.imread(str(frames_dir / nm))
        if bgr is None:
            continue
        d_map = cached_depths.pop(nm, None)
        if d_map is None:
            d_map = infer(bgr)

        w2c = np.asarray(fr["w2c"], np.float64)
        R, t = w2c[:3, :3], w2c[:3, 3]
        # Per-frame Huber refinement against scaled sparse COLMAP points
        if nm in per_image:
            uv, ids = per_image[nm]
            h0, w0 = d_map.shape
            ui = np.clip(np.rint(uv[:, 0]).astype(int), 0, w0 - 1)
            vi = np.clip(np.rint(uv[:, 1]).astype(int), 0, h0 - 1)
            pts_m = np.array([sparse_pts[int(pid)] for pid in ids], dtype=np.float64) * scale
            z_true = (pts_m @ R.T + t * scale)[:, 2]
            d_preds = d_map[vi, ui].astype(np.float64)
            a, b = robust_scale_shift(d_preds, z_true)
            d_map = np.clip(a * d_map + b, 0.0, 20.0).astype(np.float32)

        # Edge-discontinuity flying-pixel mask: reject pixels where depth jumps sharply
        gx = cv2.Sobel(d_map, cv2.CV_32F, 1, 0, ksize=3) * 0.25
        gy = cv2.Sobel(d_map, cv2.CV_32F, 0, 1, ksize=3) * 0.25
        rel_grad = np.hypot(gx, gy) / np.maximum(d_map, 0.2)
        # Also erode away 3 px border around depth discontinuities
        edge_bad = (rel_grad > GRAD_REL_MAX).astype(np.uint8)
        edge_bad = cv2.dilate(edge_bad, np.ones((5, 5), np.uint8)) > 0

        h, w = d_map.shape
        u = np.arange(8, w - 8, stride)
        v = np.arange(8, h - 8, stride)
        uu, vv = np.meshgrid(u, v)
        d = d_map[vv, uu]
        bad = edge_bad[vv, uu]
        valid = (~bad) & (d >= DEPTH_MIN_M) & (d <= DEPTH_MAX_M)
        if not valid.any():
            continue

        uu_v = uu[valid].astype(np.float64)
        vv_v = vv[valid].astype(np.float64)
        dd_v = d[valid].astype(np.float64)
        fl_x, fl_y = float(fr["fl_x"]), float(fr["fl_y"])
        cx, cy = float(fr["cx"]), float(fr["cy"])

        xc = (uu_v - cx) * dd_v / fl_x
        yc = (vv_v - cy) * dd_v / fl_y
        zc = dd_v
        pts_cam = np.stack([xc, yc, zc], axis=1)
        # Camera -> metric world: p_world_m = R^T @ (pts_cam - t*scale)
        pts_w = (pts_cam - t * scale) @ R
        rgb = bgr[vv[valid], uu[valid], ::-1]
        all_pts.append(pts_w.astype(np.float32))
        all_cols.append(rgb.astype(np.uint8))
        frames_fused += 1

    del model, processor
    torch.cuda.empty_cache()

    pts_raw = np.concatenate(all_pts, axis=0)
    cols_raw = np.concatenate(all_cols, axis=0)
    n_raw = len(pts_raw)

    # Bit-packed voxel downsample + require >= 2 observations per 2.5 cm voxel to crush stray flying outliers!
    keys = np.floor(pts_raw / VOXEL_M).astype(np.int64)
    packed = ((keys[:, 0] + (1 << 20)) << 42) | ((keys[:, 1] + (1 << 20)) << 21) | (keys[:, 2] + (1 << 20))
    _, inv, counts = np.unique(packed, return_inverse=True, return_counts=True)
    n_vox = len(counts)
    out_p = np.empty((n_vox, 3), dtype=np.float32)
    out_c = np.empty((n_vox, 3), dtype=np.uint8)
    for c in range(3):
        out_p[:, c] = np.bincount(inv, weights=pts_raw[:, c], minlength=n_vox) / counts
        out_c[:, c] = np.clip(np.rint(np.bincount(inv, weights=cols_raw[:, c], minlength=n_vox) / counts), 0, 255)
    keep_vox = counts >= 2
    pts_vox = out_p[keep_vox]
    cols_vox = out_c[keep_vox]
    log(f"depth fused: {n_raw:,} raw -> {n_vox:,} voxels -> {len(pts_vox):,} multi-view consistent voxels (count>=2)")

    # Write metric poses copy (sfm/poses_m.json) so geometry.py aligns in the exact metric frame!
    poses_m = json.loads((sfm / "poses.json").read_text(encoding="utf-8"))
    for fr in poses_m["frames"]:
        w2c = np.asarray(fr["w2c"], np.float64)
        w2c[:3, 3] *= scale
        fr["w2c"] = w2c.tolist()
    poses_m["note"] = f"translations scaled by depth-derived metric scale {scale:.6f}"
    (sfm / "poses_m.json").write_text(json.dumps(poses_m), encoding="utf-8")

    depth_dir = RUN / "depth"
    depth_dir.mkdir(exist_ok=True)
    np.savez_compressed(depth_dir / "map.npz", points=pts_vox, colors=cols_vox)
    (depth_dir / "scale.json").write_text(json.dumps({
        "scale_m_per_unit": scale,
        "method": "median(depth_m / sparse_camera_z) + per-frame Huber edge-masked fusion",
        "samples": int(len(ratios)),
        "mad_rel": mad_rel,
    }, indent=2), encoding="utf-8")
    report = {
        "stage": "depth",
        "status": "ok",
        "model": MODEL_ID,
        "frames": len(f_list),
        "frames_fused": frames_fused,
        "points_raw": int(n_raw),
        "points_voxel": int(len(pts_vox)),
        "scale_m_per_unit": round(scale, 5),
        "scale_samples": int(len(ratios)),
        "scale_mad_rel": round(mad_rel, 4),
        "depth_max_m": DEPTH_MAX_M,
        "grad_rel_max": GRAD_REL_MAX,
        "timing_seconds": round(time.time() - t0, 1),
        "warnings": [],
    }
    (depth_dir / "depth_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def write_ply_xyzrgb(path: Path, pts: np.ndarray, cols: np.ndarray) -> None:
    n = len(pts)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n"
    ).encode("ascii")
    dt = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                   ("r", "u1"), ("g", "u1"), ("b", "u1")])
    arr = np.empty(n, dtype=dt)
    arr["x"], arr["y"], arr["z"] = pts[:, 0], pts[:, 1], pts[:, 2]
    arr["r"], arr["g"], arr["b"] = cols[:, 0], cols[:, 1], cols[:, 2]
    with open(path, "wb") as f:
        f.write(header)
        f.write(arr.tobytes())


def read_ply_xyzrgb(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with open(path, "rb") as f:
        props, count = [], 0
        while True:
            line = f.readline().decode("ascii").strip()
            parts = line.split()
            if parts[:2] == ["element", "vertex"]:
                count = int(parts[2])
            elif parts[:1] == ["property"]:
                props.append((parts[2], parts[1]))
            elif line == "end_header":
                break
        np_t = {"float": "<f4", "float32": "<f4", "double": "<f8", "uchar": "u1", "uint8": "u1"}
        dt = np.dtype([(n, np_t[t]) for n, t in props])
        raw = np.frombuffer(f.read(count * dt.itemsize), dtype=dt, count=count)
    pts = np.column_stack([raw["x"], raw["y"], raw["z"]]).astype(np.float32)
    cols = np.column_stack([raw["red"], raw["green"], raw["blue"]]).astype(np.uint8)
    return pts, cols


def build_combined_seed_cloud() -> int:
    """Combine metricized SfM sparse points + clean multi-view consistent metric depth points."""
    sfm_pts, sfm_cols = read_ply_xyzrgb(RUN / "sparse.ply")
    d = np.load(RUN / "depth" / "map.npz")
    d_pts, d_cols = d["points"], d["colors"]

    # Subsample depth voxels to SEED_MAX_PTS evenly
    if len(d_pts) > SEED_MAX_PTS:
        rng = np.random.default_rng(42)
        sel = rng.choice(len(d_pts), SEED_MAX_PTS, replace=False)
        d_pts, d_cols = d_pts[sel], d_cols[sel]

    pts = np.vstack([sfm_pts, d_pts])
    cols = np.vstack([sfm_cols, d_cols])
    seed_p = RUN / "seed_cloud.ply"
    write_ply_xyzrgb(seed_p, pts, cols)

    tf_p = RUN / "transforms.json"
    tf = json.loads(tf_p.read_text(encoding="utf-8"))
    tf["ply_file_path"] = "seed_cloud.ply"
    tf_p.write_text(json.dumps(tf, indent=2), encoding="utf-8")
    log(f"combined seed cloud: {len(sfm_pts):,} SfM + {len(d_pts):,} depth = {len(pts):,} seeds -> seed_cloud.ply")
    return len(pts)


def run_stage(args: list[str]) -> None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    log(f"run: {' '.join(args)}")
    subprocess.run([sys.executable, "-m", "namma.cli", *args], cwd=CODE, env=env, check=True)


TRAIN_SNIPPET = r'''
import copy
import sys
from pathlib import Path

from nerfstudio.configs.method_configs import method_configs
from nerfstudio.data.dataparsers.nerfstudio_dataparser import NerfstudioDataParserConfig

RUN = Path(sys.argv[1])
NS_OUT = Path(sys.argv[2])
ITERS = int(sys.argv[3])

method_name = "splatfacto-big" if "splatfacto-big" in method_configs else "splatfacto"
cfg = copy.deepcopy(method_configs[method_name])
cfg.output_dir = NS_OUT
cfg.experiment_name = "capture"
cfg.timestamp = "run1"
cfg.max_num_iterations = ITERS
cfg.viewer.quit_on_train_completion = True

m = cfg.pipeline.model

def set_if(obj, attr, val):
    if hasattr(obj, attr):
        setattr(obj, attr, val)
        print(f"  [cfg] {attr} = {val!r}", flush=True)
    else:
        print(f"  [skip] no attr {attr}", flush=True)

print(f"Configuring {method_name} ({ITERS} iters)...", flush=True)
# 1. Refine 1.57 px DISK poses jointly during 3DGS -> eliminates pose-jitter blur!
if hasattr(m, "camera_optimizer") and hasattr(m.camera_optimizer, "mode"):
    m.camera_optimizer.mode = "SO3xR3"
    print("  [cfg] camera_optimizer.mode = 'SO3xR3'", flush=True)

# 2. Suppress spikes & elongated needles mathematically during training!
set_if(m, "use_scale_regularization", True)
set_if(m, "max_gauss_ratio", 3.5)

# 3. Match DC-only web .ksplat 1:1 (zero SH-stripping color collapse / off-angle gray shards!)
set_if(m, "sh_degree", 0)

# 4. Mip-Splatting anti-aliasing + native resolution from iter 0 + AbsGS wall sharpening!
set_if(m, "rasterize_mode", "antialiased")
set_if(m, "num_downscales", 0)
set_if(m, "use_absgrad", True)
set_if(m, "densify_grad_thresh", 0.0008)
set_if(m, "stop_split_at", min(20000, ITERS - 5000))

# 5. Aggressive indoor floater & giant-blob culling (scene is in metric meters!)
set_if(m, "cull_alpha_thresh", 0.025)
set_if(m, "cull_scale_thresh", 0.06)
set_if(m, "cull_screen_size", 0.10)
set_if(m, "continue_cull_post_densification", True)

# 6. Bilateral grid for phone auto-exposure shifts across doorways (if supported)
set_if(m, "use_bilateral_grid", True)

cfg.pipeline.datamanager.camera_res_scale_factor = 1.0
if hasattr(cfg.pipeline.datamanager, "cache_images_type"):
    cfg.pipeline.datamanager.cache_images_type = "uint8"

# Train on 100% of all continuous loop frames (no 10% holdout blind spots!)
dp_kwargs = dict(
    data=RUN,
    orientation_method="none",
    center_method="none",
    auto_scale_poses=False,
    load_3D_points=True,
    eval_mode="all",
)
cfg.pipeline.datamanager.dataparser = NerfstudioDataParserConfig(**dp_kwargs)
cfg.save_config()

trainer = cfg.setup(local_rank=0, world_size=1)
trainer.setup()
trainer.train()
print("TRAIN_DONE", flush=True)
'''

EXPORT_SNIPPET = r'''
import sys
from pathlib import Path
import torch

_orig_load = torch.load
def _load(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_load(*args, **kwargs)
torch.load = _load

from nerfstudio.scripts.exporter import ExportGaussianSplat

config = Path(sys.argv[1])
out = Path(sys.argv[2])
ExportGaussianSplat(load_config=config, output_dir=out).main()
print("EXPORT_DONE", flush=True)
'''


def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    errors: dict[str, str] = {}

    try:
        stage_code()
        stage_capture()
        ensure_deps()

        import torch
        log(f"CUDA: {torch.cuda.is_available()} | {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none'}")
        if not torch.cuda.is_available():
            raise SystemExit("CUDA unavailable")

        # 1. Drop disconnected outlier tail frames before depth & 3DGS
        n_frames = filter_continuous_loop()

        # 2. Clean edge-filtered, Huber-aligned indoor metric depth fusion
        depth_report = run_clean_depth_and_seed()

        # 3. Metricize transforms.json + sparse.ply using the new metric scale
        run_stage(["metricize", str(RUN)])

        # 4. Run geometry on the clean dense metric depth cloud
        run_stage(["geometry", str(RUN)])

        # 5. Build combined SfM + multi-view-consistent dense depth seed cloud
        n_seeds = build_combined_seed_cloud()

        # 6. Train anti-blur, anti-spike splatfacto-big
        train_py = SCRATCH / "train_hq.py"
        train_py.write_text(TRAIN_SNIPPET, encoding="utf-8")
        env = os.environ.copy()
        env["MAX_JOBS"] = os.environ.get("NM_MAX_JOBS", "2")
        env["TORCH_CUDA_ARCH_LIST"] = "7.5"
        env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        r = subprocess.run([sys.executable, str(train_py), str(RUN), str(NS_OUT), str(ITERS)],
                           env=env, capture_output=True, text=True, timeout=6 * 3600)
        log(f"train exit={r.returncode}")
        log("TRAIN STDOUT TAIL:\n" + (r.stdout or "")[-2000:])
        if r.returncode != 0 or "TRAIN_DONE" not in (r.stdout or ""):
            log("TRAIN STDERR TAIL:\n" + (r.stderr or "")[-2500:])
            raise SystemExit(f"training failed (exit {r.returncode})")

        configs = sorted(NS_OUT.glob("capture/**/config.yml"))
        if not configs:
            raise SystemExit("no config.yml after training")
        cfg_p = configs[-1]

        # 7. Export raw splat.ply
        exp_dir = SCRATCH / "export"
        exp_dir.mkdir(parents=True, exist_ok=True)
        exp_py = SCRATCH / "export_hq.py"
        exp_py.write_text(EXPORT_SNIPPET, encoding="utf-8")
        re_ = subprocess.run([sys.executable, str(exp_py), str(cfg_p), str(exp_dir)],
                             capture_output=True, text=True, timeout=3600)
        log(f"export exit={re_.returncode}")
        if re_.returncode != 0 or "EXPORT_DONE" not in (re_.stdout or ""):
            raise SystemExit(f"export failed:\n{(re_.stderr or '')[-2000:]}")
        ply = sorted(exp_dir.glob("*.ply"))[0]
        shutil.copy2(ply, OUT / "splat.ply")
        log(f"exported raw PLY: {ply.stat().st_size / 1e6:.2f} MB")

        # 8. Collect all clean artifacts
        for rel in ("depth/scale.json", "depth/depth_report.json", "depth/map.npz",
                    "metricize.json", "nav/nav.json", "nav/nav_report.json",
                    "nav/occupancy.png", "sfm/poses.json", "sfm/sfm_report.json",
                    "frames_meta.json", "transforms.json"):
            src = RUN / rel
            if src.exists():
                shutil.copy2(src, OUT / Path(rel).name)

        summary = {
            "status": "ok",
            "elapsed_s": round(time.time() - t0, 1),
            "frames_trained": n_frames,
            "seed_points": n_seeds,
            "iters": ITERS,
            "depth_report": depth_report,
            "ply_bytes": (OUT / "splat.ply").stat().st_size,
            "errors": errors,
        }
        (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        log(f"DONE in {summary['elapsed_s']:.1f}s -> {[p.name for p in sorted(OUT.iterdir())]}")
    except Exception as e:
        errors["fatal"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        (OUT / "summary.json").write_text(json.dumps({"status": "error", "errors": errors}, indent=2), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
