"""Capture QA -- say what is wrong with a capture and what the pipeline does about it.

Philosophy (from the Syntheta robustness brief, applied to our SOP): QA is a
report, never a gate. Every FAIL states the compensation the pipeline already
applies, and the capture SOP's recapture rule consumes this report.

Reads whatever stages have produced under <capture>/ and emits:
    capture_qa.json     machine-readable checks
    capture_qa.md       the same, human-readable (for docs / demo video)

Any missing stage downgrades its checks to SKIP, so QA works at every point
of the pipeline.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    compensation: str = ""
    value: float | None = None


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def run_qa(capture_dir: Path) -> list[Check]:
    capture_dir = Path(capture_dir)
    checks: list[Check] = []

    frames_meta = _read_json(capture_dir / "frames_meta.json")
    sfm = _read_json(capture_dir / "sfm" / "sfm_report.json")
    nav = _read_json(capture_dir / "nav" / "nav_report.json")

    # 1 -- frame sharpness
    if frames_meta:
        p10 = frames_meta["stats"]["rank_blur_p10"]
        ok = PASS if p10 >= 100 else WARN if p10 >= 50 else FAIL
        checks.append(Check(
            "frame_sharpness", ok,
            f"p10 Laplacian {p10:.0f} (threshold 100)",
            "watch the demo video for soft zones; recapture the worst rooms in brighter light"))
        kept = frames_meta["stats"]["frames_kept"]
        checks.append(Check(
            "frame_count", PASS if kept >= 80 else WARN,
            f"{kept} frames kept (stride {frames_meta['stride']})",
            "fewer views -> weaker splat around fast-motion areas"))
    else:
        checks.append(Check("frame_sharpness", SKIP, "frames_meta.json not found"))

    # 2 -- registration (post-SfM)
    if sfm:
        frac = sfm.get("registered_fraction", 0.0)
        ok = PASS if frac >= 0.8 else WARN if frac >= 0.6 else FAIL
        checks.append(Check(
            "sfm_registered_fraction", ok,
            f"{sfm.get('frames_registered')}/{sfm.get('frames_in')} frames registered",
            "unregistered stretches get no texture; walk slower with more overlap there",
            value=frac))
        med = sfm.get("median_reprojection_error_px", 9.9)
        ok = PASS if med <= 1.0 else WARN if med <= 1.5 else FAIL
        checks.append(Check(
            "sfm_reprojection_error", ok,
            f"median {med}px (threshold 1.0)",
            "check video stabilization is OFF; EIS warps break rigid geometry",
            value=med))
    else:
        checks.append(Check("sfm_registered_fraction", SKIP, "sfm_report.json not found"))

    # 3 -- geometry / walkability
    if nav:
        pts = nav.get("outline_points", 0)
        checks.append(Check(
            "floor_outline", PASS if pts >= 3 else WARN,
            f"{nav.get('outline_points')} outline points, {nav.get('walkable_area_m2')} m2 walkable",
            "sparse cloud can under-draw the footprint; the depth stage densifies it"))
        warns = nav.get("warnings", [])
        checks.append(Check(
            "geometry_warnings", PASS if not warns else WARN,
            "; ".join(warns) if warns else "none",
            "see nav_report.json for details"))
    else:
        checks.append(Check("floor_outline", SKIP, "nav_report.json not found"))

    return checks


def write_qa(capture_dir: Path, checks: list[Check]) -> Path:
    capture_dir = Path(capture_dir)
    order = {PASS: 0, WARN: 1, FAIL: 2}
    overall = max(checks, key=lambda c: order.get(c.status, 0)).status
    doc = {
        "stage": "qa",
        "capture": capture_dir.name,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "overall": overall,
        "checks": [asdict(c) for c in checks],
    }
    out = capture_dir / "capture_qa.json"
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    lines = [f"# Capture QA -- {capture_dir.name}", "",
             f"**Overall: {overall}** ({doc['time']})", "",
             "| Check | Status | Detail | Compensation |",
             "|---|---|---|---|"]
    for c in checks:
        lines.append(f"| {c.name} | {c.status} | {c.detail} | {c.compensation} |")
    (capture_dir / "capture_qa.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[qa] overall {overall}")
    for c in checks:
        print(f"  {c.status:4} {c.name}: {c.detail}")
    return out
