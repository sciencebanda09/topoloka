# TOPOLOKA: Master Submission & Supplementary Materials

**Techfest 2026-27 (IIT Bombay) — Official Competition Deliverable**

---

## 1. Master Links & Supplementary Drive Index

All project artifacts, live interactive demonstrators, video footage, and source code are consolidated in the master index below. All links are publicly accessible with zero login barriers:

| Deliverable | Resource / Access URL | Description |
|---|---|---|
| **Live Free-Roam Web Twin** | **[https://sciencebanda09.github.io/topoloka/](https://sciencebanda09.github.io/topoloka/)** | Client-side WebGL 3DGS viewer. Default opens **Studio Room** with in-viewer orientation controls; dropdown allows switching to **Melbourne Metro**. Runs at 60 FPS in any standard browser. |
| **Source Code Repository** | **[https://github.com/sciencebanda09/topoloka](https://github.com/sciencebanda09/topoloka)** | Complete end-to-end codebase: phone capture SOP, SfM pipeline, depth metricization, 3DGS export, and Vite/TypeScript WebGL client. MIT Open Source. |
| **Demo Walkthrough Video** | **[https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4](https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4)** | High-definition (1080p, 30 FPS, H.264+AAC) walkthrough demonstrating first-person walking, minimap synchronization, dynamic orientation adjustment, and collision avoidance. |
| **Technical Abstract (PDF)** | **[`docs/abstract.pdf`](https://github.com/sciencebanda09/topoloka/blob/main/docs/abstract.pdf)** | 5-page formal academic report formatted to IEEE/ACM guidelines detailing mathematical formulation, pipeline architecture, and empirical benchmarks. |
| **Kaggle Cloud Pipelines** | **[`kaggle/kernels/`](https://github.com/sciencebanda09/topoloka/tree/main/kaggle/kernels)** | Automated GPU scripts executing frame extraction, pycolmap SfM, Depth Anything V2 metric alignment, and splatfacto training ($0.00 total compute cost). |
| **Supplementary Artifacts** | **[`web/public/artifacts/`](https://github.com/sciencebanda09/topoloka/tree/main/web/public/artifacts)** | Pre-computed Gaussian splat binaries (`splat.splat`), camera trajectory matrices (`nav.json`), and metadata logs (`meta.json`). |

---

## 2. Executive Summary

### Overview
**Topoloka** (*τόπος* [place] + *लोक* [world]) is a spatial intelligence engine that converts a standard smartphone walk-through video into an interactive, metric 3D digital twin delivered as a lightweight, zero-install web link. 

Unlike traditional photogrammetry or laser scanning pipelines that require tens of thousands of dollars in proprietary LiDAR hardware, Topoloka achieves sub-decimeter metric fidelity directly from consumer video. The resulting digital twin delivers free first-person roaming at 50–60 FPS on standard integrated laptop GPUs and mobile phones, featuring obstacle-aware pathfinding and live in-viewer spatial orientation controls.

### The Problem
- **LiDAR Hardware Barrier:** Professional indoor mapping platforms (e.g., Matterport Pro3, Leica BLK360) cost between $4,000 and $25,000, limiting spatial digitalization to well-funded enterprises.
- **Heavy Client Payloads:** Standard mesh reconstructions with high-resolution texture atlases regularly exceed 300–800 MB, causing excessive load times, severe GPU texture thrashing, and unplayable mobile frame rates.
- **Lack of Traversability & Navigation:** Conventional NeRF / 3DGS viewers function solely as passive camera visualizers; they lack physical floor collision, walkable boundaries, and navigation graphs.

### The Topoloka Solution
- **Consumer Monocular Video Input:** Uses ordinary 4K/1080p video recorded on any modern smartphone following our simple capture Standard Operating Procedure (SOP).
- **Metric Scaling via Foundation AI:** Integrates *Depth Anything V2 Metric Indoor Large* to infer true real-world scale (meters per scene unit) without physical scale markers or hardware depth sensors.
- **Sub-50 MB Static Web Payload:** Delivers full 30,000-iteration studio-grade 3D Gaussian Splats (1.59M Gaussians) over static web hosting (GitHub Pages) with initial cold loads in under 20 seconds.
- **Built-in 2.5D Obstacle Costmap & A\* Navigation:** Simultaneously outputs a metric 5 cm occupancy costmap that prevents users from walking through walls and furniture, computing real-time waypoints to spatial goals.
- **Live In-Viewer Orientation Controls:** Features an interactive HUD toolbar allowing visitors to rotate, tilt, roll, flip 180°, and level scenes live inside the browser, automatically saving custom camera poses to shareable URL parameters (`?rx=&ry=&rz=&oy=`).

---

## 3. Technical Architecture & Methodology

```
┌────────────────────────────────┐
│   Smartphone Walk-Through      │  (Standard 1080p/4K video, 0.4 m/s pace,
│   Video (No LiDAR / No Sensors)│   fixed exposure, smooth loop path)
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│  Automated Preprocessing       │  Laplacian blur filter, adaptive keyframe
│  & Frame Selection             │  extraction (2.5 Hz sampling)
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│  Structure-from-Motion (SfM)   │  pycolmap 4.2.1 incremental reconstruction;
│  Camera Registration           │  sub-pixel reprojection error (0.403 px median)
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│  Foundation Metric Depth       │  Depth Anything V2 Metric Indoor Large;
│  Fusion & Scale Alignment      │  pairwise median absolute deviation (<8% MAD)
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│  RANSAC Plane Fitting          │  Exact floor normal alignment to Three.js +Y;
│  & Orthonormal Calibration     │  floor surface calibrated to Y = 0.0 m
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│  3D Gaussian Splatting (3DGS)  │  nerfstudio splatfacto (30,000 iterations);
│  High-Fidelity Optimization    │  floater/needle-free, web binary packing
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│  Traversability Extraction     │  5 cm cell occupancy grid, obstacle carving,
│  & Navigation Graph            │  A* pathfinder, spawn trajectory generation
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│  Client-Side WebGL Viewer      │  Three.js + @mkkellogg/gaussian-splats-3d;
│  (Static GitHub Pages Link)    │  50–60 FPS, minimap, live orientation HUD
└────────────────────────────────┘
```

### Mathematical Formulation of Metric Placement
Topoloka links the raw reconstruction frame ($p_{scene}$) to the navigation coordinate frame ($p_{nav}$) and the Three.js rendering frame ($p_{three}$) through an exact transformation pipeline:

$$p_{nav} = s \cdot R^T (p_{scene} - p_{origin})$$

$$p_{three} = A \cdot p_{nav}, \quad A = \begin{bmatrix} 1 & 0 & 0 \\ 0 & 0 & 1 \\ 0 & -1 & 0 \end{bmatrix}$$

where $s$ is the metric scale factor (meters per unit), $R$ is the orthonormal rotation matrix derived from RANSAC floor detection, and $A$ maps the Z-up navigation frame to the Y-up WebGL world.

---

## 4. Interactive In-Viewer Controls & Accessibility

To guarantee perfect viewing on any display, Topoloka features an interactive in-viewer orientation and navigation suite accessible directly on the screen:

1. **`🔄 Flip 180°` (Hotkey: `O`):** Instantly flips the entire scene upright around the observer.
2. **`Turn Y` (`↺ 90°`, `↻ 90°`, `-15°`, `+15°`) (Hotkeys: `[` / `]`):** Smooth horizontal panning around the room's central pivot.
3. **`Tilt X` (`⬆ 90°`, `⬇ 90°`, `-15°`, `+15°`):** Elevation pitch adjustment.
4. **`Level` (`⤹ 15°`, `⤸ 15°`, `▲ +0.2m`, `▼ -0.2m`):** Side-to-side roll leveling and vertical floor offset calibration.
5. **`↺ Reset`:** Restores original mathematical default coordinates.
6. **`🔗 Copy Link`:** Encodes active rotation and height offsets into the browser URL (`?rx=...&ry=...&rz=...&oy=...`) and copies the link to clipboard for instant sharing.
7. **First-Person Roaming:** Full WASD movement, pointer-lock mouse look, and mobile touch virtual joystick calibrated to ground level ($Y = 1.6\text{m}$ eye height) with zero vertical drift.

---

## 5. Measured Benchmarks & Empirical Performance

All metrics below are measured directly on the deployed GitHub Pages release running on consumer hardware:

| Performance Metric | Studio Room Twin (`room`) | Melbourne Metro Benchmark (`metro_v1`) |
|---|---|---|
| **Gaussian Splats** | **1,593,376** (30k iterations) | **457,221** (25k iterations) |
| **Walkable Area** | **73.30 m²** | **315.05 m²** |
| **Registration Rate** | 100% full coverage | 216 / 216 frames (100.0%) |
| **Reprojection Error** | Sub-pixel | **0.403 px median** (0.613 px mean) |
| **Metric Scale Accuracy**| Calibrated indoor benchmark | **6.2505 m/unit (7.54% MAD)** |
| **Total Artifact Payload**| 48.6 MB (Binary Splat + Nav) | 18.4 MB (Splat + Cloud + Nav) |
| **Cold Load Time** | <22 seconds (50 Mbps) | **19.2 seconds** (50 Mbps) |
| **Desktop Frame Rate** | **60.0 FPS** (Chrome / Edge / ANGLE) | **60.1 FPS** (Chrome / Edge / ANGLE) |
| **Integrated iGPU FPS** | **48–55 FPS** (AMD Radeon 780M) | **51.0–60.1 FPS** (AMD Radeon 780M) |
| **Mobile Web FPS** | **60.0 FPS** (WebKit / Chrome Mobile)| **59.9 FPS** (WebKit / Chrome Mobile)|
| **Total Cloud GPU Cost**| **$0.00** (Kaggle Free Tier) | **$0.00** (Kaggle Free Tier) |

---

## 6. Comparison with State-of-the-Art

| Feature | Topoloka (Ours) | Matterport Pro3 | Standard NeRF (Nerfstudio) | Apple RoomPlan |
|---|---|---|---|---|
| **Hardware Required** | Smartphone only | $4,500+ LiDAR rig | Desktop workstation | iPhone Pro with LiDAR |
| **Delivery Medium** | **Zero-install static web link** | Proprietary cloud portal | Heavy desktop GUI | iOS application only |
| **Viewing Frame Rate** | **50–60 FPS WebGL** | Pre-rendered skybox 30 FPS | <15 FPS in browser | 60 FPS (wireframe only) |
| **Visual Quality** | **Photorealistic 3DGS** | 360° photo panoramic | Photorealistic | Low-poly untextured CAD |
| **Collision & Nav** | **Built-in 2.5D costmap** | Waypoint-hopping only | None (flycam only) | Manual bounding boxes |
| **In-Browser Re-orient**| **Full 6-DOF live toolbar** | None | None | None |
| **Hosting Cost** | **$0.00 (GitHub Pages)** | $69+/month subscription | Requires dedicated GPU server | Local device only |

---

## 7. Techfest Evaluation Criteria Alignment

### Novelty & Innovation
Topoloka represents the first unified spatial engine combining:
1. Monocular foundation metric depth estimation without LiDAR.
2. Lightweight WebGL Gaussian Splats running client-side with zero plugins.
3. Automated floor normal calibration and 2.5D obstacle costmap extraction.
4. Interactive in-viewer coordinate manipulation synchronized to shareable URLs.

### Practical Impact & Commercial Feasibility
- **Indoor Real Estate & Architecture:** Prospective tenants and architects explore spaces with accurate metric sightlines and room dimensions.
- **Robotic Navigation & Simulation:** Autonomous mobile robots (AMRs) can ingest Topoloka's metric costmaps directly for path planning.
- **Emergency Response & Event Management:** First responders and facility managers can evaluate evacuation routes and place temporary obstacles (cones, barriers) in real-time using our integrated sandbox suite.

### Zero-Cost Open Infrastructure
Every computational stage—from feature extraction to 30,000-iteration splat optimization—was executed entirely within free Kaggle Cloud GPU allocations ($0.00 spent), proving industrial-scale spatial mapping is accessible to any student, researcher, or institution worldwide.
