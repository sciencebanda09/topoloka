"""Regenerate the demo voice-over from narration.json.

Requires edge-tts (pip install edge-tts) and ffprobe on PATH or at the
WinGet FFmpeg location. Writes docs/demo/audio/*.mp3 and durations.json.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import edge_tts

BASE = Path(__file__).resolve().parent
AUDIO = BASE / "audio"
VOICE = "en-US-AndrewNeural"
RATE = "-4%"
_FFPROBE = (r"C:\Users\kumar\AppData\Local\Microsoft\WinGet\Packages"
            r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
            r"\ffmpeg-8.1.2-full_build\bin\ffprobe.exe")
FFPROBE = _FFPROBE if Path(_FFPROBE).exists() else "ffprobe"


def duration(path: Path) -> float:
    out = subprocess.check_output([
        FFPROBE, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path)])
    return float(out.decode().strip())


async def main() -> None:
    AUDIO.mkdir(exist_ok=True)
    scenes = json.loads((BASE / "narration.json").read_text(encoding="utf-8"))
    durations = {}
    for scene in scenes:
        out = AUDIO / f"{scene['id']}.mp3"
        await edge_tts.Communicate(scene["text"], VOICE, rate=RATE).save(
            str(out))
        durations[scene["id"]] = round(duration(out), 2)
        print(scene["id"], durations[scene["id"]], "s")
    (AUDIO / "durations.json").write_text(
        json.dumps(durations, indent=2) + "\n", encoding="utf-8")
    print("total", round(sum(durations.values()), 2), "s")


if __name__ == "__main__":
    asyncio.run(main())
