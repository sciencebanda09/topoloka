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
TRAJ_FREE_RADIUS_M = 0.15
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
                 iters: int = RANSAC_ITERS, tol: float = RANSAC_TOL_M):
    """Best (plane, inlier_mask) by inlier count. Plane = unit normal + offset."""
    rng = np.random.default_rng(seed)
    n = len(points)
    best_count, best = 0, None
    for _ in range(iters):
        idx = rng.choice(n, 3, replace=False)
        p0, p1, p2 = points[idx]
        normal = np.cross(p1 - p0, p2 - p0)
        norm = np.linalg.norm(normal)
        if norm < 1e-9:
            continue
        normal = normal / norm
        d = -float(normal @ p0)
        dist = np.abs(points @ normal + d)
        count = int((dist < tol).sum())
        if count > best_count:
            best_count, best = count, (normal.copy(), d)
    if best is None:
        return None, None
    normal, d = best
    dist = np.abs(points @ normal + d)
    mask = dist < tol
    # refit on inliers (one least-squares polish step)
    inl = points[mask]
    centroid = inl.mean(axis=0)
    _, _, vt = np.linalg.svd(inl - centroid, full_matrices=False)
    normal = vt[-1]
    d = -float(normal @ centroid)
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
                min_cam_z: float = 0.9, max_cam_z: float = 3.5):
    """Find the floor plane (below cameras, normal = ±down) and build the aligned frame.

    Returns (R, origin, scale_units_per_m, floor_report) such that
        p_aligned_m = ((p - origin) @ R) * scale
    has z=0 on the floor and meters as units.
    """
    down = down / np.linalg.norm(down)
    cam_mean = cam_centers.mean(axis=0)

    # candidate planes: big planes roughly perpendicular to down
    # keep points at plausible floor heights below the cameras to focus RANSAC
    rel = points - cam_mean
    h = rel @ down                      # + = below camera mean
    cand = points[(h > min_cam_z - 0.5) & (h < max_cam_z)] if len(points) else points
    if len(cand) < 50:
        cand = points

    best = None
    rng = np.random.default_rng(17)
    for _ in range(6):  # several RANSAC restarts, keep the best floor-consistent plane
        (normal, d), mask = ransac_plane(cand, seed=int(rng.integers(1 << 30)))
        if normal is None:
            continue
        alignment = float(abs(normal @ down))
        if alignment < 0.85:
            continue  # not a horizontal plane
        # orient normal to point "up" (against down)
        if normal @ down > 0:
            normal, d = -normal, -d
        height_cam_mean = -(normal @ cam_mean + d)   # floor below cameras => negative
        if not (-4.0 < height_cam_mean < -0.4):
            continue
        count = int(mask.sum())
        if best is None or count > best[0]:
            best = (count, normal, d)

    if best is None:
        raise SystemExit("no floor plane found (no horizontal plane below the cameras)")

    count, normal, d = best
    # distance of camera mean from the floor plane (in scene units)
    cam_height_units = float(-(normal @ cam_mean + d))
    cam_height_units = max(cam_height_units, 0.2)
    scale = CHEST_HEIGHT_M / cam_height_units

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
    # obstacles
    band = pts[(pts[:, 2] >= OBSTACLE_Z[0]) & (pts[:, 2] <= OBSTACLE_Z[1])]
    if len(band):
        gy, gx = cells_of(band)
        grid[gy, gx] = OBSTACLE
    # trajectory -> free (last word: the person walked there)
    ty, tx = cells_of(traj_m)
    rad = max(1, int(round(TRAJ_FREE_RADIUS_M / cell)))
    for y, x in zip(ty, tx):
        grid[max(0, y - rad):y + rad + 1, max(0, x - rad):x + rad + 1] = FREE
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
    poses_path = sfm_dir / "poses.json"
    if not poses_path.exists():
        raise SystemExit(f"missing {poses_path} (run `sfm` first)")
    cloud_path = Path(cloud_path) if cloud_path else sfm_dir / "sparse.ply"
    if not cloud_path.exists():
        raise SystemExit(f"missing cloud {cloud_path}")

    t0 = time.time()
    report = NavReport()
    xyz, rgb = load_cloud(cloud_path)
    report.points_in = len(xyz)
    centers, _fwd, poses_frames = load_camera_centers(poses_path)

    down = estimate_down_from_poses(poses_frames)
    R, origin, scale, floor_info = align_scene(xyz, centers, down)
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
        "cam_height_units": report.camera_height_units,
        "down_axis_source": report.down_axis_source,
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
