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

from . import imu, pois

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
    nav_doc = _read_json(capture_dir / "nav" / "nav.json")

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

    # 4 -- R2 POI dataset (authored tags staged beside nav.json)
    poi_path = capture_dir / "nav" / "pois.json"
    if poi_path.exists():
        try:
            poi_doc, warnings = pois.read_poi_file(
                poi_path, nav=nav_doc, capture=capture_dir.name)
            categories = sorted({poi["category"] for poi in poi_doc["pois"]})
            checks.append(Check(
                "poi_dataset", PASS if not warnings else WARN,
                f"{len(poi_doc['pois'])} POIs across {len(categories)} categories",
                "; ".join(warnings) if warnings else "indexed by the viewer at load time",
                value=len(poi_doc["pois"])))
        except pois.PoiValidationError as exc:
            checks.append(Check(
                "poi_dataset", FAIL, str(exc),
                "fix nav/pois.json; package refuses an invalid POI file"))
    else:
        checks.append(Check(
            "poi_dataset", SKIP, "nav/pois.json not found",
            "tag POIs in the viewer and export them to nav/pois.json"))

    # 5 -- IMU / EIS checks (Sensor Logger + capture_info.json)
    imu_summary = imu.load_imu(capture_dir)
    if imu_summary and imu_summary.eis_enabled is not None:
        eis = imu_summary.eis_enabled
        checks.append(Check(
            "video_stabilization", FAIL if eis else PASS,
            "EIS ON (non-rigid warps break SfM)" if eis else "EIS OFF",
            "disable video stabilization and recapture" if eis else "rigid projection verified"))
    else:
        checks.append(Check(
            "video_stabilization", SKIP, "capture_info.json EIS flag not present"))

    if imu_summary and imu_summary.motion_blur_px_p90 is not None:
        blur_px = imu_summary.motion_blur_px_p90
        ok = PASS if blur_px <= 4.0 else WARN if blur_px <= 8.0 else FAIL
        checks.append(Check(
            "imu_motion_blur", ok,
            f"p90 gyro blur {blur_px:.2f} px (threshold 4.0 px)",
            "walk slower with deliberate turns (~30 deg/s) in brighter light",
            value=blur_px))
    else:
        checks.append(Check(
            "imu_motion_blur", SKIP, "sensors.csv / Gyroscope.csv not found"))

    # 6 -- R3 QR anchors (nav/anchors.json)
    anchors_path = capture_dir / "nav" / "anchors.json"
    if anchors_path.exists():
        anchors_doc = _read_json(anchors_path)
        items = (anchors_doc or {}).get("anchors")
        if isinstance(items, list) and len(items) > 0:
            checks.append(Check(
                "qr_anchors", PASS,
                f"{len(items)} QR anchor(s) localized",
                "staged for AR relocalization",
                value=float(len(items))))
        else:
            checks.append(Check(
                "qr_anchors", WARN,
                "anchors.json has 0 localized QR markers",
                "show each A4 QR marker for >= 3 s per SOP section 3.4"))
    else:
        checks.append(Check(
            "qr_anchors", SKIP, "nav/anchors.json not found",
            "run `namma anchors` when QR markers are recorded for R3 AR"))

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
