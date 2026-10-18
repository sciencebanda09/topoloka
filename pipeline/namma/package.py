"""Stage 7 -- package: assemble the artifact bundle the web app consumes.

Input:  <capture>/nav/nav.json, sfm/sparse.ply or depth/map.npz,
        splat/splat.splat (optional, from the GPU kernel)
Output: <capture>/web/
    nav.json        copy of the nav artifact (grid, outline, trajectory, align)
    cloud.ply       point cloud in the NAV frame (x/y ground, z up, meters)
    splat.splat     gaussian splat (kept in its training frame; the web app
                    places it with nav.json's align transform)
    occupancy.png   debug grid
    meta.json       capture summary: counts, scale source, QA overall, timings

This is the only stage that produces web-consumable files -- one contract,
one place to look when the viewer shows something unexpected.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np

from .geometry import load_cloud


def _apply_align(xyz: np.ndarray, align: dict) -> np.ndarray:
    """p_nav_m = scale * R^T @ (p_world_units - origin) -- documented in nav.json."""
    R = np.asarray(align["R_row_major"], np.float64)
    origin = np.asarray(align["origin"], np.float64)
    scale = float(align["scale_m_per_unit"])
    return ((xyz.astype(np.float64) - origin) @ R * scale).astype(np.float32)


def _write_ply(path: Path, xyz: np.ndarray, rgb: np.ndarray) -> None:
    """Binary little-endian PLY, PER-VERTEX layout (see sfm._write_ply)."""
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(xyz)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n"
    ).encode("ascii")
    xyz = xyz.astype("<f4")
    rgb = rgb.astype(np.uint8)
    vertex = np.empty(len(xyz), dtype=np.dtype(
        [("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
         ("red", "u1"), ("green", "u1"), ("blue", "u1")]))
    vertex["x"], vertex["y"], vertex["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    vertex["red"], vertex["green"], vertex["blue"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    with open(path, "wb") as f:
        f.write(header)
        f.write(vertex.tobytes())


def run_package(capture_dir: Path) -> dict:
    capture_dir = Path(capture_dir)
    out = capture_dir / "web"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    nav_path = capture_dir / "nav" / "nav.json"
    if not nav_path.exists():
        raise SystemExit(f"missing {nav_path} (run `geometry` first)")
    nav = json.loads(nav_path.read_text(encoding="utf-8"))
    shutil.copy2(nav_path, out / "nav.json")

    occ = capture_dir / "nav" / "occupancy.png"
    if occ.exists():
        shutil.copy2(occ, out / "occupancy.png")

    # prefer the dense metric cloud, fall back to the sparse one
    dense = capture_dir / "depth" / "map.npz"
    sparse = capture_dir / "sfm" / "sparse.ply"
    if dense.exists():
        xyz, rgb = load_cloud(dense)
        cloud_source = "depth/map.npz"
    elif sparse.exists():
        xyz, rgb = load_cloud(sparse)
        cloud_source = "sfm/sparse.ply"
    else:
        raise SystemExit("no point cloud to package (ran sfm or depth?)")

    nav_xyz = _apply_align(xyz, nav["align"])
    _write_ply(out / "cloud.ply", nav_xyz, rgb)

    splat_src = capture_dir / "splat" / "splat.splat"
    splat = {"present": False}
    if splat_src.exists():
        shutil.copy2(splat_src, out / "splat.splat")
        rep = capture_dir / "splat" / "splat_convert_report.json"
        splat = {"present": True, "bytes": splat_src.stat().st_size}
        if rep.exists():
            r = json.loads(rep.read_text(encoding="utf-8"))
            splat["gaussians"] = r.get("gaussians_out")

    qa = None
    qa_path = capture_dir / "capture_qa.json"
    if qa_path.exists():
        qa = json.loads(qa_path.read_text(encoding="utf-8")).get("overall")

    meta = {
        "capture": capture_dir.name,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cloud_source": cloud_source,
        "cloud_points": int(len(nav_xyz)),
        "splat": splat,
        "scale_source": nav.get("scale_source"),
        "walkable_area_m2": None,
        "qa_overall": qa,
        "packaging_seconds": round(time.time() - t0, 1),
    }
    if occ.exists():
        meta["walkable_area_m2"] = json.loads(
            (capture_dir / "nav" / "nav_report.json").read_text(encoding="utf-8")
        ).get("walkable_area_m2")
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"[package] web bundle in {out}: cloud {len(nav_xyz)} pts "
          f"({cloud_source}), splat {'yes' if splat['present'] else 'no'}")
    return meta
