# Submission notes — running log

What was submitted, when, and where the canonical links live. Append-only;
the portal is the only place that matters, this file is the defense copy.

## Links (canonical)

| Item | Link | Status |
|------|------|--------|
| Repo | https://github.com/sciencebanda09/topoloka | public (MIT), created 2026-10-18 |
| Viewer (hosted) | https://sciencebanda09.github.io/topoloka/?capture=metro_v1 | metro sample live; QA/perf verified 2026-10-24 |
| Demo video | https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4 | 3:33, 1080p30, 41.0 MB; hosted 2026-10-26 |
| Abstract PDF | `docs/abstract.pdf` in repo | metro, 5 pages, 2.42 MB; rebuilt 2026-10-26 with demo link |

## Log

- **2026-10-18 — Public repo + hosting.** GitHub Pages deploys via Actions; the
  committed sample under `test/<capture>/web/` is staged into the build, so
  there is no duplicated artifact tree in git.

- **2026-10-18 — Pipeline v1.** Frame picking → pycolmap SfM → geometry →
  depth/metricize → splat → package. Fixed the pycolmap 4.2.1 API drift
  (`extract_features` / `match_exhaustive` / `incremental_mapping` return
  `(rec, stats)`), verified the binary PLY really has a header newline, and
  added the EIS-off capture rule after motion-blur frames failed the sharpness
  gate.

- **2026-10-19 — Capture SOP + QA.** `capture/SOP.md` codifies EIS off, AE/AF
  lock, 4K30, two-pass loop with a still tail, ~0.4 m/s pace, stride-synced
  frame picking, and QR anchors per zone. The SOP was exercised on a private
  phone capture (not redistributed); the public artifact is stock footage, so
  it has no IMU and gravity comes from the SfM camera-y mean.

- **2026-10-20 — Public capture pivot.** The first public candidate (a metro
  corridor) passed geometry/QA but rendered as translucent smears: white,
  glossy, low-texture panels with long sightlines under-densify badly in 3DGS.
  Kept it as the QA/nav reference and moved the demo to a second public
  walk-through: *Modern Melbourne Metro Walkway Urban Design* (Pexels License),
  trimmed to 86.07 s at 1920×1080/30. No people in the foreground, no cuts.

- **2026-10-21 — CPU run.** 216 frames (1600×900, 2.5 Hz). SfM 216/216
  registered, 51,677 points, 0.403 px median (0.613 mean), 3,553 s. Depth
  fusion 216/216, 31.2 M raw → 10.28 M voxel points, scale **6.2505 m/unit**,
  MAD **7.54%** over 37,844 samples. Replaced the floor detection with a
  scale-free sparse-point height histogram (15/15 tests pass); 929,436 floor
  inliers, camera height **1.588 m**, 5 cm grid **1188 × 1259**, **315.05 m²**
  walkable, nav 61 s. All 6 QA gates pass.

- **2026-10-22 — GPU run v7 (failed) → v8 (success).** v7 died in the gsplat JIT
  because four parallel `nvcc` jobs were OOM-killed on the 2×T4 node; v8 set
  `MAX_JOBS=1` and serialized the build. v8 trained splatfacto 25,000 iters at
  full resolution (1600×900) with trainer auto-orient/center/scale disabled,
  then exported via the Python API. **510,336** web gaussians / 16.33 MB;
  total GPU wall **4,741 s (79.0 min)** including the JIT build. Re-pruned the
  raw export with a 3 m volume crop for the sample: **457,221** gaussians /
  14.63 MB, QA regenerated 6/6 PASS.

- **2026-10-22 — Render verification.** The original headless screenshots were
  taken under SwiftShader (software WebGL), which stretches anisotropic
  gaussians and makes any splat look smeared. Re-captured with ANGLE/D3D11 on
  the AMD GPU: the corridor reads correctly (tiled floor, metal panels, ad
  screens, exit sign), still soft where the source is reflective. Lowered the
  viewer's `splatAlphaRemovalThreshold` to 40; antialiasing made it worse.
  Figures in `docs/fig/` are GPU captures. A reviewer with software rendering
  should compare against a GPU-backed browser.

- **2026-10-23 — R1 packaging verified.** Pages deploy run 39863541101
  succeeded. Cold load of `?capture=metro_v1&t=160` from a fresh profile on
  ANGLE/D3D11: splat 0.46 M, 315.05 m², QA PASS, 18.4 MB web payload; cold
  ready **19.2 s** (13.96 MB splat + 3.38 MB cloud transferred). Abstract
  rebuilt at 5 pages. Fresh-clone check passed (`git clone` → `npm ci` →
  `npm run build`, 18.4 MB web payload).

- **2026-10-23 — Navigation pass.** The raw 5 cm grid fragments at gates and
  railings, and A* was treating unknown cells as walkable, so the route from
  the default spawn failed or detoured through unobserved space. The viewer now
  blocks unknown cells and carves a 1 m free corridor along the camera path
  (the camera proved it traversable). Default spawn moved from trajectory 0
  (at the reconstruction boundary, sideways view) to 75% of the path. Verified
  `?route` renders 350 waypoints / 20.3 m from the default spawn in 3D and on
  the minimap. Pages redeploy 39928019529 verified live: default opens at 75%,
  route 350 wp / 20.3 m. Remaining R1 item: the 3–5 min demo video and its
  link (closed 2026-10-26).

- **2026-10-24 — Viewer fidelity/perf pass.** Root-caused the "smeared walls
  and black ceiling void" to the viewer using a generic **72° vertical** FOV
  while the capture lens is **41.6° vertical / 67.98° horizontal**
  (`fl_x=fl_y=1186.5608`, 1600×900). The viewer now reads `nav.json.camera`,
  preserves the capture's horizontal FOV in landscape, caps portrait at 50°
  vertical, and clamps pitch to −0.85..+0.35 rad. The black "needle" lines on
  the floor were partly the **debug `GridHelper` and floor outline showing
  through the splat**, not splat geometry: both are now hidden as soon as the
  splat loads (they remain in point-cloud mode). MSAA was the dominant iGPU
  cost; `antialias:false` raised the default-spawn reading from 23.3 to
  **36.8 fps idle / 52.4 walking** at 1600×900 (internal 1155×650). At the
  worst view `?t=90`: **35.5 / 37.9 fps** (899×506); at 1920×1080: **34.0 /
  48.2 fps**. Adaptive resolution now targets 32 fps (0.08 steps, 0.4 floor),
  the HUD reports true frame time (the old loop clamped `dt` before `1/dt`,
  which imposed a fake 20 fps floor), the route is a 2.2 cm floor tube, and
  the minimap gained a free/obstacle/unknown/path/route legend plus **M** to
  hide it. These changes are committed but the Pages deploy had not yet been
  re-verified when this entry was written.

- **2026-10-24 — Live verification of the fidelity/perf pass.** Pages run
  `40057483066` succeeded. On the live URL with ANGLE/D3D11 on the AMD
  integrated GPU at 1600×900: **51.0 fps idle / 60.1 walking** at spawn,
  **43.0 / 40.2** at `?t=90`, and **47.5 / 55.9** with `?route` (350 wp /
  20.3 m), all at a 1155×650 internal buffer. A 390×844 DPR2 mobile layout
  with touch emulation reported **59.9 / 60.2 fps**, showed the touch hint,
  and kept the HUD, map, and legend from overlapping. The workflow now stages
  every `test/*/web` folder, so a second committed sample deploys without a
  workflow edit.

- **2026-10-24 — Generality run started.** Locked a second public capture:
  *Narrow Corridor under Lights* by Vincuk (Pexels License, Pexels video
  10577776), trimmed to **0–41 s** before the end cut to the exterior window.
  The source is 1920×1080 / ~29.97 fps. Uploaded as
  `shashankdev09/namma-corridor-video-v1` and started
  `shashankdev09/namma-pipeline-corridor` on Kaggle CPU with the **unchanged**
  pipeline code. No generality claim is made until SfM/QA complete and the
  twin is hosted.

- **2026-10-25 — Second capture: two attempts, both SfM failures; claim
  dropped.** The corridor run registered **56/103 frames (54%)** as 7
  disconnected models with a ~16 m pose jump at frames 34/35 (~14 s) and
  therefore failed the geometry gate. A second candidate, *A Moving Walkway
  Inside An Airport* by Melvin (Pexels 4919617), trimmed to 0–42 s, registered
  only **2/106 frames (2%)** — the repeated ceiling/window bands defeat SIFT
  matching. Per the Oct 26 timeline guard, R1 does **not** claim a second
  capture or a second hosted twin; the metro capture remains the only
  claimed artifact. The failed kernels and reports are kept under
  `kaggle/kernels/namma_*_airport` and `kaggle/out/namma_pipeline_*` for the
  paper trail, not as deliverables.

- **2026-10-26 — R1 demo video shipped.** The 3:33, 1920×1080/30 cut is a
  release asset (`r1-demo`, 41.0 MB). It uses a **17.9 s real-time take** of
  the hosted Pages build (normal Chrome, ANGLE/D3D11, AMD iGPU) recorded with
  ffmpeg `gdigrab` at 30 fps while the viewer was driven via CDP. The CDP
  screencast path was too slow at 1080p (~4 fps), so it was not used. The
  recorder stopped at 17.9 s; the viewer chapter pads with the measured
  default-spawn still (`51.0 / 60.1 fps`) and the `?t=90` still
  (`43.0 / 40.2 fps`) rather than freezing or looping the last frame. The
  remaining chapters are cards/figures generated from the shipped JSONs and
  Edge TTS narration; there is no terminal footage and no invented number.
  The abstract now links the release asset; the PDF was rebuilt at 5 pages /
  2.42 MB with the 25 k pipeline figure. Build scripts and narration are in
  `docs/demo/`; `docs/demo/build/` and the MP4 are gitignored.

- **2026-10-27 — R2 preview: sandbox pick-and-place.** Added an additive prop
  layer behind `?sandbox=1` / `G`; the R1 default view, demo, abstract, and
  hosted artifacts are unchanged. Four procedural props (cone, barrier, crate,
  wet-floor sign) can be picked up, rotated, placed, removed, persisted in
  `localStorage`, and shared via a `?props=` link. Placement raycasts the
  splat's BVH for the real floor; placed footprints are rasterized into the
  5 cm costmap's dynamic layer, so collision and A* reroute around them. The
  props are synthetic meshes layered over the read-only splat; moving scanned
  geometry remains out of scope (segmentation + inpainting + missing backsides).
  Build + headless dynamic-costmap tests pass. Details: `docs/sandbox.md`.

## Engineering decisions worth defending

- **One frame convention, one align block.** Raw SfM → metric nav
  (`p_nav = scale · Rᵀ(p_scene − origin)`) → three.js. Training inputs are
  metricized first, so the cloud, splat, and trajectory share one transform.
  `nav.json.align` is the single source of truth; the viewer applies it to all
  three.
- **Scale is measured, not assumed.** The median of `depth_m / camera_z` over
  tens of thousands of sparse points; the MAD, sample count, and residual are
  shipped in `scale.json`.
- **QA is a deliverable.** 6/6 gates on the sample: sharpness p10 582, 216
  frames, 216/216 registered, 0.403 px, 193-point outline / 315.05 m², no
  geometry warnings. Failures must name their compensation.
- **Blob-URL splat loading.** The viewer fetches the `.splat` bytes itself and
  hands the library a blob URL with a timeout; `addSplatScene(httpUrl)` gave no
  error/abort path and could hang the page.
- **Sample first.** The hosted web payload is 18.4 MB (14.63 MB splat +
  3.75 MB cloud + nav); the full sample folder is 24.7 MB. The 139 MB PLY
  never goes to the web.

## Known limitations (also in the abstract)

- Reflective, low-texture walls render softer than the floor at ~1.5 K
  gaussians/m². The ceiling is under-observed, but matching the capture lens
  and clamping pitch now keeps the normal first-person view inside the
  observed shell instead of showing a black void above it.
- DC-only `.splat` drops view-dependent highlights.
- No IMU in the public clip; the phone SOP is not exercised by the artifact.
- Metric depth degrades past ~8–12 m.
- The raw 5 cm grid fragments at gates/railings; the viewer blocks unknown
  cells and carves the walked path. The pipeline should emit a connected nav
  grid in R2 rather than relying on the viewer carve.
- POIs/search and AR are R2/R3; `?route` is a dev flag, not the shipped UI.

## Reproduce

```powershell
. .\kaggle\config.ps1
.\kaggle\tools\push_code.ps1
.\kaggle\tools\push_kernel.ps1 namma_pipeline
.\kaggle\tools\fetch_output.ps1 -Kernel namma_pipeline
.\kaggle\tools\push_capture.ps1
.\kaggle\tools\push_kernel.ps1 namma_splat
.\kaggle\tools\fetch_output.ps1 -Kernel namma_splat
.venv\Scripts\python.exe tools\make_sample.py --dest test\metro_v1 --frames 14 --max-gaussians 1000000
```
