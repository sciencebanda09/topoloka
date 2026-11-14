"""Stage 4c (R3 foundation) -- QR anchor detection and 3D localization.

Detects printed A4 QR anchors (per `capture/SOP.md` section 3.4) in registered
keyframes, estimates each marker's 3D pose via PnP in camera coordinates,
transforms it through `sfm/poses.json` and `nav/nav.json`'s `align` contract
into the metric navigation frame, and writes `<capture>/nav/anchors.json`.
"""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

DEFAULT_MARKER_SIZE_M = 0.15


@dataclass
class AnchorReport:
    stage: str = "anchors"
    status: str = "ok"
    marker_size_m: float = DEFAULT_MARKER_SIZE_M
    frames_scanned: int = 0
    detections: int = 0
    anchors_out: int = 0
    timing_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _camera_matrix(capture_dir: Path, width: int, height: int) -> np.ndarray:
    nav_path = capture_dir / "nav" / "nav.json"
    cam: dict[str, Any] = {}
    if nav_path.exists():
        cam = json.loads(nav_path.read_text(encoding="utf-8")).get("camera") or {}
    if not cam and (capture_dir / "transforms.json").exists():
        cam = json.loads((capture_dir / "transforms.json").read_text(encoding="utf-8"))
    fx = float(cam.get("fl_x") or max(width, height) * 0.85)
    fy = float(cam.get("fl_y") or fx)
    cx = float(cam.get("cx") or width / 2.0)
    cy = float(cam.get("cy") or height / 2.0)
    return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)


def _scene_to_nav(point_scene: np.ndarray, align: dict[str, Any]) -> np.ndarray:
    R = np.asarray(align["R_row_major"], dtype=np.float64)
    origin = np.asarray(align["origin"], dtype=np.float64)
    scale = float(align["scale_m_per_unit"])
    return ((point_scene - origin) @ R) * scale


def _scene_dir_to_nav(vec_scene: np.ndarray, align: dict[str, Any]) -> np.ndarray:
    R = np.asarray(align["R_row_major"], dtype=np.float64)
    out = vec_scene @ R
    norm = float(np.linalg.norm(out))
    return out / norm if norm > 1e-9 else np.array([0.0, 1.0, 0.0], dtype=np.float64)


def solve_qr_pose_nav(
    corners_px: np.ndarray,
    K: np.ndarray,
    w2c: np.ndarray,
    align: dict[str, Any],
    marker_size_m: float = DEFAULT_MARKER_SIZE_M,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Solve 3D marker center + outward wall normal in metric nav coordinates."""
    half = marker_size_m / 2.0
    obj_pts = np.array([
        [-half, -half, 0.0],
        [half, -half, 0.0],
        [half, half, 0.0],
        [-half, half, 0.0],
    ], dtype=np.float64)
    img_pts = np.asarray(corners_px, dtype=np.float64).reshape(4, 2)
    flag = cv2.SOLVEPNP_ITERATIVE
    ok, rvec, tvec = cv2.solvePnP(obj_pts, img_pts, K, None, flags=flag)
    if not ok or float(tvec[2, 0]) <= 0.05:
        return None
    R_m2c, _ = cv2.Rodrigues(rvec)
    # Marker local +Z (or -Z facing camera): ensure normal points toward the camera.
    normal_cam = R_m2c @ np.array([0.0, 0.0, 1.0], dtype=np.float64)
    pos_cam = tvec.reshape(3)
    if float(normal_cam @ pos_cam) > 0:
        normal_cam = -normal_cam

    scale = float(align["scale_m_per_unit"])
    if scale <= 0:
        return None
    # Convert metric camera-frame coordinates into raw SfM scene units, then nav.
    R_w2c = w2c[:3, :3]
    t_w2c = w2c[:3, 3]
    pos_scene = R_w2c.T @ ((pos_cam / scale) - t_w2c)
    normal_scene = R_w2c.T @ normal_cam

    pos_nav = _scene_to_nav(pos_scene, align)
    normal_nav = _scene_dir_to_nav(normal_scene, align)
    return pos_nav, normal_nav


def run_anchors(
    capture_dir: Path,
    *,
    marker_size_m: float = DEFAULT_MARKER_SIZE_M,
    max_frames: int = 300,
) -> dict[str, Any]:
    capture_dir = Path(capture_dir)
    nav_path = capture_dir / "nav" / "nav.json"
    poses_path = capture_dir / "sfm" / "poses.json"
    frames_dir = capture_dir / "frames"
    if not nav_path.exists():
        raise SystemExit(f"missing {nav_path} (run `geometry` first)")
    if not poses_path.exists():
        raise SystemExit(f"missing {poses_path} (run `sfm` first)")

    nav = json.loads(nav_path.read_text(encoding="utf-8"))
    align = nav.get("align")
    if not align:
        raise SystemExit("nav.json missing `align` block")
    poses = json.loads(poses_path.read_text(encoding="utf-8")).get("frames", [])
    if not poses:
        raise SystemExit("poses.json contains no frames")

    t0 = time.time()
    step = max(1, len(poses) // max(1, max_frames))
    sampled = poses[::step]
    detector = cv2.QRCodeDetector()
    grouped_pos: dict[str, list[np.ndarray]] = defaultdict(list)
    grouped_nrm: dict[str, list[np.ndarray]] = defaultdict(list)
    scanned = 0
    detections = 0
    K: np.ndarray | None = None

    for fr in sampled:
        img_path = frames_dir / fr["image"]
        if not img_path.exists():
            continue
        bgr = cv2.imread(str(img_path))
        if bgr is None:
            continue
        scanned += 1
        if K is None:
            h, w = bgr.shape[:2]
            K = _camera_matrix(capture_dir, w, h)
        w2c = np.asarray(fr["w2c"], dtype=np.float64)

        decoded_list: list[tuple[str, np.ndarray]] = []
        if hasattr(detector, "detectAndDecodeMulti"):
            ok, infos, points, _ = detector.detectAndDecodeMulti(bgr)
            if ok and points is not None:
                for text, pts in zip(infos, points):
                    if text and pts is not None and len(pts) == 4:
                        decoded_list.append((text.strip(), pts))
        if not decoded_list:
            text, pts, _ = detector.detectAndDecode(bgr)
            if text and pts is not None:
                pts_arr = np.asarray(pts).reshape(-1, 2)
                if len(pts_arr) == 4:
                    decoded_list.append((text.strip(), pts_arr))

        for qr_id, corners in decoded_list:
            solved = solve_qr_pose_nav(corners, K, w2c, align, marker_size_m=marker_size_m)
            if solved is None:
                continue
            pos_nav, nrm_nav = solved
            grouped_pos[qr_id].append(pos_nav)
            grouped_nrm[qr_id].append(nrm_nav)
            detections += 1

    anchors: list[dict[str, Any]] = []
    for qr_id in sorted(grouped_pos):
        pts = np.asarray(grouped_pos[qr_id], dtype=np.float64)
        nrms = np.asarray(grouped_nrm[qr_id], dtype=np.float64)
        pos = np.median(pts, axis=0)
        nrm = nrms.mean(axis=0)
        nrm_len = float(np.linalg.norm(nrm))
        nrm = nrm / nrm_len if nrm_len > 1e-9 else np.array([0.0, 1.0, 0.0])
        spread = float(np.max(np.linalg.norm(pts - pos, axis=1))) if len(pts) > 1 else 0.0
        # Viewer yaw facing away from the wall along the outward normal.
        yaw = math.atan2(-float(nrm[0]), float(nrm[1]))
        anchors.append({
            "id": qr_id,
            "x": round(float(pos[0]), 3),
            "y": round(float(pos[1]), 3),
            "z": round(float(pos[2]), 3),
            "normal": [round(float(v), 4) for v in nrm],
            "yaw": round(yaw, 4),
            "marker_size_m": round(float(marker_size_m), 4),
            "observations": int(len(pts)),
            "spread_m": round(spread, 3),
        })

    doc = {
        "version": 1,
        "capture": capture_dir.name,
        "marker_size_m": round(float(marker_size_m), 4),
        "anchors": anchors,
    }
    out_dir = capture_dir / "nav"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "anchors.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")

    report = AnchorReport(
        marker_size_m=round(float(marker_size_m), 4),
        frames_scanned=scanned,
        detections=detections,
        anchors_out=len(anchors),
        timing_seconds=round(time.time() - t0, 2),
    )
    (out_dir / "anchors_report.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8"
    )
    print(f"[anchors] scanned {scanned} frames, {detections} QR detections -> {len(anchors)} anchors")
    return doc
