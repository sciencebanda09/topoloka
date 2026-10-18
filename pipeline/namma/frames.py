"""Stage 1 -- frame extraction with sharpness-based picking.

Reads a phone video and keeps one frame per stride-sized window. The sharpest
frame in each window (highest Laplacian variance) wins, mirroring the picking
policy used by the Syntheta/dmx SLAM pipeline: a fixed stride gives even
temporal spacing, and picking within the window avoids the blur-inducing
moment of the step cycle (footfall shake) typical of walking phone captures.

The module is sensor-agnostic on purpose: if a gyro log is available, a future
stage can override the pick index per window (least rotational blur wins);
without a sensor log, image sharpness is the fallback and this module is the
whole story.

Outputs, under out_dir/:
    frames/00000.jpg ...        picked frames, sequential names
    frames_meta.json            per-frame records + QA stats

The metadata format is our contract for downstream stages (SfM, depth,
splat); keep it stable and additive-only.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

RANK_WIDTH = 640  # sharpness ranking runs on a small gray copy (fast, rank-only)


@dataclass
class FrameRecord:
    """One kept frame."""

    name: str
    seq: int          # sequence number in the kept set (matches file name)
    index: int        # source frame index in the video
    time_s: float     # source timestamp (index / fps)
    blur: float       # Laplacian variance at saved resolution (higher = sharper)
    rank_blur: float  # Laplacian variance used for in-window ranking (small copy)
    width: int
    height: int


def _rank_blur(bgr: np.ndarray) -> float:
    """Laplacian variance on a small grayscale copy; used only for ranking."""
    h, w = bgr.shape[:2]
    if w > RANK_WIDTH:
        scale = RANK_WIDTH / w
        bgr = cv2.resize(bgr, (RANK_WIDTH, max(1, round(h * scale))),
                         interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _save_blur(bgr: np.ndarray) -> float:
    """Honest blur score at the resolution we actually keep."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def extract_frames(
    video: Path,
    out_dir: Path,
    *,
    stride: int = 6,
    target_rate_hz: float | None = None,
    max_width: int = 0,
    max_seconds: float | None = None,
    start_s: float = 0.0,
    jpeg_quality: int = 95,
) -> dict[str, Any]:
    """Extract window-sharpest frames from `video` into `out_dir/frames`.

    Args:
        stride: window size in source frames (window advances by stride).
        target_rate_hz: if set, stride is computed from the video's fps so that
            kept frames land at this rate (e.g. 2.5 -> one frame per 0.4 s).
            The Kaggle kernels use this so 30/60/120 fps sources all produce
            similar frame counts.
        max_width: downscale kept frames so width <= max_width (0 = native).
        max_seconds: stop reading after this many seconds of video.
        start_s: skip the first this many seconds.
        jpeg_quality: JPEG encode quality for kept frames.

    Returns the metadata dict (also written to out_dir/frames_meta.json).
    """
    video = Path(video)
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"cannot open video: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if target_rate_hz and target_rate_hz > 0:
        stride = max(1, int(round(fps / target_rate_hz)))

    start_index = int(start_s * fps)
    limit_index = start_index + int(max_seconds * fps) if max_seconds else None
    if start_index:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_index)

    records: list[FrameRecord] = []
    all_rank_blur: list[float] = []
    i = start_index
    window_best: tuple[float, int, np.ndarray] | None = None
    t0 = time.time()

    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        if limit_index is not None and i >= limit_index:
            break

        score = _rank_blur(bgr)
        if window_best is None or score > window_best[0]:
            window_best = (score, i, bgr)

        window_done = (i - start_index + 1) % stride == 0
        if window_done and window_best is not None:
            records.append(_flush(window_best, records, frames_dir, max_width, jpeg_quality, fps))
            all_rank_blur.append(window_best[0])
            window_best = None
        i += 1

    if window_best is not None:  # tail window
        records.append(_flush(window_best, records, frames_dir, max_width, jpeg_quality, fps))
        all_rank_blur.append(window_best[0])

    cap.release()

    blur_arr = np.asarray(all_rank_blur, dtype=np.float64)
    stats = {
        "frames_kept": len(records),
        "windows_scored": len(blur_arr),
        "rank_blur_mean": float(blur_arr.mean()) if len(blur_arr) else 0.0,
        "rank_blur_p10": float(np.percentile(blur_arr, 10)) if len(blur_arr) else 0.0,
        "rank_blur_p90": float(np.percentile(blur_arr, 90)) if len(blur_arr) else 0.0,
        "rank_blur_min": float(blur_arr.min()) if len(blur_arr) else 0.0,
        "extract_seconds": round(time.time() - t0, 1),
    }
    meta = {
        "stage": "frames",
        "video": str(video),
        "video_fps": fps,
        "video_frames": total,
        "stride": stride,
        "target_rate_hz": target_rate_hz,
        "max_width": max_width,
        "max_seconds": max_seconds,
        "start_s": start_s,
        "stats": stats,
        "frames": [asdict(r) for r in records],
    }
    (out_dir / "frames_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"[frames] {video.name}: kept {len(records)} frames "
          f"(stride {stride}, {stats['extract_seconds']}s, "
          f"blur p10 {stats['rank_blur_p10']:.1f} / p90 {stats['rank_blur_p90']:.1f})")
    return meta


def _flush(
    window_best: tuple[float, int, np.ndarray],
    records: list[FrameRecord],
    frames_dir: Path,
    max_width: int,
    jpeg_quality: int,
    fps: float,
) -> FrameRecord:
    score, index, bgr = window_best
    if max_width and bgr.shape[1] > max_width:
        scale = max_width / bgr.shape[1]
        bgr = cv2.resize(bgr, (max_width, max(1, round(bgr.shape[0] * scale))),
                         interpolation=cv2.INTER_AREA)
    seq = len(records)
    name = f"{seq:05d}.jpg"
    cv2.imwrite(str(frames_dir / name), bgr, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
    h, w = bgr.shape[:2]
    return FrameRecord(
        name=name, seq=seq, index=index, time_s=round(index / fps, 3),
        blur=round(_save_blur(bgr), 1), rank_blur=round(score, 1), width=w, height=h,
    )
