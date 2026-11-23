# TOPOLOKA: Master Submission & Supplementary Materials

**Techfest 2026–27 (IIT Bombay) — Namma Space Round 2 Official Deliverable**

| Submission Field | Details / Access |
|---|---|
| **Author / Lead** | **Shashank Dev** (`coderperson043@gmail.com`) |
| **Team / Competition ID** | `TM-60A7F03511D` · `NAMM-B3B981411E93` |
| **Official Google Drive Folder** | [Google Drive Submission Folder](https://drive.google.com/drive/folders/1vY_eKNKpsiaX1dGYe3TORipPhjcY-D5I?usp=sharing) |
| **Live Web App (R2 — `home_v1`)** | [https://sciencebanda09.github.io/topoloka/](https://sciencebanda09.github.io/topoloka/) |
| **Source Code Repository** | [https://github.com/sciencebanda09/topoloka](https://github.com/sciencebanda09/topoloka) (`main` & synced `r2-pois-nav`, MIT License) |
| **Technical Abstract & SOP (PDF)** | [`docs/abstract.pdf`](https://github.com/sciencebanda09/topoloka/blob/main/docs/abstract.pdf) (4 pages, ≤ 5-page limit) |
| **R2 Evidence Pack** | [`docs/r2_evidence.md`](https://github.com/sciencebanda09/topoloka/blob/main/docs/r2_evidence.md) |
| **Raw Capture Video (SOP Proof)** | `home_v1_raw_full.mp4` (`98.6 s`, `1280×576 @ 30 fps` — see Google Drive folder) |
| **Narrated Demo Video (R2, 3–5 min)** | `[Own-voice 1080p30 walkthrough of home_v1 — see Google Drive folder]` |

---

## 1. Executive Summary

**Topoloka** (*τόπος* [place] + *लोक* [world]) converts a single continuous smartphone walkthrough video into a **hybrid metric 3D digital twin** — combining photorealistic compressed **3D Gaussian Splats (`.ksplat`)** with a **5 cm metric 2.5D occupancy costmap** — served as a zero-backend static web application running at **~51.5 FPS** in desktop and mobile browsers.

All third-party and public datasets (`room`, `playroom`, `guildhall-*`, `metro_v1`) have been purged. The sole deployed scene (`test/home_v1/`) is reconstructed end-to-end from our team's own 3-room flat walkthrough (`Entry Study Room`, `Central Hall`, and full closed loop through the `Master Bedroom`).

### Core Round 2 Capabilities
- **Deterministic Multi-Room Capture SOP (`capture/SOP.md`):** Specifies phone lens, 4K/30 landscape (1080p/720p fallback), EIS OFF, AE/AF lock, lighting, `0.4 m/s` pace, `1.2–2.0 m` wall stand-off, dual-tilt passes (`+10°` / `-20°`), 3-second corner arc sweeps, doorway/stairwell transitions, optional 2D plan & 2.00 m scale photos, and an automated QA analyzer (`namma qa`).
- **Commercially Licensed Reconstruction Pipeline (`pipeline/namma/`):** Uses **Kornia `DISK + LightGlue` (Apache 2.0)** + `pycolmap 4.2.1` (`CameraMode.SINGLE`), **`Depth-Anything-V2-Metric-Indoor-Small-hf` (Apache 2.0 — zero `CC-BY-NC` weights)** with doorway flying-pixel masking (`|∇D|/D < 0.055`), bed-rejecting gravity-prior RANSAC floor alignment (`floor_z = 0.0 m`, `camera_height = 0.857 m`), continuous corridor-carved 5 cm costmaps (`21.71 m²`), `nerfstudio splatfacto-big` 3DGS (Apache 2.0, 30k iters, `SO3xR3` pose refinement, `max_gauss_ratio = 3.5` reducing `p99.9` spike ratio `9,647:1 → 3.78:1`), cigar-spike / floater pruning (`splat_convert.py`), and spatial-sorted Level-1 `.ksplat` compression (`13.95 MB`, `580,000` Gaussians).
- **Browser Walkthrough & 2D Minimap (`web/src/`):** Clamps vertical FOV to the captured smartphone lens shell (`21.5°` with `0.90` inner margin) at `1.5×` HiDPI to eliminate unobserved ceiling voids, streams an instant `cloud.ply` preview before swapping seamlessly into `.ksplat`, and supports WASD/mouse/touch roaming with 5 cm wall collision, live 2D minimap (`M`), and `Gaussian splats` / `Point cloud` model switcher (`P`).
- **Spatial + Fuzzy POI Search & A\* Navigation:** Versioned `pois.json` contract (`9` validated POIs across all 3 rooms, `0` warnings), 1 m spatial bucket + inverted token + Levenshtein `≤ 2` index (`/`), proximity-decluttered 3D & minimap markers without unwanted camera jumps, explicit **Jump here** (`?poi=`), VCCW/EDT clearance-weighted A\* floor routing with landmark-anchored turn-by-turn banners, ETA, 1.2 m off-route rerouting, 0.7 m arrival detection, and in-browser click-floor POI tagging (`E`) with JSON export.
- **Interactive Sandbox (`G`) & R3 AR Bonus (`AR`):** Pick-and-place physical props (`Cone`, `Barrier`, `Crate`, `Sign`) that dynamically carve obstacles into the A\* router (`6.5 m → 7.7 m` Central Hall → Bedroom loop reroute verified live); optional WebRTC camera + QR fiducial relocalization (`anchors.json`, `namma anchors`) for directional AR overlays.

---

## 2. System Architecture & Coordinate Contract

```
[Team Smartphone Walkthrough Video (home_v1_raw_full.mp4 -> 75 s indoor trim)]
           │
           ▼
[Kaggle GPU Pipeline (DISK+LightGlue SfM + T4 Depth & 3DGS)]
   ├─ Stride-Adaptive Blur Filter (frames.py, Laplacian variance @ 5.0 Hz -> 375 frames)
   ├─ Learned GPU SfM (sfm.py, Kornia DISK+LightGlue Apache 2.0 + pycolmap 4.2.1 -> 296/375 = 78.9%)
   ├─ Commercial Metric Depth Fusion (depth.py, Depth-Anything-V2-Metric-Indoor-Small Apache 2.0, edge-masked 732k voxels)
   ├─ Bed-Rejecting Gravity RANSAC Floor & 5 cm Costmap (geometry.py -> 21.71 m², 0 warnings)
   ├─ Anti-Spike 3DGS Training & Pruning (nerfstudio splatfacto-big 30k SO3xR3 + scale reg + splat_convert.py)
   ├─ Spatial Bucket Level-1 .ksplat Compression (convert_to_ksplat.mjs -> 13.95 MB, 580k splats)
   └─ Automated QA, 9-POI Validation & QR Anchors (qa.py, pois.py, anchors.py, package.py)
           │
           ▼
[Static Artifact Bundle (test/home_v1/web/, 17.7 MB web / 19.42 MB total committed)]
           │
           ▼
[Client-Side WebGL Viewer (Static GitHub Pages, $0/view runtime cost, 33.6–51.5 FPS @ 1.5x HiDPI)]
   ├─ Instant Point-Cloud Preview → Level-1 .ksplat Streaming (@mkkellogg/gaussian-splats-3d)
   ├─ Captured-VFOV First-Person Roaming, Collision & Live 2D Minimap (controls.ts, minimap.ts)
   ├─ Spatial + Fuzzy POI Search & Click-Floor Authoring (pois.ts, ui.ts)
   ├─ VCCW/EDT A* Wayfinding & Dynamic Obstacle Sandbox (nav.ts, navigation.ts, sandbox.ts)
   └─ R3 Bonus QR-Anchor AR Overlay (ar.ts)
```

Exact metric transformation from reconstruction space (`p_scene`) to Z-up metric navigation (`p_nav`) and Y-up WebGL (`p_three`):

```text
s       = median( D_metric(u, v) / Z_sfm(u, v) )   [measured home_v1: 0.65836 m/unit]
p_nav   = s · R^T · (p_scene - p_origin)
p_three = A · p_nav,    A = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]
```

---

## 3. Original Contributions, Commercial Licensing & Infrastructure Cost

- **Original Team Code (MIT):** Capture SOP, 6-gate QA & IMU blur analyzer, Apache-2.0 `DISK+LightGlue` GPU SfM integration, pairwise median metric scale fusion, bed-rejecting gravity RANSAC floor aligner & continuous corridor costmap, fog-floater/needle/spike pruner, QR fiducial pose solver, POI schema/validator, and the full static TypeScript/WebGL viewer (captured-VFOV clamping, proximity marker decluttering, spatial/fuzzy index, VCCW A\* router, and dynamic sandbox).
- **Commercial-Use Third-Party Stack:** `pycolmap 4.2.1` (BSD 3-Clause), `Kornia DISK + LightGlue` (Apache 2.0), `Depth-Anything-V2-Metric-Indoor-Small-hf` (Apache 2.0), `nerfstudio`/`gsplat` (Apache 2.0), `PyTorch` (BSD 3-Clause), `transformers` (Apache 2.0), `OpenCV`/`NumPy`/`SciPy` (Apache 2.0 / BSD), `Three.js` & `@mkkellogg/gaussian-splats-3d` (MIT), `Vite`/`TypeScript`/`Vitest`/`Pytest` (MIT), `FFmpeg` (CLI). Zero `CC-BY-NC` weights.
- **API vs. Own GPU Cost Analysis:** Static `.ksplat` delivery incurs **$0/view** runtime API fees. Based on our measured `home_v1` runtime (`95 min` on T4 / `40 min` L4 / `22 min` RTX 4070), self-hosted cloud GPUs cost **`$0.50–$0.56/scene`** (`$530` for 1,000 scenes) vs. **`$2.50–$5.50/scene`** (`$3,200–$6,000+` for 1,000 scenes) for managed commercial 3D APIs — an **82–90% reduction**. An owned RTX 4070 workstation (`$600` capex + `$0.01`/scene power) breaks even at **~200 scenes**. Full table in [`docs/abstract.pdf`](https://github.com/sciencebanda09/topoloka/blob/main/docs/abstract.pdf).

---

## 4. Verified Results (`home_v1` + Automated Test Suite)

### Automated Code & Browser Verification

| Check | Command / Harness | Measured Result |
|---|---|---|
| Pipeline unit tests | `python -m pytest pipeline/tests` | **30 / 30 pass** (floater/needle pruner, RANSAC, IMU, QR anchors, POIs, metricize, SfM API) |
| Web unit tests | `cd web && npm test` | **63 / 63 pass** (`pois`, `nav`, `navigation`, `splat`, `ar`) |
| TypeScript & Vite build | `cd web && npm run typecheck && npm run build` | **Pass** (`tsc --noEmit` + static `web/dist/` bundle) |
| Live Chrome WebGL E2E | Playwright D3D11 (`1440×810`) on `home_v1` | **`51.5 FPS`**, **0 console errors**, **0 failed HTTP requests** |

### Self-Captured 3-Room Twin Metrics (`test/home_v1/`)

| Metric | Measured (`home_v1`) | Source Artifact |
|---|---|---|
| **Raw Capture & Rooms** | `98.6 s` → `75.0 s` indoor trim (`1280×576 @ 30 fps`); 3 rooms (Entry Study Room, Central Hall, Master Bedroom loop) | `home_v1_raw_full.mp4`, `frames_meta.json` |
| **SfM Ablation (SIFT → DISK+LightGlue)** | `35/225` (`15.6%`) SIFT 3 Hz → **`296/375` (`78.9%`) DISK+LightGlue 5 Hz** (`51,304` 3D pts, unbroken 293-frame 3-room loop) | `sfm/sfm_report.json` |
| **Apache-2.0 Metric Depth Scale** | `scale = 0.65426 m/unit`, `MAD = 15.21%` (`61,019` samples), `732,355` edge-filtered voxels, `camera_height = 0.857 m` | `depth/depth_report.json`, `nav/nav_report.json` |
| **Walkable Area & `.ksplat` Payload** | `21.71 m²` walkable (`207 × 229` @ 5 cm, `0` geometry warnings), **`13.95 MB` `.ksplat`** (`580,000` splats, `p99.9` spike ratio `3.78:1`) | `web/meta.json`, `nav/nav_report.json` |
| **POIs, Fuzzy Search & Multi-Room A\*** | **9 POIs** across 4 categories (`0` warnings); `"wardobe"` → `Wooden Wardrobe`; Entry Study Desk → Bedroom Alcove **`9.6 m`** (*"In 4.6 m, turn left past Refrigerator"*) | `nav/pois.json`, Playwright E2E |
| **Dynamic Sandbox Loop Reroute** | 3 barriers across Wooden Wardrobe corridor reroute Central Hall → Bedroom Alcove **`6.5 m` → `7.7 m`** (Bedroom Entry → Alcove **`2.4 m` → `5.4 m`**) | Playwright E2E (`?props=...`) |
| **Honest QA Notes** | `PASS`: frame count, floor outline, geometry warnings, POI dataset; `WARN`: `78.9%` reg.; `FAIL`: `p10=26` sharpness (soft walls) & `1.569 px` reproj (expected for 8px CNN DISK features) | `capture_qa.json` / `capture_qa.md` |

---

## 5. Round 2 Google Drive Submission Checklist

1. **`MASTER_SUBMISSION_DOCUMENT.pdf`** — This consolidated master document.
2. **`Technical_Abstract_Topoloka.pdf`** — 4-page Technical Abstract & SOP (`docs/abstract.pdf`, ≤ 5 pages) with figures, ablation, commercial license matrix & cost analysis.
3. **`Proof_of_Concept_Web_Viewer_Link.txt`** — Live GitHub Pages URL serving exclusively our self-captured 3-room `home_v1` twin.
4. **`Demonstration_Video_Link.txt`** — Public link to the **own-voice narrated** 3–5 min 1080p30 Round 2 walkthrough + technical overview MP4 + raw capture `home_v1_raw_full.mp4`.
5. **`Code_Repository_Link.txt`** — Public MIT GitHub repository link with `test/home_v1/` committed and reproducible setup.
