"""Rank 90-second windows of the full Guildhall video by frame sharpness.

Runs only on Kaggle. Samples one frame per second, downsizes to 480x270, and
uses Laplacian variance to rank continuous windows. The current sample uses
the 305-395 second segment, which is reported as the baseline.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np


INPUT_ROOT = Path("/kaggle/input")
OUTPUT_ROOT = Path("/kaggle/working/out")
WINDOW_SECONDS = 90
BASELINE_START = 305
SAMPLE_WIDTH = 480
SAMPLE_HEIGHT = 270


def metric(values: np.ndarray) -> dict[str, float]:
    return {
        "p10": round(float(np.percentile(values, 10)), 2),
        "median": round(float(np.median(values)), 2),
        "mean": round(float(np.mean(values)), 2),
    }


def main() -> None:
    videos = sorted(INPUT_ROOT.rglob("*.webm"))
    if len(videos) != 1:
        raise RuntimeError(f"expected one .webm input, found: {videos}")
    video = videos[0]

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open {video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0 or frame_count <= 0:
        raise RuntimeError(f"invalid video metadata: fps={fps}, frames={frame_count}")
    duration = frame_count / fps

    scores: list[dict[str, float | int]] = []
    for second in range(int(duration)):
        capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = capture.read()
        if not ok:
            continue
        small = cv2.resize(
            frame,
            (SAMPLE_WIDTH, SAMPLE_HEIGHT),
            interpolation=cv2.INTER_AREA,
        )
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        actual_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC))
        scores.append(
            {
                "requested_second": second,
                "actual_second": round(actual_ms / 1000, 3),
                "laplacian_variance": round(sharpness, 3),
            }
        )
    capture.release()

    by_second = {
        int(row["requested_second"]): float(row["laplacian_variance"])
        for row in scores
    }
    windows: list[dict[str, float | int]] = []
    for start in range(0, int(duration) - WINDOW_SECONDS + 1):
        seconds = range(start, start + WINDOW_SECONDS)
        if not all(second in by_second for second in seconds):
            continue
        values = np.asarray([by_second[second] for second in seconds], dtype=np.float64)
        windows.append({"start_second": start, "end_second": start + WINDOW_SECONDS, **metric(values)})

    if not windows:
        raise RuntimeError("no complete 90-second window was decoded")
    ranked = sorted(windows, key=lambda row: (row["p10"], row["median"], row["mean"]), reverse=True)
    baseline_values = np.asarray(
        [by_second[s] for s in range(BASELINE_START, BASELINE_START + WINDOW_SECONDS) if s in by_second],
        dtype=np.float64,
    )

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_ROOT / "sharpness.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(scores[0]))
        writer.writeheader()
        writer.writerows(scores)

    report = {
        "source": video.name,
        "fps": round(fps, 3),
        "frame_count": frame_count,
        "duration_seconds": round(duration, 2),
        "sampled_frames": len(scores),
        "metric": "variance of Laplacian on 480x270 grayscale frames sampled at 1 fps",
        "baseline_305_395": metric(baseline_values) if len(baseline_values) else None,
        "top_windows": ranked[:20],
    }
    (OUTPUT_ROOT / "sharpness.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
