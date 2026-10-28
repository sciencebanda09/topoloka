"""Kaggle kernel: Namma pipeline stage-runs on free Kaggle compute.

v0 scope: phone video -> picked frames -> sparse reconstruction (SfM).
Outputs (fetched locally with kaggle/tools/fetch_output.ps1):
    out/frames_meta.json, out/sfm_report.json, out/poses.json,
    out/transforms.json, out/sparse.ply, out/sparse_txt.zip, out/summary.txt

Later versions add: depth, 3DGS splat, geometry/costmap, POIs.
"""

import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
from pathlib import Path

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")          # only out/ is published as kernel output
SCRATCH = Path("/tmp/namma")            # code/ and runs/ stay OFF the output list
OUT = WORK / "out"
CODE = SCRATCH / "code"
RUN = SCRATCH / "runs" / "capture_v1"
TARGET_RATE = os.environ.get("NM_TARGET_RATE", "2.5")
MAX_WIDTH = os.environ.get("NM_MAX_W", "1600")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def stage_code() -> None:
    """Extract our pipeline source (code.tar preferred; loose package fallback)."""
    tars = sorted(INPUT.glob("**/code.tar"))
    if tars:
        CODE.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tars[0]) as t:
            t.extractall(CODE)
    else:
        # fallback: a dataset that ships the pipeline source as loose files
        cli = next(INPUT.glob("**/namma/cli.py"), None)
        if not cli:
            listing = sorted(str(p.relative_to(INPUT)) for p in INPUT.iterdir())
            raise SystemExit(f"no code.tar and no namma/cli.py under /kaggle/input "
                             f"(dataset namma-code missing? mounts: {listing})")
        shutil.copytree(cli.parents[1], CODE, dirs_exist_ok=True)
    log(f"code: {sorted(p.name for p in CODE.iterdir())}")


def ensure_pycolmap() -> str:
    try:
        import pycolmap
        return pycolmap.__version__
    except ImportError:
        log("pycolmap missing; pip install")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pycolmap==4.2.1"],
                       check=True)
        import pycolmap
        return pycolmap.__version__


# Phone cameras do not agree on a container: Android usually writes .mp4,
# iPhones write .mov, and browser MediaRecorder can write .webm. OpenCV/ffmpeg
# decodes all of them; the old .mp4-only glob silently rejected real phone
# footage.
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


def find_video() -> Path:
    vids = sorted(p for p in INPUT.glob("**/*")
                  if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
    if not vids:
        raise SystemExit("no phone video under /kaggle/input "
                         f"(looked for {', '.join(sorted(VIDEO_EXTS))})")
    for v in vids:
        log(f"input video: {v} ({v.stat().st_size / 1e6:.1f} MB)")
    return sorted(vids, key=lambda p: p.stat().st_size, reverse=True)[0]


def run_stage(args: list[str]) -> None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    log(f"run: {' '.join(args)}")
    subprocess.run([sys.executable, "-m", "namma.cli", *args], cwd=CODE, env=env, check=True)


def collect() -> None:
    """Copy the small, durable outputs to /kaggle/working/out."""
    OUT.mkdir(parents=True, exist_ok=True)
    for rel in ["frames_meta.json", "sfm/sfm_report.json", "sfm/poses.json",
                "sfm/transforms.json", "sfm/sparse.ply",
                "nav/nav.json", "nav/nav_report.json", "nav/occupancy.png",
                "capture_qa.json", "capture_qa.md"]:
        src = RUN / rel
        if src.exists():
            shutil.copy2(src, OUT / Path(rel).name)
    web = RUN / "web"
    if web.is_dir():
        dst = OUT / "web"
        dst.mkdir(exist_ok=True)
        for f in sorted(web.iterdir()):
            if f.is_file():
                shutil.copy2(f, dst / f.name)
    txt = RUN / "sfm" / "sparse_txt"
    if txt.is_dir():
        shutil.make_archive(str(OUT / "sparse_txt"), "zip", root_dir=txt)
    frames = RUN / "frames"
    if frames.is_dir():
        shutil.make_archive(str(OUT / "frames"), "zip", root_dir=frames)
    log(f"out: {sorted(p.name for p in OUT.iterdir())}")


def summary(pycolmap_version: str, video: Path, t_seconds: float, error: str | None) -> None:
    lines = [
        "namma pipeline kernel v2",
        f"python      {sys.version.split()[0]}",
        f"pycolmap    {pycolmap_version}",
        f"target_rate {TARGET_RATE}",
        f"max_width   {MAX_WIDTH}",
        f"video       {video.name} ({video.stat().st_size / 1e6:.1f} MB)"
        if video.exists() else "video       n/a",
        f"elapsed_s   {t_seconds:.1f}",
        f"status      {'error' if error else 'ok'}",
    ]
    if error:
        lines.append(error)
    (OUT / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    t0 = time.time()
    video = Path("/kaggle/input/__none__.mp4")
    pycolmap_version = ""
    error = None
    try:
        stage_code()
        pycolmap_version = ensure_pycolmap()
        log(f"pycolmap {pycolmap_version}")
        video = find_video()
        run_stage(["frames", str(video), str(RUN), "--target-rate", TARGET_RATE,
                   "--max-width", MAX_WIDTH])
        run_stage(["sfm", str(RUN)])
        run_stage(["geometry", str(RUN)])
        run_stage(["qa", str(RUN)])
        run_stage(["package", str(RUN)])
    except BaseException:  # SystemExit included -- the summary must never lie
        error = traceback.format_exc()
        log("ERROR:\n" + error)
    finally:
        try:
            collect()
        except Exception:
            log("collect failed:\n" + traceback.format_exc())
        summary(pycolmap_version, video, time.time() - t0, error)
        log("done")


if __name__ == "__main__":
    main()
