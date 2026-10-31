"""Kaggle GPU job: COLMAP MVS + a photo-textured mesh for the Guildhall.

The output is a conventional triangle mesh whose surface pixels come directly
from the sharp source frames. It is an independent representation beside the
Gaussian splat, so the viewer can switch between both from its single link.
All reconstruction and mesh generation happens in this Kaggle kernel.
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
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

import numpy as np

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")
SCRATCH = Path("/tmp/guildhall-mesh")
OUT = WORK / "out"
RUN = SCRATCH / "run"
CODE = SCRATCH / "code"
MVS = SCRATCH / "mvs"
TEX_W, TEX_H = 1024, 576
ATLAS_COLS, ATLAS_ROWS = 8, 8
MAX_TEXTURE_VIEWS = ATLAS_COLS * ATLAS_ROWS
TARGET_FACES = 650_000
PREFLIGHT_ONLY = False


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def find_file(name: str, root: Path = INPUT) -> Path:
    found = sorted(root.rglob(name))
    if not found:
        raise FileNotFoundError(f"could not find {name} beneath {root}")
    return found[0]


def stage_inputs() -> Path:
    capture = None
    for poses_path in sorted(INPUT.rglob("poses.json")):
        roots = [poses_path.parent]
        if poses_path.parent.name == "sfm":
            roots.insert(0, poses_path.parent.parent)
        for root in roots:
            frames_ok = (root / "frames.zip").exists() or (root / "frames").is_dir()
            sparse_ok = ((root / "sparse_txt.zip").exists()
                         or (root / "sparse_txt").is_dir()
                         or (root / "sfm" / "sparse_txt").is_dir())
            if frames_ok and sparse_ok and (root / "transforms.json").exists():
                capture = root
                break
        if capture is not None:
            break
    if capture is None:
        tree = [str(path.relative_to(INPUT)) for path in sorted(INPUT.rglob("*"))[:100]]
        raise FileNotFoundError("capture input not found; expected frames, sparse text, poses, and "
                                "transforms. Kaggle input tree:\n" + "\n".join(tree))

    CODE.mkdir(parents=True, exist_ok=True)
    code_tars = sorted(INPUT.rglob("code.tar"))
    if code_tars:
        with tarfile.open(code_tars[0]) as archive:
            archive.extractall(CODE)
    else:
        cli = next(INPUT.rglob("namma/cli.py"), None)
        if cli is None:
            raise FileNotFoundError("namma-code input has neither code.tar nor namma/cli.py")
        shutil.copytree(cli.parents[1], CODE, dirs_exist_ok=True)

    RUN.mkdir(parents=True, exist_ok=True)
    frames_out = RUN / "frames"
    frames_out.mkdir(parents=True, exist_ok=True)
    frames_zip = capture / "frames.zip"
    if frames_zip.exists():
        with zipfile.ZipFile(frames_zip) as archive:
            archive.extractall(frames_out)
    else:
        shutil.copytree(capture / "frames", frames_out, dirs_exist_ok=True)
    sfm = RUN / "sfm"
    sfm.mkdir(parents=True, exist_ok=True)
    sparse_out = sfm / "sparse_txt"
    sparse_out.mkdir(parents=True, exist_ok=True)
    sparse_zip = capture / "sparse_txt.zip"
    sparse_dir = capture / "sparse_txt"
    if not sparse_dir.exists() and (capture / "sfm" / "sparse_txt").is_dir():
        sparse_dir = capture / "sfm" / "sparse_txt"
    if sparse_zip.exists():
        with zipfile.ZipFile(sparse_zip) as archive:
            archive.extractall(sparse_out)
    elif sparse_dir.is_dir():
        shutil.copytree(sparse_dir, sparse_out, dirs_exist_ok=True)

    sources = {
        "poses.json": (capture / "poses.json") if (capture / "poses.json").exists()
        else (capture / "sfm" / "poses.json"),
        "transforms.json": (capture / "transforms.json") if (capture / "transforms.json").exists()
        else (capture / "sfm" / "transforms.json"),
        "sparse.ply": (capture / "sparse.ply") if (capture / "sparse.ply").exists()
        else (capture / "sfm" / "sparse.ply"),
        "frames_meta.json": capture / "frames_meta.json",
    }
    for name, source in sources.items():
        if source.exists():
            destination = (sfm / name) if name == "poses.json" else (RUN / name)
            shutil.copy2(source, destination)

    # Preserve the COLMAP-to-metre factor; MVS uses the raw SfM frame while the
    # existing splat has already been metricized. Keep both from one run.
    splat_source = find_file("splat.splat")
    source_root = splat_source.parent.parent if splat_source.parent.name == "web" else splat_source.parent
    nav_dir = RUN / "nav"
    nav_dir.mkdir(parents=True, exist_ok=True)
    nav_roots = [capture / "nav", capture, capture / "web",
                 source_root / "nav", source_root, source_root / "web"]
    for name in ("nav.json", "occupancy.png", "nav_report.json"):
        for root in nav_roots:
            candidate = root / name
            if candidate.is_file():
                shutil.copy2(candidate, nav_dir / name)
                break
    scale_source = source_root / "scale.json"
    if not scale_source.exists():
        scale_source = find_file("scale.json")
    raw_scale = float(json.loads(scale_source.read_text(encoding="utf-8"))
                      ["scale_m_per_unit"])
    fallback_nav_path = nav_dir / "nav.json"
    if fallback_nav_path.exists():
        fallback_nav = json.loads(fallback_nav_path.read_text(encoding="utf-8"))
        fallback_align = fallback_nav.get("align")
        if fallback_align:
            fallback_align["origin"] = (
                np.asarray(fallback_align["origin"], dtype=np.float64) * raw_scale
            ).tolist()
            fallback_align["scale_m_per_unit"] = 1.0
            fallback_align["source_scale_m_per_unit"] = raw_scale
            fallback_nav["scale_m_per_unit"] = 1.0
            fallback_nav["scale_source"] = "capture-navigation metricized MVS frame"
            fallback_nav_path.write_text(json.dumps(fallback_nav), encoding="utf-8")
    depth_dir = RUN / "depth"
    depth_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(scale_source, depth_dir / "raw_scale.json")
    (depth_dir / "scale.json").write_text(json.dumps({
        "scale_m_per_unit": 1.0, "method": "MVS cloud and poses pre-scaled to metres",
        "source_scale_file": str(scale_source),
    }), encoding="utf-8")
    (RUN / "splat").mkdir(parents=True, exist_ok=True)
    shutil.copy2(splat_source, RUN / "splat" / "splat.splat")
    source_meta = splat_source.with_name("meta.json")
    if source_meta.exists():
        shutil.copy2(source_meta, SCRATCH / "source_meta.json")
    source_qa = source_root / "capture_qa.json"
    if source_qa.exists():
        shutil.copy2(source_qa, RUN / "capture_qa.json")
    log(f"staged {len(list((RUN / 'frames').glob('*.jpg')))} frames from {capture}")
    log(f"using metric scale from {scale_source}")
    return capture


def ensure_dependencies() -> None:
    import importlib.util
    from importlib.metadata import PackageNotFoundError, version

    try:
        cuda_colmap_version = version("pycolmap-cuda12")
    except PackageNotFoundError:
        cuda_colmap_version = ""
    if (cuda_colmap_version == "4.2.1" and importlib.util.find_spec("pycolmap")
            and importlib.util.find_spec("open3d")):
        return
    log("installing CUDA COLMAP and Open3D")
    subprocess.run([
        sys.executable, "-m", "pip", "install", "-q",
        "pycolmap-cuda12==4.2.1", "open3d==0.20.0",
    ], check=True)


def ensure_colmap_cli() -> list[str]:
    executable = shutil.which("colmap")
    if executable:
        return [executable]

    manager = shutil.which("micromamba") or shutil.which("conda")
    if not manager:
        archive_path = Path("/tmp/micromamba.tar.bz2")
        binary_path = Path("/tmp/micromamba/bin/micromamba")
        binary_path.parent.mkdir(parents=True, exist_ok=True)
        log("downloading micromamba to install the isolated COLMAP CLI")
        with urllib.request.urlopen(
                "https://micro.mamba.pm/api/micromamba/linux-64/latest", timeout=60) as response:
            archive_path.write_bytes(response.read())
        with tarfile.open(archive_path, mode="r:bz2") as archive:
            member = archive.extractfile("bin/micromamba")
            if member is None:
                raise RuntimeError("micromamba archive did not contain its executable")
            binary_path.write_bytes(member.read())
        binary_path.chmod(0o755)
        manager = str(binary_path)

    if not manager:
        raise RuntimeError("could not provision a COLMAP CLI")

    environment = Path("/tmp/guildhall-colmap-cli")
    mamba_root = Path("/tmp/guildhall-mamba-root")
    log("installing COLMAP 4.2.1 CLI in an isolated conda-forge environment")
    install = subprocess.run([
        manager, "create", "--yes", "--prefix", str(environment),
        "--channel", "conda-forge", "--json", "colmap=4.2.1", "libopenimageio",
    ], capture_output=True, text=True, encoding="utf-8", errors="replace",
       env={**os.environ, "MAMBA_ROOT_PREFIX": str(mamba_root)})
    if install.returncode:
        details = (install.stderr or install.stdout)[-2000:]
        log("COLMAP CLI environment install failed:\n" + details)
        raise RuntimeError(f"COLMAP CLI installer exited with {install.returncode}")
    executable = str(environment / "bin" / "colmap")
    library_dir = str(environment / "lib")
    existing_library_path = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = library_dir + (
        os.pathsep + existing_library_path if existing_library_path else "")
    command = [executable]
    env = {**os.environ, "MAMBA_ROOT_PREFIX": str(mamba_root)}
    check = subprocess.run([*command, "-h"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=env)
    if check.returncode:
        details = (check.stderr or check.stdout)[-1200:]
        raise RuntimeError(f"COLMAP CLI preflight failed ({check.returncode}): {details}")
    return command


def write_sparse_binary(sparse_txt: Path, sparse_bin: Path) -> None:
    import pycolmap

    reconstruction = pycolmap.Reconstruction(str(sparse_txt))
    sparse_bin.mkdir(parents=True, exist_ok=True)
    reconstruction.write(str(sparse_bin))
    log(f"sparse model: {reconstruction.summary()}")


def run_mvs(sparse_bin: Path, colmap_cli: list[str]) -> Path:
    import pycolmap

    MVS.mkdir(parents=True, exist_ok=True)
    log(f"PyCOLMAP {pycolmap.__version__}: undistorting source frames")
    pycolmap.undistort_images(MVS, sparse_bin, RUN / "frames")
    log("PatchMatch stereo on the T4")
    pycolmap.patch_match_stereo(MVS)
    fused = MVS / "fused.ply"
    log("fusing consistent multi-view depth maps with COLMAP CLI")
    subprocess.run([
        *colmap_cli, "stereo_fusion",
        "--workspace_path", str(MVS),
        "--workspace_format", "COLMAP",
        "--input_type", "geometric",
        "--output_path", str(fused),
    ], check=True)
    if not fused.exists() or fused.stat().st_size < 1024:
        raise RuntimeError("COLMAP did not produce a dense fused point cloud")
    log(f"fused cloud: {fused.stat().st_size / 1e6:.1f} MB")
    return fused


def write_simple_ply(path: Path, xyz: np.ndarray, rgb: np.ndarray) -> None:
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


def write_glb(path: Path, positions: np.ndarray, normals: np.ndarray,
              uvs: np.ndarray, indices: np.ndarray, atlas_jpg: bytes) -> None:
    """Write a minimal indexed GLB; this avoids a heavy exporter dependency."""
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
        accessor = {"bufferView": view, "componentType": component,
                    "count": count, "type": kind}
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
        "asset": {"version": "2.0", "generator": "Topoloka Guildhall MVS"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": p_acc, "NORMAL": n_acc, "TEXCOORD_0": uv_acc},
            "indices": i_acc, "material": 0, "mode": 4,
        }]}],
        "materials": [{"pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0}, "metallicFactor": 0.0,
            "roughnessFactor": 1.0,
        }, "doubleSided": True}],
        "textures": [{"sampler": 0, "source": 0}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987,
                       "wrapS": 33071, "wrapT": 33071}],
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


def read_depth_map(path: Path) -> np.ndarray | None:
    try:
        with path.open("rb") as handle:
            dims = []
            token = bytearray()
            while len(dims) < 3:
                ch = handle.read(1)
                if not ch:
                    return None
                if ch == b"&":
                    dims.append(int(token.decode("ascii")))
                    token.clear()
                else:
                    token.extend(ch)
            w, h, channels = dims
            data = np.frombuffer(handle.read(), dtype="<f4")
        if len(data) != w * h * channels:
            return None
        return data.reshape((h, w, channels))[:, :, 0]
    except Exception:
        return None


def colmap_value(obj, name):
    value = getattr(obj, name)
    return value() if callable(value) else value


def find_undistorted_sparse_model(workspace: Path) -> Path:
    candidates = [workspace / "sparse", workspace / "sparse" / "0"]
    candidates.extend(sorted(workspace.glob("sparse/*")))
    for candidate in candidates:
        if (candidate / "cameras.bin").is_file() and (candidate / "images.bin").is_file():
            return candidate
    found = sorted(workspace.glob("**/cameras.bin"))
    if found:
        raise RuntimeError(f"undistorted sparse model is incomplete near {found[0].parent}")
    raise FileNotFoundError(f"no undistorted COLMAP sparse model beneath {workspace}")


def texture_mesh(fused: Path, nav_path: Path, out_path: Path) -> dict:
    import cv2
    import open3d as o3d
    import pycolmap

    t0 = time.time()
    pcd = o3d.io.read_point_cloud(str(fused))
    if len(pcd.points) < 100_000:
        raise RuntimeError(f"dense cloud unexpectedly small ({len(pcd.points)} points)")
    if not pcd.has_normals():
        log("estimating oriented MVS point normals")
        pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=0.09, max_nn=48))
        pcd.orient_normals_consistent_tangent_plane(24)
    log(f"Poisson surface from {len(pcd.points):,} dense points")
    mesh, density = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
        pcd, depth=11, scale=1.08, linear_fit=True)
    density = np.asarray(density)
    mesh.remove_vertices_by_mask(density < np.quantile(density, 0.035))
    mesh.remove_degenerate_triangles()
    mesh.remove_duplicated_triangles()
    mesh.remove_duplicated_vertices()
    mesh.remove_unreferenced_vertices()
    if len(mesh.triangles) > TARGET_FACES:
        mesh = mesh.simplify_quadric_decimation(TARGET_FACES)
    mesh.compute_vertex_normals()
    mesh.compute_triangle_normals()
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.triangles, dtype=np.int64)
    face_normals = np.asarray(mesh.triangle_normals, dtype=np.float64)
    if len(faces) < 100_000:
        raise RuntimeError(f"Poisson mesh too small ({len(faces)} triangles)")

    # Open3D's MVS cloud carries the input-view color and COLMAP's dense normals.
    # A simple cloud is also used by the regular nav/package stages.
    colors = np.asarray(pcd.colors)
    if colors.size:
        rgb = np.clip(np.round(colors * 255), 0, 255).astype(np.uint8)
    else:
        rgb = np.full((len(pcd.points), 3), 180, np.uint8)
    raw_to_metric = float(json.loads((RUN / "depth" / "raw_scale.json")
                                     .read_text(encoding="utf-8"))["scale_m_per_unit"])
    poses_path = RUN / "sfm" / "poses.json"
    poses = json.loads(poses_path.read_text(encoding="utf-8"))
    for frame in poses["frames"]:
        w2c = np.asarray(frame["w2c"], dtype=np.float64)
        w2c[:3, 3] *= raw_to_metric
        frame["w2c"] = w2c.tolist()
    poses["note"] = f"COLMAP translations metricized by {raw_to_metric:.8f} m/unit"
    poses_path.write_text(json.dumps(poses), encoding="utf-8")
    work_cloud = RUN / "mvs-cloud.ply"
    write_simple_ply(work_cloud, np.asarray(pcd.points, np.float32) * raw_to_metric, rgb)

    # Recompute the costmap from the dense MVS cloud: unlike the sparse map it
    # contains floor support between capture positions and around furnishings.
    sys.path.insert(0, str(CODE))
    from namma import geometry, package
    nav_path = RUN / "nav" / "nav.json"
    has_fallback_nav = nav_path.is_file()
    try:
        geometry_report = geometry.run_geometry(RUN, cloud_path=work_cloud)
    except SystemExit as exc:
        if not has_fallback_nav:
            raise
        log(f"MVS cloud could not support a new floor fit ({exc}); retaining capture navigation")
        previous_report_path = RUN / "nav" / "nav_report.json"
        previous_report = (json.loads(previous_report_path.read_text(encoding="utf-8"))
                           if previous_report_path.exists() else {})
        geometry_report = geometry.NavReport(
            status="fallback",
            walkable_area_m2=float(previous_report.get("walkable_area_m2", 0.0)),
            warnings=[f"retained capture navigation: {exc}"],
        )
        previous_report_path.write_text(json.dumps(geometry_report.to_dict(), indent=2),
                                        encoding="utf-8")
    nav = json.loads((RUN / "nav" / "nav.json").read_text(encoding="utf-8"))

    # Load the undistorted MVS reconstruction. The same sparse camera poses are
    # used by PatchMatch and by the face-to-source-image UV projection.
    sparse_model = find_undistorted_sparse_model(MVS)
    log(f"loading undistorted camera model from {sparse_model}")
    rec = pycolmap.Reconstruction(str(sparse_model))
    blur_by_name = {}
    frames_meta_path = RUN / "frames_meta.json"
    if frames_meta_path.exists():
        frames_meta = json.loads(frames_meta_path.read_text(encoding="utf-8"))
        blur_by_name = {frame["name"]: float(frame.get("rank_blur", frame.get("blur", 1.0)))
                        for frame in frames_meta.get("frames", [])}
    blur_values = np.asarray(list(blur_by_name.values()), dtype=np.float64)
    blur_median = float(np.median(blur_values)) if len(blur_values) else 1.0
    image_records = []
    registered_ids = rec.reg_image_ids
    registered_ids = registered_ids() if callable(registered_ids) else registered_ids
    for image_id in registered_ids:
        image = rec.image(image_id)
        camera = rec.camera(colmap_value(image, "camera_id"))
        rigid = colmap_value(image, "cam_from_world")
        rotation = np.asarray(colmap_value(colmap_value(rigid, "rotation"), "matrix"), dtype=np.float64)
        translation = np.asarray(colmap_value(rigid, "translation"), dtype=np.float64)
        params = np.asarray(colmap_value(camera, "params"), dtype=np.float64)
        if "PINHOLE" in str(colmap_value(camera, "model")):
            fx, fy, cx, cy = params[:4]
        else:
            fx, cx, cy = params[:3]
            fy = fx
        image_records.append({
            "name": image.name, "R": rotation, "t": translation,
            "fx": float(fx), "fy": float(fy), "cx": float(cx), "cy": float(cy),
            "w": int(colmap_value(camera, "width")),
            "h": int(colmap_value(camera, "height")),
            "center": -rotation.T @ translation,
            "sharpness": float(np.clip(np.sqrt(blur_by_name.get(image.name, blur_median)
                                         / max(blur_median, 1.0)), 0.72, 1.28)),
        })
    image_records.sort(key=lambda item: item["name"])
    if len(image_records) < 20:
        raise RuntimeError(f"only {len(image_records)} undistorted cameras available")

    # Sample even coverage along the whole walk. COLMAP still uses every
    # registered frame for MVS; only the texture atlas is capped at 64 views.
    picked = np.linspace(0, len(image_records) - 1,
                         min(MAX_TEXTURE_VIEWS, len(image_records))).round().astype(int)
    cams = [image_records[i] for i in np.unique(picked)]
    texture_dir = MVS / "images"
    atlas = np.zeros((ATLAS_ROWS * TEX_H, ATLAS_COLS * TEX_W, 3), dtype=np.uint8)
    for slot, cam in enumerate(cams):
        image_path = texture_dir / cam["name"]
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            raise FileNotFoundError(f"undistorted source image missing: {image_path}")
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        tile = cv2.resize(frame, (TEX_W, TEX_H), interpolation=cv2.INTER_AREA)
        row, col = divmod(slot, ATLAS_COLS)
        atlas[row * TEX_H:(row + 1) * TEX_H,
              col * TEX_W:(col + 1) * TEX_W] = tile

    centroids = vertices[faces].mean(axis=1)
    best_score = np.zeros(len(faces), dtype=np.float32)
    best_slot = np.full(len(faces), -1, dtype=np.int16)
    for slot, cam in enumerate(cams):
        cam_pts = centroids @ cam["R"].T + cam["t"]
        z = cam_pts[:, 2]
        u = cam["fx"] * cam_pts[:, 0] / np.maximum(z, 1e-6) + cam["cx"]
        v = cam["fy"] * cam_pts[:, 1] / np.maximum(z, 1e-6) + cam["cy"]
        valid = ((z > 0.15) & (u >= 1) & (v >= 1)
                 & (u < cam["w"] - 1) & (v < cam["h"] - 1))
        depth_dir = MVS / "stereo" / "depth_maps"
        depth_path = depth_dir / f"{cam['name']}.geometric.bin"
        if not depth_path.exists():
            depth_path = depth_dir / f"{cam['name']}.photometric.bin"
        depth = read_depth_map(depth_path)
        if depth is not None:
            dh, dw = depth.shape
            px = np.clip(np.round(u * dw / cam["w"]).astype(np.int32), 0, dw - 1)
            py = np.clip(np.round(v * dh / cam["h"]).astype(np.int32), 0, dh - 1)
            observed = depth[py, px]
            tolerance = np.maximum(0.08, 0.045 * z)
            valid &= np.isfinite(observed) & (observed > 0) & (np.abs(observed - z) < tolerance)
        delta = cam["center"][None, :] - centroids
        distance = np.maximum(np.linalg.norm(delta, axis=1), 1e-3)
        cos = np.abs(np.einsum("ij,ij->i", face_normals, delta / distance[:, None]))
        score = (cos ** 3 * cam["sharpness"] / (distance ** 1.4)).astype(np.float32)
        valid &= cos > 0.16
        score[~valid] = 0.0
        improve = score > best_score
        best_score[improve] = score[improve]
        best_slot[improve] = slot
        if (slot + 1) % 16 == 0:
            log(f"texture visibility {slot + 1}/{len(cams)}")

    assigned = best_slot >= 0
    if float(assigned.mean()) < 0.35:
        raise RuntimeError(f"only {assigned.mean():.1%} of mesh faces project into a captured view")
    best_slot[~assigned] = 0

    # Split only at image seams: adjacent faces using the same camera share
    # vertices, keeping the GLB small while preserving per-face UV coordinates.
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
        view_points = vertices[vertex_ids[mask]] @ cam["R"].T + cam["t"]
        z = np.maximum(view_points[:, 2], 1e-5)
        px = cam["fx"] * view_points[:, 0] / z + cam["cx"]
        py = cam["fy"] * view_points[:, 1] / z + cam["cy"]
        local_u = np.clip(px / cam["w"], 0, 1)
        local_v = np.clip(py / cam["h"], 0, 1)
        row, col = divmod(slot, ATLAS_COLS)
        uv[mask, 0] = (col * TEX_W + pad + local_u * (TEX_W - 2 * pad)) / (ATLAS_COLS * TEX_W)
        uv[mask, 1] = (row * TEX_H + pad + local_v * (TEX_H - 2 * pad)) / (ATLAS_ROWS * TEX_H)

    # Place the geometry in the navigation frame (metres, z up), then the web
    # viewer maps that frame to Three.js Y-up coordinates.
    align = nav["align"]
    R_nav = np.asarray(align["R_row_major"], dtype=np.float64)
    origin = np.asarray(align["origin"], dtype=np.float64)
    metric_scale = float(align["scale_m_per_unit"])
    metric_vertices = vertices[vertex_ids] * raw_to_metric
    nav_positions = ((metric_vertices - origin) @ R_nav) * metric_scale
    nav_normals = np.asarray(mesh.vertex_normals, dtype=np.float64)[vertex_ids] @ R_nav
    nav_normals /= np.maximum(np.linalg.norm(nav_normals, axis=1, keepdims=True), 1e-9)
    atlas_path = SCRATCH / "atlas.jpg"
    cv2.imwrite(str(atlas_path), cv2.cvtColor(atlas, cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, 93])
    write_glb(out_path, nav_positions.astype(np.float32), nav_normals.astype(np.float32),
              uv, inverse.reshape(-1, 3), atlas_path.read_bytes())

    # Package the dense fallback, new mesh, recalculated navigation, and the
    # existing splat as one interchangeable public sample bundle.
    shutil.copy2(work_cloud, RUN / "sfm" / "sparse.ply")
    package.run_package(RUN)
    shutil.copy2(out_path, RUN / "web" / "mesh.glb")
    meta_path = RUN / "web" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["mesh"] = {"present": True, "format": "glb", "source": "COLMAP MVS"}
    source_meta_path = SCRATCH / "source_meta.json"
    if source_meta_path.exists():
        source_meta = json.loads(source_meta_path.read_text(encoding="utf-8"))
        if source_meta.get("splat"):
            meta["splat"] = source_meta["splat"]
        if source_meta.get("qa_overall"):
            meta["qa_overall"] = source_meta["qa_overall"]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    for name in ("nav.json", "occupancy.png", "nav_report.json"):
        shutil.copy2(RUN / "nav" / name, OUT / name)
    for name in ("cloud.ply", "splat.splat", "meta.json", "mesh.glb"):
        shutil.copy2(RUN / "web" / name, OUT / name)

    report = {
        "method": "COLMAP PatchMatch MVS + Poisson surface + best-visible-view texture projection",
        "dense_points": len(pcd.points), "mesh_faces": len(faces),
        "mesh_vertices_after_texture_seams": len(unique_pairs),
        "texture_views": len(cams), "texture_atlas": [ATLAS_COLS * TEX_W, ATLAS_ROWS * TEX_H],
        "textured_face_fraction": round(float(assigned.mean()), 4),
        "mesh_bytes": out_path.stat().st_size,
        "walkable_area_m2": geometry_report.walkable_area_m2,
        "navigation_status": geometry_report.status,
        "geometry_seconds": round(time.time() - t0, 1),
    }
    (OUT / "mesh_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if PREFLIGHT_ONLY:
        ensure_dependencies()
        cli = ensure_colmap_cli()
        report = {"status": "ok", "colmap_cli": cli}
        (OUT / "preflight_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        log(f"preflight passed: {cli}")
        return

    started = time.time()
    errors: dict[str, str] = {}
    report: dict = {"status": "failed"}
    try:
        capture = stage_inputs()
        ensure_dependencies()
        colmap_cli = ensure_colmap_cli()
        sparse_bin = SCRATCH / "sparse_bin"
        write_sparse_binary(RUN / "sfm" / "sparse_txt", sparse_bin)
        fused = run_mvs(sparse_bin, colmap_cli)
        report = texture_mesh(fused, RUN / "nav" / "nav.json", OUT / "mesh.glb")
        report.update({"status": "ok", "capture": capture.name,
                       "elapsed_seconds": round(time.time() - started, 1)})
    except BaseException:
        errors["mesh"] = traceback.format_exc()
        log("MESH ERROR:\n" + errors["mesh"])
    report["errors"] = errors
    report["outputs"] = sorted(p.name for p in OUT.iterdir())
    (OUT / "mesh_run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(f"done: {report.get('status')} {report.get('outputs')}")


if __name__ == "__main__":
    main()
