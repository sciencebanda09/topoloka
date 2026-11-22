# TOPOLOKA: Master Submission Document and Supplementary Materials

**Techfest 2026–27, IIT Bombay — Namma Space Competition (Round 2 Official Deliverable)**

| Submission Details | Verification & Access |
|---|---|
| **Author / Lead** | **Shashank Dev** (`coderperson043@gmail.com`) |
| **Team / Competition ID** | `TM-60A7F03511D` · `NAMM-B3B981411E93` |
| **Official Google Drive Folder** | [Google Drive Submission Folder](https://drive.google.com/drive/folders/1vY_eKNKpsiaX1dGYe3TORipPhjcY-D5I?usp=sharing) |
| **Live Web App (R2 — `home_v1`)** | [https://sciencebanda09.github.io/topoloka/](https://sciencebanda09.github.io/topoloka/) |
| **Source Code Repository** | [https://github.com/sciencebanda09/topoloka](https://github.com/sciencebanda09/topoloka) (`main` & synced `r2-pois-nav`, MIT License) |
| **Technical Abstract & SOP (PDF)** | [`Technical_Abstract_Topoloka.pdf`](Technical_Abstract_Topoloka.pdf) (4 pages, ≤ 5-page limit; mirrors `docs/abstract.pdf`) |
| **R2 Evidence Pack** | [`docs/r2_evidence.md`](https://github.com/sciencebanda09/topoloka/blob/main/docs/r2_evidence.md) |
| **Raw Capture Video (SOP Proof)** | `home_v1_raw_full.mp4` (`98.6 s`, `1280×576 @ 30 fps` — see Google Drive folder) |
| **Own-Voice Demo Video (R2, 3–5 min)** | `[Own-voice 1080p30 walkthrough of home_v1 — see Google Drive folder]` |

---

## 1. Executive Summary & Technical Stack

**Topoloka** (*τόπος* [place] + *लोक* [world]) converts a single continuous smartphone walkthrough video into a **hybrid metric 3D digital twin** — combining photorealistic compressed **3D Gaussian Splats (`.ksplat`)** with a **5 cm metric 2.5D occupancy costmap** — deployed as a zero-backend static web application running at **~51.5 FPS** in desktop and mobile browsers.

All third-party and public datasets (`room`, `playroom`, `guildhall-*`, `metro_v1`) have been purged. The sole deployed scene (`test/home_v1/`) is reconstructed strictly from our team's self-captured 3-room flat walkthrough (`Entry Study Room`, `Central Hall`, and a closed loop around the `Master Bedroom`).

### Key Round 2 Capabilities
- **Deterministic Multi-Room Capture SOP (`capture/SOP.md`):** Specifies device, 4K/30 landscape (1080p/720p fallback), EIS OFF, AE/AF lock, lighting, `0.4 m/s` pace, `1.2–2.0 m` wall stand-off, dual-tilt passes (`+10°` / `-20°`), 3 s corner arc sweeps, doorway/stairwell crossings, optional 2D plan & 2.00 m scale photos, and an automated QA analyzer (`namma qa`).
- **Commercially Licensed Reconstruction Pipeline (`pipeline/namma/`):** Uses **Kornia `DISK + LightGlue` (Apache 2.0)** + `pycolmap 4.2.1` (`CameraMode.SINGLE`), **`Depth-Anything-V2-Metric-Indoor-Small-hf` (Apache 2.0 — zero `CC-BY-NC` weights)**, bed-rejecting gravity-prior RANSAC floor alignment, continuous corridor-carved 5 cm costmaps, `nerfstudio splatfacto` 3DGS (Apache 2.0), fog-floater / needle / ceiling-spike pruning (`splat_convert.py`), and Level-1 `.ksplat` compression (`11.55 MB`, `480,000` splats).
- **Browser Walkthrough & Live 2D Minimap (`web/src/`):** Captured-lens vertical FOV clamping (`23.9°`), instant colored `cloud.ply` preview before swapping seamlessly into `.ksplat`, WASD/mouse/touch free-roam with wall collision, live 2D minimap (`M`), and `Gaussian splats` / `Point cloud` switcher (`P`).
- **Spatial + Fuzzy POI Search & VCCW/EDT A\* Navigation:** Versioned `pois.json` contract (`9` POIs across 3 rooms, `0` warnings), 1 m spatial bucket + inverted token + Levenshtein `≤ 2` index (`/`), proximity-decluttered 3D & minimap markers without camera jumps, explicit **Jump here** (`?poi=`), clearance-weighted A\* floor routing with landmark-anchored turn-by-turn banners, ETA, off-route rerouting, and click-floor POI tagging (`E`) with JSON export.
- **Interactive Sandbox (`G`) & R3 AR Bonus (`AR`):** Pick-and-place physical props (`Cone`, `Barrier`, `Crate`, `Sign`) that dynamically carve obstacles into the live A\* router (`6.5 m → 7.7 m` bedroom loop reroute verified live); optional WebRTC camera + QR fiducial relocalization (`anchors.json`).

---

## 2. Original Contributions, Licensing & Cost Economics

- **Original Team Code (MIT):** Capture SOP, 6-gate QA & IMU blur analyzer, Apache-2.0 `DISK+LightGlue` GPU SfM integration, pairwise median metric scale fusion, bed-rejecting gravity RANSAC floor aligner & continuous corridor costmap, fog-floater/needle/spike pruner, QR fiducial solver, POI validator, and the complete static TypeScript/WebGL viewer, spatial/fuzzy index, VCCW A\* router, and dynamic sandbox.
- **Commercial-Use Open-Source Stack:** `pycolmap 4.2.1` (BSD 3-Clause), `Kornia DISK + LightGlue` (Apache 2.0), `Depth-Anything-V2-Metric-Indoor-Small-hf` (Apache 2.0), `nerfstudio`/`gsplat` (Apache 2.0), `PyTorch` (BSD 3-Clause), `transformers` (Apache 2.0), `OpenCV`/`NumPy`/`SciPy` (Apache 2.0 / BSD), `Three.js`/`@mkkellogg/gaussian-splats-3d` (MIT), `Vite`/`TypeScript`/`Vitest`/`Pytest` (MIT), `FFmpeg` (CLI).
- **Third-Party API vs. Own GPU Cost Analysis:** Static `.ksplat` delivery incurs **$0/view** runtime fees. Based on our measured `home_v1` runtime (`95 min` T4 / `40 min` L4), self-hosted cloud GPUs cost **`$0.50–$0.56/scene`** (`$530` / 1,000 scenes) vs. **`$2.50–$5.50/scene`** (`$3,200–$6,000+` / 1,000 scenes) for managed commercial 3D APIs (**82–90% savings**); an owned RTX 4070 workstation (`$600` capex) breaks even at **~200 scenes**. See [`Technical_Abstract_Topoloka.pdf`](Technical_Abstract_Topoloka.pdf) for the full breakdown.

---

## 3. Verified Code Health & Team Capture Results (`home_v1`)

- **Automated Verification:** **30/30** pipeline `pytest` tests + **63/63** web `vitest` tests + strict `tsc --noEmit` + Vite static production build + live Chrome D3D11 Playwright E2E (`51.5 FPS`, `0` console/HTTP errors) all passing.

| Metric | Measured (`home_v1`) | Evidence |
|---|---|---|
| Raw Capture & Rooms Covered | 3 rooms (Entry Study Room, Central Hall, Master Bedroom loop); `98.6 s` → `75.0 s` indoor trim (`1280×576 @ 30 fps`) | `home_v1_raw_full.mp4`, `frames_meta.json` |
| SfM Ablation & Registration | SIFT 3 Hz `15.6%` → **DISK+LightGlue 5 Hz `296/375` (`78.9%`, 293-frame continuous 3-room loop, `51,304` 3D pts)** | `test/home_v1/sfm/sfm_report.json` |
| Metric Scale (Apache-2.0 Depth Small) | `scale = 0.65836 m/unit` · `MAD = 11.88%` (`55,274` samples) · `camera_height = 0.868 m` | `depth_report.json`, `nav_report.json` |
| `.ksplat` Payload, Walkable Area & FPS | **`11.55 MB`** Level-1 `.ksplat` (`480,000` splats) · **`22.21 m²`** walkable (`0` geom warnings) · **`51.5 FPS`** | `web/meta.json`, Playwright E2E |
| Authored POIs & Live Sandbox Reroute | **9 POIs** (`0` warnings) · `"wardobe"` → `Wooden Wardrobe` · 3-room A\* `9.8 m` · Sandbox barrier reroute **`6.5 m` → `7.7 m`** (`2.4 m` → `5.4 m` from Bedroom Entry) | `nav/pois.json`, Playwright E2E |
| Honest QA Paper Trail | `PASS` (frame count, floor outline, geom warnings, POIs); `WARN` (78.9% reg); `FAIL` (p10=26 soft walls, 1.569 px CNN DISK grid) | `test/home_v1/capture_qa.md` |
