"""IMU and capture-info loader for Sensor Logger bundles.

Supports:
- Combined `sensors.csv` (Sensor Logger / custom export with accel + gyro columns)
- Split `Accelerometer.csv` + `Gyroscope.csv` (standard Sensor Logger Android zip)
- Optional `capture_info.json` (exposure time, EIS flag)

Used by `geometry` (gravity prior) and `qa` (gyro-derived motion blur p90,
video stabilization gate per `capture/SOP.md`).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_EXPOSURE_S = 1.0 / 60.0
DEFAULT_FOCAL_PX = 1200.0


@dataclass
class ImuSummary:
    source: str
    accel_samples: int
    gyro_samples: int
    gravity_down_dir: list[float] | None
    gyro_rad_s_p90: float | None
    motion_blur_px_p90: float | None
    eis_enabled: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_csv_xyz(path: Path, prefixes: tuple[str, ...]) -> np.ndarray | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return None
        cols = {c.strip().lower(): c for c in reader.fieldnames}
        xyz_cols: tuple[str, str, str] | None = None
        for p in prefixes:
            if p:
                candidates = (
                    (f"{p}_x", f"{p}_y", f"{p}_z"),
                    (f"{p}x", f"{p}y", f"{p}z"),
                )
            else:
                candidates = (("x", "y", "z"),)
            for cx, cy, cz in candidates:
                if cx in cols and cy in cols and cz in cols:
                    xyz_cols = (cols[cx], cols[cy], cols[cz])
                    break
            if xyz_cols:
                break
        if not xyz_cols:
            return None
        rows: list[list[float]] = []
        for row in reader:
            try:
                vx = float(row[xyz_cols[0]])
                vy = float(row[xyz_cols[1]])
                vz = float(row[xyz_cols[2]])
            except (TypeError, ValueError):
                continue
            if np.isfinite(vx) and np.isfinite(vy) and np.isfinite(vz):
                rows.append([vx, vy, vz])
    return np.asarray(rows, dtype=np.float64) if rows else None


def load_capture_info(capture_dir: Path) -> dict[str, Any]:
    path = Path(capture_dir) / "capture_info.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def load_imu(
    capture_dir: Path,
    *,
    focal_px: float | None = None,
    exposure_s: float | None = None,
) -> ImuSummary | None:
    """Load IMU readings from `<capture_dir>` when Sensor Logger files exist."""
    capture_dir = Path(capture_dir)
    info = load_capture_info(capture_dir)

    sensors_csv = capture_dir / "sensors.csv"
    accel_csv = capture_dir / "Accelerometer.csv"
    gyro_csv = capture_dir / "Gyroscope.csv"

    accel: np.ndarray | None = None
    gyro: np.ndarray | None = None
    sources: list[str] = []

    if sensors_csv.exists():
        accel = _read_csv_xyz(sensors_csv, ("acc", "accel", "accelerometer"))
        gyro = _read_csv_xyz(sensors_csv, ("gyro", "gyroscope"))
        if accel is not None or gyro is not None:
            sources.append("sensors.csv")
    if accel is None and accel_csv.exists():
        accel = _read_csv_xyz(accel_csv, ("", "acc", "accel"))
        if accel is not None:
            sources.append("Accelerometer.csv")
    if gyro is None and gyro_csv.exists():
        gyro = _read_csv_xyz(gyro_csv, ("", "gyro"))
        if gyro is not None:
            sources.append("Gyroscope.csv")

    eis_val = info.get("eis_enabled")
    if eis_val is None and "video_stabilization" in info:
        eis_val = info.get("video_stabilization")
    eis_enabled = bool(eis_val) if isinstance(eis_val, bool) else None

    if accel is None and gyro is None and eis_enabled is None:
        return None

    gravity_dir: list[float] | None = None
    if accel is not None and len(accel) > 0:
        # Specific force points opposite gravity (+up when level); negate for down.
        mean_acc = -accel.mean(axis=0)
        norm = float(np.linalg.norm(mean_acc))
        if norm > 1e-6:
            gravity_dir = (mean_acc / norm).round(6).tolist()

    if exposure_s is None:
        raw_exp = info.get("exposure_s") or info.get("shutter_s")
        exposure_s = float(raw_exp) if isinstance(raw_exp, (int, float)) and raw_exp > 0 else DEFAULT_EXPOSURE_S
    if focal_px is None:
        tf_path = capture_dir / "transforms.json"
        if tf_path.exists():
            try:
                tf = json.loads(tf_path.read_text(encoding="utf-8"))
                if tf.get("fl_x"):
                    focal_px = float(tf["fl_x"])
            except (ValueError, TypeError):
                pass
    if focal_px is None or focal_px <= 0:
        focal_px = DEFAULT_FOCAL_PX

    gyro_p90: float | None = None
    blur_p90: float | None = None
    if gyro is not None and len(gyro) > 0:
        speeds = np.linalg.norm(gyro, axis=1)
        gyro_p90 = round(float(np.percentile(speeds, 90)), 4)
        blur_p90 = round(gyro_p90 * exposure_s * focal_px, 2)

    return ImuSummary(
        source="+".join(sources) if sources else "capture_info.json",
        accel_samples=0 if accel is None else int(len(accel)),
        gyro_samples=0 if gyro is None else int(len(gyro)),
        gravity_down_dir=gravity_dir,
        gyro_rad_s_p90=gyro_p90,
        motion_blur_px_p90=blur_p90,
        eis_enabled=eis_enabled,
    )
