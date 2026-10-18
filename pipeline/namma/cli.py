"""namma CLI -- one entry point for every pipeline stage.

Usage (from the pipeline/ directory):
    python -m namma.cli frames <video> runs/<capture> --stride 12
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import depth, frames, geometry, package, qa, sfm, splat_convert


def main() -> None:
    parser = argparse.ArgumentParser(prog="namma", description="Namma Space reconstruction pipeline")
    sub = parser.add_subparsers(dest="stage", required=True)

    f = sub.add_parser("frames", help="extract picked frames from a phone video")
    f.add_argument("video", type=Path, help="input video file")
    f.add_argument("out_dir", type=Path, help="capture working dir (frames land in <out_dir>/frames)")
    f.add_argument("--stride", type=int, default=6, help="window size in source frames (default 6)")
    f.add_argument("--target-rate", type=float, default=None,
                   help="compute stride for this many kept frames per second (fps-aware)")
    f.add_argument("--max-width", type=int, default=0, help="downscale kept frames to this width (0 = native)")
    f.add_argument("--max-seconds", type=float, default=None, help="stop after this many seconds")
    f.add_argument("--start", type=float, default=0.0, help="skip this many seconds at the start")
    f.add_argument("--jpeg-quality", type=int, default=95)

    s = sub.add_parser("sfm", help="sparse reconstruction (structure from motion)")
    s.add_argument("capture_dir", type=Path, help="capture working dir (must contain frames/)")
    s.add_argument("--matcher", choices=["auto", "exhaustive", "sequential"], default="auto")
    s.add_argument("--exhaustive-max", type=int, default=sfm.EXHAUSTIVE_MAX_IMAGES)

    g = sub.add_parser("geometry", help="floor plane, gravity align, walkable costmap")
    g.add_argument("capture_dir", type=Path, help="capture working dir (must contain sfm/)")
    g.add_argument("--cloud", type=Path, default=None,
                   help="point cloud (.ply/.npz); default: sfm/sparse.ply")

    sc = sub.add_parser("splat-convert", help="3DGS .ply -> web .splat")
    sc.add_argument("ply", type=Path, help="input gaussian PLY")
    sc.add_argument("out", type=Path, help="output .splat file")
    sc.add_argument("--max-gaussians", type=int, default=0,
                    help="prune to this many gaussians (0 = keep all above alpha floor)")

    q = sub.add_parser("qa", help="capture QA report (never blocks, always reports)")
    q.add_argument("capture_dir", type=Path, help="capture working dir")

    d = sub.add_parser("depth", help="metric depth fusion -> dense map.npz (GPU recommended)")
    d.add_argument("capture_dir", type=Path, help="capture working dir (must contain sfm/)")

    pk = sub.add_parser("package", help="assemble the web artifact bundle (<capture>/web/)")
    pk.add_argument("capture_dir", type=Path, help="capture working dir")

    args = parser.parse_args()

    if args.stage == "frames":
        frames.extract_frames(
            args.video,
            args.out_dir,
            stride=args.stride,
            target_rate_hz=args.target_rate,
            max_width=args.max_width,
            max_seconds=args.max_seconds,
            start_s=args.start,
            jpeg_quality=args.jpeg_quality,
        )
    elif args.stage == "sfm":
        sfm.run_sfm(
            args.capture_dir,
            matcher=args.matcher,
            exhaustive_max=args.exhaustive_max,
        )
    elif args.stage == "geometry":
        geometry.run_geometry(args.capture_dir, cloud_path=args.cloud)
    elif args.stage == "splat-convert":
        splat_convert.convert_splat(args.ply, args.out,
                                    max_gaussians=args.max_gaussians)
    elif args.stage == "qa":
        checks = qa.run_qa(args.capture_dir)
        qa.write_qa(args.capture_dir, checks)
    elif args.stage == "depth":
        depth.run_depth(args.capture_dir)
    elif args.stage == "package":
        package.run_package(args.capture_dir)


if __name__ == "__main__":
    main()
