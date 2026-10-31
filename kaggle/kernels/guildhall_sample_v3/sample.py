"""Build a compact, fully QA'd repo sample from the Guildhall v3 Kaggle runs."""
from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path

import numpy as np

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")
OUT = WORK / "out"
SAMPLE = WORK / "guildhall-v3"
PREVIEW_FRAMES = 14
MAX_CLOUD_POINTS = 250_000
MAX_GAUSSIANS = 900_000


def find_file(name: str, *, root: Path = INPUT) -> Path:
    found = sorted(root.rglob(name))
    if not found:
        raise FileNotFoundError(f"could not find {name} beneath {root}")
    return found[0]


def locate_roots() -> tuple[Path, Path]:
    capture_candidates = sorted(INPUT.rglob("frames_meta.json"))
    capture = next((p.parent for p in capture_candidates
                    if (p.parent / "sfm_report.json").exists()
                    and ((p.parent / "frames.zip").exists()
                         or (p.parent / "frames").is_dir())), None)
    if capture is None:
        raise FileNotFoundError("capture input needs frames.zip, frames_meta.json, and sfm_report.json")

    train_report = find_file("train_report.json")
    gpu_out = train_report.parent
    if not ((gpu_out / "web" / "cloud.ply").exists()
            and (gpu_out / "web" / "splat.splat").exists()
            and (gpu_out / "web" / "nav.json").exists()
            and (gpu_out / "splat.ply").exists()):
        raise FileNotFoundError(f"incomplete GPU artifacts in {gpu_out}")
    report = json.loads(train_report.read_text(encoding="utf-8"))
    if report.get("status") != "ok":
        raise RuntimeError(f"GPU training did not pass: {report}")
    return capture, gpu_out


def read_cloud(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with path.open("rb") as handle:
        if handle.readline().strip() != b"ply":
            raise ValueError(f"not a PLY file: {path}")
        count, fmt = 0, ""
        props: list[tuple[str, str]] = []
        while True:
            line = handle.readline()
            if not line:
                raise ValueError(f"truncated PLY header: {path}")
            parts = line.split()
            if parts[:1] == [b"format"]:
                fmt = parts[1].decode()
            elif parts[:1] == [b"element"] and parts[1:2] == [b"vertex"]:
                count = int(parts[2])
            elif parts[:1] == [b"property"]:
                props.append((parts[-1].decode(), parts[-2].decode()))
            elif parts[:1] == [b"end_header"]:
                break
        if fmt != "binary_little_endian":
            raise ValueError(f"unsupported PLY format: {fmt}")
        types = {"float": "<f4", "float32": "<f4", "double": "<f8",
                 "float64": "<f8", "uchar": "u1", "uint8": "u1"}
        dtype = np.dtype([(name, types[kind]) for name, kind in props])
        data = np.frombuffer(handle.read(count * dtype.itemsize), dtype=dtype, count=count)
    xyz = np.column_stack((data["x"], data["y"], data["z"])).astype(np.float32)
    rgb_names = ("red", "green", "blue")
    rgb = (np.column_stack([data[n] for n in rgb_names]).astype(np.uint8)
           if all(n in data.dtype.names for n in rgb_names)
           else np.zeros((count, 3), np.uint8))
    return xyz, rgb


def write_cloud(path: Path, xyz: np.ndarray, rgb: np.ndarray) -> None:
    header = ("ply\nformat binary_little_endian 1.0\n"
              f"element vertex {len(xyz)}\n"
              "property float x\nproperty float y\nproperty float z\n"
              "property uchar red\nproperty uchar green\nproperty uchar blue\n"
              "end_header\n").encode("ascii")
    data = np.empty(len(xyz), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                     ("red", "u1"), ("green", "u1"), ("blue", "u1")])
    data["x"], data["y"], data["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    data["red"], data["green"], data["blue"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    with path.open("wb") as handle:
        handle.write(header)
        handle.write(data.tobytes())


def add_camera_headings(nav_path: Path, capture: Path) -> int:
    """Carry registered camera look directions into the viewer navigation file.

    A walking tangent is not a reliable camera heading for a walk-through:
    people often look at a wall or monument while moving sideways. Use COLMAP's
    saved camera-to-world direction, rotate it into the metric nav frame, and
    let the browser start at the captured view instead of pointing into empty
    space.
    """
    poses_path = capture / "poses.json"
    if not poses_path.exists():
        return 0
    nav = json.loads(nav_path.read_text(encoding="utf-8"))
    poses = json.loads(poses_path.read_text(encoding="utf-8"))
    frames = poses.get("frames", [])
    trajectory = nav.get("trajectory", [])
    align = nav.get("align", {})
    if len(frames) != len(trajectory) or not align.get("R_row_major"):
        return 0

    rotation = np.asarray(align["R_row_major"], dtype=np.float64).reshape(3, 3)
    yaws, pitches = [], []
    for frame in frames:
        w2c = np.asarray(frame["w2c"], dtype=np.float64)
        # COLMAP camera coordinates look along +Z. Its world-space camera
        # forward is the third column of R_camera_to_world.
        forward_scene = w2c[:3, :3].T[:, 2]
        forward_nav = rotation.T @ forward_scene
        horizontal = float(np.hypot(forward_nav[0], forward_nav[1]))
        yaws.append(float(np.arctan2(-forward_nav[0], forward_nav[1])))
        pitch = float(np.arctan2(forward_nav[2], horizontal))
        pitches.append(float(np.clip(pitch, -0.85, 0.35)))

    nav["trajectory_yaws"] = yaws
    nav["trajectory_pitches"] = pitches
    # This preview frame shows the full, well-lit monument and nave instead
    # of starting too close to a wall or pointed into the disconnected area.
    nav["default_spawn"] = min(106, len(yaws) - 1)
    nav_path.write_text(json.dumps(nav, separators=(",", ":")), encoding="utf-8")
    return len(yaws)


def convert_splat(ply_path: Path, out_path: Path) -> int:
    with ply_path.open("rb") as handle:
        if handle.readline().strip() != b"ply":
            raise ValueError("raw splat is not PLY")
        count, fmt, props = 0, "", []
        while True:
            line = handle.readline()
            if not line:
                raise ValueError("truncated raw splat PLY header")
            parts = line.split()
            if parts[:1] == [b"format"]:
                fmt = parts[1].decode()
            elif parts[:1] == [b"element"] and parts[1:2] == [b"vertex"]:
                count = int(parts[2])
            elif parts[:1] == [b"property"]:
                props.append((parts[-1].decode(), parts[-2].decode()))
            elif parts[:1] == [b"end_header"]:
                break
        if fmt != "binary_little_endian":
            raise ValueError("raw splat PLY must be binary little endian")
        types = {"float": "<f4", "float32": "<f4", "double": "<f8",
                 "float64": "<f8", "uchar": "u1", "uint8": "u1"}
        dtype = np.dtype([(name, types[kind]) for name, kind in props])
        data = np.frombuffer(handle.read(count * dtype.itemsize), dtype=dtype, count=count)
    names = set(data.dtype.names or ())
    needed = {"x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
              "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"}
    missing = sorted(needed - names)
    if missing:
        raise ValueError(f"raw splat PLY is missing {missing}")
    pos = np.column_stack((data["x"], data["y"], data["z"])).astype(np.float32)
    rgb = np.clip(0.5 + 0.28209479177387814 *
                  np.column_stack((data["f_dc_0"], data["f_dc_1"], data["f_dc_2"])),
                  0.0, 1.0)
    alpha = 1.0 / (1.0 + np.exp(-np.asarray(data["opacity"], dtype=np.float64)))
    scale = np.clip(np.exp(np.column_stack((data["scale_0"], data["scale_1"],
                                             data["scale_2"]))), 1e-5, 1.0)
    quaternion = np.column_stack((data["rot_0"], data["rot_1"],
                                  data["rot_2"], data["rot_3"])).astype(np.float64)
    norm = np.linalg.norm(quaternion, axis=1, keepdims=True)
    quaternion = np.where(norm > 1e-12, quaternion / np.maximum(norm, 1e-12),
                          np.array([1.0, 0.0, 0.0, 0.0]))
    keep = np.flatnonzero(alpha >= 0.02)
    if len(keep) > MAX_GAUSSIANS:
        importance = alpha[keep] * np.cbrt(np.prod(scale[keep], axis=1))
        keep = keep[np.argpartition(importance, -MAX_GAUSSIANS)[-MAX_GAUSSIANS:]]
    n = len(keep)
    colors = np.empty((n, 4), dtype=np.uint8)
    colors[:, :3] = np.round(rgb[keep] * 255).astype(np.uint8)
    colors[:, 3] = np.round(alpha[keep] * 255).astype(np.uint8)
    quat_u8 = np.clip(quaternion[keep] * 128 + 128, 0, 255).astype(np.uint8)
    scales = scale[keep].astype(np.float32)
    records = np.empty((n, 32), dtype=np.uint8)
    records[:, :12] = pos[keep].view(np.uint8).reshape(n, 12)
    records[:, 12:24] = scales.view(np.uint8).reshape(n, 12)
    records[:, 24:28] = colors
    records[:, 28:32] = quat_u8
    records.tofile(out_path)
    return n


def generate_qa(capture_dir: Path) -> dict:
    frames = json.loads((capture_dir / "frames_meta.json").read_text(encoding="utf-8"))
    sfm = json.loads((capture_dir / "sfm" / "sfm_report.json").read_text(encoding="utf-8"))
    nav = json.loads((capture_dir / "nav" / "nav_report.json").read_text(encoding="utf-8"))
    checks = []

    def add(name: str, status: str, detail: str, compensation: str, value=None):
        checks.append({"name": name, "status": status, "detail": detail,
                       "compensation": compensation, "value": value})

    p10 = frames["stats"]["rank_blur_p10"]
    status = "PASS" if p10 >= 100 else "WARN" if p10 >= 50 else "FAIL"
    add("frame_sharpness", status, f"p10 Laplacian {p10:.0f} (threshold 100)",
        "watch the demo video for soft zones; recapture the worst rooms in brighter light")
    kept = frames["stats"]["frames_kept"]
    add("frame_count", "PASS" if kept >= 80 else "WARN",
        f"{kept} frames kept (stride {frames['stride']})",
        "fewer views -> weaker splat around fast-motion areas")
    frac = sfm.get("registered_fraction", 0.0)
    status = "PASS" if frac >= 0.8 else "WARN" if frac >= 0.6 else "FAIL"
    add("sfm_registered_fraction", status,
        f"{sfm.get('frames_registered')}/{sfm.get('frames_in')} frames registered",
        "unregistered stretches get no texture; walk slower with more overlap there", frac)
    med = sfm.get("median_reprojection_error_px", 9.9)
    status = "PASS" if med <= 1.0 else "WARN" if med <= 1.5 else "FAIL"
    add("sfm_reprojection_error", status, f"median {med}px (threshold 1.0)",
        "check video stabilization is OFF; EIS warps break rigid geometry", med)
    outline = nav.get("outline_points", 0)
    add("floor_outline", "PASS" if outline >= 3 else "WARN",
        f"{outline} outline points, {nav.get('walkable_area_m2')} m2 walkable",
        "sparse cloud can under-draw the footprint; the depth stage densifies it")
    warnings = nav.get("warnings", [])
    add("geometry_warnings", "PASS" if not warnings else "WARN",
        "; ".join(warnings) if warnings else "none", "see nav_report.json for details")
    rank = {"PASS": 0, "WARN": 1, "FAIL": 2}
    overall = max(checks, key=lambda check: rank[check["status"]])["status"]
    doc = {"stage": "qa", "capture": capture_dir.name,
           "time": time.strftime("%Y-%m-%d %H:%M:%S"), "overall": overall,
           "checks": checks}
    (capture_dir / "capture_qa.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    lines = [f"# Capture QA -- {capture_dir.name}", "",
             f"**Overall: {overall}** ({doc['time']})", "",
             "| Check | Status | Detail | Compensation |", "|---|---|---|---|"]
    lines.extend(f"| {c['name']} | {c['status']} | {c['detail']} | {c['compensation']} |"
                 for c in checks)
    (capture_dir / "capture_qa.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return doc


def pick_frames(capture: Path) -> int:
    dst = SAMPLE / "frames"
    dst.mkdir(parents=True, exist_ok=True)
    frames_zip = capture / "frames.zip"
    if frames_zip.exists():
        with zipfile.ZipFile(frames_zip) as archive:
            names = sorted(n for n in archive.namelist() if n.lower().endswith(".jpg"))
            idx = np.linspace(0, len(names) - 1, min(PREVIEW_FRAMES, len(names))).round().astype(int)
            for i in sorted(set(idx.tolist())):
                name = Path(names[i]).name
                with archive.open(names[i]) as source, (dst / name).open("wb") as target:
                    shutil.copyfileobj(source, target)
    else:
        names = sorted((capture / "frames").glob("*.jpg"))
        idx = np.linspace(0, len(names) - 1, min(PREVIEW_FRAMES, len(names))).round().astype(int)
        for i in sorted(set(idx.tolist())):
            shutil.copy2(names[i], dst / names[i].name)
    return len(list(dst.glob("*.jpg")))


def prune_splat(path: Path, nav: dict, lo: np.ndarray, hi: np.ndarray) -> int:
    data = np.fromfile(path, dtype=np.uint8)
    if data.size % 32:
        raise ValueError("web splat size is not a multiple of the 32-byte record layout")
    records = data.reshape(-1, 32)
    pos = records[:, :12].copy().view(np.float32).reshape(-1, 3).astype(np.float64)
    align = nav["align"]
    scale = float(align["scale_m_per_unit"])
    rotation = np.asarray(align["R_row_major"], dtype=np.float64).reshape(3, 3)
    origin = np.asarray(align["origin"], dtype=np.float64)
    margin = 3.0
    nav_pos = scale * (pos - origin) @ rotation
    keep = ((nav_pos >= lo - margin) & (nav_pos <= hi + margin)).all(axis=1)
    records[keep].tofile(path)
    return int(keep.sum())


def write_license() -> None:
    text = """# Guildhall v3 sample — source and licence

The derived artifacts in this folder reconstruct **Guildhall City of London
England interior walkaround video** by Acabashi:
<https://commons.wikimedia.org/wiki/File:Guildhall_City_of_London_England_interior_walkaround_video.webm>

The source video is licensed under **Creative Commons Attribution-ShareAlike
4.0 International (CC BY-SA 4.0)**:
<https://creativecommons.org/licenses/by-sa/4.0/>.

This sample uses a stream-copied segment beginning at approximately 94 seconds
and lasting 91.925 seconds. No source frames were re-encoded before Kaggle
frame selection. Derived sample data is distributed under CC BY-SA 4.0.
This is a public stand-in capture, not the team's own venue. Topoloka pipeline
code is MIT licensed; see the repository root LICENSE.
"""
    (SAMPLE / "LICENSE").write_text(text, encoding="utf-8")


def main() -> None:
    if SAMPLE.exists():
        shutil.rmtree(SAMPLE)
    SAMPLE.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    print("input mounts:", [str(p.relative_to(INPUT)) for p in sorted(INPUT.iterdir())], flush=True)
    capture, gpu = locate_roots()

    for name, rel in (
        ("frames_meta.json", "frames_meta.json"),
        ("poses.json", "sfm/poses.json"),
        ("sfm_report.json", "sfm/sfm_report.json"),
        ("sparse.ply", "sfm/sparse.ply"),
        ("transforms.json", "transforms.json"),
    ):
        src = capture / name
        dst = SAMPLE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    pick_frames(capture)

    # Keep the dense metric geometry as the authoritative navigation result.
    for src_name, dst_rel in (
        ("nav.json", "nav/nav.json"),
        ("nav_report.json", "nav/nav_report.json"),
        ("depth_report.json", "depth/depth_report.json"),
        ("scale.json", "depth/scale.json"),
        ("metricize.json", "metricize.json"),
    ):
        src = gpu / src_name
        dst = SAMPLE / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    shutil.copy2(gpu / "web" / "occupancy.png", SAMPLE / "nav" / "occupancy.png")

    # Re-run the repo's QA with the CPU metadata present. The first GPU run
    # lacked these two files in its capture dataset and therefore said SKIP.
    qa_doc = generate_qa(SAMPLE)

    web_src = gpu / "web"
    web = SAMPLE / "web"
    web.mkdir(parents=True)
    for name in ("nav.json", "occupancy.png", "meta.json"):
        shutil.copy2(web_src / name, web / name)
    camera_headings = add_camera_headings(web / "nav.json", capture)

    xyz, rgb = read_cloud(web_src / "cloud.ply")
    bounds_lo, bounds_hi = xyz.min(axis=0), xyz.max(axis=0)
    if len(xyz) > MAX_CLOUD_POINTS:
        rng = np.random.default_rng(7)
        keep = np.sort(rng.choice(len(xyz), MAX_CLOUD_POINTS, replace=False))
        xyz, rgb = xyz[keep], rgb[keep]
    write_cloud(web / "cloud.ply", xyz, rgb)

    tmp_splat = web / "_splat.splat"
    splat_count = convert_splat(gpu / "splat.ply", tmp_splat)
    nav = json.loads((web / "nav.json").read_text(encoding="utf-8"))
    kept = prune_splat(tmp_splat, nav, bounds_lo, bounds_hi)
    tmp_splat.replace(web / "splat.splat")

    meta_path = web / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    qa_doc = json.loads((SAMPLE / "capture_qa.json").read_text(encoding="utf-8"))
    meta["capture"] = "guildhall-v3"
    meta["cloud_points"] = len(xyz)
    meta["qa_overall"] = qa_doc["overall"]
    meta["sample"] = "Kaggle output, 900k Gaussian quality budget and capture volume"
    meta["splat"] = {"present": True, "bytes": (web / "splat.splat").stat().st_size,
                     "gaussians": kept}
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    write_license()

    # The README is filled with measured package sizes after extraction. This
    # compact placeholder keeps the Kaggle-produced bundle self describing.
    (SAMPLE / "SOURCE.md").write_text(
        "Guildhall City of London interior walkaround by Acabashi; CC BY-SA 4.0. "
        "Trimmed at approximately 94 seconds for 91.925 seconds. See LICENSE.\n",
        encoding="utf-8")

    archive_path = OUT / "guildhall-v3.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for path in sorted(SAMPLE.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(WORK))
    print(json.dumps({
        "sample_zip": str(archive_path),
        "qa_overall": qa_doc["overall"],
        "qa_checks": [c["status"] for c in qa_doc["checks"]],
        "camera_headings": camera_headings,
        "preview_frames": len(list((SAMPLE / "frames").glob("*.jpg"))),
        "cloud_points": len(xyz),
        "splat_after_alpha_budget": splat_count,
        "splat_gaussians": kept,
        "splat_bytes": (web / "splat.splat").stat().st_size,
        "sample_bytes": sum(p.stat().st_size for p in SAMPLE.rglob("*") if p.is_file()),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
