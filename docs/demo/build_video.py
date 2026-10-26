"""Assemble the R1 demo video from the generated cards and existing captures.

This is a headless ffmpeg build: no browser, no pipeline compute. It expects:
  docs/demo/cards/*.png            (run build_cards.py first)
  docs/demo/audio/*.mp3            (Edge TTS narration)
  kaggle/staging/video/metro_walk_86s.mp4
  %TEMP%/demo_walk20.mkv           (already-captured live viewer take)

Output:
  docs/demo/topoloka_demo.mp4
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = Path(__file__).resolve().parent
CARDS = DEMO / "cards"
AUDIO = DEMO / "audio"
BUILD = DEMO / "build"
BUILD.mkdir(exist_ok=True)

FFMPEG = (r"C:\Users\kumar\AppData\Local\Microsoft\WinGet\Packages"
          r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
          r"\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe")
FFPROBE = str(Path(FFMPEG).with_name("ffprobe.exe"))
SOURCE = ROOT / "kaggle" / "staging" / "video" / "metro_walk_86s.mp4"
LIVE = Path(os.environ["TEMP"]) / "demo_walk20.mkv"
FPS = 30
W, H = 1920, 1080

DUR = json.loads((AUDIO / "durations.json").read_text(encoding="utf-8"))


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
        "-frames:v", str(n), "-r", str(FPS),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
        "-video_track_timescale", "30000", "-an", str(out),
    ]
    run(args, f"  image {seg['image']} -> {out.name} ({n} frames)")


def encode_source(seg: dict, out: Path) -> None:
    n = seg["frames"]
    args = [
        FFMPEG, "-hide_banner", "-y",
        "-ss", str(seg["start"]), "-t", f"{n / FPS + 0.1:.3f}",
        "-i", str(SOURCE),
        "-i", str(CARDS / "source_credit.png"),
        "-filter_complex",
        f"[0:v]scale={W}:{H},fps={FPS}[v0];[v0][1:v]overlay=0:0,format=yuv420p[v]",
        "-map", "[v]", "-frames:v", str(n), "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
        "-video_track_timescale", "30000", "-an", str(out),
    ]
    run(args, f"  source {seg['start']}s -> {out.name} ({n} frames)")


def encode_live(seg: dict, out: Path) -> None:
    n = seg["frames"]
    args = [
        FFMPEG, "-hide_banner", "-y", "-fflags", "+genpts",
        "-i", str(LIVE), "-t", f"{n / FPS + 0.1:.3f}",
        "-vf", f"scale={W}:{H},fps={FPS},format=yuv420p",
        "-frames:v", str(n), "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
        "-video_track_timescale", "30000", "-an", str(out),
    ]
    run(args, f"  live -> {out.name} ({n} frames)")


def build_audio(scene_id: str, out: Path) -> None:
    n = scene_frames(scene_id)
    dur = n / FPS
    args = [
        FFMPEG, "-hide_banner", "-y", "-i", str(AUDIO / f"{scene_id}.mp3"),
        "-af", "adelay=300|300,apad=pad_dur=0.7,aresample=48000",
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
    if not SOURCE.exists():
        raise SystemExit(f"missing source clip: {SOURCE}")
    if not LIVE.exists():
        raise SystemExit(f"missing live capture: {LIVE}")

    # Visual segments in order. Frame counts within each scene sum to the
    # scene's audio length plus 1.0 s of breathing room.
    plan = [
        ("01_title", [
            {"kind": "image", "image": "01_title.png", "frames": 150},
            {"kind": "source", "start": 22.0, "frames": scene_frames("01_title") - 150},
        ]),
        ("02_problem", [
            {"kind": "image", "image": "02_problem.png", "frames": scene_frames("02_problem")},
        ]),
        ("03_pipeline", [
            {"kind": "image", "image": "03_pipeline.png", "frames": 540},
            {"kind": "image", "image": "03b_artifacts.png",
             "frames": scene_frames("03_pipeline") - 540},
        ]),
        ("04_qa", [
            {"kind": "image", "image": "04_qa.png", "frames": 510},
            {"kind": "image", "image": "04b_nav.png",
             "frames": scene_frames("04_qa") - 510},
        ]),
        ("05_viewer", [
            # The captured take is 537 frames (17.9 s). Give the balance of
            # the scene to the default-spawn still rather than freezing the
            # last live frame.
            {"kind": "live", "frames": 537},
            {"kind": "image", "image": "05b_default.png", "frames": 243},
            {"kind": "image", "image": "05c_t90.png",
             "frames": scene_frames("05_viewer") - 780},
        ]),
        ("06_route", [
            {"kind": "image", "image": "06a_route.png", "frames": 360},
            {"kind": "image", "image": "06b_route_walk.png",
             "frames": scene_frames("06_route") - 360},
        ]),
        ("07_limits", [
            {"kind": "image", "image": "07_limits.png", "frames": scene_frames("07_limits")},
        ]),
        ("08_close", [
            {"kind": "image", "image": "08_close.png", "frames": scene_frames("08_close")},
        ]),
    ]

    for scene_id, segs in plan:
        total = sum(s["frames"] for s in segs)
        want = scene_frames(scene_id)
        if total != want:
            raise SystemExit(f"{scene_id}: segments {total} != scene {want}")

    # 1) silent visual segments
    visual_files: list[Path] = []
    idx = 0
    for scene_id, segs in plan:
        for seg in segs:
            idx += 1
            out = BUILD / f"seg_{idx:02d}.mp4"
            first = idx == 1
            last = idx == sum(len(s) for _, s in plan)
            if seg["kind"] == "image":
                encode_image(seg, out, first, last)
            elif seg["kind"] == "source":
                encode_source(seg, out)
            elif seg["kind"] == "live":
                encode_live(seg, out)
            else:
                raise SystemExit(f"unknown segment kind {seg['kind']}")
            visual_files.append(out)

    # 2) one continuous video track
    silent = BUILD / "video_silent.mp4"
    concat(visual_files, silent)

    # 3) one continuous narration track
    audio_files: list[Path] = []
    for scene_id, _ in plan:
        wav = BUILD / f"audio_{scene_id}.wav"
        build_audio(scene_id, wav)
        audio_files.append(wav)
    narration = BUILD / "narration.wav"
    concat(audio_files, narration)

    # 4) mux. Keep the exact planned length instead of -shortest so the
    # close-card fade-out is not clipped by AAC priming.
    total_dur = sum(scene_frames(k) for k in DUR) / FPS
    final = DEMO / "topoloka_demo.mp4"
    args = [
        FFMPEG, "-hide_banner", "-y", "-i", str(silent), "-i", str(narration),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        "-af", "volume=4.0dB",
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
