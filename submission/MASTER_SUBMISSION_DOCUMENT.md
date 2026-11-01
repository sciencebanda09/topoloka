# TOPOLOKA: Master Submission Document and Supplementary Materials

**Techfest 2026-27, IIT Bombay - Namma Space Competition (Official Competition Deliverable)**

| Submission Details | Verification & Access |
|---|---|
| **Author / Lead** | **Shashank Dev** (`coderperson043@gmail.com`) |
| **Team ID** | **TM-60A7F03511D** |
| **Competition ID** | **NAMM-B3B981411E93** |
| **Official Google Drive Folder** | [Google Drive Submission Folder](https://drive.google.com/drive/folders/1vY_eKNKpsiaX1dGYe3TORipPhjcY-D5I?usp=sharing) |
| **Live Free-Roam Web Twin** | [https://sciencebanda09.github.io/topoloka/](https://sciencebanda09.github.io/topoloka/) |
| **Source Code Repository** | [https://github.com/sciencebanda09/topoloka](https://github.com/sciencebanda09/topoloka) (MIT License) |
| **Demo Walkthrough Video** | [https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4](https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4) |
| **Technical Abstract (PDF)** | [`submission/Technical_Abstract_Topoloka.pdf`](Technical_Abstract_Topoloka.pdf) (4 pages, IEEE/ACM format) |
| **Kaggle Cloud Pipelines** | [`kaggle/kernels/`](https://github.com/sciencebanda09/topoloka/tree/main/kaggle/kernels) ($0.00 compute expenditure) |
| **Local Merged Video** | `topoloka_demo.mp4` (Full HD 1080p, 30 FPS, H.264 + AAC) |

---

## 1. Master Links and Supplementary Drive Index

All project deliverables, interactive web demonstrators, video recordings, and source code are consolidated in the master index below:

| Deliverable | Resource / Access URL | Description |
|---|---|---|
| **Live Free-Roam Web Twin** | [https://sciencebanda09.github.io/topoloka/](https://sciencebanda09.github.io/topoloka/) | WebGL 3DGS viewer. Default opens **Studio Room** with in-viewer orientation controls; dropdown allows switching to **Melbourne Metro**. Runs at 60 FPS in standard browsers. |
| **Source Code Repository** | [https://github.com/sciencebanda09/topoloka](https://github.com/sciencebanda09/topoloka) | Complete end-to-end codebase: smartphone capture SOP, SfM pipeline, depth metricization, 3DGS export, and Vite/TypeScript WebGL client. MIT Open Source. |
| **Demo Walkthrough Video** | [topoloka_demo.mp4](https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4) | High-definition (1080p, 30 FPS, H.264+AAC) walkthrough combining Metro corridor 3DGS roaming, multi-representation point cloud inspection, and Studio Room live HUD orientation controls. |
| **Technical Abstract (PDF)** | [`submission/Technical_Abstract_Topoloka.pdf`](Technical_Abstract_Topoloka.pdf) | Formal 4-page academic report detailing mathematical formulation, pipeline architecture, and empirical benchmarks. |
| **Kaggle Cloud Pipelines** | [`kaggle/kernels/`](https://github.com/sciencebanda09/topoloka/tree/main/kaggle/kernels) | Automated GPU scripts executing frame extraction, pycolmap SfM, Depth Anything V2 metric alignment, and splatfacto training ($0.00 total compute cost). |
| **Supplementary Artifacts** | [`web/public/artifacts/`](https://github.com/sciencebanda09/topoloka/tree/main/web/public/artifacts) | Pre-computed Gaussian splat binaries (`splat.splat`), camera trajectory matrices (`nav.json`), and metadata logs (`meta.json`). |

---

## 2. Executive Summary

### Overview
**Topoloka** (*topos* [place] + *loka* [world]) is a spatial intelligence engine that converts a standard smartphone walk-through video into an interactive, metric 3D digital twin delivered as a lightweight, zero-install web link.

Unlike traditional photogrammetry or laser scanning pipelines that require expensive proprietary LiDAR hardware, Topoloka achieves sub-decimeter metric fidelity directly from consumer video. The resulting digital twin delivers free first-person roaming at 50-60 FPS on standard integrated laptop GPUs and mobile phones, featuring obstacle-aware pathfinding and live in-viewer spatial orientation controls.

### The Problem
- **LiDAR Hardware Barrier:** Professional indoor mapping platforms (e.g., Matterport Pro3, Leica BLK360) cost between $4,000 and $25,000, limiting spatial digitalization to well-funded enterprises.
- **Heavy Client Payloads:** Standard mesh reconstructions with high-resolution texture atlases regularly exceed 300 MB to 800 MB, causing excessive load times, severe GPU texture thrashing, and unplayable mobile frame rates.
- **Lack of Traversability and Navigation:** Conventional NeRF / 3DGS viewers function solely as passive camera visualizers; they lack physical floor collision, walkable boundaries, and navigation graphs.

### The Topoloka Solution
- **Consumer Monocular Video Input:** Uses ordinary 4K/1080p video recorded on any modern smartphone following our simple capture Standard Operating Procedure (SOP).
- **Metric Scaling via Foundation AI:** Integrates Depth Anything V2 Metric Indoor Large to infer true real-world scale (meters per scene unit) without physical scale markers or hardware depth sensors.
- **Sub-50 MB Static Web Payload:** Delivers full 30,000-iteration studio-grade 3D Gaussian Splats (1.59M Gaussians) over static web hosting (GitHub Pages) with initial cold loads in under 22 seconds.
- **Built-in 2.5D Obstacle Costmap and A\* Navigation:** Simultaneously outputs a metric 5 cm occupancy costmap that prevents users from walking through walls and furniture, computing real-time waypoints to spatial goals.
- **Live In-Viewer Orientation Controls:** Features an interactive HUD toolbar allowing visitors to rotate, tilt, roll, flip 180 degrees, and level scenes live inside the browser, automatically saving custom camera poses to shareable URL parameters (`?rx=&ry=&rz=&oy=`).

---

## 3. Measured Benchmarks and Empirical Performance

All metrics below are measured directly on the deployed GitHub Pages release running on consumer hardware:

| Performance Metric | Studio Room Twin (`room`) | Melbourne Metro Benchmark (`metro_v1`) |
|---|---|---|
| **Gaussian Splats** | **1,593,376** (30,000 iterations) | **457,221** (25,000 iterations) |
| **Walkable Area** | **73.30 m²** | **315.05 m²** |
| **Registration Rate** | 100% full coverage | 216 / 216 frames (100.0%) |
| **Reprojection Error** | Sub-pixel | **0.403 px median** (0.613 px mean) |
| **Metric Scale Accuracy**| Calibrated indoor benchmark | **6.2505 m/unit (7.54% MAD)** |
| **Total Artifact Payload**| 48.6 MB (Binary Splat + Nav) | 18.4 MB (Splat + Cloud + Nav) |
| **Cold Load Time** | <22 seconds (50 Mbps) | **19.2 seconds** (50 Mbps) |
| **Desktop Frame Rate** | **60.0 FPS** (Chrome / Edge / ANGLE) | **60.1 FPS** (Chrome / Edge / ANGLE) |
| **Integrated iGPU FPS** | **48 to 55 FPS** (AMD Radeon 780M) | **51.0 to 60.1 FPS** (AMD Radeon 780M) |
| **Mobile Web FPS** | **60.0 FPS** (WebKit / Chrome Mobile) | **59.9 FPS** (WebKit / Chrome Mobile) |
| **Total Cloud GPU Cost**| **$0.00** (Kaggle Free Tier) | **$0.00** (Kaggle Free Tier) |

---

## 4. Google Drive Submission Folder Structure

Per Techfest Page 5 guidelines, all submission materials are organized inside the `submission/` directory:

1. **`MASTER_SUBMISSION_DOCUMENT.pdf`**: This master document compiling all supplementary links and materials.
2. **`Technical_Abstract_Topoloka.pdf`**: 4-page formal technical abstract.
3. **`topoloka_demo.mp4`**: Merged 1080p demonstration video (Metro walkthrough, Point cloud inspection, Studio Room HUD controls).
4. **`Proof_of_Concept_Web_Viewer_Link.txt`**: Direct URL to the live hosted WebGL twin.
5. **`Demonstration_Video_Link.txt`**: Direct URL to the video stream and download.
6. **`Code_Repository_Link.txt`**: Direct URL to the GitHub repository.
