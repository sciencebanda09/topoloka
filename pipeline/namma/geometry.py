"""Stage 3 -- geometry: floor plane, gravity alignment, walkable costmap.

Input:  <capture>/sfm/poses.json + a point cloud (sparse.ply, later a dense cloud)
Output: <capture>/nav/
    nav.json         the web app's navigation artifact:
                       occupancy grid (base64 PNG), floor outline polygon (meters),
                       trajectory, scale, grid origin -- everything a minimap
                       and an A* need
    occupancy.png    debug view of the grid
    nav_report.json  how the floor was found + scale + area stats (no hidden steps)

No gravity sensor is needed: in a walking capture the phone is held roughly
upright, so the mean camera-Y axis (image "down") is a good gravity prior.
The floor plane is then the largest RANSAC plane whose normal agrees with it
and that lies below the camera trajectory. If a sensor log exists later, the
same slot can take a real gravity vector instead.
"""

from __future__ import annotations

import base64
import json
import math
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

CELL_M = 0.05            # costmap cell size in meters
OBSTACLE_Z = (0.15, 1.60)  # point heights counted as obstacles above the floor
FLOOR_BAND = 0.15        # points within this height count as floor evidence
CHEST_HEIGHT_M = 1.35    # assumed phone height above the floor -> metric scale
TRAJ_FREE_RADIUS_M = 0.40
TRAJ_UNKNOWN_RADIUS_M = 0.85
MAX_POINT_DIST_M = 30.0
RANSAC_ITERS = 800
RANSAC_TOL_M = 0.06      # scene units (=m after scaling; before scaling it's relative)

FREE, OBSTACLE, UNKNOWN = 0, 1, 2


@dataclass
class NavReport:
    stage: str = "geometry"
    status: str = "ok"
    points_in: int = 0
    points_used: int = 0
    floor_inliers: int = 0
    down_axis_source: str = "camera-y-mean"
    scale_source: str = "chest-height"
    scale_m_per_unit: float = 0.0
    camera_height_units: float = 0.0
    grid_w: int = 0
    grid_h: int = 0
    free_cells: int = 0
    obstacle_cells: int = 0
    unknown_cells: int = 0
    walkable_area_m2: float = 0.0
    outline_points: int = 0
    timing_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# loading

def load_cloud(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load xyz (N,3) float32 + rgb (N,3) uint8 from our binary PLY or npz."""
    path = Path(path)
    if path.suffix == ".npz":
        d = np.load(path)
        return d["points"].astype(np.float32), d["colors"].astype(np.uint8)
    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise SystemExit(f"not a PLY: {path}")
        n, fmt = 0, ""
        props: list[str] = []
        while True:
            line = f.readline()
            if not line:
                raise SystemExit(f"PLY header truncated: {path}")
            parts = line.split()
            if parts[:1] == [b"format"]:
                fmt = parts[1].decode()
            elif parts[:1] == [b"element"] and parts[1:2] == [b"vertex"]:
                n = int(parts[2])
            elif parts[:1] == [b"property"]:
                props.append(parts[-1].decode())
            elif parts[:1] == [b"end_header"]:
                break
        if fmt != "binary_little_endian":
            raise SystemExit(f"unsupported PLY format: {fmt}")
        has_rgb = {"red", "green", "blue"}.issubset(props)
        dtype = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4")] +
                         ([("red", "u1"), ("green", "u1"), ("blue", "u1")] if has_rgb else []))
        buf = np.frombuffer(f.read(n * dtype.itemsize), dtype=dtype, count=n)
    xyz = np.stack([buf["x"], buf["y"], buf["z"]], axis=1)
    rgb = (np.stack([buf["red"], buf["green"], buf["blue"]], axis=1)
           if has_rgb else np.zeros((n, 3), np.uint8))
    return xyz.astype(np.float32), rgb


def load_camera_centers(poses_path: Path) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """camera centers + forward axes in world coords, from poses.json (w2c)."""
    poses = json.loads(poses_path.read_text(encoding="utf-8"))
    centers, forward = [], []
    for fr in poses["frames"]:
        w2c = np.asarray(fr["w2c"], np.float64)
        R, t = w2c[:3, :3], w2c[:3, 3]
        centers.append(-R.T @ t)
        forward.append(R.T @ np.array([0.0, 0.0, 1.0]))
    return np.asarray(centers), np.asarray(forward), poses["frames"]


# --------------------------------------------------------------------------
# floor + alignment

def ransac_plane(points: np.ndarray, seed: int = 17,
                 iters: int = RANSAC_ITERS, tol: float = RANSAC_TOL_M,
                 max_sample: int = 16000,
                 up_prior: np.ndarray | None = None,
                 min_alignment: float = 0.85):
    """Best (plane, inlier_mask) by inlier count using vectorized batch RANSAC.

    Searches on a stratified subsample of <= `max_sample` points in vectorized BLAS
    batches for O(iters * M) throughput without Python loop overhead. When `up_prior`
    is provided, only hypotheses matching `|n . up_prior| >= min_alignment` are scored,
    preventing dominant vertical walls from starving horizontal floor detection.
    """
    rng = np.random.default_rng(seed)
    n = len(points)
    if n < 3:
        return None, None
    pts = np.asarray(points, dtype=np.float32)
    pts_s = pts if n <= max_sample else pts[rng.choice(n, max_sample, replace=False)]
    ns = len(pts_s)
    up_u = None
    if up_prior is not None:
        up_norm = float(np.linalg.norm(up_prior))
        if up_norm > 1e-9:
            up_u = (np.asarray(up_prior, dtype=np.float32) / up_norm)

    # Collect up to `iters` non-degenerate (and optionally gravity-aligned) triangles vectorized.
    draw_batch = iters * (4 if up_u is not None else 1)
    cand_normals: list[np.ndarray] = []
    cand_ds: list[np.ndarray] = []
    collected = 0
    for _ in range(5):
        tri = rng.integers(0, ns, size=(draw_batch, 3))
        p0 = pts_s[tri[:, 0]]
        normals = np.cross(pts_s[tri[:, 1]] - p0, pts_s[tri[:, 2]] - p0)
        norms = np.linalg.norm(normals, axis=1)
        valid = norms > 1e-7
        if not valid.any():
            continue
        normals = normals[valid] / norms[valid, None]
        p0 = p0[valid]
        if up_u is not None:
            align_ok = np.abs(normals @ up_u) >= min_alignment
            if not align_ok.any():
                continue
            normals = normals[align_ok]
            p0 = p0[align_ok]
        ds = -np.einsum("ij,ij->i", normals, p0)
        cand_normals.append(normals)
        cand_ds.append(ds)
        collected += len(normals)
        if collected >= iters:
            break

    if not cand_normals:
        return None, None

    all_n = np.vstack(cand_normals)[:iters]
    all_d = np.concatenate(cand_ds)[:iters]
    pts_s_t = pts_s.T  # (3, ns)

    best_count, best_idx = 0, -1
    chunk = 64
    for start in range(0, len(all_n), chunk):
        cn = all_n[start:start + chunk]
        cd = all_d[start:start + chunk, None]
        dist = np.abs(cn @ pts_s_t + cd)
        counts = (dist < tol).sum(axis=1)
        local_i = int(np.argmax(counts))
        local_c = int(counts[local_i])
        if local_c > best_count:
            best_count = local_c
            best_idx = start + local_i

    if best_idx < 0:
        return None, None
    normal = all_n[best_idx].astype(np.float64)
    d = float(all_d[best_idx])

    dist = np.abs(pts @ normal.astype(np.float32) + np.float32(d))
    mask = dist < tol
    if not mask.any():
        return None, None
    # refit on inliers (one least-squares polish step, capped at 100k pts for SVD speed)
    inl = pts[mask].astype(np.float64)
    if len(inl) > 100_000:
        inl = inl[rng.choice(len(inl), 100_000, replace=False)]
    centroid = inl.mean(axis=0)
    _, _, vt = np.linalg.svd(inl - centroid, full_matrices=False)
    normal = vt[-1]
    d = -float(normal @ centroid)
    dist = np.abs(pts @ normal.astype(np.float32) + np.float32(d))
    mask = dist < tol
    return (normal, d), mask


def _rotation_to_up(normal: np.ndarray, up_hint: np.ndarray) -> np.ndarray:
    """Rotation R (3x3) mapping `normal` to (0,0,1); disambiguates with up_hint."""
    z = normal if (normal @ up_hint) > 0 else -normal
    z = z / np.linalg.norm(z)
    ref = np.array([1.0, 0.0, 0.0])
    if abs(z @ ref) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    x = np.cross(ref, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return np.stack([x, y, z], axis=1)  # columns = world axes of new frame


def estimate_down_from_poses(poses_frames: list[dict]) -> np.ndarray:
    """Mean camera-Y axis (image down) in world coords -- the gravity prior."""
    acc = np.zeros(3)
    for fr in poses_frames:
        w2c = np.asarray(fr["w2c"], np.float64)
        R = w2c[:3, :3]
        acc += R.T @ np.array([0.0, 1.0, 0.0])
    n = np.linalg.norm(acc)
    return acc / n if n > 1e-9 else np.array([0.0, 0.0, -1.0])


def align_scene(points: np.ndarray, cam_centers: np.ndarray, down: np.ndarray,
                fixed_scale: float | None = None,
                min_cam_z: float = 0.9, max_cam_z: float = 3.5):
    """Find the floor plane (below cameras, normal = ±down) and build the aligned frame.

    Returns (R, origin, scale_units_per_m, floor_report) such that
        p_aligned_m = ((p - origin) @ R) * scale
    has z=0 on the floor and meters as units.

    When fixed_scale is given (depth-derived metric scale, or 1.0 for an
    already-metric cloud+poses pair), the chest-height heuristic is skipped.
    """
    down = down / np.linalg.norm(down)
    cam_mean = cam_centers.mean(axis=0)

    # Candidate points. The sparse path has no metric scale, so a fixed band
    # in scene units can miss the floor entirely (e.g. a reconstruction where
    # 1 unit ~ 5 m puts the floor only 0.25 units below the cameras). Use every
    # point below the camera mean there. The metric path keeps the band, where
    # units are metres.
    rel = points - cam_mean
    h = rel @ down                      # + = below camera mean
    if len(points) == 0:
        cand = points
    elif fixed_scale is None:
        cand = points[h > 0]
    else:
        cand = points[(h >= min_cam_z - 0.5) & (h <= max_cam_z)]
    if len(cand) < 50:
        cand = points

    # a plane closer than this to the camera mean is degenerate (units unknown)
    extent = float(np.linalg.norm(cam_centers.max(axis=0) - cam_centers.min(axis=0)))
    min_floor_drop = 1e-3 * max(extent, 1e-9)
    tol = RANSAC_TOL_M if fixed_scale is not None else max(0.015, min(0.15, 0.008 * max(extent, 1.0)))

    best = None
    rng = np.random.default_rng(17)
    for _ in range(3):  # vectorized gravity-guided RANSAC restarts
        (normal, d), mask = ransac_plane(
            cand,
            seed=int(rng.integers(1 << 30)),
            tol=tol,
            up_prior=down,
            min_alignment=0.85,
        )
        if normal is None:
            continue
        alignment = float(abs(normal @ down))
        if alignment < 0.85:
            continue  # not a horizontal plane
        # orient normal to point "up" (against down)
        if normal @ down > 0:
            normal, d = -normal, -d
        # signed distance of the camera mean above the plane (positive, since
        # normal points up and the floor lies below the cameras)
        h_cam = float(normal @ cam_mean + d)
        if fixed_scale is None:
            if h_cam <= min_floor_drop:
                continue
        elif not (0.4 < h_cam < 4.0):
            continue
        count = int(mask.sum())
        if best is None or count > best[0]:
            best = (count, normal, d)

    if best is None:
        raise SystemExit("no floor plane found (no horizontal plane below the cameras)")

    count, normal, d = best
    # distance of the camera mean above the floor plane (in the input's units).
    # Was negated until 2026-10-19, which clamped every heuristic run to
    # scale = CHEST_HEIGHT_M / 0.2 = 6.75 regardless of camera height.
    cam_height_units = max(float(normal @ cam_mean + d), 0.2)
    scale = fixed_scale if fixed_scale is not None else CHEST_HEIGHT_M / cam_height_units

    # rotation mapping floor normal -> +Z (up)
    up = -down
    R = _rotation_to_up(normal, up)
    # origin: point on the floor plane nearest the cameras
    origin = cam_mean - normal * float(normal @ cam_mean + d)
    return R, origin, scale, {"floor_inliers": count, "cam_height_units": cam_height_units}


# --------------------------------------------------------------------------
# costmap

def build_costmap(points_m: np.ndarray, traj_m: np.ndarray, cell: float = CELL_M):
    """2.5D occupancy: obstacle = points in the obstacle height band, free = trajectory."""
    pts = points_m
    ok = (pts[:, 2] > -0.3) & (pts[:, 2] < 4.0)
    pts = pts[ok]
    # clip to a sane radius around the trajectory
    if len(traj_m):
        tmin, tmax = traj_m.min(axis=0) - 5.0, traj_m.max(axis=0) + 5.0
        inb = np.all((pts[:, :2] >= tmin[:2]) & (pts[:, :2] <= tmax[:2]), axis=1)
        pts = pts[inb]
    if len(traj_m) == 0 or len(pts) == 0:
        raise SystemExit("empty trajectory or cloud")

    lo = np.minimum(pts[:, :2].min(axis=0), traj_m[:, :2].min(axis=0)) - 1.0
    hi = np.maximum(pts[:, :2].max(axis=0), traj_m[:, :2].max(axis=0)) + 1.0
    w = int(math.ceil((hi[0] - lo[0]) / cell)) + 1
    h = int(math.ceil((hi[1] - lo[1]) / cell)) + 1

    grid = np.full((h, w), UNKNOWN, np.uint8)

    def cells_of(p: np.ndarray):
        ix = ((p[:, 0] - lo[0]) / cell).astype(np.int64)
        iy = ((p[:, 1] - lo[1]) / cell).astype(np.int64)
        ok = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
        return iy[ok], ix[ok]

    # floor evidence -> free
    floor_pts = pts[pts[:, 2] < FLOOR_BAND]
    if len(floor_pts):
        gy, gx = cells_of(floor_pts)
        grid[gy, gx] = FREE
        # Dense MVS samples still leave occasional one-cell holes between
        # adjacent floor pixels. Close only those tiny gaps; do not dilate the
        # observed floor footprint into unobserved space.
        floor_mask = np.zeros((h, w), np.uint8)
        floor_mask[gy, gx] = 255
        floor_mask = cv2.morphologyEx(
            floor_mask, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        )
        grid[floor_mask > 0] = FREE
    # obstacles
    band = pts[(pts[:, 2] >= OBSTACLE_Z[0]) & (pts[:, 2] <= OBSTACLE_Z[1])]
    if len(band):
        gy, gx = cells_of(band)
        grid[gy, gx] = OBSTACLE
    # trajectory -> free (last word: the person walked there).
    # Draw continuous capsules between consecutive trajectory poses (<= 4 m gap)
    # via OpenCV C++ rasterization so strided frames keep corridors connected.
    ty, tx = cells_of(traj_m)
    rad_clear = max(1, int(math.floor(TRAJ_FREE_RADIUS_M / cell + 1e-9)))
    rad_unk = max(rad_clear, int(math.floor(TRAJ_UNKNOWN_RADIUS_M / cell + 1e-9)))
    unk_mask = np.zeros((h, w), np.uint8)
    clr_mask = np.zeros((h, w), np.uint8)

    pts_px = []
    for p in traj_m:
        px = int(math.floor((float(p[0]) - float(lo[0])) / cell))
        py = int(math.floor((float(p[1]) - float(lo[1])) / cell))
        pts_px.append((px, py, float(p[0]), float(p[1])))

    for idx_t, (px, py, wx, wy) in enumerate(pts_px):
        cv2.circle(unk_mask, (px, py), rad_unk, 255, -1)
        cv2.circle(clr_mask, (px, py), rad_clear, 255, -1)
        if idx_t > 0:
            ppx, ppy, pwx, pwy = pts_px[idx_t - 1]
            if math.hypot(wx - pwx, wy - pwy) <= 4.0:
                cv2.line(unk_mask, (ppx, ppy), (px, py), 255, rad_unk * 2 + 1)
                cv2.line(clr_mask, (ppx, ppy), (px, py), 255, rad_clear * 2 + 1)

    grid[(unk_mask > 0) & (grid == UNKNOWN)] = FREE
    grid[clr_mask > 0] = FREE
    return grid, lo, cell


def footprint_outline(grid: np.ndarray, lo: np.ndarray, cell: float) -> list[list[float]]:
    """Floor outline (meters) of the scanned footprint = free+obstacle cells."""
    fp = ((grid != UNKNOWN).astype(np.uint8)) * 255
    k = max(3, int(round(0.45 / cell)) | 1)
    fp = cv2.morphologyEx(fp, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fp, 8)
    if n <= 1:
        return []
    big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = (labels == big).astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    cnt = max(contours, key=cv2.contourArea)
    eps = 2.0  # cells
    approx = cv2.approxPolyDP(cnt, eps, True).reshape(-1, 2)
    # grid (x=col, y=row) -> meters
    return [[round(float(lo[0] + (x + 0.5) * cell), 3),
             round(float(lo[1] + (y + 0.5) * cell), 3)] for x, y in approx]


# --------------------------------------------------------------------------
# orchestration

def run_geometry(capture_dir: Path, cloud_path: Path | None = None) -> NavReport:
    capture_dir = Path(capture_dir)
    out_dir = capture_dir / "nav"
    out_dir.mkdir(parents=True, exist_ok=True)

    sfm_dir = capture_dir / "sfm"
    cloud_path = Path(cloud_path) if cloud_path else sfm_dir / "sparse.ply"
    if not cloud_path.exists():
        raise SystemExit(f"missing cloud {cloud_path}")

    # scale contract (one code path, two honest sources):
    #  - metric .npz cloud (depth fusion): needs metric poses_m.json; scale = 1
    #  - scene-unit .ply cloud: use the depth-derived metric scale when it
    #    exists, else fall back to the chest-height heuristic
    poses_path = sfm_dir / "poses.json"
    fixed_scale: float | None = None
    scale_source = "chest-height"
    if cloud_path.suffix == ".npz":
        poses_m = sfm_dir / "poses_m.json"
        if not poses_m.exists():
            raise SystemExit("metric cloud requires sfm/poses_m.json (run `depth` first)")
        poses_path = poses_m
        fixed_scale = 1.0
        scale_source = "metric-input"
    else:
        scale_json = capture_dir / "depth" / "scale.json"
        if scale_json.exists():
            fixed_scale = float(json.loads(scale_json.read_text(encoding="utf-8"))
                                ["scale_m_per_unit"])
            scale_source = "depth-scale"
    if not poses_path.exists():
        raise SystemExit(f"missing {poses_path} (run `sfm` first)")

    t0 = time.time()
    report = NavReport()
    report.scale_source = scale_source
    xyz, rgb = load_cloud(cloud_path)
    report.points_in = len(xyz)
    centers, _fwd, poses_frames = load_camera_centers(poses_path)

    down = estimate_down_from_poses(poses_frames)
    try:
        from . import imu
        imu_summary = imu.load_imu(capture_dir)
        if imu_summary and imu_summary.gravity_down_dir:
            imu_cam_down = np.asarray(imu_summary.gravity_down_dir, dtype=np.float64)
            # Align sign against pose camera-Y prior and map into scene world via mean R^T.
            acc = np.zeros(3, dtype=np.float64)
            for fr in poses_frames:
                R_w2c = np.asarray(fr["w2c"], dtype=np.float64)[:3, :3]
                acc += R_w2c.T @ imu_cam_down
            if np.linalg.norm(acc) > 1e-6:
                cand_down = acc / np.linalg.norm(acc)
                if float(cand_down @ down) < 0:
                    cand_down = -cand_down
                if float(cand_down @ down) > 0.7:
                    down = cand_down
                    report.down_axis_source = f"imu-{imu_summary.source}"
    except Exception:
        pass
    R, origin, scale, floor_info = align_scene(xyz, centers, down, fixed_scale=fixed_scale)
    report.floor_inliers = floor_info["floor_inliers"]
    report.camera_height_units = round(floor_info["cam_height_units"], 3)
    report.scale_m_per_unit = round(scale, 4)

    pts_m = (((xyz - origin) @ R) * scale).astype(np.float64)
    traj_m = (((centers - origin) @ R) * scale).astype(np.float64)
    report.points_used = len(pts_m)

    # floats: height of cameras should now be ~CHEST_HEIGHT_M
    cam_h = float(np.median(traj_m[:, 2]))
    if not (0.8 < cam_h < 2.2):
        report.warnings.append(f"camera median height after scaling is {cam_h:.2f} m (expected ~1.35)")

    grid, lo, cell = build_costmap(pts_m, traj_m)
    report.grid_w, report.grid_h = grid.shape[1], grid.shape[0]
    report.free_cells = int((grid == FREE).sum())
    report.obstacle_cells = int((grid == OBSTACLE).sum())
    report.unknown_cells = int((grid == UNKNOWN).sum())
    report.walkable_area_m2 = round(report.free_cells * cell * cell, 2)

    outline = footprint_outline(grid, lo, cell)
    report.outline_points = len(outline)
    if report.outline_points < 3:
        report.warnings.append("floor outline has < 3 points; footprint too small or too sparse")

    # -- artifacts --------------------------------------------------------
    png_ok, png = cv2.imencode(".png", grid, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    if not png_ok:
        raise SystemExit("PNG encode failed")
    (out_dir / "occupancy.png").write_bytes(png.tobytes())
    nav = {
        "version": 1,
        "units": "meters",
        "cell_m": cell,
        "origin": [round(float(lo[0]), 3), round(float(lo[1]), 3)],
        "grid": {"w": grid.shape[1], "h": grid.shape[0],
                 "encoding": "uint8-png-base64",
                 "legend": {"0": "free", "1": "obstacle", "2": "unknown"},
                 "data_b64": base64.b64encode(png.tobytes()).decode("ascii")},
        "outline": outline,
        "trajectory": [[round(float(x), 3) for x in p] for p in traj_m],
        "scale_m_per_unit": report.scale_m_per_unit,
        "scale_source": report.scale_source,
        "cam_height_units": report.camera_height_units,
        "down_axis_source": report.down_axis_source,
        # The alignment from the raw reconstruction frame (scene units) into
        # this metric frame -- needed by the web app to place the splat:
        #     p_nav_m = scale * R^T @ (p_scene_units - origin)
        "align": {
            "R_row_major": [[round(float(v), 7) for v in row] for row in R],
            "origin": [round(float(v), 7) for v in origin],
            "scale_m_per_unit": report.scale_m_per_unit,
            "formula": "p_nav_m = scale * R^T @ (p_scene_units - origin)",
        },
    }
    # Capture lens: the viewer must render with this FOV, not a generic 72°.
    # Otherwise anisotropic gaussians stretch and the top of the frame shows
    # unobserved ceiling that the camera never captured.
    tf_path = capture_dir / "transforms.json"
    if tf_path.exists():
        tf = json.loads(tf_path.read_text(encoding="utf-8"))
        if tf.get("fl_x") and tf.get("w") and tf.get("h"):
            nav["camera"] = {
                "camera_model": tf.get("camera_model", "PINHOLE"),
                "w": int(tf["w"]), "h": int(tf["h"]),
                "fl_x": round(float(tf["fl_x"]), 6),
                "fl_y": round(float(tf.get("fl_y", tf["fl_x"])), 6),
                "cx": round(float(tf.get("cx", tf["w"] / 2)), 3),
                "cy": round(float(tf.get("cy", tf["h"] / 2)), 3),
            }
    (out_dir / "nav.json").write_text(json.dumps(nav), encoding="utf-8")

    # debug png: colorize
    dbg = np.zeros((*grid.shape, 3), np.uint8)
    dbg[grid == FREE] = (60, 60, 60)
    dbg[grid == OBSTACLE] = (0, 0, 220)
    dbg[grid == UNKNOWN] = (180, 180, 180)
    ty = ((traj_m[:, 1] - lo[1]) / cell).astype(int)
    tx = ((traj_m[:, 0] - lo[0]) / cell).astype(int)
    ok = (tx >= 0) & (tx < grid.shape[1]) & (ty >= 0) & (ty < grid.shape[0])
    dbg[ty[ok], tx[ok]] = (0, 255, 0)
    cv2.imwrite(str(out_dir / "occupancy_debug.png"), dbg)

    report.timing_seconds = round(time.time() - t0, 1)
    report.outputs = {"nav": str(out_dir / "nav.json"),
                      "occupancy": str(out_dir / "occupancy.png")}
    (out_dir / "nav_report.json").write_text(json.dumps(report.to_dict(), indent=2),
                                             encoding="utf-8")
    print(f"[geometry] floor inliers {report.floor_inliers}, scale {report.scale_m_per_unit} m/unit, "
          f"grid {report.grid_w}x{report.grid_h} ({report.walkable_area_m2} m2 walkable), "
          f"outline {report.outline_points} pts, {report.timing_seconds}s")
    for w in report.warnings:
        print(f"[geometry][warn] {w}")
    return report
