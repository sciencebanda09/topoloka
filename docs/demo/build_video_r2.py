"""Assemble the Round 2 demo video from cards, live clips, and narration.

Headless ffmpeg build: no browser and no pipeline compute. It expects:
  docs/demo/cards_r2/*.png
  docs/demo/audio_r2/*.mp3
  the raw browser captures listed in CLIPS

Output:
  docs/demo/topoloka_r2_demo.mp4
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = Path(__file__).resolve().parent
CARDS = DEMO / "cards_r2"
AUDIO = DEMO / "audio_r2"
BUILD = DEMO / "build_r2"
BUILD.mkdir(exist_ok=True)

FFMPEG = (r"C:\Users\kumar\AppData\Local\Microsoft\WinGet\Packages"
          r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
          r"\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe")
FFPROBE = str(Path(FFMPEG).with_name("ffprobe.exe"))
FPS = 30
W, H = 1920, 1080

DUR = json.loads((AUDIO / "durations.json").read_text(encoding="utf-8"))
CAPTURE = Path(r"G:\My Drive\temp\opencode\r2_qa")
CLIPS = {
    "intro": (CAPTURE / "clips6" / "page@b5e5fd816164a73ee16d4c4afcef73ab.webm", 13.00),
    "index": (CAPTURE / "clips5" / "index" / "page@4be79dca51db4302378a53d6df4d7009.webm", 13.35),
    "search": (CAPTURE / "clips3" / "search" / "page@9add9a9a8dec9857038dcb8ef62d3b9f.webm", 14.38),
    "nav": (CAPTURE / "clips3" / "nav" / "page@f33ca2a2f671a23fae6566f27475b803.webm", 14.83),
    "obstacles": (CAPTURE / "clips3" / "obstacles" / "page@0ec867a8d33250e8fe7d03a11ca62974.webm", 16.25),
    "authoring": (CAPTURE / "clips5" / "authoring" / "page@52d4d46691c2cf4efcf92235abe692d1.webm", 12.73),
}


def run(args: list[str], label: str) -> None:
    print(label, flush=True)
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        print(p.stderr.decode("utf-8", "replace")[-4000:])
        raise SystemExit(f"ffmpeg failed: {label}")


def frames(seconds: float) -> int:
    return int(math.ceil(seconds * FPS - 1e-9))


def scene_frames(scene_id: str) -> int:
    return frames(DUR[scene_id] + 1.0)


def encode_image(seg: dict, out: Path, first: bool, last: bool) -> None:
    n = seg["frames"]
    vf = f"scale={W}:{H},format=yuv420p"
    if first:
        vf = f"fade=t=in:st=0:d=0.6,{vf}"
    if last:
        d = n / FPS
        vf = f"{vf},fade=t=out:st={max(0.0, d - 0.8):.3f}:d=0.8"
    args = [
        FFMPEG, "-hide_banner", "-y", "-loop", "1", "-framerate", str(FPS),
        "-i", str(CARDS / seg["image"]),
        "-frames:v", str(n), "-r", str(FPS), "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
        "-video_track_timescale", "30000", "-an", str(out),
    ]
    run(args, f"  image {seg['image']} -> {out.name} ({n} frames)")


def encode_clip(seg: dict, out: Path) -> None:
    n = seg["frames"]
    src, start = CLIPS[seg["clip"]]
    if not src.exists():
        raise SystemExit(f"missing capture: {src}")
    args = [
        FFMPEG, "-hide_banner", "-y",
        "-ss", f"{start:.3f}", "-t", f"{n / FPS + 0.12:.3f}",
        "-i", str(src),
        "-vf", (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p"),
        "-frames:v", str(n), "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
        "-video_track_timescale", "30000", "-an", str(out),
    ]
    run(args, f"  clip {seg['clip']} @ {start:.2f}s -> {out.name} ({n} frames)")


def build_audio(scene_id: str, out: Path) -> None:
    n = scene_frames(scene_id)
    dur = n / FPS
    args = [
        FFMPEG, "-hide_banner", "-y", "-i", str(AUDIO / f"{scene_id}.mp3"),
        "-af", ("adelay=300|300,apad=pad_dur=0.7,volume=3.0dB,"
                "alimiter=limit=0.85:level=false,aresample=48000,"
                "pan=stereo|c0=c0|c1=c0"),
        "-ac", "2", "-ar", "48000", "-t", f"{dur:.6f}",
        "-c:a", "pcm_s16le", str(out),
    ]
    run(args, f"  audio {scene_id} -> {out.name} ({dur:.3f}s)")


def concat(files: list[Path], out: Path, with_audio: bool = False) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{(f.as_posix())}'\n" for f in files),
                   encoding="utf-8")
    args = [FFMPEG, "-hide_banner", "-y", "-f", "concat", "-safe", "0",
            "-i", str(lst), "-c", "copy"]
    if with_audio:
        args += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                 "-movflags", "+faststart"]
    args.append(str(out))
    run(args, f"  concat {len(files)} -> {out.name}")


def main() -> None:
    # Visual segments in order. Segment frames sum to 1 s beyond narration.
    plan = [
        ("r2_intro", [
            {"kind": "image", "image": "r2_01_title.png", "frames": 210},
            {"kind": "clip", "clip": "intro", "frames": 609},
        ]),
        ("r2_index", [
            {"kind": "image", "image": "r2_02_contract.png", "frames": 620},
            {"kind": "image", "image": "r2_03_index.png", "frames": 500},
            {"kind": "clip", "clip": "index", "frames": 375},
        ]),
        ("r2_search", [
            {"kind": "clip", "clip": "search", "frames": 891},
        ]),
        ("r2_nav", [
            {"kind": "clip", "clip": "nav", "frames": 651},
            {"kind": "image", "image": "r2_04b_nav_failsafe.png", "frames": 433},
            {"kind": "image", "image": "r2_04c_nav_overlay.png", "frames": 240},
        ]),
        ("r2_obstacles", [
            {"kind": "clip", "clip": "obstacles", "frames": 839},
        ]),
        ("r2_authoring", [
            {"kind": "clip", "clip": "authoring", "frames": 745},
        ]),
        ("r2_verified", [
            {"kind": "image", "image": "r2_04_verified.png", "frames": 620},
            {"kind": "image", "image": "r2_05_live.png", "frames": 330},
        ]),
        ("r2_close", [
            {"kind": "image", "image": "r2_06_close.png", "frames": 459},
        ]),
    ]

    for scene_id, segs in plan:
        total = sum(s["frames"] for s in segs)
        want = scene_frames(scene_id)
        if total != want:
            raise SystemExit(f"{scene_id}: segments {total} != scene {want}")

    visual_files: list[Path] = []
    idx = 0
    last_idx = sum(len(s) for _, s in plan)
    for scene_id, segs in plan:
        for seg in segs:
            idx += 1
            out = BUILD / f"r2_seg_{idx:02d}.mp4"
            if seg["kind"] == "image":
                encode_image(seg, out, idx == 1, idx == last_idx)
            elif seg["kind"] == "clip":
                encode_clip(seg, out)
            else:
                raise SystemExit(f"unknown segment kind {seg['kind']}")
            visual_files.append(out)

    silent = BUILD / "r2_video_silent.mp4"
    concat(visual_files, silent)

    audio_files: list[Path] = []
    for scene_id, _ in plan:
        wav = BUILD / f"r2_audio_{scene_id}.wav"
        build_audio(scene_id, wav)
        audio_files.append(wav)
    narration = BUILD / "r2_narration.wav"
    concat(audio_files, narration)

    total_dur = sum(scene_frames(k) for k in DUR) / FPS
    final = DEMO / "topoloka_r2_demo.mp4"
    args = [
        FFMPEG, "-hide_banner", "-y", "-i", str(silent), "-i", str(narration),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", f"{total_dur:.6f}", "-movflags", "+faststart", str(final),
    ]
    run(args, f"mux -> {final.name}")

    probe = subprocess.check_output([
        FFPROBE, "-v", "error", "-show_entries",
        "format=duration,size:stream=codec_name,width,height,r_frame_rate,channels",
        "-of", "json", str(final)])
    print(probe.decode("utf-8"))
    print("wrote", final, final.stat().st_size)


if __name__ == "__main__":
    main()
