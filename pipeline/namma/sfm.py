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
import os
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
# COLMAP SIFT crashed on Windows above ~4 threads in the dmx reference work;
# 0 = auto (COLMAP default -1). Kaggle Linux runs fine on auto.
THREADS = int(os.environ.get("NM_THREADS", "0"))


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
    features: str = "sift",
    seq_window: int = 18,
    loop_topk: int = 12,
    max_kpts: int = 2048,
) -> SfMReport:
    if features == "disk_lightglue":
        return _run_sfm_disk_lightglue(
            capture_dir,
            seq_window=seq_window,
            loop_topk=loop_topk,
            max_kpts=max_kpts,
        )
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
    # pycolmap 4.x: num_reg_images is a method; 3.x: a property -- _get handles both
    recs = sorted(recs, key=lambda r: _get(r, "num_reg_images"), reverse=True)
    report.models_found = len(recs)
    if not recs:
        report.status = "failed_no_model"
        report.timing_seconds = round(time.time() - t0, 1)
        _write_report(out_dir, report)
        return report

    rec = recs[0]
    if len(recs) > 1:
        sizes = [int(_get(r, "num_reg_images")) for r in recs]
        report.warnings.append(f"{len(recs)} disconnected models {sizes}; kept the largest")

    # canonical single model on disk
    model_dir = sparse_dir / "model"
    model_dir.mkdir(exist_ok=True)
    try:
        rec.write(str(model_dir))
    except TypeError:  # older/newer API name
        rec.write_binary(str(model_dir))
    txt_dir = out_dir / "sparse_txt"
    txt_dir.mkdir(exist_ok=True)  # 4.2.1 requires the target dir to exist
    rec.write_text(str(txt_dir))

    # -- stats ----------------------------------------------------------------
    report.frames_registered = int(_get(rec, "num_reg_images"))
    report.registered_fraction = round(report.frames_registered / len(images), 3)
    report.points3d = int(_get(rec, "num_points3D"))
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
    """One shared SIMPLE_RADIAL camera for the whole capture (monocular video).

    pycolmap 4.x defaults to per-image cameras; the intrinsics then vary frame
    to frame (we measured ±13% focal spread on a real capture). A phone video
    has ONE camera -- sharing it makes the intrinsics a global, well-constrained
    estimate and gives the .splat stage honest focal numbers.
    """
    import pycolmap
    kwargs: dict[str, Any] = {}
    if THREADS > 0:
        opts = pycolmap.FeatureExtractionOptions()
        opts.num_threads = THREADS
        kwargs["extraction_options"] = opts
    try:
        pycolmap.extract_features(str(database), str(image_dir),
                                  camera_mode=pycolmap.CameraMode.SINGLE, **kwargs)
        return "camera_mode=SINGLE" + (f" threads={THREADS}" if THREADS > 0 else "")
    except (TypeError, AttributeError, ValueError):
        pass
    try:  # plain SINGLE, no options object
        pycolmap.extract_features(str(database), str(image_dir),
                                  camera_mode=pycolmap.CameraMode.SINGLE)
        return "camera_mode=SINGLE"
    except (TypeError, AttributeError, ValueError):
        pass
    try:  # pycolmap 3.x accepted a string
        pycolmap.extract_features(str(database), str(image_dir), camera_mode="SINGLE")
        return "camera_mode='SINGLE'"
    except (TypeError, AttributeError, ValueError):
        pass
    try:  # positional; may fall back to per-image cameras
        pycolmap.extract_features(str(database), str(image_dir))
        return "positional (per-image cameras)"
    except TypeError:
        pass
    try:
        opts = pycolmap.FeatureExtractionOptions.create()
        pycolmap.extract_features(str(database), str(image_dir), extraction_options=opts)
        return "FeatureExtractionOptions.create (per-image cameras)"
    except (TypeError, AttributeError):
        pass
    pycolmap.extract_features(str(database), str(image_dir), camera_mode="AUTO")
    return "camera_mode_string AUTO (per-image cameras)"


def _match(database: Path, matcher: str) -> str:
    import pycolmap
    fn = pycolmap.match_exhaustive if matcher == "exhaustive" else pycolmap.match_sequential
    kwargs: dict[str, Any] = {}
    if THREADS > 0:
        try:
            mopts = pycolmap.FeatureMatchingOptions()
            mopts.num_threads = THREADS
            kwargs["matching_options"] = mopts
        except Exception:
            kwargs = {}
    try:
        fn(str(database), **kwargs)
        return "positional" + (f" threads={THREADS}" if kwargs else "")
    except (TypeError, ValueError):
        pass
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
    """Binary little-endian PLY, standard PER-VERTEX layout: x,y,z,r,g,b.

    Payload layout matters: the PLY spec stores each vertex's properties
    consecutively (interleaved), and every reader we use --
    geometry.load_cloud, nerfstudio's trimesh/open3d point loading, three.js
    PLYLoader -- assumes that. An xyz-block-then-rgb-block variant silently
    garbled the nav grid on the 2026-10-18 run.
    """
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
        xyz[i] = np.asarray(_get(p, "xyz"), dtype=np.float32)
        rgb[i] = np.asarray(_get(p, "color"), dtype=np.uint8)
    vertex = np.empty(n, dtype=np.dtype(
        [("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
         ("red", "u1"), ("green", "u1"), ("blue", "u1")]))
    vertex["x"], vertex["y"], vertex["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    vertex["red"], vertex["green"], vertex["blue"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    with open(path, "wb") as f:
        f.write(header)
        f.write(vertex.tobytes())


def _poses(rec: pycolmap.Reconstruction, frames_dir: Path) -> dict[str, Any]:
    """Raw COLMAP poses: world->camera (x right, y down, z forward)."""
    frames = []
    for image_id in _get(rec, "reg_image_ids"):
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
    image_ids = list(_get(rec, "reg_image_ids"))
    first_id = image_ids[0]
    cam0 = rec.camera(rec.image(first_id).camera_id)
    flip = np.diag([1.0, -1.0, -1.0, 1.0])
    frames = []
    for image_id in image_ids:
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
        "camera_model": _model_name(cam0),
        "w": cam0.width, "h": cam0.height,
        "fl_x": fl_x, "fl_y": fl_y,
        "cx": _principal(cam0, 0), "cy": _principal(cam0, 1),
        "ply_file_path": "sparse.ply",
        "frames": frames,
        "n_cameras": len(cams),
    }
    return out


def _model_name(cam: Any) -> str:
    """'SIMPLE_RADIAL' -- 4.x stores an enum whose str() is 'CameraModelId.X'."""
    model = cam.model
    name = getattr(model, "name", None)
    if isinstance(name, str):
        return name
    return str(model).rsplit(".", 1)[-1]


def _get(obj: Any, name: str) -> Any:
    v = getattr(obj, name)
    return v() if callable(v) else v


def _matrix(rigid: Any) -> list[list[float]]:
    m = np.eye(4)
    m[:3, :3] = np.asarray(_get(_get(rigid, "rotation"), "matrix"), dtype=np.float64)
    m[:3, 3] = np.asarray(_get(rigid, "translation"), dtype=np.float64)
    return m.tolist()


def _focal(cam: Any, axis: int) -> float:
    name = ("focal_length_x", "focal_length_y")[axis]
    if hasattr(cam, name):
        return float(_get(cam, name))
    # fallback: params[0] is focal for most models (SIMPLE_PINHOLE..OPENCV)
    return float(cam.params[0])


def _principal(cam: Any, axis: int) -> float:
    names = ("principal_point_x", "principal_point_y")
    if hasattr(cam, names[axis]):
        return float(_get(cam, names[axis]))
    return float(cam.params[1 + axis])


def _pair_id(id1: int, id2: int) -> int:
    if id1 > id2:
        id1, id2 = id2, id1
    return id1 * 2147483647 + id2


def _run_sfm_disk_lightglue(
    capture_dir: Path,
    *,
    seq_window: int = 18,
    loop_topk: int = 12,
    max_kpts: int = 2048,
    min_matches: int = 20,
) -> SfMReport:
    """Learned multi-room SfM using Apache-2.0 Kornia DISK + LightGlue + pycolmap BA."""
    import shutil
    import sqlite3
    import cv2
    import kornia.feature as KF
    import pycolmap
    import torch

    capture_dir = Path(capture_dir)
    frames_dir = capture_dir / "frames"
    if not frames_dir.is_dir():
        raise SystemExit(f"no frames dir: {frames_dir} (run `frames` first)")
    images = sorted(p.name for p in frames_dir.glob("*.jpg"))
    n_imgs = len(images)
    if n_imgs < 2:
        raise SystemExit(f"need >=2 frames, found {n_imgs}")

    out_dir = capture_dir / "sfm"
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "database.db"
    if db_path.exists():
        db_path.unlink()
    sparse_dir = out_dir / "sparse"
    if sparse_dir.exists():
        shutil.rmtree(sparse_dir)
    sparse_dir.mkdir(parents=True, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    t0 = time.time()
    report = SfMReport(
        frames_in=n_imgs,
        backend="disk+lightglue+pycolmap",
        pycolmap_version=pycolmap.__version__,
        matcher=f"disk_lightglue_seq{seq_window}_loop{loop_topk}",
        extract_strategy=f"kornia.DISK(depth, max_kpts={max_kpts}) + CameraMode.SINGLE",
    )

    # Initialize valid pycolmap schema (rigs/frames/cameras/images) under CameraMode.SINGLE
    try:
        ext_opts = pycolmap.FeatureExtractionOptions()
        ext_opts.sift.max_num_features = 64
        pycolmap.extract_features(
            str(db_path), str(frames_dir),
            camera_mode=pycolmap.CameraMode.SINGLE,
            extraction_options=ext_opts,
        )
    except Exception:
        pycolmap.extract_features(
            str(db_path), str(frames_dir),
            camera_mode=pycolmap.CameraMode.SINGLE,
        )

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    name_to_id = {name: int(iid) for iid, name in cur.execute("SELECT image_id, name FROM images").fetchall()}

    disk = KF.DISK.from_pretrained("depth").to(device).eval()
    kpts_cpu: list[np.ndarray] = []
    kpts_gpu: list[torch.Tensor] = []
    descs_gpu: list[torch.Tensor] = []
    global_vecs: list[np.ndarray] = []
    img_sizes: list[tuple[int, int]] = []

    for name in images:
        bgr = cv2.imread(str(frames_dir / name))
        h, w = bgr.shape[:2]
        img_sizes.append((w, h))
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        ten = torch.from_numpy(rgb).permute(2, 0, 1).float().div_(255.0).unsqueeze(0).to(device)
        with torch.inference_mode():
            feat = disk(ten, n=max_kpts, pad_if_not_divisible=True)[0]
            kp = feat.keypoints.float()
            desc = feat.descriptors.float()
        kpts_gpu.append(kp)
        descs_gpu.append(desc)
        kpts_cpu.append(kp.cpu().numpy().astype(np.float32))
        gv = desc.mean(dim=0).cpu().numpy()
        global_vecs.append((gv / max(float(np.linalg.norm(gv)), 1e-8)).astype(np.float32))

    cur.execute("DELETE FROM keypoints")
    cur.execute("DELETE FROM descriptors")
    cur.execute("DELETE FROM matches")
    cur.execute("DELETE FROM two_view_geometries")
    for name, kp_np in zip(images, kpts_cpu):
        iid = name_to_id[name]
        n = len(kp_np)
        kp6 = np.zeros((n, 6), dtype=np.float32)
        if n > 0:
            kp6[:, 0:2] = kp_np
            kp6[:, 2] = 1.0
            kp6[:, 5] = 1.0
        cur.execute("INSERT INTO keypoints (image_id, rows, cols, data) VALUES (?, ?, ?, ?)",
                    (iid, n, 6, kp6.tobytes()))
    conn.commit()

    pair_set: set[tuple[int, int]] = set()
    for i in range(n_imgs):
        for j in range(i + 1, min(n_imgs, i + 1 + seq_window)):
            pair_set.add((i, j))
    if n_imgs > seq_window + 1 and loop_topk > 0:
        G = np.stack(global_vecs, axis=0)
        sim = G @ G.T
        for i in range(n_imgs):
            row = sim[i].copy()
            row[max(0, i - seq_window):min(n_imgs, i + seq_window + 1)] = -1.0
            k = min(loop_topk, n_imgs - 1)
            for j in np.argpartition(row, -k)[-k:]:
                if row[j] > 0.55:
                    a, b = (i, int(j)) if i < int(j) else (int(j), i)
                    pair_set.add((a, b))

    pairs = sorted(pair_set)
    lg = KF.LightGlue(features="disk").to(device).eval()
    verified_pairs: list[tuple[str, str]] = []
    for i, j in pairs:
        wi, hi = img_sizes[i]
        wj, hj = img_sizes[j]
        inp = {
            "image0": {
                "keypoints": kpts_gpu[i].unsqueeze(0),
                "descriptors": descs_gpu[i].unsqueeze(0),
                "image_size": torch.tensor([[wi, hi]], device=device, dtype=torch.float32),
            },
            "image1": {
                "keypoints": kpts_gpu[j].unsqueeze(0),
                "descriptors": descs_gpu[j].unsqueeze(0),
                "image_size": torch.tensor([[wj, hj]], device=device, dtype=torch.float32),
            },
        }
        with torch.inference_mode():
            m = lg(inp)["matches"][0]
        if m.shape[0] < min_matches:
            continue
        m_np = m.cpu().numpy().astype(np.uint32)
        id_i, id_j = name_to_id[images[i]], name_to_id[images[j]]
        if id_i > id_j:
            m_np = m_np[:, [1, 0]]
            id_i, id_j = id_j, id_i
        cur.execute("INSERT OR REPLACE INTO matches (pair_id, rows, cols, data) VALUES (?, ?, ?, ?)",
                    (_pair_id(id_i, id_j), int(len(m_np)), 2, m_np.tobytes()))
        verified_pairs.append((images[i], images[j]))
    conn.commit()
    conn.close()

    report.match_strategy = f"kornia.LightGlue(disk) -> {len(verified_pairs)}/{len(pairs)} pairs"
    pairs_txt = out_dir / "pairs.txt"
    pairs_txt.write_text("\n".join(f"{a} {b}" for a, b in verified_pairs) + "\n", encoding="utf-8")
    try:
        vopts = pycolmap.TwoViewGeometryOptions()
        vopts.min_num_inliers = 15
        vopts.ransac.max_error = 4.0
        pycolmap.verify_matches(str(db_path), str(pairs_txt), options=vopts)
    except Exception:
        pycolmap.verify_matches(str(db_path), str(pairs_txt))

    mopts = pycolmap.IncrementalPipelineOptions()
    for attr, val in (("min_num_matches", 12), ("multiple_models", True)):
        if hasattr(mopts, attr):
            setattr(mopts, attr, val)
    if hasattr(mopts, "mapper"):
        for attr, val in (("init_min_num_inliers", 50), ("abs_pose_min_num_inliers", 15), ("filter_max_reproj_error", 4.0)):
            if hasattr(mopts.mapper, attr):
                setattr(mopts.mapper, attr, val)
    recs = sorted(_as_list(pycolmap.incremental_mapping(str(db_path), str(frames_dir), str(sparse_dir), options=mopts)),
                  key=lambda r: _get(r, "num_reg_images"), reverse=True)
    report.map_strategy = "pycolmap.incremental_mapping"
    report.models_found = len(recs)
    if not recs:
        report.status = "failed_no_model"
        report.timing_seconds = round(time.time() - t0, 1)
        _write_report(out_dir, report)
        return report

    rec = recs[0]
    if len(recs) > 1:
        sizes = [int(_get(r, "num_reg_images")) for r in recs]
        report.warnings.append(f"{len(recs)} disconnected models {sizes}; kept the largest")
    model_dir = sparse_dir / "model"
    model_dir.mkdir(exist_ok=True)
    rec.write(str(model_dir))
    txt_dir = out_dir / "sparse_txt"
    txt_dir.mkdir(exist_ok=True)
    rec.write_text(str(txt_dir))

    report.frames_registered = int(_get(rec, "num_reg_images"))
    report.registered_fraction = round(report.frames_registered / n_imgs, 3)
    report.points3d = int(_get(rec, "num_points3D"))
    errors = [p.error for p in rec.points3D.values() if p.error is not None]
    if errors:
        report.mean_reprojection_error_px = round(float(np.mean(errors)), 3)
        report.median_reprojection_error_px = round(float(np.median(errors)), 3)
    _write_ply(rec, out_dir / "sparse.ply")
    (out_dir / "poses.json").write_text(json.dumps(_poses(rec, frames_dir), indent=2), encoding="utf-8")
    (out_dir / "transforms.json").write_text(json.dumps(_transforms(rec, frames_dir), indent=2), encoding="utf-8")
    report.outputs = {
        "sparse": str(model_dir), "sparse_ply": str(out_dir / "sparse.ply"),
        "poses": str(out_dir / "poses.json"), "transforms": str(out_dir / "transforms.json"),
    }
    report.timing_seconds = round(time.time() - t0, 1)
    _write_report(out_dir, report)
    return report


def _write_report(out_dir: Path, report: SfMReport) -> None:
    (out_dir / "sfm_report.json").write_text(json.dumps(report.to_dict(), indent=2),
                                             encoding="utf-8")
