# Demo video — shipped cut (3:33, R1)

**Watch:** <https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4>

3:33 · 1920×1080 / 30 fps · H.264 + AAC · 41.0 MB · GitHub release asset
`r1-demo`.

The cut proves the R1 claim — one walk-through video in, a metric 3D twin and
a navigable floor out, served as a static link — using only numbers that ship
in `test/metro_v1/` and the Kaggle outputs. It is a narrated build, not a live
voice-over: the viewer take is real-time screen capture, and the cards are
generated from the report JSONs.

## What the cut actually contains

- **One continuous live take, 17.9 s.** Chrome on the hosted Pages build,
  hardware ANGLE/D3D11 on an AMD integrated GPU, captured at 1920×1080/30 with
  ffmpeg `gdigrab` while the viewer was driven through CDP. It shows the
  default spawn, WASD walking, mouse look, the HUD, and the minimap.
- **The rest of the viewer chapter is measured stills.** The live take ended
  at 17.9 s (the recorder stopped early), so the 31.4 s chapter uses the
  default-spawn still (`51.0 / 60.1 fps`) and the worst-view still
  (`?t=90`, `43.0 / 40.2 fps`). This is a deliberate trim, not a speed-up or a
  loop: the stills carry their own captions.
- **No terminal footage.** The pipeline is shown as the repo's stage diagram,
  the artifact tree, and the QA table. Every number is copied from the shipped
  reports, not from a shell transcript.
- **No second capture is claimed.** Two public candidates failed SfM (54% and
  2% registered), so the metro twin is the only hosted artifact.

## Chapters

| Time | Visual | What it proves |
|---|---|---|
| 0:00–0:20 | Title card; 14.8 s of the credited metro source clip (source 22–36.8 s) | The input is one ordinary RGB walk-through, no LiDAR or depth sensor. |
| 0:20–0:44 | "Google Maps stops at the door" card | The problem and the one-video constraint. |
| 0:44–1:02 | Pipeline stage diagram (now 25 k Splatfacto iters) | The whole pipeline runs on the Kaggle free tier: CPU SfM/depth/nav, one T4 for training. |
| 1:02–1:20 | `test/metro_v1/` artifact tree; 24.7 MB total | The deliverable is a folder of static files, no server or database. |
| 1:20–1:37 | QA table (216/216, 0.403 px, 6.2505 m/unit, 7.54% MAD, 315.05 m²) | The trust layer is auditable. |
| 1:37–1:54 | Metric occupancy grid with stats | The floor is measured; unknown cells are blocked and the walked path is carved free. |
| 1:54–2:26 | Live twin (17.9 s) + default-spawn and `?t=90` stills | Free-roam, collision, minimap, capture lens, and measured FPS. |
| 2:26–2:49 | `?route` still and route-walk still | A* is scaffolded: 350 waypoints / 20.3 m, green floor tube and minimap route. |
| 2:49–3:11 | Limits card | Reflective walls, DC-only `.splat`, depth past 8–12 m, portal gaps; no second capture claim. |
| 3:11–3:33 | Roadmap + links card | R2 POIs/search/routing; R3 campus capture + QR AR; repo, viewer, abstract. |

## Build / reproduce

```powershell
# 1) cards (Pillow; uses docs/fig/*.png and four live stills)
python docs\demo\build_cards.py

# 2) voice-over (Edge TTS, en-US-AndrewNeural, rate -4%)
#    narration.json is the source; audio/*.mp3 + durations.json are committed
python docs\demo\make_narration.py

# 3) cut (headless ffmpeg; needs the source clip and the live take)
python docs\demo\build_video.py
```

`build_video.py` expects:

- `kaggle/staging/video/metro_walk_86s.mp4` (source clip, gitignored)
- `%TEMP%\demo_walk20.mkv` (the 17.9 s live take, gitignored)
- `docs/demo/audio/*.mp3` + `durations.json` (committed)
- `docs/demo/cards/*.png` (committed, or regenerated)

The final MP4 is gitignored and uploaded as the `r1-demo` release asset.
`docs/demo/build/` holds intermediates and is gitignored.

## Recording notes

- **Hardware acceleration is mandatory.** Headless/software WebGL
  (SwiftShader) stretches anisotropic gaussians. The live take used normal
  Chrome with `--use-gl=angle --use-angle=d3d11`; the HUD reported 60 fps
  while walking.
- **CDP screencast was too slow at 1080p** (~4 fps), so the take used
  `gdigrab` at 30 fps and drove the viewer with CDP `keydown`/`mousemove`.
- **The take is 17.9 s, not 80 s.** The recorder stopped early; the chapter
  pads with the two measured stills instead of freezing the last live frame.
- **The source clip is licensed and credited on screen.** *Modern Melbourne
  Metro Walkway Urban Design* by Joolsmagool, Pexels License, trimmed to
  86.07 s. No house footage is used.
- **The release asset is the canonical link.** It is a direct MP4, not a
  YouTube upload; no YouTube credentials were available in the build
  environment. The abstract and repo both point at it.
- **Loudness:** the narration is normalized to **−16.3 LUFS integrated /
  −1.5 dBTP** (+4 dB from the TTS master) so it is audible on laptop and
  projector playback without clipping.

## Numbers on hand (from `test/metro_v1/capture_qa.md`, `nav_report.json`, `train_report.json`)

- 216 frames at 2.5 Hz; 216/216 registered; median reprojection 0.403 px
  (mean 0.613)
- SfM: 51,677 points, 3,553 s (59.2 min) on Kaggle CPU
- Metric scale 6.2505 m/unit; MAD 7.54% over 37,844 depth samples
- Depth: 31.2 M raw → 10.28 M voxel points; 216/216 frames fused
- Nav: 929,436 floor inliers; camera height 1.588 m; 315.05 m² walkable
  (126,020 free cells); grid 1188 × 1259 @ 5 cm; nav stage 61 s
- Splat: 25,000 iters at 1600×900; full export 510,336 gaussians / 16.33 MB;
  hosted sample 457,221 / 14.63 MB after the 3 m crop
- Web payload 18.4 MB (14.63 MB splat + 3.75 MB cloud + nav); full sample
  folder 24.7 MB; cold ready 19.2 s in a fresh profile
- Viewer: default spawn at 75% of the path; A* 350 waypoints / 20.3 m;
  live Pages **51.0 fps idle / 60.1 walking** at spawn, **43.0 / 40.2** at
  `?t=90`, **47.5 / 55.9** with `?route` (1155×650 internal)
- Lens: 1600×900, `fl_x=fl_y=1186.56` → 67.98° horizontal / 41.6° vertical;
  pitch clamped −0.85..+0.35 rad
- GPU wall: 79.0 min total (depth, gsplat JIT, train, export)
