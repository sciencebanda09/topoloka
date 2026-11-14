"""IMU and Sensor Logger parsing + QA gate tests."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from namma import imu, qa  # noqa: E402


def test_load_imu_parses_sensor_logger_and_qa_passes():
    with tempfile.TemporaryDirectory() as tmp:
        cap = Path(tmp)
        (cap / "capture_info.json").write_text(
            json.dumps({"eis_enabled": False, "exposure_s": 0.01}), encoding="utf-8"
        )
        # Level phone: specific force ~ +9.81 along +Y (or +Z) -> gravity down is opposite
        (cap / "sensors.csv").write_text(
            "seconds_elapsed,acc_x,acc_y,acc_z,gyro_x,gyro_y,gyro_z\n"
            "0.0,0.0,9.81,0.0,0.05,0.10,0.02\n"
            "0.1,0.0,9.80,0.0,0.04,0.12,0.01\n",
            encoding="utf-8",
        )
        summary = imu.load_imu(cap, focal_px=1000.0)
        assert summary is not None
        assert summary.accel_samples == 2
        assert summary.gyro_samples == 2
        assert summary.eis_enabled is False
        assert summary.gravity_down_dir == [0.0, -1.0, 0.0]
        assert summary.motion_blur_px_p90 is not None and summary.motion_blur_px_p90 < 4.0

        checks = qa.run_qa(cap)
        eis_chk = next(c for c in checks if c.name == "video_stabilization")
        blur_chk = next(c for c in checks if c.name == "imu_motion_blur")
        assert eis_chk.status == qa.PASS
        assert blur_chk.status == qa.PASS


def test_qa_flags_eis_on_and_high_gyro_blur():
    with tempfile.TemporaryDirectory() as tmp:
        cap = Path(tmp)
        (cap / "capture_info.json").write_text(
            json.dumps({"video_stabilization": True, "exposure_s": 0.02}), encoding="utf-8"
        )
        (cap / "Gyroscope.csv").write_text(
            "seconds_elapsed,x,y,z\n"
            "0.0,0.8,0.0,0.0\n",
            encoding="utf-8",
        )
        checks = qa.run_qa(cap)
        eis_chk = next(c for c in checks if c.name == "video_stabilization")
        blur_chk = next(c for c in checks if c.name == "imu_motion_blur")
        assert eis_chk.status == qa.FAIL
        assert blur_chk.status == qa.FAIL
