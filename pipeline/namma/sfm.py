"""Stage 2 -- sparse reconstruction (Structure from Motion) with pycolmap.

Input:  <capture>/frames/*.jpg + frames_meta.json (stage 1 output)
Output: <capture>/sfm/
    database.db          pycolmap feature/match database
    sparse/              binary model (cameras.bin/images.bin/points3D.bin)
    sparse_txt/          same model in text form (debuggability)
    sparse.ply           colored sparse point cloud (our own PLY writer)
    poses.json           per-frame camera pose (COLMAP world->camera, no ambiguity)
    transforms.json      nerfstudio-style camera-to-world (OpenGL convention)
    sfm_report.json      quality gates + timing

Design rules (mirroring the Syntheta SLAM robustness brief):
    - report, never lie: quality numbers are always written, gates only warn
    - no hidden fallbacks: whichever strategy ran is recorded in the report
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

import numpy as np

# NOTE: pycolmap is imported lazily inside the functions that need it -- the
# `namma.cli` entry point imports every module, and the GPU kernel runs
# depth/geometry/qa/package without pycolmap installed.

# pycolmap's pybind11 entry points expose no signatures; call strategies are
# tried in order and the winner is recorded so behavior is never implicit.
EXHAUSTIVE_MAX_IMAGES = 300  # above this, plain exhaustive matching gets slow


@dataclass
class SfMReport:
    stage: str = "sfm"
    status: str = "ok"
    backend: str = "pycolmap"
    pycolmap_version: str = ""
    matcher: str = ""
    extract_strategy: str = ""
    match_strategy: str = ""
    map_strategy: str = ""
    frames_in: int = 0
    models_found: int = 0
    frames_registered: int = 0
    registered_fraction: float = 0.0
    points3d: int = 0
    mean_reprojection_error_px: float = 0.0
    median_reprojection_error_px: float = 0.0
    timing_seconds: float = 0.0
    outputs: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_sfm(
    capture_dir: Path,
    *,
    matcher: str = "auto",
    exhaustive_max: int = EXHAUSTIVE_MAX_IMAGES,
) -> SfMReport:
    capture_dir = Path(capture_dir)
    import pycolmap
    frames_dir = capture_dir / "frames"
    if not frames_dir.is_dir():
        raise SystemExit(f"no frames dir: {frames_dir} (run `frames` first)")
    images = sorted(p.name for p in frames_dir.glob("*.jpg"))
    if len(images) < 2:
        raise SystemExit(f"need >=2 frames, found {len(images)}")

    out_dir = capture_dir / "sfm"
    out_dir.mkdir(parents=True, exist_ok=True)
    database = out_dir / "database.db"
    sparse_dir = out_dir / "sparse"
    sparse_dir.mkdir(exist_ok=True)

    report = SfMReport(frames_in=len(images), pycolmap_version=pycolmap.__version__)
    t0 = time.time()

    # -- feature extraction -------------------------------------------------
    report.extract_strategy = _extract_features(database, frames_dir)

    # -- matching -------------------------------------------------------------
    if matcher == "auto":
        matcher = "exhaustive" if len(images) <= exhaustive_max else "sequential"
    report.matcher = matcher
    report.match_strategy = _match(database, matcher)

    # -- incremental mapping --------------------------------------------------
    recs, report.map_strategy = _incremental_mapping(database, frames_dir, sparse_dir)
    recs = sorted(recs, key=lambda r: r.num_reg_images, reverse=True)
    report.models_found = len(recs)
    if not recs:
        report.status = "failed_no_model"
        report.timing_seconds = round(time.time() - t0, 1)
        _write_report(out_dir, report)
        return report

    rec = recs[0]
    if len(recs) > 1:
        sizes = [r.num_reg_images for r in recs]
        report.warnings.append(f"{len(recs)} disconnected models {sizes}; kept the largest")

    # canonical single model on disk
    model_dir = sparse_dir / "model"
    model_dir.mkdir(exist_ok=True)
    try:
        rec.write(str(model_dir))
    except TypeError:  # older/newer API name
        rec.write_binary(str(model_dir))
    rec.write_text(str(out_dir / "sparse_txt"))

    # -- stats ----------------------------------------------------------------
    report.frames_registered = rec.num_reg_images
    report.registered_fraction = round(rec.num_reg_images / len(images), 3)
    report.points3d = rec.num_points3D
    errors = [p.error for p in rec.points3D.values() if p.error is not None]
    if errors:
        report.mean_reprojection_error_px = round(float(np.mean(errors)), 3)
        report.median_reprojection_error_px = round(float(np.median(errors)), 3)
    if report.registered_fraction < 0.6:
        report.warnings.append(
            f"only {report.registered_fraction:.0%} of frames registered; "
            "capture likely needs more overlap or less motion blur")
    if report.median_reprojection_error_px > 1.0:
        report.warnings.append(
            f"median reprojection error {report.median_reprojection_error_px:.2f}px > 1px")

    # -- exports ---------------------------------------------------------------
    _write_ply(rec, out_dir / "sparse.ply")
    poses = _poses(rec, frames_dir)
    (out_dir / "poses.json").write_text(json.dumps(poses, indent=2), encoding="utf-8")
    transforms = _transforms(rec, frames_dir)
    (out_dir / "transforms.json").write_text(json.dumps(transforms, indent=2), encoding="utf-8")

    report.outputs = {
        "sparse": str(model_dir), "sparse_ply": str(out_dir / "sparse.ply"),
        "poses": str(out_dir / "poses.json"), "transforms": str(out_dir / "transforms.json"),
    }
    report.timing_seconds = round(time.time() - t0, 1)
    _write_report(out_dir, report)
    print(f"[sfm] registered {report.frames_registered}/{report.frames_in} "
          f"({report.registered_fraction:.0%}), {report.points3d} points, "
          f"med err {report.median_reprojection_error_px}px, {report.timing_seconds}s "
          f"[{report.matcher}]")
    for w in report.warnings:
        print(f"[sfm][warn] {w}")
    return report


# --------------------------------------------------------------------------
# pycolmap call strategies (API differs across 3.x/4.x; winner gets recorded)

def _extract_features(database: Path, image_dir: Path) -> str:
    import pycolmap
    try:
        pycolmap.extract_features(str(database), str(image_dir))
        return "positional"
    except TypeError:
        pass
    try:
        opts = pycolmap.FeatureExtractionOptions.create()
        pycolmap.extract_features(str(database), str(image_dir), extraction_options=opts)
        return "FeatureExtractionOptions.create"
    except (TypeError, AttributeError):
        pass
    pycolmap.extract_features(str(database), str(image_dir), camera_mode="AUTO")
    return "camera_mode_string"


def _match(database: Path, matcher: str) -> str:
    import pycolmap
    fn = pycolmap.match_exhaustive if matcher == "exhaustive" else pycolmap.match_sequential
    try:
        fn(str(database))
        return "positional"
    except TypeError:
        pass
    try:
        opts = pycolmap.FeatureMatchingOptions.create()
        fn(str(database), matching_options=opts)
        return "FeatureMatchingOptions.create"
    except (TypeError, AttributeError):
        pass
    fn(str(database), num_threads=-1)
    return "num_threads"


def _incremental_mapping(
    database: Path, image_dir: Path, sparse_dir: Path,
) -> tuple[list[pycolmap.Reconstruction], str]:
    import pycolmap
    try:
        recs = pycolmap.incremental_mapping(str(database), str(image_dir), str(sparse_dir))
        return _as_list(recs), "positional"
    except TypeError:
        pass
    opts = pycolmap.IncrementalPipelineOptions()
    recs = pycolmap.incremental_mapping(
        str(database), str(image_dir), str(sparse_dir), options=opts)
    return _as_list(recs), "IncrementalPipelineOptions"


def _as_list(recs: Any) -> list[pycolmap.Reconstruction]:
    if isinstance(recs, dict):
        return list(recs.values())
    return list(recs)


# --------------------------------------------------------------------------
# exports

def _write_ply(rec: pycolmap.Reconstruction, path: Path) -> None:
    """Binary little-endian PLY: xyz float32 + rgb uint8. No external deps."""
    pts = rec.points3D
    n = len(pts)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n"
    ).encode("ascii")
    xyz = np.empty((n, 3), np.float32)
    rgb = np.empty((n, 3), np.uint8)
    for i, p in enumerate(pts.values()):
        xyz[i] = p.xyz
        rgb[i] = p.color
    with open(path, "wb") as f:
        f.write(header)
        f.write(xyz.astype("<f4").tobytes())
        f.write(rgb.tobytes())


def _poses(rec: pycolmap.Reconstruction, frames_dir: Path) -> dict[str, Any]:
    """Raw COLMAP poses: world->camera (x right, y down, z forward)."""
    frames = []
    for image_id in rec.reg_image_ids():
        img = rec.image(image_id)
        cam = rec.camera(img.camera_id)
        w2c = _matrix(_get(img, "cam_from_world"))
        frames.append({
            "name": img.name,
            "width": cam.width, "height": cam.height,
            "fl_x": _focal(cam, 0), "fl_y": _focal(cam, 1),
            "cx": _principal(cam, 0), "cy": _principal(cam, 1),
            "w2c": w2c,
        })
    frames.sort(key=lambda f: f["name"])
    return {"convention": "world->camera (COLMAP), row-major 4x4", "frames": frames}


def _transforms(rec: pycolmap.Reconstruction, frames_dir: Path) -> dict[str, Any]:
    """nerfstudio-style transforms.json, camera->world, OpenGL convention."""
    first_id = list(rec.reg_image_ids())[0]
    cam0 = rec.camera(rec.image(first_id).camera_id)
    flip = np.diag([1.0, -1.0, -1.0, 1.0])
    frames = []
    for image_id in rec.reg_image_ids():
        img = rec.image(image_id)
        w2c = _matrix(_get(img, "cam_from_world"))
        c2w = np.linalg.inv(w2c) @ flip  # OpenGL: y up, z back
        frames.append({
            "file_path": f"frames/{img.name}",
            "transform_matrix": c2w.tolist(),
        })
    frames.sort(key=lambda f: f["file_path"])
    fl_x = _focal(cam0, 0)
    fl_y = _focal(cam0, 1)
    # assume one camera (phone capture); record it explicitly if not
    cams = {i.camera_id for i in rec.images.values()}
    out = {
        "camera_model": str(cam0.model),
        "w": cam0.width, "h": cam0.height,
        "fl_x": fl_x, "fl_y": fl_y,
        "cx": _principal(cam0, 0), "cy": _principal(cam0, 1),
        "ply_file_path": "sparse.ply",
        "frames": frames,
        "n_cameras": len(cams),
    }
    return out


def _get(obj: Any, name: str) -> Any:
    v = getattr(obj, name)
    return v() if callable(v) else v


def _matrix(rigid: Any) -> list[list[float]]:
    m = np.eye(4)
    m[:3, :3] = np.asarray(rigid.rotation.matrix())
    m[:3, 3] = np.asarray(rigid.translation)
    return m.tolist()


def _focal(cam: Any, axis: int) -> float:
    name = ("focal_length_x", "focal_length_y")[axis]
    if hasattr(cam, name):
        return float(getattr(cam, name))
    # fallback: params[0] is focal for most models (SIMPLE_PINHOLE..OPENCV)
    return float(cam.params[0])


def _principal(cam: Any, axis: int) -> float:
    names = ("principal_point_x", "principal_point_y")
    if hasattr(cam, names[axis]):
        return float(getattr(cam, names[axis]))
    return float(cam.params[1 + axis])


def _write_report(out_dir: Path, report: SfMReport) -> None:
    (out_dir / "sfm_report.json").write_text(json.dumps(report.to_dict(), indent=2),
                                             encoding="utf-8")
