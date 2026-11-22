"""Mux a 1080p walkthrough capture with your own recorded voice narration.

Competition Rule 9 Compliance:
  Narration MUST be recorded in your own human voice (AI TTS is strictly
  prohibited). Record your voiceover following `docs/demo/NARRATION_SCRIPT.md`,
  record a screen capture of your browser walkthrough + technical slides, and
  run this tool to produce a broadcast-ready 1080p/30fps H.264 + AAC MP4.

Usage:
    python docs/demo/mux_submission_video.py ^
        --video path\\to\\walkthrough.mp4 ^
        --audio path\\to\\my_voice.m4a ^
        --out docs\\demo\\topoloka_r2_submission.mp4
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _find_tool(name: str) -> str:
    winget = (
        Path.home()
        / "AppData/Local/Microsoft/WinGet/Packages"
        / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / "ffmpeg-8.1.2-full_build/bin"
        / f"{name}.exe"
    )
    if winget.exists():
        return str(winget)
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit(f"Required tool '{name}' not found on PATH.")


def probe_media(ffprobe: str, path: Path) -> dict:
    raw = subprocess.check_output(
        [
            ffprobe,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        text=True,
    )
    return json.loads(raw)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video", type=Path, required=True, help="Recorded walkthrough video (mp4/mkv/webm/mov)")
    ap.add_argument("--audio", type=Path, required=True, help="Human-voice narration audio (wav/m4a/mp3/aac)")
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("docs/demo/topoloka_r2_submission.mp4"),
        help="Output 1080p30 H.264 + AAC MP4 path",
    )
    ap.add_argument("--no-loudnorm", action="store_true", help="Skip EBU R128 voice loudness normalization")
    ap.add_argument("--crf", type=int, default=19, help="H.264 CRF quality (lower = sharper, default 19)")
    args = ap.parse_args()

    if not args.video.exists():
        raise SystemExit(f"Video file not found: {args.video}")
    if not args.audio.exists():
        raise SystemExit(f"Audio file not found: {args.audio}")

    ffmpeg = _find_tool("ffmpeg")
    ffprobe = _find_tool("ffprobe")

    v_info = probe_media(ffprobe, args.video)
    a_info = probe_media(ffprobe, args.audio)
    v_dur = float(v_info["format"]["duration"])
    a_dur = float(a_info["format"]["duration"])
    print(f"Input video: {args.video.name} ({v_dur:.1f}s)")
    print(f"Input voice: {args.audio.name} ({a_dur:.1f}s)")

    if abs(v_dur - a_dur) > 15.0:
        print(
            f"WARNING: video ({v_dur:.1f}s) and voice ({a_dur:.1f}s) differ by "
            f"{abs(v_dur - a_dur):.1f}s; output will end at the shorter stream."
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p"
    )
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-i",
        str(args.video),
        "-i",
        str(args.audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(args.crf),
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-pix_fmt",
        "yuv420p",
    ]
    if not args.no_loudnorm:
        cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    cmd += [
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        "-shortest",
        str(args.out),
    ]

    print("Muxing 1080p30 submission MP4...")
    subprocess.run(cmd, check=True)

    out_info = probe_media(ffprobe, args.out)
    out_dur = float(out_info["format"]["duration"])
    size_mb = args.out.stat().st_size / 1e6
    streams = {s["codec_type"] for s in out_info.get("streams", [])}
    print(f"Done: {args.out} ({size_mb:.1f} MB, {out_dur:.1f}s, streams={sorted(streams)})")

    if "audio" not in streams:
        raise SystemExit("ERROR: output MP4 has no audio track!")
    if out_dur < 180.0 or out_dur > 300.0:
        print(
            f"WARNING: output duration is {out_dur:.1f}s; official Round 2 "
            "guidelines specify 3 to 5 minutes (180-300s)."
        )


if __name__ == "__main__":
    sys.exit(main())
