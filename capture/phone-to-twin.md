# Phone → 3D twin (the live-capture path)

This is the shortest honest path from **live phone footage** to a hosted twin.
It exists because Round 1 asks teams to map **their own indoor space**, not a
stock clip.

## What "live" means here

| Stage | Live? | Where it runs |
|---|---|---|
| Camera capture | **Yes** — you walk the room with the phone | Phone, native camera app |
| Frame picking, SfM, metric nav | No — ~30–60 min | Kaggle CPU kernel |
| Depth fusion, splat training, web export | No — ~60–90 min | Kaggle GPU kernel |
| Free-roam viewing | **Yes** | Static GitHub Pages |

Real-time splat training on the phone is **not** claimed. The official R3
format also allows capture on Day 1 and reconstruction before the Day 2 pitch;
this path matches that shape.

**Privacy first:** the twin, preview frames, and video metadata become public
in the repo and on Pages. Capture a lab, classroom, corridor, or other space
you have permission to publish — not a private home. The raw video stays out
of git (`.gitignore` covers `*.mp4` / `*.mov`).

## 1. Record (one continuous take, 90–150 s)

Follow `capture/SOP.md`. The short version:

- Landscape, 4K/30 if the phone allows (1080p/30 is the fallback).
- **EIS / video stabilization OFF** (Android). On iPhone, keep the phone steady;
  iOS stabilization cannot be disabled.
- Lock exposure and focus before walking; lights on; flash off.
- Two passes of one loop: chest height tilted ~10° up, then the same loop
  reversed tilted ~20° down. Walk at ~0.4 m/s, turn at ~30°/s.
- Return to the start and hold still for 5 seconds before stopping.
- Doors, corners, and at least two angles on every wall. Avoid mirrors head-on.

A 90-second clip is enough for one room. For a multi-room venue, keep recording
through the doorways — one file per session.

## 2. Move the file to the laptop

- **Android:** USB → `Internal storage/DCIM/Camera/` → copy the `.mp4`.
- **iPhone:** USB → `DCIM/` → copy the `.mov`; or AirDrop / iCloud Drive.
- Put it somewhere outside git, e.g. `C:\capture\room.mov`.

`.mp4`, `.mov`, `.m4v`, `.webm`, `.mkv`, and `.avi` are all accepted now. The
pipeline kernel used to glob only `.mp4`, which silently rejected iPhone
footage; that boundary is fixed.

## 3. One command: upload + reconstruct

From the repo root, with the Kaggle CLI configured (`kaggle/config.local.ps1`):

```powershell
powershell -File kaggle\tools\push_video.ps1 `
  -Video "C:\capture\room.mov" -Name room-v1 -Splat
```

What it does:

1. Stages the raw video as the private dataset `namma-room-v1-video`.
2. Waits for the dataset to be `ready` (avoiding the empty-mount failure).
3. Generates and pushes `namma-pipeline-room-v1` (CPU) with that dataset.
4. Fetches the output and refuses to continue unless `summary.txt` says `ok`.
5. Syncs `namma-capture-room-v1` and pushes `namma-splat-room-v1` (GPU).
6. Fetches the splat output and checks `web/splat.splat` exists.

Budget ~2.5 hours wall time. Kaggle CPU and GPU quota are separate; the CPU
stage does not consume GPU hours.

Without `-Splat` the script stops after uploading and pushing the CPU kernel,
and prints the follow-up commands.

## 4. Assemble the committed sample

```powershell
.venv\Scripts\python.exe tools\make_sample.py `
  --pipe-out kaggle\out\namma_pipeline_room_v1 `
  --splat-out kaggle\out\namma_splat_room_v1 `
  --dest test\room-v1 `
  --frames 14 --max-gaussians 1000000 `
  --source-note "Captured on <phone> by <name>, <date>; indoor room, landscape 4K/30."
```

This writes `test/room-v1/` (QA report, nav, preview frames, web splat). It is
the redistributable artifact; the raw phone video is not committed.

## 5. Activate, build & deploy

```powershell
# Stage into web/public/artifacts/, update main.ts / index.html / web-pages.yml,
# and print exact metrics for docs/abstract.md:
python tools\activate_capture.py home_v1 --label "Home 3-Room Twin — POIs & nav"

cd web
npm run typecheck
npm test
npm run build
```

Test locally with `npm run dev`: press **E** to click-tag POIs across every room,
export `pois.json`, validate with `python -m namma.cli pois test\room_v1 --source <exported.json>`,
and verify `capture_qa.json` reports `PASS` before pushing:

```powershell
git add -A
git commit -m "feat: publish self-captured room_v1 twin and POIs"
git push origin main
```

Then check the QA report before claiming success:

- `capture_qa.json` / `.md` — sharpness, registered fraction, reprojection,
  coverage (registered ≥ 60%, median reprojection ≤ 1.0 px, QA overall PASS).
- `depth/depth_report.json` — Apache-2.0 `Depth-Anything-V2-Metric-Indoor-Small-hf`
  scale MAD (`≤ 10%`).
- `nav/nav_report.json` — walkable area and floor inliers.
- The live viewer HUD — spawn, 2D minimap, wall collision, POI search, A\* route,
  and sandbox barrier reroute.

## 6. Finalize Round 2 abstract, video & Drive submission

Once `room_v1` is live on GitHub Pages:

- `capture/SOP.md` Section 6 → add the public raw capture video URL + `test/room_v1/frames/` & `capture_qa.md`.
- `docs/abstract.md` → paste the measured metrics printed by `activate_capture.py`, then rebuild PDFs:
  ```powershell
  python tools\build_pdf.py docs\abstract.md docs\abstract.pdf
  Copy-Item docs\abstract.pdf submission\Technical_Abstract_Topoloka.pdf -Force
  python tools\build_pdf.py docs\MASTER_SUBMISSION_DOCUMENT.md docs\MASTER_SUBMISSION_DOCUMENT.pdf
  python tools\build_pdf.py submission\MASTER_SUBMISSION_DOCUMENT.md submission\MASTER_SUBMISSION_DOCUMENT.pdf
  ```
- Record your **own-voice** 3–5 min narration (`docs/demo/NARRATION_SCRIPT.md`) over a 1080p walkthrough of `room_v1` and mux cleanly:
  ```powershell
  python docs\demo\mux_submission_video.py --video walkthrough.mp4 --audio my_voice.m4a --out docs\demo\topoloka_r2_submission.mp4
  ```
- Fast-forward `r2-pois-nav` to `main`, push both branches, upload `submission/` to Google Drive ("Anyone with the link can view"), and verify every single link in an **Incognito browser window**.

Do not claim "live reconstruction" anywhere. The capture is live; the twin is
built after the walk.

## Failure modes and fixes

| Symptom | Cause / fix |
|---|---|
| `no phone video under /kaggle/input` | Wrong dataset mount, or an unsupported container. Check the mount name and extension. |
| Kernel dies in seconds | Dataset was not `ready`; re-run `push_video.ps1` (it polls). |
| Registered fraction < 60% | Too fast, too dark, or EIS on. Recapture slower and brighter. |
| Reprojection > 1 px | EIS left on, or rolling-shutter/motion blur. Recapture with EIS off. |
| Portrait warning in the frames log | Recapture in landscape. The SOP requires it. |
| Splat looks empty / black | Check `web/splat.splat` exists and `meta.json` reports `splat.present`. |
| QA fails one gate | Recapture the worst zones; do not patch the report. |
