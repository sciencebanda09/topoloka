# TOPOLOKA: Master Submission Document and Supplementary Materials

**Techfest 2026-27, IIT Bombay — Namma Space Competition (Round 2 Official Deliverable)**

| Submission Details | Verification & Access |
|---|---|
| **Author / Lead** | **Shashank Dev** (`coderperson043@gmail.com`) |
| **Team ID** | **TM-60A7F03511D** |
| **Competition ID** | **NAMM-B3B981411E93** |
| **Official Google Drive Folder** | [Google Drive Submission Folder](https://drive.google.com/drive/folders/1vY_eKNKpsiaX1dGYe3TORipPhjcY-D5I?usp=sharing) |
| **Live Free-Roam Web Twin (R2)** | [https://sciencebanda09.github.io/topoloka/](https://sciencebanda09.github.io/topoloka/) |
| **Source Code Repository** | [https://github.com/sciencebanda09/topoloka](https://github.com/sciencebanda09/topoloka) (MIT License) |
| **R2 Evidence Pack** | [`docs/r2_evidence.md`](https://github.com/sciencebanda09/topoloka/blob/main/docs/r2_evidence.md) |
| **Demo Walkthrough Video (R2)** | [topoloka_r2_demo.mp4](https://github.com/sciencebanda09/topoloka/releases/download/r2-demo/topoloka_r2_demo.mp4) (4:11, 1080p30) |
| **Demo Walkthrough Video (R1)** | [topoloka_demo.mp4](https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4) (3:33, 1080p30) |
| **Technical Abstract (PDF)** | [`submission/Technical_Abstract_Topoloka.pdf`](Technical_Abstract_Topoloka.pdf) (IEEE/ACM format) |
| **Kaggle Cloud Pipelines** | [`kaggle/kernels/`](https://github.com/sciencebanda09/topoloka/tree/main/kaggle/kernels) ($0.00 compute expenditure) |

---

## 1. Master Links and Supplementary Drive Index

All project deliverables, interactive web demonstrators, video recordings, and source code are consolidated in the master index below:

| Deliverable | Resource / Access URL | Description |
|---|---|---|
| **Live Free-Roam Web Twin (R2)** | [https://sciencebanda09.github.io/topoloka/](https://sciencebanda09.github.io/topoloka/) | WebGL 3DGS viewer. Default opens **Melbourne Metro (`metro_v1`)** with 7 authored POIs, spatial+fuzzy search, A* navigation, interactive sandbox, and R3 QR-AR preview; dropdown switches to **Studio Room (`room`)**. Runs at 50–60 FPS. |
| **Source Code Repository** | [https://github.com/sciencebanda09/topoloka](https://github.com/sciencebanda09/topoloka) | End-to-end codebase: capture SOP, IMU QA, SfM pipeline, depth metricization, 3DGS export, QR anchor solver, POI contract, and Vite/TypeScript WebGL client. MIT Open Source. |
| **Demo Walkthrough Video (R2)** | [topoloka_r2_demo.mp4](https://github.com/sciencebanda09/topoloka/releases/download/r2-demo/topoloka_r2_demo.mp4) | 4:11 1080p30 H.264+AAC walkthrough of POI search, explicit jump, obstacle-aware navigation, sandbox barrier rerouting (31.66 m to 31.86 m), POI authoring/JSON export, and verification. |
| **Demo Walkthrough Video (R1 baseline)** | [topoloka_demo.mp4](https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4) | 3:33 1080p30 walkthrough of baseline first-person roaming, minimap synchronization, and Studio Room orientation controls. |
| **Technical Abstract (PDF)** | [`submission/Technical_Abstract_Topoloka.pdf`](Technical_Abstract_Topoloka.pdf) | Formal IEEE/ACM report detailing mathematical formulation, pipeline architecture, POI/navigation stack, and empirical benchmarks. |
| **Kaggle Cloud Pipelines** | [`kaggle/kernels/`](https://github.com/sciencebanda09/topoloka/tree/main/kaggle/kernels) | Automated GPU scripts executing frame extraction, pycolmap SfM, Depth Anything V2 metric alignment, and splatfacto training ($0.00 total compute cost). |
| **Supplementary Artifacts** | [`web/public/artifacts/`](https://github.com/sciencebanda09/topoloka/tree/main/web/public/artifacts) | Pre-computed Gaussian splat binaries (`splat.splat`), camera trajectory matrices (`nav.json`), POIs (`pois.json`), and metadata logs (`meta.json`). |

---

## 2. Executive Summary

### Overview
**Topoloka** (*topos* [place] + *loka* [world]) is a spatial intelligence engine that converts a standard smartphone walk-through video into an interactive, metric 3D digital twin delivered as a lightweight, zero-install web link.

Unlike traditional photogrammetry or laser scanning pipelines that require expensive proprietary LiDAR hardware, Topoloka achieves sub-decimeter metric fidelity directly from consumer video. The Round 2 system adds structured Points of Interest (`pois.json`), multi-word spatial+fuzzy search, A* obstacle-aware turn-by-turn wayfinding, an interactive physics/costmap sandbox (`G`), in-browser POI authoring/export (`E`), IMU/EIS capture validation, and Round 3 QR-anchor AR wayfinding foundations.

### Key Capabilities
- **Consumer Monocular Video Input:** Uses ordinary 4K/1080p video recorded on any modern smartphone following our capture SOP (`capture/SOP.md`).
- **Metric Scaling via Foundation AI:** Integrates Depth Anything V2 Metric Indoor Large to infer true real-world scale (meters per scene unit) without LiDAR or stereo cameras.
- **Sub-50 MB Static Web Payload:** Delivers 3D Gaussian Splats (`1.59M` Gaussians in `room`, `457k` in `metro_v1`) over static GitHub Pages with adaptive resolution scaling.
- **Built-in 2.5D Obstacle Costmap & A\* Navigation:** Outputs a metric 5 cm occupancy grid with trajectory corridor clearing, preventing wall pass-through and computing live turn-by-turn paths (`31.66 m` end-to-end Metro route; `31.86 m` around user-placed barriers).
- **Spatial POI Search & In-Browser Authoring:** Supports versioned `pois.json` (`test/` + live UI authoring/export), multi-word Levenshtein + token search, category chips, and explicit click-to-jump / navigate cards.
- **R3 AR Mode Preview (`AR`):** Supports WebRTC camera feed, Web `BarcodeDetector` QR scanning / simulated anchor relocalization against `anchors.json` (`namma anchors`), and real-time directional HUD arrow guidance.

---

## 3. Measured Benchmarks and Empirical Performance

| Performance Metric | Studio Room Twin (`room`) | Melbourne Metro Benchmark (`metro_v1`) |
|---|---|---|
| **Gaussian Splats** | **1,593,376** (30,000 iterations) | **457,221** (25,000 iterations) |
| **Walkable Area** | **73.30 m²** | **315.05 m²** |
| **Registration Rate** | 100% full coverage | **216 / 216 frames (100.0%)** |
| **Reprojection Error** | Sub-pixel | **0.403 px median** (0.613 px mean) |
| **Metric Scale Accuracy** | Calibrated indoor benchmark | **6.2505 m/unit (7.54% MAD)** |
| **Authored POIs & Route** | Optional authoring via `E` | **7 POIs (5 categories) · 31.66 m route** |
| **Total Artifact Payload** | 48.6 MB (Binary Splat + Nav) | 18.4 MB (Splat + Cloud + Nav + POIs) |
| **Desktop / Mobile FPS** | **48–60 FPS** | **51–60 FPS** |
| **Total Cloud GPU Cost** | **$0.00** (Kaggle Free Tier) | **$0.00** (Kaggle Free Tier) |

---

## 4. Google Drive Submission Folder Structure

1. **`MASTER_SUBMISSION_DOCUMENT.pdf`**: This master document compiling all supplementary links and benchmarks.
2. **`Technical_Abstract_Topoloka.pdf`**: Formal IEEE/ACM technical abstract (`docs/abstract.pdf`).
3. **`Proof_of_Concept_Web_Viewer_Link.txt`**: Direct URL and feature summary for the live hosted WebGL twin.
4. **`Demonstration_Video_Link.txt`**: Direct URLs for the R2 (4:11) and R1 (3:33) 1080p walkthrough videos.
5. **`Code_Repository_Link.txt`**: Direct URL and overview of the MIT-licensed GitHub repository.
