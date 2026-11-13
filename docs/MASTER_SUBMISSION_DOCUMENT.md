# TOPOLOKA: Master Submission & Supplementary Materials

**Techfest 2026-27 (IIT Bombay) — Official Competition Deliverable**

---

## 1. Master Links & Supplementary Drive Index

All project artifacts, live interactive demonstrators, video footage, and source code are consolidated in the master index below. All links are publicly accessible with zero login barriers:

| Deliverable | Resource / Access URL | Description |
|---|---|---|
| **Live Web Twin (R2)** | **[https://sciencebanda09.github.io/topoloka/](https://sciencebanda09.github.io/topoloka/)** | Client-side WebGL 3DGS viewer. Default opens **Melbourne Metro — POIs & navigation** with 7 authored POIs, spatial search, and obstacle-aware routes; dropdown switches to **Studio Room**. Runs at 50–60 FPS in any standard browser. |
| **Source Code Repository** | **[https://github.com/sciencebanda09/topoloka](https://github.com/sciencebanda09/topoloka)** | Complete end-to-end codebase: phone capture SOP, SfM pipeline, depth metricization, 3DGS export, POI validation, and Vite/TypeScript WebGL client. MIT Open Source. |
| **R2 Feature Branch** | **[https://github.com/sciencebanda09/topoloka/tree/r2-pois-nav](https://github.com/sciencebanda09/topoloka/tree/r2-pois-nav)** | Round 2 branch: POI contract/editor, in-browser spatial+lexical index, search UI, POI routing, overlay pass, and browser QA. |
| **R2 Evidence Pack** | **[`docs/r2_evidence.md`](https://github.com/sciencebanda09/topoloka/blob/main/docs/r2_evidence.md)** | Measured route evidence, POI inventory, test/QA results, smoke flow, and the shipped demo shot map. |
| **R2 Demo Video (4:11)** | **[https://github.com/sciencebanda09/topoloka/releases/download/r2-demo/topoloka_r2_demo.mp4](https://github.com/sciencebanda09/topoloka/releases/download/r2-demo/topoloka_r2_demo.mp4)** | 1080p/30 H.264+AAC cut from live Pages captures: POI search, explicit jump, obstacle-aware navigation, sandbox reroute, authoring/export, and verification. |
| **Demo Walkthrough Video (R1 baseline)** | **[https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4](https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4)** | 1080p/30 H.264+AAC walkthrough of first-person walking, minimap sync, orientation controls, and collision avoidance. |
| **Technical Abstract (R1 PDF)** | **[`docs/abstract.pdf`](https://github.com/sciencebanda09/topoloka/blob/main/docs/abstract.pdf)** | Formal academic report detailing the mathematical formulation, pipeline architecture, and R1 empirical benchmarks. |
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
- **Spatial POI Search & Wayfinding:** A versioned `pois.json` contract, an in-browser 1 m bucket index with an inverted token index and Levenshtein fallback, seven authored Metro POIs across five categories, click-to-select markers, and turn-by-turn routes on the same costmap used for collision.
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
│  Traversability & POI Index    │  5 cm occupancy grid, obstacle carving,
│  (Metric Navigation Contract)  │  validated POIs, A* pathfinder, spawn
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│  Client-Side WebGL Viewer      │  Three.js + @mkkellogg/gaussian-splats-3d;
│  (Static GitHub Pages Link)    │  search, POI card, routes, minimap, HUD
└────────────────────────────────┘
```

### Mathematical Formulation of Metric Placement
Topoloka links the raw reconstruction frame (`p_scene`) to the navigation coordinate frame (`p_nav`) and the Three.js rendering frame (`p_three`) through an exact transformation pipeline:

```text
p_nav   = s · Rᵀ · (p_scene − p_origin)

p_three = A · p_nav,    A = [ 1  0  0 ]
                             [ 0  0  1 ]
                             [ 0 -1  0 ]
```

where `s` is the metric scale factor (meters per unit), `R` is the orthonormal rotation matrix derived from RANSAC floor detection, and `A` maps the Z-up navigation frame to the Y-up WebGL world.

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

## 5. R2: POIs, Spatial Search and Obstacle-Aware Navigation

Round 2 turns the free-roam twin into a queryable, routable map. Everything runs
client-side on the same static link; there is no backend.

- **POI contract and authoring.** `nav/pois.json` (version 1) stores id, name,
  category, aliases, description, floor position, radius, and an optional camera
  view. `namma pois` validates schema, unique ids, bounds, free-floor placement,
  radius, and view; `namma package` copies it beside `nav.json`, and `namma qa`
  reports `poi_dataset`. In the viewer, **E** opens a click-floor authoring
  form; tags persist in `localStorage` and **Export pois.json** downloads the
  contract-shaped file.
- **Spatial + lexical index.** The browser builds a 1 m bucket grid for
  proximity queries and an inverted token index over names, aliases, and
  categories, with Levenshtein (≤ 2) fallback and deterministic ranking.
  `?q=` opens a search; selecting a result or 3D marker highlights it without
  moving the camera. **Jump here** or `?poi=<id>` moves to the authored view.
- **Navigation.** **Navigate** plans A* on the same 5 cm costmap used for
  collision (unknown/obstacle blocked, walked path carved, 0.10 m clearance).
  The route renders as a green chevron ribbon in 3D and on the minimap, the
  banner shows instruction and remaining distance, the camera auto-turns toward
  the next waypoint, and the tracker reroutes after 1.2 m off-route and stops
  within 0.7 m of the goal. POIs/route render in a dedicated after-splat pass;
  otherwise the Gaussian pass paints over transparent overlays.
- **Sample dataset.** Seven authored POIs across five categories: Accessible
  Ramp, Tunnel Walkway, Emergency Exit, Advertising Panels, Curved Passage,
  Town Hall Station Sign, and Platforms 1 & 2. Three earlier candidates were
  removed because the shipped splat under-reconstructs their surroundings.
- **Obstacle evidence.** Two barriers placed across the Metro corridor move the
  Tunnel Walkway route from **31.66 m / 2 waypoints** to **31.86 m / 3
  waypoints**; disabling the sandbox restores 31.66 m. This uses the live
  `?props=` path, not a unit-test mock.
- **Verification.** 50 Vitest tests (`pois`, `nav`, `navigation`), 21 pipeline
  tests, and a 76-check Playwright pass covering desktop flow, deep links,
  editor/export, sandbox reroute, sample switching, mobile layout/orientation,
  and 980–1280 px responsive layouts.
- **Demo cut.** The 4:11, 1080p30 release asset is assembled from live browser
  captures and typographic cards: search, explicit jump, navigation, sandbox
  reroute, authoring/export, and the verification matrix. Link:
  <https://github.com/sciencebanda09/topoloka/releases/download/r2-demo/topoloka_r2_demo.mp4>.

---

## 6. Measured Benchmarks & Empirical Performance

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

R2 additions on the Metro twin:

| R2 Metric | Value |
|---|---|
| Authored POIs | **7 across 5 categories** (area 2, landmark 2, facility 1, exit 1, platform 1) |
| Search index | 1 m spatial buckets + inverted token index + Levenshtein ≤ 2 |
| Route to Tunnel Walkway (free) | **31.66 m**, 2 waypoints |
| Route with two barriers | **31.86 m**, 3 waypoints, no footprint crossing |
| Web unit tests | **50 / 50** (`pois`, `nav`, `navigation`) |
| Pipeline tests | **21 / 21** |
| Browser QA | **76 / 76** checks (desktop, mobile, responsive, deep links, sandbox) |
| Live Pages QA | **27 / 27** checks on the public URL |
| R2 demo video | **4:11**, 1920×1080 / 30 fps, H.264 + AAC, 51.3 MB release asset |

---

## 7. Comparison with State-of-the-Art

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

## 8. Techfest Evaluation Criteria Alignment

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

### R2 Criteria Alignment

| Criterion | Shipped evidence |
|---|---|
| **Spatial indexing & POI tagging** | Versioned contract + pipeline validator; in-browser 1 m bucket grid and inverted token index; click-floor editor with local persistence and validated export |
| **Pathfinding accuracy** | A* on the collision costmap with 0.10 m clearance; visible 3D/minimap route; live obstacle reroute measured at 31.66 → 31.86 m; off-route reroute and arrival thresholds |
| **Search UI & transition** | Ranked search with category facets, fuzzy fallback, live card distance, select-without-camera-move, explicit **Jump here** and `?poi=` deep link, responsive/mobile layout |
| **Code cleanliness & repo** | Typed TS modules (`pois`, `nav`, `navigation`, `viewer`, `ui`), 50 web tests + 21 pipeline tests, 76-check browser QA, documented contract and evidence pack |
