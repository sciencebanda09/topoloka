"""Kaggle GPU kernel: High-registration multi-room SfM using Apache-2.0 DISK + LightGlue
(via Kornia) + pycolmap 4.2.1 geometric verification & bundle adjustment.

Why this exists:
  Standard SIFT on narrow indoor rooms with painted walls, curtains, and doorway turns
  fractured our 75s multi-room walkthrough into 10 disconnected models (35/225 = 16%
  in the largest model). Dense 6 Hz sampling (~450 frames) + commercially licensed
  Apache-2.0 DISK keypoints + LightGlue transformer matching across sequential +
  global loop-closure pairs bridges low-texture walls and doorway turns into ONE
  unified metric reconstruction.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
import traceback
from pathlib import Path

import cv2
import numpy as np

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")
SCRATCH = Path("/tmp/namma")
OUT = WORK / "out"
CODE = SCRATCH / "code"
RUN = SCRATCH / "runs" / "home_v1"

TARGET_RATE = os.environ.get("NM_TARGET_RATE", "5.0")   # ~375 frames across 75s
MAX_WIDTH = os.environ.get("NM_MAX_W", "1600")
SEQ_WINDOW = int(os.environ.get("NM_SEQ_WINDOW", "18"))
LOOP_TOPK = int(os.environ.get("NM_LOOP_TOPK", "12"))
MAX_KPTS = int(os.environ.get("NM_MAX_KPTS", "2048"))
MIN_MATCHES = int(os.environ.get("NM_MIN_MATCHES", "20"))


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def stage_code() -> None:
    tars = sorted(INPUT.glob("**/code.tar"))
    if tars:
        CODE.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tars[0]) as t:
            t.extractall(CODE)
    else:
        cli = next(INPUT.glob("**/namma/cli.py"), None)
        if not cli:
            raise SystemExit("namma/cli.py not found under /kaggle/input")
        shutil.copytree(cli.parents[1], CODE, dirs_exist_ok=True)
    sys.path.insert(0, str(CODE))
    log(f"code staged: {sorted(p.name for p in CODE.iterdir())}")


def ensure_deps() -> tuple[str, str]:
    pkgs = []
    try:
        import pycolmap
    except ImportError:
        pkgs.append("pycolmap==4.2.1")
    try:
        import kornia
    except ImportError:
        pkgs.append("kornia>=0.7.3")
    if pkgs:
        log(f"pip installing: {pkgs}")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", *pkgs], check=True)
    import kornia
    import pycolmap
    return pycolmap.__version__, kornia.__version__


def find_video() -> Path:
    exts = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
    vids = sorted(p for p in INPUT.glob("**/*") if p.is_file() and p.suffix.lower() in exts)
    if not vids:
        raise SystemExit("no video under /kaggle/input")
    return sorted(vids, key=lambda p: p.stat().st_size, reverse=True)[0]


def pair_id(id1: int, id2: int) -> int:
    if id1 > id2:
        id1, id2 = id2, id1
    return id1 * 2147483647 + id2


def run_disk_lightglue_sfm(capture_dir: Path) -> dict:
    import kornia.feature as KF
    import pycolmap
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"DISK+LightGlue device: {device} ({torch.cuda.get_device_name(0) if device == 'cuda' else 'cpu'})")

    frames_dir = capture_dir / "frames"
    images = sorted(p.name for p in frames_dir.glob("*.jpg"))
    n_imgs = len(images)
    out_dir = capture_dir / "sfm"
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "database.db"
    if db_path.exists():
        db_path.unlink()
    sparse_dir = out_dir / "sparse"
    if sparse_dir.exists():
        shutil.rmtree(sparse_dir)
    sparse_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # 1. Initialize valid pycolmap 4.2.1 database (cameras, rigs, frames, images)
    #    with shared CameraMode.SINGLE using tiny dummy SIFT extraction (fast!).
    log("initializing pycolmap 4.2.1 database with CameraMode.SINGLE...")
    try:
        sift_opts = pycolmap.SiftExtractionOptions()
        sift_opts.max_num_features = 64
        ext_opts = pycolmap.FeatureExtractionOptions()
        ext_opts.sift = sift_opts
        pycolmap.extract_features(
            str(db_path), str(frames_dir),
            camera_mode=pycolmap.CameraMode.SINGLE,
            extraction_options=ext_opts,
        )
    except Exception as exc:
        log(f"fast SIFT init fallback ({exc}); running plain extract_features")
        pycolmap.extract_features(
            str(db_path), str(frames_dir),
            camera_mode=pycolmap.CameraMode.SINGLE,
        )

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    name_to_id = {name: int(iid) for iid, name in cur.execute("SELECT image_id, name FROM images").fetchall()}
    log(f"DB initialized with {len(name_to_id)} images")

    # 2. Extract Apache-2.0 DISK features on GPU
    disk = KF.DISK.from_pretrained("depth").to(device).eval()
    kpts_cpu: list[np.ndarray] = []
    descs_gpu: list[torch.Tensor] = []
    kpts_gpu: list[torch.Tensor] = []
    global_vecs: list[np.ndarray] = []
    img_sizes: list[tuple[int, int]] = []

    t_ext = time.time()
    for idx, name in enumerate(images):
        bgr = cv2.imread(str(frames_dir / name))
        h, w = bgr.shape[:2]
        img_sizes.append((w, h))
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        ten = torch.from_numpy(rgb).permute(2, 0, 1).float().div_(255.0).unsqueeze(0).to(device)
        with torch.inference_mode():
            feat = disk(ten, n=MAX_KPTS, pad_if_not_divisible=True)[0]
            kp = feat.keypoints.float()        # (K, 2) x, y
            desc = feat.descriptors.float()    # (K, 128)
        kpts_gpu.append(kp)
        descs_gpu.append(desc)
        kp_np = kp.cpu().numpy().astype(np.float32)
        kpts_cpu.append(kp_np)
        # L2-normalized mean descriptor for fast global loop-closure retrieval
        gv = desc.mean(dim=0).cpu().numpy()
        gn = float(np.linalg.norm(gv))
        global_vecs.append((gv / max(gn, 1e-8)).astype(np.float32))
        if (idx + 1) % 50 == 0 or idx + 1 == n_imgs:
            log(f"DISK extracted {idx + 1}/{n_imgs} (last={len(kp_np)} kpts)")
    log(f"DISK extraction done in {time.time() - t_ext:.1f}s")

    # Overwrite keypoints in DB (6-column affine format [x, y, 1, 0, 0, 1] accepted by all COLMAP versions)
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
        cur.execute(
            "INSERT INTO keypoints (image_id, rows, cols, data) VALUES (?, ?, ?, ?)",
            (iid, n, 6, kp6.tobytes()),
        )
    conn.commit()

    # 3. Build candidate pairs: dense sequential window + global loop closure
    pair_set: set[tuple[int, int]] = set()
    for i in range(n_imgs):
        for j in range(i + 1, min(n_imgs, i + 1 + SEQ_WINDOW)):
            pair_set.add((i, j))

    # Global cosine similarity loop closure (links Central Hall pass 1 <-> pass 2, Bedroom entry <-> exit)
    G = np.stack(global_vecs, axis=0)  # (N, 128)
    sim = G @ G.T
    for i in range(n_imgs):
        # Exclude already-added immediate neighbors
        row = sim[i].copy()
        lo = max(0, i - SEQ_WINDOW)
        hi = min(n_imgs, i + SEQ_WINDOW + 1)
        row[lo:hi] = -1.0
        top_idx = np.argpartition(row, -LOOP_TOPK)[-LOOP_TOPK:]
        for j in top_idx:
            if row[j] > 0.55:
                a, b = (i, int(j)) if i < int(j) else (int(j), i)
                pair_set.add((a, b))

    pairs = sorted(pair_set)
    log(f"matching {len(pairs)} candidate pairs (seq_window={SEQ_WINDOW}, loop_topk={LOOP_TOPK}) with Apache-2.0 LightGlue...")

    # 4. Run Apache-2.0 LightGlue matching on GPU
    lg = KF.LightGlue(features="disk").to(device).eval()
    t_match = time.time()
    verified_pairs: list[tuple[str, str]] = []
    total_matches = 0

    for p_idx, (i, j) in enumerate(pairs):
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
            out = lg(inp)
            m = out["matches"][0]  # (M, 2)
        if m.shape[0] < MIN_MATCHES:
            continue
        m_np = m.cpu().numpy().astype(np.uint32)
        id_i = name_to_id[images[i]]
        id_j = name_to_id[images[j]]
        if id_i > id_j:
            m_np = m_np[:, [1, 0]]
            id_i, id_j = id_j, id_i
        pid = pair_id(id_i, id_j)
        cur.execute(
            "INSERT OR REPLACE INTO matches (pair_id, rows, cols, data) VALUES (?, ?, ?, ?)",
            (pid, int(len(m_np)), 2, m_np.tobytes()),
        )
        verified_pairs.append((images[i], images[j]))
        total_matches += int(len(m_np))
        if (p_idx + 1) % 1000 == 0 or p_idx + 1 == len(pairs):
            log(f"LightGlue matched {p_idx + 1}/{len(pairs)} pairs -> {len(verified_pairs)} kept (avg {total_matches / max(len(verified_pairs), 1):.0f} matches)")

    conn.commit()
    conn.close()
    log(f"LightGlue matching done in {time.time() - t_match:.1f}s ({len(verified_pairs)} matched pairs)")

    # 5. Geometric verification via pycolmap.verify_matches
    pairs_txt = out_dir / "pairs.txt"
    pairs_txt.write_text("\n".join(f"{a} {b}" for a, b in verified_pairs) + "\n", encoding="utf-8")
    t_ver = time.time()
    log("running pycolmap.verify_matches...")
    try:
        vopts = pycolmap.TwoViewGeometryOptions()
        vopts.min_num_inliers = 15
        vopts.ransac.max_error = 4.0
        pycolmap.verify_matches(str(db_path), str(pairs_txt), options=vopts)
    except Exception as exc:
        log(f"verify_matches options fallback ({exc}); calling positional")
        pycolmap.verify_matches(str(db_path), str(pairs_txt))
    log(f"verify_matches done in {time.time() - t_ver:.1f}s")

    # 6. Incremental mapping (bundle adjustment)
    t_map = time.time()
    log("running pycolmap.incremental_mapping...")
    mopts = pycolmap.IncrementalPipelineOptions()
    for attr, val in (("min_num_matches", 12), ("multiple_models", True)):
        if hasattr(mopts, attr):
            setattr(mopts, attr, val)
    if hasattr(mopts, "mapper"):
        for attr, val in (
            ("init_min_num_inliers", 50),
            ("abs_pose_min_num_inliers", 15),
            ("filter_max_reproj_error", 4.0),
        ):
            if hasattr(mopts.mapper, attr):
                setattr(mopts.mapper, attr, val)
    recs_raw = pycolmap.incremental_mapping(str(db_path), str(frames_dir), str(sparse_dir), options=mopts)
    from namma import sfm as namma_sfm
    recs = namma_sfm._as_list(recs_raw)
    recs = sorted(recs, key=lambda r: namma_sfm._get(r, "num_reg_images"), reverse=True)
    sizes = [int(namma_sfm._get(r, "num_reg_images")) for r in recs]
    log(f"incremental_mapping done in {time.time() - t_map:.1f}s: {len(recs)} model(s), sizes={sizes}")

    if not recs:
        raise SystemExit("incremental_mapping produced 0 models")

    rec = recs[0]
    model_dir = sparse_dir / "model"
    model_dir.mkdir(exist_ok=True)
    rec.write(str(model_dir))
    txt_dir = out_dir / "sparse_txt"
    txt_dir.mkdir(exist_ok=True)
    rec.write_text(str(txt_dir))

    reg = int(namma_sfm._get(rec, "num_reg_images"))
    pts = int(namma_sfm._get(rec, "num_points3D"))
    errors = [p.error for p in rec.points3D.values() if p.error is not None]
    mean_err = round(float(np.mean(errors)), 3) if errors else 0.0
    med_err = round(float(np.median(errors)), 3) if errors else 0.0

    namma_sfm._write_ply(rec, out_dir / "sparse.ply")
    (out_dir / "poses.json").write_text(json.dumps(namma_sfm._poses(rec, frames_dir), indent=2), encoding="utf-8")
    (out_dir / "transforms.json").write_text(json.dumps(namma_sfm._transforms(rec, frames_dir), indent=2), encoding="utf-8")

    report = {
        "stage": "sfm",
        "status": "ok",
        "backend": "disk+lightglue+pycolmap",
        "pycolmap_version": pycolmap.__version__,
        "matcher": f"disk_lightglue_seq{SEQ_WINDOW}_loop{LOOP_TOPK}",
        "extract_strategy": f"kornia.DISK(depth, max_kpts={MAX_KPTS}) + CameraMode.SINGLE",
        "match_strategy": f"kornia.LightGlue(disk) -> {len(verified_pairs)}/{len(pairs)} pairs",
        "map_strategy": "pycolmap.incremental_mapping",
        "frames_in": n_imgs,
        "models_found": len(recs),
        "model_sizes": sizes,
        "frames_registered": reg,
        "registered_fraction": round(reg / n_imgs, 3),
        "points3d": pts,
        "mean_reprojection_error_px": mean_err,
        "median_reprojection_error_px": med_err,
        "timing_seconds": round(time.time() - t0, 1),
        "warnings": ([] if len(recs) == 1 else [f"{len(recs)} models {sizes}; kept largest"]),
    }
    (out_dir / "sfm_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(f"RESULT: {reg}/{n_imgs} ({reg/n_imgs:.1%}) registered, {pts} 3D pts, med_err={med_err}px, models={sizes}")
    return report


def run_stage(args: list[str]) -> None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    log(f"run: {' '.join(args)}")
    subprocess.run([sys.executable, "-m", "namma.cli", *args], cwd=CODE, env=env, check=True)


def collect() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for rel in [
        "frames_meta.json", "sfm/sfm_report.json", "sfm/poses.json",
        "sfm/transforms.json", "sfm/sparse.ply",
        "nav/nav.json", "nav/nav_report.json", "nav/occupancy.png",
        "capture_qa.json", "capture_qa.md",
    ]:
        src = RUN / rel
        if src.exists():
            shutil.copy2(src, OUT / Path(rel).name)
    txt = RUN / "sfm" / "sparse_txt"
    if txt.is_dir():
        shutil.make_archive(str(OUT / "sparse_txt"), "zip", root_dir=txt)
    frames = RUN / "frames"
    if frames.is_dir():
        shutil.make_archive(str(OUT / "frames"), "zip", root_dir=frames)
    log(f"collected out/: {sorted(p.name for p in OUT.iterdir())}")


def main() -> None:
    t0 = time.time()
    error = None
    try:
        stage_code()
        pyv, kv = ensure_deps()
        log(f"pycolmap={pyv} kornia={kv}")
        vid = find_video()
        log(f"video: {vid} ({vid.stat().st_size / 1e6:.1f} MB)")
        run_stage(["frames", str(vid), str(RUN), "--target-rate", TARGET_RATE, "--max-width", MAX_WIDTH])
        run_disk_lightglue_sfm(RUN)
        run_stage(["geometry", str(RUN)])
        run_stage(["qa", str(RUN)])
    except BaseException:
        error = traceback.format_exc()
        log("ERROR:\n" + error)
    finally:
        try:
            collect()
        except Exception:
            log("collect failed:\n" + traceback.format_exc())
        (OUT / "summary.txt").write_text(
            f"status {'error' if error else 'ok'}\nelapsed_s {time.time() - t0:.1f}\n"
            + (error or ""),
            encoding="utf-8",
        )
        log("done")


if __name__ == "__main__":
    main()
