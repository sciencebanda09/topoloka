# Topoloka — Techfest 2026-27 (IIT Bombay) Official Submission Package

---

## 1. Quick Copy-Paste Submission Sheet

| Submission Field | Details / URLs to Enter |
|---|---|
| **Project Name** | **Topoloka** |
| **Project Tagline** | *One video in. Google Maps for indoors out — in a shareable link.* |
| **Live Web App (Free Roam)** | [https://sciencebanda09.github.io/topoloka/](https://sciencebanda09.github.io/topoloka/) |
| **GitHub Repository** | [https://github.com/sciencebanda09/topoloka](https://github.com/sciencebanda09/topoloka) |
| **Demo Video (1080p MP4)** | [https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4](https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4) |
| **Technical Abstract (PDF)** | [`docs/abstract.pdf`](https://github.com/sciencebanda09/topoloka/blob/main/docs/abstract.pdf) (5 pages, fully referenced) |
| **Compute Cost** | **$0.00** (Executed exclusively on free Kaggle GPU T4 nodes; no paid services) |
| **License** | Open Source (MIT License) |

---

## 2. Short Submission Descriptions (For Form Limits)

### 50-Word Summary
> **Topoloka** turns standard smartphone indoor walk-through video into an interactive, photorealistic 3D metric digital twin served via a zero-install web link. Combining 3D Gaussian Splatting, metric depth estimation, and 2.5D obstacle costmaps, it enables free-roam walkthroughs, obstacle-aware pathfinding, and interactive in-viewer orientation controls running smoothly at 60 FPS.

### 100-Word Summary
> Indoor spaces lack the metric street-view mapping available for outdoor worlds. **Topoloka** bridges this gap: upload a single walk-through video, and our automated reconstruction pipeline generates a lightweight, metric 3D digital twin accessible directly in any mobile or desktop web browser. Topoloka integrates structure-from-motion, foundation metric depth fusion (Depth Anything V2), 30k 3D Gaussian Splatting, and gravity-aligned 2.5D occupancy costmaps. Visitors experience photorealistic free-roam exploration, intelligent A* navigation, sandbox spatial layout simulation, and dynamic orientation controls—all computed on free-tier Kaggle GPUs with zero deployment friction.

### 250-Word Summary / Abstract
> **Problem:** Traditional indoor mapping requires expensive LiDAR rigs ($15k+) or manual CAD modeling, while consumer 3D scans typically output heavy, untextured meshes that cannot navigate or run on standard mobile browsers.
>
> **Solution:** **Topoloka** is an end-to-end spatial twin engine that transforms single-pass smartphone video into an ultra-fast, photorealistic, metric indoor twin served via a static URL. Our automated pipeline registers camera poses with pycolmap SfM, anchors metric scale via monocular foundation depth models (Depth Anything V2 Metric Indoor), trains 3D Gaussian Splats, and extracts a 5 cm 2.5D traversability costmap with sub-centimeter floor height calibration.
>
> **Key Innovations:**
> 1. **Zero-LiDAR Metric Fusion:** Derives true metric scale from uncalibrated video with <8% median absolute deviation.
> 2. **Static Web-Native 3DGS:** Custom WebGL drop-in renderer delivering 50–60 FPS on integrated laptop GPUs and smartphones without native plugins.
> 3. **Dynamic In-Link Orientation Toolbar:** Allows users to interactively rotate, tilt, roll, flip 180°, and adjust height directly inside the browser, saving exact camera configurations into shareable URL parameters.
> 4. **Obstacle-Aware Navigation & Sandbox:** Built-in A* route planning across the floor plane, with pick-and-place props that dynamically alter the costmap in real-time.
>
> All training and pipeline execution runs under Kaggle's free GPU tier ($0.00 spent), proving industrial-grade spatial intelligence is achievable on open-source infrastructure.

---

## 3. Detailed Answers for Portal Questions

### Q1: What problem does your project solve?
> Indoor environments (metro stations, conference halls, hospitals, shopping malls, university campuses) remain dark zones for spatial navigation. Unlike roads mapped by GPS and satellite imagery, indoor spaces require specialized equipment, proprietary scanners, or manual architectural plans. Furthermore, existing NeRF and 3DGS viewers require multi-gigabyte downloads or cloud compute servers to stream pixels. Topoloka democratizes indoor twins: anyone can walk through a space with an everyday phone, upload the video, and get a sub-50MB lightweight web link that runs client-side WebGL navigation at 60 FPS.

### Q2: What is the novelty and technical highlight?
> 1. **Dual-Representation Architecture:** Simultaneously produces photorealistic 3D Gaussian Splats for human visual immersion AND a 2.5D metric costmap (5 cm resolution) for robotic/pedestrian collision and pathfinding.
> 2. **Foundation Metric Scaling without Sensors:** Uses Depth Anything V2 Indoor Large to anchor scale without hardware LiDAR or IMU markers.
> 3. **In-Browser Dynamic Orientation & Anchor:** Features live Three.js matrix decomposition with pivot-anchored transforms, allowing users to flip, rotate (yaw/pitch/roll), and level models live in WebGL while synchronizing state to URL query parameters (`?rx=&ry=&rz=&oy=`).
> 4. **Adaptive Fill-Rate Management:** Automatically tunes rendering buffers between 0.6x and 1.0x to guarantee consistent 50–60 FPS on low-power devices.

### Q3: What is the system architecture?
> ```
> [Smartphone Walk-Through Video]
>            │
>            ▼
> [Kaggle Cloud Pipeline]
>    ├─ Frame Extraction & Blur Filter (Laplacian variance)
>    ├─ Structure-from-Motion (pycolmap 4.2.1)
>    ├─ Metric Depth Fusion (Depth Anything V2 Metric Large)
>    ├─ Gravity Alignment & Floor Detection (RANSAC Plane Fitting)
>    ├─ 2.5D Metric Costmap (5 cm occupancy grid)
>    └─ 3D Gaussian Splatting (nerfstudio splatfacto 30k)
>            │
>            ▼
> [Artifact Bundle: splat.splat + nav.json + meta.json]
>            │
>            ▼
> [Client-Side WebGL Viewer (GitHub Pages)]
>    ├─ First-Person Walk Controls (WASD, touch stick, pointer-lock)
>    ├─ Dynamic Scene Re-Sorting & Rendering (@mkkellogg/gaussian-splats-3d)
>    ├─ Interactive Orientation Toolbar (Flip 180°, Turn, Tilt, Height)
>    ├─ Real-Time 2.5D Minimap & A* Route Navigation
>    └─ R2 Sandbox Prop Layering & Collision Re-Carving
> ```

### Q4: What are the measured benchmarks?
> - **Reprojection Error:** 0.403 px median on Melbourne Metro benchmark (216/216 frames registered).
> - **Gaussian Count:** 1,593,376 splats in Pristine Studio Room; 457,221 splats in Melbourne Metro.
> - **Payload Size:** Under 49 MB for complete 30,000-iteration studio capture; loads in <20s on standard 4G/5G connections.
> - **Frame Rate:** 51.0–60.1 FPS on integrated AMD Radeon GPUs; 60 FPS on desktop Chrome/Edge; 60 FPS touch navigation on mobile devices.
> - **Compute Budget:** 100% within free-tier limits ($0.00 compute cost across all runs).

---

## 4. Live Verification Checklist

- [x] **Hosted URL:** [https://sciencebanda09.github.io/topoloka/](https://sciencebanda09.github.io/topoloka/) loads instantly without login.
- [x] **Sample 1 (Studio Room):** 1.59M 3DGS twin, upright and centered, horizontal walk controls (no up/down drift), interactive orientation panel with Flip 180°, Turn Y, Tilt X, Level, and Copy Link.
- [x] **Sample 2 (Melbourne Metro):** Accessible from the sample dropdown, featuring full A* route navigation, minimap, and collision avoidance.
- [x] **Demo Video:** R2 cut on GitHub Releases (4:11, 1080p30, 51.3 MB):
      <https://github.com/sciencebanda09/topoloka/releases/download/r2-demo/topoloka_r2_demo.mp4>;
      R1 baseline remains at <https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4>.
- [x] **Technical Abstract:** 5-page PDF compiled with IEEE/ACM formatting guidelines in `docs/abstract.pdf`.
- [x] **Clean Repository:** All dead links, unverified captures, and private personal captures purged from the public codebase.
