"""Activate a reconstructed self-captured twin as the deployed Topoloka viewer scene.

After reconstructing your own smartphone walkthrough video on Kaggle and
assembling `test/<capture>/` via `tools/make_sample.py`, run:

    python tools/activate_capture.py <capture> --label "Home Multi-Room Twin"

What it does:
  1. Verifies required web artifacts (`nav.json`, `meta.json`, `cloud.ply`,
     and `splat.ksplat` or `splat.splat`) exist under `test/<capture>/web/`.
  2. Copies `test/<capture>/web/*` into `web/public/artifacts/<capture>/`.
  3. Updates `web/src/main.ts` (`DEFAULT_CAPTURE` & `AVAILABLE_CAPTURES`),
     `web/index.html` (`#capture-select`), and `.github/workflows/web-pages.yml`
     so GitHub Pages deploys ONLY your self-captured space (no third-party or
     public datasets).
  4. Prints the verified metrics summary from the capture's JSON reports so you
     can paste exact numbers into `docs/abstract.md` and `capture/SOP.md`.

Pass `--dry-run` to inspect changes without modifying files.
Pass `--purge-standin` to also delete `test/metro_v1/` and its staged copy.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def validate_bundle(capture_dir: Path) -> dict:
    web_dir = capture_dir / "web"
    if not web_dir.is_dir():
        raise SystemExit(f"Missing web bundle directory: {web_dir}")

    required = ["nav.json", "meta.json", "cloud.ply"]
    missing = [f for f in required if not (web_dir / f).exists()]
    if missing:
        raise SystemExit(f"Missing required web artifact(s) in {web_dir}: {missing}")

    has_splat = (web_dir / "splat.ksplat").exists() or (web_dir / "splat.splat").exists()
    if not has_splat:
        raise SystemExit(f"Missing splat.ksplat or splat.splat in {web_dir}")

    meta = _read_json(web_dir / "meta.json") or {}
    return meta


def print_metrics(capture: str, capture_dir: Path, meta: dict) -> None:
    sfm = _read_json(capture_dir / "sfm" / "sfm_report.json") or {}
    depth = _read_json(capture_dir / "depth" / "depth_report.json") or {}
    nav = _read_json(capture_dir / "nav" / "nav_report.json") or {}
    qa = _read_json(capture_dir / "capture_qa.json") or {}
    pois_doc = _read_json(capture_dir / "web" / "pois.json") or {}

    splat = meta.get("splat") or {}
    splat_mb = (splat.get("bytes") or 0) / 1e6
    gaussians = splat.get("gaussians") or 0
    poi_count = len(pois_doc.get("pois") or [])

    print("\n=== Verified Capture Metrics (paste into docs/abstract.md & capture/SOP.md) ===")
    print(f"Capture ID:        {capture}")
    print(f"QA Overall:        {qa.get('overall', meta.get('qa_overall', 'unknown'))}")
    if sfm:
        print(
            f"SfM Registration:  {sfm.get('frames_registered')}/{sfm.get('frames_in')} "
            f"({sfm.get('registered_fraction', 0) * 100:.1f}%) · "
            f"median reproj {sfm.get('median_reprojection_error_px')} px"
        )
    if depth:
        print(
            f"Depth Model:       {depth.get('model')} · "
            f"scale {depth.get('scale_m_per_unit')} m/unit "
            f"(MAD {depth.get('scale_mad_rel', 0) * 100:.2f}%)"
        )
    if nav:
        print(f"Walkable Area:     {nav.get('walkable_area_m2')} m^2")
    print(
        f"Web Splat:         {splat.get('file')} ({splat_mb:.2f} MB, "
        f"{gaussians:,} gaussians)"
    )
    print(f"Authored POIs:     {poi_count}")
    print("===============================================================================\n")


def update_files(capture: str, label: str, dry_run: bool) -> None:
    main_ts = ROOT / "web" / "src" / "main.ts"
    index_html = ROOT / "web" / "index.html"
    workflow = ROOT / ".github" / "workflows" / "web-pages.yml"

    main_src = main_ts.read_text(encoding="utf-8")
    main_new = re.sub(
        r"const DEFAULT_CAPTURE = '[^']+';",
        f"const DEFAULT_CAPTURE = '{capture}';",
        main_src,
        count=1,
    )
    main_new = re.sub(
        r"const AVAILABLE_CAPTURES = new Set\(\[[^\]]*\]\);",
        f"const AVAILABLE_CAPTURES = new Set(['{capture}']);",
        main_new,
        count=1,
    )

    html_src = index_html.read_text(encoding="utf-8")
    escaped_label = html.escape(label)
    html_new = re.sub(
        r'(<select id="capture-select"[^>]*>\s*)(?:<option[^>]*>.*?</option>\s*)+(\s*</select>)',
        rf'\1<option value="{capture}" selected>{escaped_label}</option>\n          \2',
        html_src,
        flags=re.DOTALL,
        count=1,
    )

    wf_src = workflow.read_text(encoding="utf-8")
    wf_new = re.sub(
        r"for name in [^\n;]+; do",
        f"for name in {capture}; do",
        wf_src,
        count=1,
    )

    for path, old, new in (
        (main_ts, main_src, main_new),
        (index_html, html_src, html_new),
        (workflow, wf_src, wf_new),
    ):
        if old == new:
            print(f"[unchanged] {path.relative_to(ROOT)}")
        elif dry_run:
            print(f"[dry-run] would update {path.relative_to(ROOT)}")
        else:
            path.write_text(new, encoding="utf-8")
            print(f"[updated]   {path.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture", help="Capture folder name under test/ (e.g. home_v1)")
    ap.add_argument(
        "--label",
        default="",
        help="Display label in viewer dropdown (default: '<capture> — POIs & nav')",
    )
    ap.add_argument("--dry-run", action="store_true", help="Validate and preview only")
    ap.add_argument(
        "--purge-standin",
        action="store_true",
        help="Also remove temporary stand-in test/metro_v1 and web/public/artifacts/metro_v1",
    )
    args = ap.parse_args()

    if not re.fullmatch(r"[a-zA-Z0-9_-]+", args.capture):
        raise SystemExit(f"Invalid capture name '{args.capture}': use [a-zA-Z0-9_-]+")

    capture_dir = ROOT / "test" / args.capture
    meta = validate_bundle(capture_dir)
    label = args.label or f"{args.capture} — POIs & nav"

    staged_dst = ROOT / "web" / "public" / "artifacts" / args.capture
    if args.dry_run:
        print(f"[dry-run] would stage {capture_dir / 'web'} -> {staged_dst}")
    else:
        if staged_dst.exists():
            shutil.rmtree(staged_dst)
        shutil.copytree(capture_dir / "web", staged_dst)
        print(f"[staged]    {staged_dst.relative_to(ROOT)}")

    update_files(args.capture, label, dry_run=args.dry_run)

    if args.purge_standin and args.capture != "metro_v1":
        for stale in (ROOT / "test" / "metro_v1", ROOT / "web" / "public" / "artifacts" / "metro_v1"):
            if stale.exists():
                if args.dry_run:
                    print(f"[dry-run] would remove stand-in {stale.relative_to(ROOT)}")
                else:
                    shutil.rmtree(stale)
                    print(f"[removed]   {stale.relative_to(ROOT)}")

    print_metrics(args.capture, capture_dir, meta)
    if not args.dry_run:
        print("Next steps:")
        print("  1. cd web && npm run typecheck && npm test && npm run build")
        print("  2. Test locally: npm run dev  (tag POIs with E -> Export pois.json -> namma pois)")
        print("  3. Update docs/abstract.md & capture/SOP.md with the metrics above, then run:")
        print("     powershell -File tools\\build_pdf.ps1")


if __name__ == "__main__":
    sys.exit(main())
