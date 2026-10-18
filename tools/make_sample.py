"""Assemble the committed R1 sample bundle (test/house_v1) from kernel outputs.

Takes the fetched outputs of the two Kaggle kernels (kaggle/out/namma_pipeline,
kaggle/out/namma_splat) and produces a small, redistributable capture:

    test/house_v1/
        README.md            auto-written summary (sizes, provenance, how-to)
        frames/              N evenly-spaced preview frames (subset)
        frames_meta.json
        sfm/                 poses.json, sfm_report.json, sparse.ply
        depth/               scale.json, depth_report.json
        nav/                 nav.json, nav_report.json, occupancy.png
        capture_qa.json/.md
        web/                 nav.json, cloud.ply (decimated), splat.splat
                             (re-pruned), occupancy.png, meta.json

Usage (repo root, venv python):
    .venv\\Scripts\\python.exe tools\\make_sample.py
    .venv\\Scripts\\python.exe tools\\make_sample.py --frames 16 --max-gaussians 400000
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from namma.geometry import load_cloud  # noqa: E402
from namma.package import _write_ply  # noqa: E402
from namma.splat_convert import convert_splat  # noqa: E402

COPY_FROM_PIPELINE = [
    "frames_meta.json",
    "sfm/poses.json",
    "sfm/sfm_report.json",
    "sfm/sparse.ply",
    "nav/nav.json",
    "nav/nav_report.json",
    "nav/occupancy.png",
]
COPY_FROM_SPLAT = [
    "depth/scale.json",
    "depth/depth_report.json",
    "capture_qa.json",
    "capture_qa.md",
]


def copy_rel(src_root: Path, rel: str, dst_root: Path) -> bool:
    src = src_root / rel
    if not src.exists():
        print(f"  skip (missing): {rel}")
        return False
    dst = dst_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def pick_frames(frames_zip: Path, dst: Path, count: int) -> int:
    if not frames_zip.exists():
        print(f"  frames.zip missing ({frames_zip}) -- no preview frames copied")
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(frames_zip) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith(".jpg"))
        if not names:
            return 0
        idx = np.linspace(0, len(names) - 1, min(count, len(names))).round().astype(int)
        picked = [names[i] for i in sorted(set(idx.tolist()))]
        for n in picked:
            with z.open(n) as f, open(dst / Path(n).name, "wb") as out:
                shutil.copyfileobj(f, out)
    return len(picked)


def build_web(pipe_out: Path, splat_out: Path, dest: Path,
              max_points: int, max_gaussians: int) -> dict:
    web_src = splat_out / "web" if (splat_out / "web").is_dir() else pipe_out / "web"
    if not (web_src / "nav.json").exists():
        raise SystemExit(f"no web bundle found under {pipe_out} or {splat_out}")
    web = dest / "web"
    web.mkdir(parents=True, exist_ok=True)
    meta = {"web_source": str(web_src)}
    for name in ("nav.json", "occupancy.png", "meta.json"):
        if (web_src / name).exists():
            shutil.copy2(web_src / name, web / name)

    # cloud: decimate so the sample stays light
    xyz, rgb = load_cloud(web_src / "cloud.ply")
    if len(xyz) > max_points:
        rng = np.random.default_rng(7)
        keep = rng.choice(len(xyz), max_points, replace=False)
        keep.sort()
        xyz, rgb = xyz[keep], rgb[keep]
    _write_ply(web / "cloud.ply", xyz, rgb)
    meta["cloud_points"] = int(len(xyz))

    # splat: re-prune the raw export if we have it, else copy as-is
    raw_ply = splat_out / "splat.ply"
    if raw_ply.exists():
        # convert into the folder, then tidy the converter's report away so the
        # web/ bundle stays exactly the artifact set the viewer expects
        tmp_out = web / "_splat_tmp.splat"
        rep = convert_splat(raw_ply, tmp_out, max_gaussians=max_gaussians)
        tmp_out.replace(web / "splat.splat")
        (web / "splat_convert_report.json").unlink(missing_ok=True)
        meta["splat_gaussians"] = rep.gaussians_out
        meta["splat_from"] = "re-pruned raw export"
    elif (web_src / "splat.splat").exists():
        shutil.copy2(web_src / "splat.splat", web / "splat.splat")
        meta["splat_from"] = "copied from web bundle"
    return meta


def write_readme(dest: Path, meta: dict, n_frames: int) -> None:
    rows = []
    total = 0
    for p in sorted(dest.rglob("*")):
        if p.is_file():
            total += p.stat().st_size
    for sub in ("", "frames", "sfm", "depth", "nav", "web"):
        d = dest / sub if sub else dest
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.is_file():
                rows.append((str(p.relative_to(dest)).replace("\\", "/"), p.stat().st_size))
    table = "\n".join(f"| `{name}` | {size/1e6:.2f} MB |" for name, size in rows)
    readme = f"""# house_v1 -- sample capture

Everything here was produced by the Topoloka pipeline on Kaggle from a single
phone walk-through video (no LiDAR, no depth sensor). It is small enough to
live in git so anyone can inspect or serve it without a Kaggle account.

| file | size |
|---|---|
{table}

Total: **{total/1e6:.1f} MB** (cloud decimated to {meta.get('cloud_points', 0):,} points,
splat pruned to {meta.get('splat_gaussians', 'n/a')} gaussians; preview frames: {n_frames}).

## View it

```powershell
cd web
npm install
npm run dev
# then open http://localhost:5173/?capture=house_v1
```

(copy this folder to `web/public/artifacts/house_v1/` first, or use
`web/tools/sync_artifacts.ps1` when the kernel outputs are present.)

## What each piece proves

- `nav/nav.json` -- the metric navigation contract: 5 cm occupancy grid,
  floor outline, camera trajectory, and the `align` block that maps the SfM
  frame into metres (scale source + rotation + origin).
- `web/cloud.ply` -- the same geometry in the nav frame; open it in any
  viewer to check that "up" is up and a metre is a metre.
- `web/splat.splat` -- the Gaussian-splat twin exactly as the web viewer
  loads it (32 bytes per gaussian).
- `sfm/`, `depth/`, `capture_qa.*` -- the honest paper trail: every quality
  number the pipeline measured, including the ones that did not pass.
"""
    (dest / "README.md").write_text(readme, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pipe-out", type=Path, default=ROOT / "kaggle/out/namma_pipeline")
    ap.add_argument("--splat-out", type=Path, default=ROOT / "kaggle/out/namma_splat")
    ap.add_argument("--dest", type=Path, default=ROOT / "test/house_v1")
    ap.add_argument("--frames", type=int, default=14)
    ap.add_argument("--max-points", type=int, default=250_000)
    ap.add_argument("--max-gaussians", type=int, default=400_000)
    args = ap.parse_args()

    if (args.dest / "web" / "nav.json").exists():
        print(f"note: {args.dest} already contains a bundle; overwriting files")

    print(f"assembling sample -> {args.dest}")
    for root, rels in ((args.pipe_out, COPY_FROM_PIPELINE),
                       (args.splat_out, COPY_FROM_SPLAT)):
        for rel in rels:
            copy_rel(root, rel, args.dest)

    n = pick_frames(args.pipe_out / "frames.zip", args.dest / "frames", args.frames)
    print(f"  preview frames: {n}")

    meta = build_web(args.pipe_out, args.splat_out, args.dest,
                     args.max_points, args.max_gaussians)
    write_readme(args.dest, meta, n)

    total = sum(p.stat().st_size for p in args.dest.rglob("*") if p.is_file())
    print(f"done: {args.dest} ({total/1e6:.1f} MB)")
    splat = args.dest / "web" / "splat.splat"
    if splat.exists() and splat.stat().st_size > 40e6:
        print(f"WARNING: splat.splat is {splat.stat().st_size/1e6:.1f} MB -- "
              "too big for git; lower --max-gaussians")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
