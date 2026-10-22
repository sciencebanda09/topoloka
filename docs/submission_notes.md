# Submission notes — running log

What was submitted, when, and where the canonical links live. Append-only;
the portal is the only place that matters, this file is the defense copy.

## Links (canonical)

| Item | Link | Status |
|------|------|--------|
| Repo | https://github.com/sciencebanda09/topoloka | public (MIT), created 2026-10-18 |
| Viewer (hosted) | https://sciencebanda09.github.io/topoloka/?capture=metro_v1 | metro sample committed; Pages verify pending |
| Demo video | (unlisted YouTube, filled after recording) | pending |
| Abstract PDF | `docs/abstract.pdf` in repo | metro, 5 pages, rebuilt 2026-10-23 |

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
  ANGLE/D3D11: splat 0.46 M, 315.05 m², QA PASS, 18.4 MB web payload. Abstract
  rebuilt at 5 pages. Fresh-clone check passed (`git clone` → `npm ci` →
  `npm run build`, 18.4 MB web payload). Remaining R1 item: the 3–5 min demo
  video and its link.

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
  gaussians/m²; the ceiling is under-observed (dark band in Fig. 3).
- DC-only `.splat` drops view-dependent highlights.
- No IMU in the public clip; the phone SOP is not exercised by the artifact.
- Metric depth degrades past ~8–12 m.
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
