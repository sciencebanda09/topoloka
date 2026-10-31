"""Build a compact public Guildhall sample from the Kaggle MVS output."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import numpy as np

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")
SCRATCH = Path("/tmp/guildhall-mvs")
OUT = WORK / "out"
SAMPLE = WORK / "guildhall-mvs"
MAX_CLOUD_POINTS = 250_000
PREVIEW_FRAMES = 14


def find(name: str) -> Path:
    result = sorted(INPUT.rglob(name))
    if not result:
        raise FileNotFoundError(f"missing {name} beneath {INPUT}")
    return result[0]


def read_cloud(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with path.open("rb") as handle:
        if handle.readline().strip() != b"ply":
            raise ValueError(f"not a PLY file: {path}")
        count, fmt, properties = 0, "", []
        while True:
            line = handle.readline()
            if not line:
                raise ValueError("truncated PLY header")
            parts = line.split()
            if parts[:1] == [b"format"]:
                fmt = parts[1].decode()
            elif parts[:1] == [b"element"] and parts[1:2] == [b"vertex"]:
                count = int(parts[2])
            elif parts[:1] == [b"property"]:
                properties.append((parts[-1].decode(), parts[-2].decode()))
            elif parts[:1] == [b"end_header"]:
                break
        if fmt != "binary_little_endian":
            raise ValueError(f"unsupported PLY encoding: {fmt}")
        types = {"float": "<f4", "float32": "<f4", "double": "<f8",
                 "float64": "<f8", "uchar": "u1", "uint8": "u1"}
        dtype = np.dtype([(name, types[kind]) for name, kind in properties])
        data = np.frombuffer(handle.read(count * dtype.itemsize), dtype=dtype, count=count)
    xyz = np.column_stack((data["x"], data["y"], data["z"])).astype(np.float32)
    if all(name in data.dtype.names for name in ("red", "green", "blue")):
        rgb = np.column_stack((data["red"], data["green"], data["blue"])).astype(np.uint8)
    else:
        rgb = np.full((count, 3), 180, np.uint8)
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


def add_camera_headings(nav_path: Path, poses_path: Path) -> None:
    nav = json.loads(nav_path.read_text(encoding="utf-8"))
    poses = json.loads(poses_path.read_text(encoding="utf-8"))
    frames = poses.get("frames", [])
    trajectory = nav.get("trajectory", [])
    align = nav.get("align", {})
    if len(frames) != len(trajectory) or not align.get("R_row_major"):
        return
    rotation = np.asarray(align["R_row_major"], dtype=np.float64)
    yaws, pitches = [], []
    for frame in frames:
        w2c = np.asarray(frame["w2c"], dtype=np.float64)
        forward_scene = w2c[:3, :3].T[:, 2]
        forward_nav = rotation.T @ forward_scene
        horizontal = float(np.hypot(forward_nav[0], forward_nav[1]))
        yaws.append(float(np.arctan2(-forward_nav[0], forward_nav[1])))
        pitches.append(float(np.clip(np.arctan2(forward_nav[2], horizontal), -0.85, 0.35)))
    nav["trajectory_yaws"] = yaws
    nav["trajectory_pitches"] = pitches
    nav["default_spawn"] = min(106, len(yaws) - 1)
    nav_path.write_text(json.dumps(nav, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    SAMPLE.mkdir(parents=True, exist_ok=True)
    capture = next((p.parent for p in sorted(INPUT.rglob("transforms.json"))
                    if (p.parent / "frames_meta.json").exists()
                    and ((p.parent / "frames.zip").is_file()
                         or (p.parent / "frames").is_dir())), None)
    if capture is None:
        raise FileNotFoundError("capture input is missing frames, frames_meta.json, or transforms.json")
    mesh_report_path = find("mesh_run_report.json")
    mesh_root = mesh_report_path.parent
    mesh_run = json.loads(mesh_report_path.read_text(encoding="utf-8"))
    if mesh_run.get("status") != "ok":
        raise RuntimeError(f"MVS reconstruction did not pass: {mesh_run}")
    required = ("mesh.glb", "cloud.ply", "splat.splat", "nav.json", "meta.json")
    for name in required:
        if not (mesh_root / name).exists():
            raise FileNotFoundError(f"MVS output is missing {name}")

    xyz, rgb = read_cloud(mesh_root / "cloud.ply")
    if len(xyz) > MAX_CLOUD_POINTS:
        rng = np.random.default_rng(17)
        keep = np.sort(rng.choice(len(xyz), MAX_CLOUD_POINTS, replace=False))
        xyz, rgb = xyz[keep], rgb[keep]

    web = SAMPLE / "web"
    web.mkdir(parents=True, exist_ok=True)
    write_cloud(web / "cloud.ply", xyz, rgb)
    for name in ("mesh.glb", "splat.splat", "nav.json", "meta.json", "occupancy.png"):
        source = mesh_root / name
        if source.exists():
            shutil.copy2(source, web / name)

    nav_report_path = mesh_root / "nav_report.json"
    if nav_report_path.exists():
        shutil.copy2(nav_report_path, SAMPLE / "nav_report.json")
    shutil.copy2(mesh_report_path.parent / "mesh_report.json", SAMPLE / "mesh_report.json")
    shutil.copy2(capture / "frames_meta.json", SAMPLE / "frames_meta.json")
    shutil.copy2(capture / "transforms.json", SAMPLE / "transforms.json")
    for name in ("capture_qa.json", "capture_qa.md", "LICENSE"):
        if (capture / name).exists():
            shutil.copy2(capture / name, SAMPLE / name)
    poses_path = capture / "poses.json"
    if poses_path.exists():
        shutil.copy2(poses_path, SAMPLE / "poses.json")
        add_camera_headings(web / "nav.json", poses_path)

    frames_dir = SCRATCH / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames_zip = capture / "frames.zip"
    if frames_zip.is_file():
        with zipfile.ZipFile(frames_zip) as archive:
            archive.extractall(frames_dir)
    else:
        shutil.copytree(capture / "frames", frames_dir, dirs_exist_ok=True)
    source_frames = sorted(frames_dir.glob("*.jpg"))
    preview_dir = SAMPLE / "frames"
    preview_dir.mkdir(parents=True, exist_ok=True)
    chosen = np.linspace(0, len(source_frames) - 1,
                         min(PREVIEW_FRAMES, len(source_frames))).round().astype(int)
    for index in np.unique(chosen):
        shutil.copy2(source_frames[int(index)], preview_dir / source_frames[int(index)].name)

    meta_path = web / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update({"capture": "guildhall-mvs", "cloud_points": len(xyz),
                 "sample": "Kaggle MVS textured mesh plus the retained Gaussian splat"})
    meta["mesh"] = {"present": True, "format": "glb", "faces": mesh_run.get("mesh_faces")}
    nav_report = json.loads(nav_report_path.read_text(encoding="utf-8")) if nav_report_path.exists() else {}
    if nav_report.get("walkable_area_m2") is not None:
        meta["walkable_area_m2"] = nav_report["walkable_area_m2"]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    (SAMPLE / "SOURCE.md").write_text(
        "# Guildhall photo-textured MVS sample\n\n"
        "The mesh was rebuilt on Kaggle from the captured frames with COLMAP "
        "multi-view stereo, then textured from the sharp undistorted views. "
        "The Gaussian splat remains available in the viewer model selector.\n",
        encoding="utf-8")
    (OUT / "sample_report.json").write_text(json.dumps({
        "status": "ok", "capture": capture.name, "mesh_faces": mesh_run.get("mesh_faces"),
        "cloud_points": len(xyz), "mesh_bytes": (web / "mesh.glb").stat().st_size,
        "outputs": [str(p.relative_to(WORK)) for p in sorted(SAMPLE.rglob("*")) if p.is_file()],
    }, indent=2), encoding="utf-8")
    print(f"[sample] packed {len(xyz):,} points and {mesh_run.get('mesh_faces'):,} faces")


if __name__ == "__main__":
    main()
