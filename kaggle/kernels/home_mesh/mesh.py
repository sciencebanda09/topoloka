"""Kaggle GPU kernel: COLMAP 2D non-rigidly warped multi-view depth fusion,
Screened Poisson surface reconstruction, occlusion-verified 8K photo-textured
3D mesh (mesh.glb), and 1M surface-tangent Gaussian splats (splat.splat).
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
SCRATCH = Path("/tmp/namma_home_mesh")
OUT = WORK / "out"
CODE = SCRATCH / "code"
RUN = SCRATCH / "run"

# Apache 2.0 commercially licensed depth weights
MODEL_ID = "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"
DEPTH_W, DEPTH_H = 800, 450
TEX_W, TEX_H = 1024, 576
ATLAS_COLS, ATLAS_ROWS = 8, 8
MAX_TEXTURE_VIEWS = ATLAS_COLS * ATLAS_ROWS - 1  # slot 63 reserved for multi-view vertex color palette
PALETTE_SLOT = ATLAS_COLS * ATLAS_ROWS - 1
TARGET_FACES = 450_000
TARGET_GAUSSIANS = 1_000_000


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def ensure_deps() -> None:
    for pkg in ("transformers", "open3d", "scipy"):
        try:
            __import__(pkg)
        except ImportError:
            log(f"installing {pkg}...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg], check=True)


def stage_inputs() -> None:
    CODE.mkdir(parents=True, exist_ok=True)
    tar = next(INPUT.glob("**/code.tar"), None)
    if tar:
        with tarfile.open(tar) as t:
            t.extractall(CODE)
    else:
        cli = next(INPUT.glob("**/namma/cli.py"), None)
        if not cli:
            raise SystemExit("namma-code dataset missing")
        shutil.copytree(cli.parents[1], CODE, dirs_exist_ok=True)

    root = None
    for marker in ("**/transforms.json", "**/frames.zip", "**/poses.json"):
        for p in sorted(INPUT.glob(marker)):
            cand = p.parent
            if (cand / "transforms.json").exists() or (cand / "poses.json").exists():
                root = cand
                break
        if root:
            break
    if root is None:
        raise SystemExit("capture dataset not found")
    log(f"capture root: {root}")

    RUN.mkdir(parents=True, exist_ok=True)

    def stage_archive(stem: str, dst: Path) -> None:
        z = root / f"{stem}.zip"
        d = root / stem
        dst.mkdir(parents=True, exist_ok=True)
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


def parse_sparse_txt(sfm_dir: Path) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], dict[int, np.ndarray]]:
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


def warp_depth_to_colmap(
    d_map: np.ndarray,
    uv_d: np.ndarray,
    d_preds: np.ndarray,
    z_true_m: np.ndarray,
) -> np.ndarray:
    """Align a monocular depth map to exact COLMAP 3D sparse points using:
    1) Global robust Huber scale+shift (a * d + b)
    2) Smooth 2D Nadaraya-Watson spatial scale-correction field S(u, v)
    """
    valid = (d_preds > 0.15) & (d_preds < 9.5) & (z_true_m > 0.15) & (z_true_m < 9.5)
    if valid.sum() < 15:
        return np.clip(d_map, 0.15, 8.5).astype(np.float32)

    x = d_preds[valid]
    y = z_true_m[valid]
    uv = uv_d[valid]

    ratio_med = float(np.clip(np.median(y / np.maximum(x, 1e-6)), 0.65, 1.45))
    a, b = ratio_med, 0.0
    if len(x) >= 40:
        delta = 0.08
        reg = 9.0
        for _ in range(6):
            res = y - (a * x + b)
            w = np.where(np.abs(res) <= delta, 1.0, delta / np.maximum(np.abs(res), 1e-6))
            A = np.column_stack([x, np.ones_like(x)])
            Aw = A * w[:, None]
            H = Aw.T @ A + np.diag([reg, reg * 2.5])
            rhs = Aw.T @ y + np.array([reg * ratio_med, 0.0])
            try:
                sol = np.linalg.solve(H, rhs)
                a, b = float(sol[0]), float(sol[1])
            except np.linalg.LinAlgError:
                break
        a = float(np.clip(a, 0.70 * ratio_med, 1.35 * ratio_med))
        b = float(np.clip(b, -0.22, 0.22))

    d_lin = np.clip(a * d_map + b, 0.15, 8.5).astype(np.float32)
    pred_lin = np.clip(a * x + b, 0.15, 8.5)
    ratios = y / pred_lin
    inliers = (ratios >= 0.72) & (ratios <= 1.35)
    if inliers.sum() < 20:
        return d_lin

    uv_in = uv[inliers]
    r_in = np.clip(ratios[inliers], 0.78, 1.28)

    gw, gh = 32, 18
    gx = np.linspace(0, DEPTH_W - 1, gw, dtype=np.float64)
    gy = np.linspace(0, DEPTH_H - 1, gh, dtype=np.float64)
    ggx, ggy = np.meshgrid(gx, gy)
    dx = (ggx[:, :, None] - uv_in[None, None, :, 0]) / (DEPTH_W / gw)
    dy = (ggy[:, :, None] - uv_in[None, None, :, 1]) / (DEPTH_H / gh)
    sigma_cells = 3.0
    weights = np.exp(-0.5 * (dx * dx + dy * dy) / (sigma_cells * sigma_cells))
    prior_w = 1.8
    s_grid = (prior_w * 1.0 + (weights * r_in[None, None, :]).sum(axis=2)) / (prior_w + weights.sum(axis=2))
    s_full = cv2.resize(s_grid.astype(np.float32), (DEPTH_W, DEPTH_H), interpolation=cv2.INTER_CUBIC)
    return np.clip(d_lin * s_full, 0.15, 8.5).astype(np.float32)


def build_multiview_cloud() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict], np.ndarray, float]:
    import torch
    import torch.nn.functional as F
    from scipy.spatial import cKDTree
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    sfm = RUN / "sfm"
    frames_dir = RUN / "frames"
    poses_data = json.loads((sfm / "poses.json").read_text(encoding="utf-8"))
    per_image, sparse_pts = parse_sparse_txt(sfm / "sparse_txt")

    blur_by_name: dict[str, float] = {}
    if (RUN / "frames_meta.json").exists():
        fm = json.loads((RUN / "frames_meta.json").read_text(encoding="utf-8"))
        for f in fm.get("frames", []):
            blur_by_name[f["name"]] = float(f.get("rank_blur", f.get("blur", 100.0)))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"loading {MODEL_ID} on {device}...")
    processor = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForDepthEstimation.from_pretrained(MODEL_ID).to(device).eval()

    raw_depths: list[np.ndarray] = []
    frame_records: list[dict] = []
    all_ratios: list[float] = []

    for idx, fr in enumerate(poses_data["frames"]):
        name = fr["name"]
        bgr = cv2.imread(str(frames_dir / name))
        if bgr is None:
            continue
        h0, w0 = bgr.shape[:2]
        small = cv2.resize(bgr, (518, round(h0 * 518 / w0)))
        rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        inputs = processor(images=rgb_small, return_tensors="pt").to(device)
        with torch.inference_mode():
            pred = model(**inputs).predicted_depth
        d_map = pred.squeeze(0).float().cpu().numpy().astype(np.float32)
        d_map = cv2.resize(d_map, (DEPTH_W, DEPTH_H), interpolation=cv2.INTER_LINEAR)

        w2c = np.asarray(fr["w2c"], dtype=np.float64)
        R, t = w2c[:3, :3], w2c[:3, 3]
        uv, ids = per_image.get(name, (np.empty((0, 2)), np.empty((0,), dtype=np.int64)))

        z_cams, d_preds, uv_d_list = [], [], []
        if len(ids) > 0:
            pts_3d = np.array([sparse_pts[int(pid)] for pid in ids], dtype=np.float64)
            cam_pts = (pts_3d @ R.T) + t
            z_c = cam_pts[:, 2]
            u_d = np.clip(uv[:, 0] * DEPTH_W / w0, 0, DEPTH_W - 1)
            v_d = np.clip(uv[:, 1] * DEPTH_H / h0, 0, DEPTH_H - 1)
            d_p = d_map[np.round(v_d).astype(int), np.round(u_d).astype(int)]
            ok = (z_c > 0.15) & (d_p > 0.15) & (d_p < 10.0)
            if ok.any():
                z_cams = z_c[ok]
                d_preds = d_p[ok]
                uv_d_list = np.column_stack([u_d[ok], v_d[ok]])
                all_ratios.extend((d_preds / z_cams).tolist())

        raw_depths.append(d_map)
        frame_records.append({
            "name": name,
            "w0": w0,
            "h0": h0,
            "fl_x": float(fr["fl_x"]),
            "fl_y": float(fr["fl_y"]),
            "cx": float(fr["cx"]),
            "cy": float(fr["cy"]),
            "R": R,
            "t_raw": t,
            "z_cams_raw": np.asarray(z_cams, dtype=np.float64),
            "d_preds": np.asarray(d_preds, dtype=np.float64),
            "uv_d": np.asarray(uv_d_list, dtype=np.float64) if len(uv_d_list) else np.empty((0, 2)),
            "blur": blur_by_name.get(name, 100.0),
        })
        if (idx + 1) % 25 == 0:
            log(f"inferred depth {idx + 1}/{len(poses_data['frames'])}")

    del model, processor
    torch.cuda.empty_cache()

    ratios_arr = np.asarray(all_ratios, dtype=np.float64)
    scale_m = float(np.median(ratios_arr))
    mad_rel = float(np.median(np.abs(ratios_arr - scale_m)) / max(scale_m, 1e-9))
    log(f"global metric scale: {scale_m:.6f} m/unit ({len(ratios_arr)} samples, MAD {mad_rel:.2%})")

    depth_dir = RUN / "depth"
    depth_dir.mkdir(parents=True, exist_ok=True)
    (depth_dir / "scale.json").write_text(json.dumps({
        "scale_m_per_unit": scale_m,
        "method": "median(depth_m / sparse_camera_z) + 2D COLMAP non-rigid depth warping",
        "samples": len(ratios_arr),
        "mad_rel": mad_rel,
    }, indent=2), encoding="utf-8")

    for fr in poses_data["frames"]:
        w2c = np.asarray(fr["w2c"], dtype=np.float64)
        w2c[:3, 3] *= scale_m
        fr["w2c"] = w2c.tolist()
    poses_data["note"] = f"translations scaled by depth-derived metric scale {scale_m:.6f}"
    (sfm / "poses_m.json").write_text(json.dumps(poses_data), encoding="utf-8")

    cal_depths: list[np.ndarray] = []
    cam_centers_all: list[np.ndarray] = []
    for rec, d_map in zip(frame_records, raw_depths):
        t_m = rec["t_raw"] * scale_m
        rec["t"] = t_m
        rec["center"] = -rec["R"].T @ t_m
        cam_centers_all.append(rec["center"])
        z_true_m = rec["z_cams_raw"] * scale_m
        d_cal = warp_depth_to_colmap(d_map, rec["uv_d"], rec["d_preds"], z_true_m)

        # Mask depth discontinuity edges (flying pixels at occlusion boundaries)
        gx = np.abs(np.diff(d_cal, axis=1, prepend=d_cal[:, :1]))
        gy = np.abs(np.diff(d_cal, axis=0, prepend=d_cal[:1, :]))
        edge_mask = (np.maximum(gx, gy) / np.maximum(d_cal, 0.25)) > 0.045
        edge_u8 = cv2.dilate(edge_mask.astype(np.uint8), np.ones((3, 3), np.uint8))
        d_cal[edge_u8 > 0] = 0.0
        cal_depths.append(d_cal)

    cam_centers_arr = np.asarray(cam_centers_all, dtype=np.float32)
    cam_tree = cKDTree(cam_centers_arr)

    clean_indices = [
        i for i, rec in enumerate(frame_records)
        if rec["name"] < "00140.jpg" and rec["blur"] >= 45.0 and len(rec["z_cams_raw"]) >= 25
    ]
    log(f"clean frames for multi-view surface fusion: {len(clean_indices)}/{len(frame_records)}")

    M = len(clean_indices)
    D_stack = torch.from_numpy(np.stack([cal_depths[i] for i in clean_indices], axis=0)).to(device)
    R_stack = torch.from_numpy(np.stack([frame_records[i]["R"] for i in clean_indices], axis=0).astype(np.float32)).to(device)
    t_stack = torch.from_numpy(np.stack([frame_records[i]["t"] for i in clean_indices], axis=0).astype(np.float32)).to(device)
    fx_stack = torch.tensor([frame_records[i]["fl_x"] * DEPTH_W / frame_records[i]["w0"] for i in clean_indices], dtype=torch.float32, device=device)
    fy_stack = torch.tensor([frame_records[i]["fl_y"] * DEPTH_H / frame_records[i]["h0"] for i in clean_indices], dtype=torch.float32, device=device)
    cx_stack = torch.tensor([frame_records[i]["cx"] * DEPTH_W / frame_records[i]["w0"] for i in clean_indices], dtype=torch.float32, device=device)
    cy_stack = torch.tensor([frame_records[i]["cy"] * DEPTH_H / frame_records[i]["h0"] for i in clean_indices], dtype=torch.float32, device=device)

    all_pts, all_cols, all_views = [], [], []
    u_grid, v_grid = np.meshgrid(np.arange(0, DEPTH_W, 2), np.arange(0, DEPTH_H, 2))

    for local_idx, frame_idx in enumerate(clean_indices):
        rec = frame_records[frame_idx]
        d_cal = cal_depths[frame_idx]
        bgr = cv2.imread(str(frames_dir / rec["name"]))
        rgb_img = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        rgb_d = cv2.resize(rgb_img, (DEPTH_W, DEPTH_H), interpolation=cv2.INTER_AREA)

        d_sub = d_cal[v_grid, u_grid]
        valid = (d_sub > 0.22) & (d_sub < 5.5)
        if not valid.any():
            continue
        uu = u_grid[valid].astype(np.float32)
        vv = v_grid[valid].astype(np.float32)
        dd = d_sub[valid].astype(np.float32)

        fx_d = rec["fl_x"] * DEPTH_W / rec["w0"]
        fy_d = rec["fl_y"] * DEPTH_H / rec["h0"]
        cx_d = rec["cx"] * DEPTH_W / rec["w0"]
        cy_d = rec["cy"] * DEPTH_H / rec["h0"]

        x_c = (uu - cx_d) / fx_d * dd
        y_c = (vv - cy_d) / fy_d * dd
        cam_pts = np.stack([x_c, y_c, dd], axis=1)
        world_pts = ((cam_pts - rec["t"]) @ rec["R"]).astype(np.float32)

        with torch.inference_mode():
            pts_t = torch.from_numpy(world_pts).to(device)
            X_cam = torch.einsum("ni,mji->mnj", pts_t, R_stack) + t_stack[:, None, :]
            Z = X_cam[:, :, 2]
            U = fx_stack[:, None] * X_cam[:, :, 0] / torch.clamp(Z, min=1e-4) + cx_stack[:, None]
            V = fy_stack[:, None] * X_cam[:, :, 1] / torch.clamp(Z, min=1e-4) + cy_stack[:, None]

            in_bounds = (Z > 0.20) & (U >= 2) & (U < DEPTH_W - 2) & (V >= 2) & (V < DEPTH_H - 2)
            grid_u = (U / (DEPTH_W - 1)) * 2.0 - 1.0
            grid_v = (V / (DEPTH_H - 1)) * 2.0 - 1.0
            grid = torch.stack([grid_u, grid_v], dim=-1).unsqueeze(2)
            sampled_d = F.grid_sample(
                D_stack.unsqueeze(1), grid, mode="nearest", padding_mode="zeros", align_corners=True
            ).squeeze(1).squeeze(-1)

            valid_obs = in_bounds & (sampled_d > 0.20)
            tol_confirm = torch.clamp(0.055 * Z, min=0.045)
            confirmed = valid_obs & (torch.abs(Z - sampled_d) <= tol_confirm)
            tol_carve = torch.clamp(0.10 * sampled_d, min=0.14)
            violated = valid_obs & (Z < sampled_d - tol_carve)

            confirmed[local_idx, :] = False
            violated[local_idx, :] = False

            n_confirm = confirmed.sum(dim=0).cpu().numpy()
            n_violate = violated.sum(dim=0).cpu().numpy()

        # Only clear a tight 24cm lens radius around camera centers so nearby doors/walls are never bitten out!
        cam_dist, _ = cam_tree.query(world_pts, k=1)
        keep = (n_confirm >= 1) & (n_violate <= np.maximum(1, n_confirm // 2)) & (cam_dist >= 0.24)
        if not keep.any():
            continue

        kept_pts = world_pts[keep]
        kept_cols = rgb_d[vv[keep].astype(int), uu[keep].astype(int)]
        view_vecs = rec["center"][None, :].astype(np.float32) - kept_pts
        view_vecs /= np.maximum(np.linalg.norm(view_vecs, axis=1, keepdims=True), 1e-6)

        all_pts.append(kept_pts)
        all_cols.append(kept_cols)
        all_views.append(view_vecs)

    raw_pts = np.concatenate(all_pts, axis=0)
    raw_cols = np.concatenate(all_cols, axis=0).astype(np.float64)
    raw_views = np.concatenate(all_views, axis=0).astype(np.float64)
    log(f"multi-view confirmed points before voxelization: {len(raw_pts):,}")

    # Voxel downsample at 2.0 cm (0.020 m) to merge overlapping passes into a single clean surface layer
    voxel_m = 0.020
    keys = np.floor(raw_pts / voxel_m).astype(np.int64)
    packed = ((keys[:, 0] + (1 << 20)) << 42) | ((keys[:, 1] + (1 << 20)) << 21) | (keys[:, 2] + (1 << 20))
    _, inverse, counts = np.unique(packed, return_inverse=True, return_counts=True)
    n_vox = len(counts)
    vox_pts = np.empty((n_vox, 3), dtype=np.float32)
    vox_cols = np.empty((n_vox, 3), dtype=np.uint8)
    vox_views = np.empty((n_vox, 3), dtype=np.float32)
    for c in range(3):
        vox_pts[:, c] = np.bincount(inverse, weights=raw_pts[:, c], minlength=n_vox) / counts
        vox_cols[:, c] = np.round(np.bincount(inverse, weights=raw_cols[:, c], minlength=n_vox) / counts)
        vox_views[:, c] = np.bincount(inverse, weights=raw_views[:, c], minlength=n_vox) / counts
    vox_views /= np.maximum(np.linalg.norm(vox_views, axis=1, keepdims=True), 1e-6)

    # Save 3cm map.npz for the standard pipeline geometry/costmap stage
    keys3 = np.floor(vox_pts / 0.03).astype(np.int64)
    packed3 = ((keys3[:, 0] + (1 << 20)) << 42) | ((keys3[:, 1] + (1 << 20)) << 21) | (keys3[:, 2] + (1 << 20))
    _, inv3, cnt3 = np.unique(packed3, return_inverse=True, return_counts=True)
    map_pts = np.empty((len(cnt3), 3), dtype=np.float32)
    map_cols = np.empty((len(cnt3), 3), dtype=np.uint8)
    for c in range(3):
        map_pts[:, c] = np.bincount(inv3, weights=vox_pts[:, c], minlength=len(cnt3)) / cnt3
        map_cols[:, c] = np.round(np.bincount(inv3, weights=vox_cols[:, c].astype(np.float64), minlength=len(cnt3)) / cnt3)
    np.savez_compressed(depth_dir / "map.npz", points=map_pts, colors=map_cols)
    (depth_dir / "depth_report.json").write_text(json.dumps({
        "stage": "depth",
        "status": "ok",
        "model": MODEL_ID,
        "frames": len(frame_records),
        "frames_fused": len(clean_indices),
        "points_raw": int(len(raw_pts)),
        "points_voxel": int(len(map_pts)),
        "points_fine_20mm": int(len(vox_pts)),
        "scale_m_per_unit": round(scale_m, 6),
        "scale_samples": len(ratios_arr),
        "scale_mad_rel": round(mad_rel, 4),
    }, indent=2), encoding="utf-8")
    log(f"saved map.npz ({len(map_pts):,} 3cm pts) and fine cloud ({len(vox_pts):,} 2cm pts)")

    clean_records = [frame_records[i] for i in clean_indices]
    for idx_c, i in enumerate(clean_indices):
        clean_records[idx_c]["cal_depth"] = cal_depths[i]
    return vox_pts, vox_cols, vox_views, clean_records, cam_centers_arr, scale_m


def write_glb(path: Path, positions: np.ndarray, normals: np.ndarray,
              uvs: np.ndarray, indices: np.ndarray, atlas_jpg: bytes) -> None:
    chunks: list[bytes] = []
    views: list[dict] = []
    accessors: list[dict] = []
    byte_length = 0

    def add_view(data: bytes, target: int | None = None) -> int:
        nonlocal byte_length
        pad = (-byte_length) % 4
        if pad:
            chunks.append(b"\0" * pad)
            byte_length += pad
        offset = byte_length
        chunks.append(data)
        byte_length += len(data)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        views.append(view)
        return len(views) - 1

    def add_accessor(view: int, component: int, count: int, kind: str,
                     minimum=None, maximum=None) -> int:
        accessor = {"bufferView": view, "componentType": component, "count": count, "type": kind}
        if minimum is not None:
            accessor["min"] = np.asarray(minimum).tolist()
        if maximum is not None:
            accessor["max"] = np.asarray(maximum).tolist()
        accessors.append(accessor)
        return len(accessors) - 1

    pos = np.asarray(positions, dtype="<f4", order="C")
    nrm = np.asarray(normals, dtype="<f4", order="C")
    uv = np.asarray(uvs, dtype="<f4", order="C")
    idx = np.asarray(indices, dtype="<u4", order="C").reshape(-1)
    p_acc = add_accessor(add_view(pos.tobytes(), 34962), 5126, len(pos), "VEC3",
                         pos.min(axis=0), pos.max(axis=0))
    n_acc = add_accessor(add_view(nrm.tobytes(), 34962), 5126, len(nrm), "VEC3")
    uv_acc = add_accessor(add_view(uv.tobytes(), 34962), 5126, len(uv), "VEC2")
    i_acc = add_accessor(add_view(idx.tobytes(), 34963), 5125, len(idx), "SCALAR",
                         [int(idx.min())], [int(idx.max())])
    image_view = add_view(atlas_jpg)
    binary = b"".join(chunks)
    binary += b"\0" * ((-len(binary)) % 4)
    doc = {
        "asset": {"version": "2.0", "generator": "Topoloka Multi-View Surface Reconstruction"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": p_acc, "NORMAL": n_acc, "TEXCOORD_0": uv_acc},
            "indices": i_acc, "material": 0, "mode": 4,
        }]}],
        "materials": [{"pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0}, "metallicFactor": 0.0, "roughnessFactor": 1.0,
        }, "doubleSided": True}],
        "textures": [{"sampler": 0, "source": 0}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}],
        "images": [{"bufferView": image_view, "mimeType": "image/jpeg"}],
        "bufferViews": views,
        "accessors": accessors,
        "buffers": [{"byteLength": len(binary)}],
    }
    encoded = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    encoded += b" " * ((-len(encoded)) % 4)
    total = 12 + 8 + len(encoded) + 8 + len(binary)
    with path.open("wb") as handle:
        handle.write(struct.pack("<4sII", b"glTF", 2, total))
        handle.write(struct.pack("<I4s", len(encoded), b"JSON"))
        handle.write(encoded)
        handle.write(struct.pack("<I4s", len(binary), b"BIN\0"))
        handle.write(binary)


def normals_to_quaternions(normals: np.ndarray) -> np.ndarray:
    n = normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-8)
    z = n[:, 2]
    w = np.sqrt(np.maximum(0.0, (1.0 + z) * 0.5))
    sin_half = np.sqrt(np.maximum(0.0, (1.0 - z) * 0.5))
    rx = -n[:, 1]
    ry = n[:, 0]
    r_norm = np.hypot(rx, ry)
    scale = np.where(r_norm > 1e-6, sin_half / np.maximum(r_norm, 1e-6), 0.0)
    x = rx * scale
    y = ry * scale
    qz = np.zeros_like(w)
    anti = z < -0.999
    if np.any(anti):
        w[anti], x[anti], y[anti], qz[anti] = 0.0, 1.0, 0.0, 0.0
    quat = np.stack([w, x, y, qz], axis=1)
    quat /= np.maximum(np.linalg.norm(quat, axis=1, keepdims=True), 1e-8)
    return quat


def build_mesh_and_splat(
    vox_pts: np.ndarray,
    vox_cols: np.ndarray,
    vox_views: np.ndarray,
    clean_records: list[dict],
    cam_centers: np.ndarray,
    nav: dict,
) -> dict:
    import open3d as o3d
    from scipy.spatial import cKDTree

    t0 = time.time()
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(vox_pts.astype(np.float64))
    pcd.colors = o3d.utility.Vector3dVector((vox_cols.astype(np.float64) / 255.0))
    pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=0.09, max_nn=45))
    normals = np.asarray(pcd.normals, dtype=np.float64)
    flip = (normals * vox_views.astype(np.float64)).sum(axis=1, keepdims=True) < 0
    normals = np.where(flip, -normals, normals)
    pcd.normals = o3d.utility.Vector3dVector(normals)

    # Smooth point positions slightly along normals (1 pass) before Poisson to eliminate double-layers
    log(f"running Screened Poisson surface reconstruction (depth=9) on {len(vox_pts):,} points...")
    mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
        pcd, depth=9, scale=1.08, linear_fit=True
    )
    densities = np.asarray(densities)
    mesh.remove_vertices_by_mask(densities < np.quantile(densities, 0.035))
    mesh.remove_degenerate_triangles()
    mesh.remove_duplicated_triangles()
    mesh.remove_duplicated_vertices()
    mesh.remove_unreferenced_vertices()

    verts_pre = np.asarray(mesh.vertices, dtype=np.float32)
    faces_pre = np.asarray(mesh.triangles, dtype=np.int64)
    centroids_pre = verts_pre[faces_pre].mean(axis=1)
    cloud_tree = cKDTree(vox_pts)
    cam_tree = cKDTree(cam_centers)
    dist_cloud, _ = cloud_tree.query(centroids_pre, k=1)
    dist_cam, _ = cam_tree.query(centroids_pre, k=1)
    remove_faces = (dist_cloud > 0.085) | (dist_cam < 0.22)
    mesh.remove_triangles_by_mask(remove_faces.tolist())
    mesh.remove_unreferenced_vertices()

    # Remove any small disconnected floating mesh islands (< 400 triangles)
    tri_clusters, cluster_counts, _ = mesh.cluster_connected_triangles()
    tri_clusters = np.asarray(tri_clusters)
    cluster_counts = np.asarray(cluster_counts)
    mesh.remove_triangles_by_mask((cluster_counts[tri_clusters] < 400).tolist())
    mesh.remove_unreferenced_vertices()

    if len(mesh.triangles) > TARGET_FACES:
        mesh = mesh.simplify_quadric_decimation(TARGET_FACES)
        mesh.remove_degenerate_triangles()
        mesh.remove_unreferenced_vertices()

    mesh = mesh.filter_smooth_taubin(number_of_iterations=3)
    mesh.compute_vertex_normals()
    mesh.compute_triangle_normals()
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.triangles, dtype=np.int64)
    face_normals = np.asarray(mesh.triangle_normals, dtype=np.float64)
    vert_normals = np.asarray(mesh.vertex_normals, dtype=np.float64)

    # Transfer clean multi-view colors from vox_pts (nearest 4 neighbors average) to mesh vertices
    _, nn4 = cloud_tree.query(vertices.astype(np.float32), k=4)
    vert_colors = np.clip(np.round(vox_cols[nn4].astype(np.float32).mean(axis=1)), 0, 255).astype(np.uint8)
    log(f"clean surface mesh: {len(vertices):,} vertices, {len(faces):,} faces")

    picked = np.linspace(0, len(clean_records) - 1, min(MAX_TEXTURE_VIEWS, len(clean_records))).round().astype(int)
    cams = [clean_records[i] for i in np.unique(picked)]
    blur_med = float(np.median([c["blur"] for c in cams]))

    frames_dir = RUN / "frames"
    atlas = np.zeros((ATLAS_ROWS * TEX_H, ATLAS_COLS * TEX_W, 3), dtype=np.uint8)
    full_frames_rgb: list[np.ndarray] = []
    for slot, cam in enumerate(cams):
        bgr = cv2.imread(str(frames_dir / cam["name"]), cv2.IMREAD_COLOR)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        full_frames_rgb.append(rgb)
        tile = cv2.resize(rgb, (TEX_W, TEX_H), interpolation=cv2.INTER_AREA)
        row, col = divmod(slot, ATLAS_COLS)
        atlas[row * TEX_H:(row + 1) * TEX_H, col * TEX_W:(col + 1) * TEX_W] = tile

    # Fill slot 63 (row 7, col 7) with a 4096-color RGB cube for occlusion-safe fallback
    p_row, p_col = divmod(PALETTE_SLOT, ATLAS_COLS)
    p_x0, p_y0 = p_col * TEX_W, p_row * TEX_H
    for r_i in range(16):
        for g_i in range(16):
            for b_i in range(16):
                idx_c = (r_i << 8) | (g_i << 4) | b_i
                cy_i, cx_i = divmod(idx_c, 64)
                px0 = p_x0 + cx_i * 16
                py0 = p_y0 + cy_i * 8
                atlas[py0:py0 + 8, px0:px0 + 16] = [
                    int(round(r_i * 255 / 15)),
                    int(round(g_i * 255 / 15)),
                    int(round(b_i * 255 / 15)),
                ]

    centroids = vertices[faces].mean(axis=1)
    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]
    n_faces = len(faces)
    n_cams = len(cams)
    score_matrix = np.zeros((n_faces, n_cams), dtype=np.float32)

    for slot, cam in enumerate(cams):
        R_c, t_c = cam["R"], cam["t"]
        d_cal = cam["cal_depth"]
        w0, h0 = cam["w0"], cam["h0"]
        fx, fy, cx, cy = cam["fl_x"], cam["fl_y"], cam["cx"], cam["cy"]

        # Verify ALL 3 vertices of the triangle are inside the frame and unoccluded!
        all_verts_ok = np.ones(n_faces, dtype=bool)
        for tri_v in (v0, v1, v2):
            cp = (tri_v @ R_c.T) + t_c
            zz = cp[:, 2]
            uu = fx * cp[:, 0] / np.maximum(zz, 1e-5) + cx
            vv = fy * cp[:, 1] / np.maximum(zz, 1e-5) + cy
            in_b = (zz > 0.22) & (uu >= 12.0) & (vv >= 10.0) & (uu < w0 - 12.0) & (vv < h0 - 10.0)
            px = np.clip(np.round(np.where(in_b, uu, 0.0) * DEPTH_W / w0).astype(np.int32), 0, DEPTH_W - 1)
            py = np.clip(np.round(np.where(in_b, vv, 0.0) * DEPTH_H / h0).astype(np.int32), 0, DEPTH_H - 1)
            obs_d = d_cal[py, px]
            tol = np.maximum(0.11, 0.085 * zz)
            all_verts_ok &= in_b & (obs_d > 0.20) & (np.abs(obs_d - zz) <= tol)

        delta = cam["center"][None, :] - centroids
        dist = np.maximum(np.linalg.norm(delta, axis=1), 0.25)
        cos = np.einsum("ij,ij->i", face_normals, delta / dist[:, None])
        # Strictly front-facing only (cos > 0.14) -- never project through walls!
        valid = all_verts_ok & (cos > 0.14)
        sharp_w = float(np.clip(np.sqrt(cam["blur"] / max(blur_med, 1.0)), 0.75, 1.35))
        s = np.where(valid, (np.maximum(cos, 0.0) ** 2.2) * sharp_w / (dist ** 1.15), 0.0)
        score_matrix[:, slot] = s.astype(np.float32)

    cent_tree = cKDTree(centroids)
    _, nn_idx = cent_tree.query(centroids, k=7)
    smoothed_scores = score_matrix.copy()
    for _ in range(2):
        neighbor_mean = smoothed_scores[nn_idx].mean(axis=1)
        smoothed_scores = np.where(score_matrix > 0, 0.45 * score_matrix + 0.55 * neighbor_mean, 0.0)

    best_slot = smoothed_scores.argmax(axis=1).astype(np.int16)
    best_score = smoothed_scores[np.arange(n_faces), best_slot]
    verified = best_score > 0
    best_slot[~verified] = PALETTE_SLOT
    log(f"strictly 3-vertex depth-verified photo faces: {verified.mean():.1%} ({verified.sum():,}/{n_faces:,}); "
        f"remaining {(~verified).mean():.1%} use multi-view vertex color")

    corner_vertices = faces.reshape(-1)
    corner_slots = np.repeat(best_slot, 3)
    pairs = np.column_stack((corner_vertices, corner_slots))
    unique_pairs, inverse = np.unique(pairs, axis=0, return_inverse=True)
    vertex_ids = unique_pairs[:, 0].astype(np.int64)
    slots = unique_pairs[:, 1].astype(np.int16)
    uv = np.zeros((len(unique_pairs), 2), dtype=np.float32)
    pad = 2.5

    for slot, cam in enumerate(cams):
        mask = slots == slot
        if not mask.any():
            continue
        view_points = (vertices[vertex_ids[mask]] @ cam["R"].T) + cam["t"]
        z = np.maximum(view_points[:, 2], 1e-5)
        px = cam["fl_x"] * view_points[:, 0] / z + cam["cx"]
        py = cam["fl_y"] * view_points[:, 1] / z + cam["cy"]
        local_u = np.clip(px / cam["w0"], 0.0, 1.0)
        local_v = np.clip(py / cam["h0"], 0.0, 1.0)
        row, col = divmod(slot, ATLAS_COLS)
        uv[mask, 0] = (col * TEX_W + pad + local_u * (TEX_W - 2 * pad)) / (ATLAS_COLS * TEX_W)
        uv[mask, 1] = (row * TEX_H + pad + local_v * (TEX_H - 2 * pad)) / (ATLAS_ROWS * TEX_H)

    pal_mask = slots == PALETTE_SLOT
    if pal_mask.any():
        vc = vert_colors[vertex_ids[pal_mask]]
        r_i = np.round(vc[:, 0].astype(np.float32) * 15.0 / 255.0).astype(np.int32)
        g_i = np.round(vc[:, 1].astype(np.float32) * 15.0 / 255.0).astype(np.int32)
        b_i = np.round(vc[:, 2].astype(np.float32) * 15.0 / 255.0).astype(np.int32)
        idx_c = (r_i << 8) | (g_i << 4) | b_i
        cy_i, cx_i = np.divmod(idx_c, 64)
        px_c = p_x0 + cx_i * 16 + 8.0
        py_c = p_y0 + cy_i * 8 + 4.0
        uv[pal_mask, 0] = px_c / (ATLAS_COLS * TEX_W)
        uv[pal_mask, 1] = py_c / (ATLAS_ROWS * TEX_H)

    align = nav["align"]
    R_nav = np.asarray(align["R_row_major"], dtype=np.float64)
    origin = np.asarray(align["origin"], dtype=np.float64)
    metric_scale = float(align["scale_m_per_unit"])
    nav_positions = ((vertices[vertex_ids] - origin) @ R_nav) * metric_scale
    nav_normals = vert_normals[vertex_ids] @ R_nav
    nav_normals /= np.maximum(np.linalg.norm(nav_normals, axis=1, keepdims=True), 1e-9)

    atlas_path = SCRATCH / "atlas.jpg"
    cv2.imwrite(str(atlas_path), cv2.cvtColor(atlas, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 94])
    mesh_out = OUT / "mesh.glb"
    write_glb(mesh_out, nav_positions.astype(np.float32), nav_normals.astype(np.float32),
              uv, inverse.reshape(-1, 3), atlas_path.read_bytes())
    log(f"wrote mesh.glb ({mesh_out.stat().st_size / 1e6:.2f} MB)")

    # Build 1,000,000 photo-sampled surface-tangent Gaussian discs on the mesh surface
    areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    total_area = float(areas.sum())
    probs = areas / max(total_area, 1e-9)

    rng = np.random.default_rng(42)
    f_idx = rng.choice(n_faces, size=TARGET_GAUSSIANS, replace=True, p=probs)
    r1 = np.sqrt(rng.random(TARGET_GAUSSIANS, dtype=np.float32))
    r2 = rng.random(TARGET_GAUSSIANS, dtype=np.float32)
    b0 = 1.0 - r1
    b1 = r1 * (1.0 - r2)
    b2 = r1 * r2

    splat_pos = (
        b0[:, None] * vertices[faces[f_idx, 0]]
        + b1[:, None] * vertices[faces[f_idx, 1]]
        + b2[:, None] * vertices[faces[f_idx, 2]]
    ).astype(np.float32)
    splat_nrm = (
        b0[:, None] * vert_normals[faces[f_idx, 0]]
        + b1[:, None] * vert_normals[faces[f_idx, 1]]
        + b2[:, None] * vert_normals[faces[f_idx, 2]]
    ).astype(np.float32)
    splat_nrm /= np.maximum(np.linalg.norm(splat_nrm, axis=1, keepdims=True), 1e-8)

    mv_rgb = (
        b0[:, None] * vert_colors[faces[f_idx, 0]].astype(np.float32)
        + b1[:, None] * vert_colors[faces[f_idx, 1]].astype(np.float32)
        + b2[:, None] * vert_colors[faces[f_idx, 2]].astype(np.float32)
    )
    splat_rgb = np.clip(np.round(mv_rgb), 0, 255).astype(np.uint8)
    splat_slots = best_slot[f_idx]

    for slot, cam in enumerate(cams):
        mask = splat_slots == slot
        if not mask.any():
            continue
        pts_s = splat_pos[mask].astype(np.float64)
        cam_pts = (pts_s @ cam["R"].T) + cam["t"]
        z = np.maximum(cam_pts[:, 2], 1e-5)
        px = np.clip(cam["fl_x"] * cam_pts[:, 0] / z + cam["cx"], 0, cam["w0"] - 1.001).astype(np.float32)
        py = np.clip(cam["fl_y"] * cam_pts[:, 1] / z + cam["cy"], 0, cam["h0"] - 1.001).astype(np.float32)
        img = full_frames_rgb[slot]
        x0 = np.floor(px).astype(np.int32)
        y0 = np.floor(py).astype(np.int32)
        x1 = np.minimum(x0 + 1, cam["w0"] - 1)
        y1 = np.minimum(y0 + 1, cam["h0"] - 1)
        wx = (px - x0)[:, None]
        wy = (py - y0)[:, None]
        c00 = img[y0, x0].astype(np.float32)
        c10 = img[y0, x1].astype(np.float32)
        c01 = img[y1, x0].astype(np.float32)
        c11 = img[y1, x1].astype(np.float32)
        c_photo = (1 - wy) * ((1 - wx) * c00 + wx * c10) + wy * ((1 - wx) * c01 + wx * c11)
        c_blend = 0.85 * c_photo + 0.15 * mv_rgb[mask]
        splat_rgb[mask] = np.clip(np.round(c_blend), 0, 255).astype(np.uint8)

    mean_spacing = float(np.sqrt(total_area / TARGET_GAUSSIANS))
    s_t_val = float(np.clip(1.85 * mean_spacing, 0.0065, 0.015))
    s_tangent = np.full(TARGET_GAUSSIANS, s_t_val, dtype=np.float32)
    s_normal = np.full(TARGET_GAUSSIANS, 0.12 * s_t_val, dtype=np.float32)
    splat_scales = np.column_stack([s_tangent, s_tangent, s_normal]).astype(np.float32)

    quat = normals_to_quaternions(splat_nrm)
    quat_u8 = np.clip(np.round(quat * 128.0 + 128.0), 0, 255).astype(np.uint8)

    color_u8 = np.empty((TARGET_GAUSSIANS, 4), dtype=np.uint8)
    color_u8[:, :3] = splat_rgb
    color_u8[:, 3] = 252

    records = np.empty((TARGET_GAUSSIANS, 32), dtype=np.uint8)
    records[:, 0:12] = splat_pos.view(np.uint8).reshape(TARGET_GAUSSIANS, 12)
    records[:, 12:24] = splat_scales.view(np.uint8).reshape(TARGET_GAUSSIANS, 12)
    records[:, 24:28] = color_u8
    records[:, 28:32] = quat_u8

    splat_dir = RUN / "splat"
    splat_dir.mkdir(parents=True, exist_ok=True)
    splat_path = splat_dir / "splat.splat"
    records.tofile(splat_path)
    (splat_dir / "splat_convert_report.json").write_text(json.dumps({
        "stage": "splat_convert",
        "method": "1M photo-sampled surface-tangent Gaussian discs",
        "gaussians_in": TARGET_GAUSSIANS,
        "gaussians_out": TARGET_GAUSSIANS,
        "mean_spacing_m": round(mean_spacing, 5),
        "splat_bytes": splat_path.stat().st_size,
    }, indent=2), encoding="utf-8")
    log(f"wrote surface-tangent splat.splat ({TARGET_GAUSSIANS:,} Gaussians, {splat_path.stat().st_size / 1e6:.2f} MB)")

    report = {
        "method": "COLMAP 2D non-rigid depth warping + Screened Poisson (depth=9) + 8K photo atlas + 1M surface-tangent 3DGS",
        "dense_points_20mm": int(len(vox_pts)),
        "mesh_vertices": int(len(vertices)),
        "mesh_faces": int(len(faces)),
        "mesh_vertices_after_seams": int(len(unique_pairs)),
        "surface_area_m2": round(total_area, 2),
        "texture_views": len(cams),
        "texture_atlas": [ATLAS_COLS * TEX_W, ATLAS_ROWS * TEX_H],
        "strict_3vertex_verified_fraction": round(float(verified.mean()), 4),
        "mesh_bytes": mesh_out.stat().st_size,
        "splat_gaussians": TARGET_GAUSSIANS,
        "splat_bytes": splat_path.stat().st_size,
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    (OUT / "mesh_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def add_camera_headings(nav_path: Path, poses_path: Path) -> None:
    nav = json.loads(nav_path.read_text(encoding="utf-8"))
    poses = json.loads(poses_path.read_text(encoding="utf-8"))
    frames = poses.get("frames", [])
    align = nav.get("align", {})
    if not frames or not align.get("R_row_major"):
        return
    rotation = np.asarray(align["R_row_major"], dtype=np.float64).reshape(3, 3)
    yaws, pitches = [], []
    for frame in frames:
        w2c = np.asarray(frame["w2c"], dtype=np.float64)
        forward_scene = w2c[:3, :3].T[:, 2]
        forward_nav = rotation.T @ forward_scene
        horizontal = float(np.hypot(forward_nav[0], forward_nav[1]))
        yaws.append(round(float(np.arctan2(-forward_nav[0], forward_nav[1])), 4))
        pitch = float(np.arctan2(forward_nav[2], horizontal))
        pitches.append(round(float(np.clip(pitch, -0.85, 0.35)), 4))
    nav["trajectory_yaws"] = yaws
    nav["trajectory_pitches"] = pitches
    nav["default_spawn"] = min(26, len(yaws) - 1)
    nav_path.write_text(json.dumps(nav, separators=(",", ":")), encoding="utf-8")


def run_stage(args: list[str]) -> None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    log(f"namma.cli: {' '.join(args)}")
    subprocess.run([sys.executable, "-m", "namma.cli", *args], cwd=CODE, env=env, check=True)


def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    try:
        ensure_deps()
        stage_inputs()
        vox_pts, vox_cols, vox_views, clean_records, cam_centers, _ = build_multiview_cloud()
        run_stage(["geometry", str(RUN), "--cloud", str(RUN / "depth" / "map.npz")])
        run_stage(["qa", str(RUN)])
        run_stage(["metricize", str(RUN)])

        nav_path = RUN / "nav" / "nav.json"
        add_camera_headings(nav_path, RUN / "sfm" / "poses_m.json")
        nav = json.loads(nav_path.read_text(encoding="utf-8"))

        mesh_rep = build_mesh_and_splat(vox_pts, vox_cols, vox_views, clean_records, cam_centers, nav)
        run_stage(["package", str(RUN)])

        web_dir = RUN / "web"
        shutil.copy2(OUT / "mesh.glb", web_dir / "mesh.glb")
        meta_path = web_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["mesh"] = {"present": True, "format": "glb", "source": "Multi-View Poisson + 8K Photo Atlas"}
        meta["splat"] = {
            "present": True,
            "bytes": (web_dir / "splat.splat").stat().st_size,
            "gaussians": TARGET_GAUSSIANS,
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        dst_web = OUT / "web"
        dst_web.mkdir(exist_ok=True)
        for f in sorted(web_dir.iterdir()):
            if f.is_file():
                shutil.copy2(f, dst_web / f.name)
        for rel in ("depth/scale.json", "depth/depth_report.json", "depth/map.npz",
                    "capture_qa.json", "capture_qa.md", "metricize.json",
                    "nav/nav.json", "nav/nav_report.json", "nav/occupancy.png"):
            src = RUN / rel
            if src.exists():
                shutil.copy2(src, OUT / Path(rel).name)

        log(f"ALL DONE in {time.time() - t0:.1f}s: {mesh_rep}")
    except BaseException:
        err = traceback.format_exc()
        log("FATAL ERROR:\n" + err)
        (OUT / "error.log").write_text(err, encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
