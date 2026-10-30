"""Extract the highest-scoring 90-second Guildhall source interval on Kaggle."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


START_SECONDS = 94
DURATION_SECONDS = 90
INPUT_ROOT = Path("/kaggle/input")
OUTPUT_ROOT = Path("/kaggle/working/out")


def main() -> None:
    sources = sorted(INPUT_ROOT.rglob("*.webm"))
    if len(sources) != 1:
        raise RuntimeError(f"expected one .webm input, found: {sources}")
    source = sources[0]
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is unavailable in the Kaggle image")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_ROOT / "source.webm"
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(START_SECONDS),
        "-i",
        str(source),
        "-t",
        str(DURATION_SECONDS),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"ffmpeg failed ({result.returncode}): {result.stderr[-2000:]}")
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("ffmpeg produced an empty clip")

    ffprobe = shutil.which("ffprobe")
    duration = None
    if ffprobe:
        probe = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0:
            duration = float(probe.stdout.strip())
            if not 86 <= duration <= 94:
                raise RuntimeError(f"trimmed duration is {duration:.2f}s, expected about 90s")

    report = {
        "source": source.name,
        "start_seconds": START_SECONDS,
        "requested_duration_seconds": DURATION_SECONDS,
        "actual_duration_seconds": duration,
        "bytes": output.stat().st_size,
        "encoding": "stream copy",
        "selection_basis": "best 90-second window by 480x270 Laplacian p10; median 2192 vs 811 baseline",
    }
    (OUTPUT_ROOT / "trim.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
