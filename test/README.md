# test — self-captured twin artifacts for reviewers and fresh clones

This directory holds the team's self-captured, end-to-end reconstructed indoor
twin (`home_v1`). All third-party and public datasets (`metro_v1`, `guildhall-*`,
`playroom`, `room`) have been completely removed to comply with Round 2 Rule 1
(*Use your own data*).

The committed bundle is small enough (`17.12 MB` total) to live in git so any
reviewer can inspect every metric, QA report, and web artifact or serve the
browser walkthrough without a Kaggle account or a GPU.

| Capture | Source | Size | Highlights |
|---|---|---|---|
| `home_v1/` | Team's own smartphone walkthrough of a 3-room flat (75 s clean indoor trim of a 98.6 s `1280×576 @ 30 fps` handheld walk) | `17.12 MB` | Apache-2.0 `DISK+LightGlue` SfM (`296/375` = `78.9%`, continuous 293-frame 3-room loop), Apache-2.0 `Depth-Anything-V2-Metric-Indoor-Small`, `22.21 m²` walkable, `11.55 MB` `.ksplat` (`480,000` Gaussians), `9` POIs across `4` categories |

## Layout

```
test/home_v1/
  README.md              generated file list + exact commands
  frames/                14 preview frames (full run extracted 375 @ 5.0 Hz)
  frames_meta.json       source timing, picked frames, sharpness stats
  sfm/                   poses.json, sparse.ply, sfm_report.json
  depth/                 scale.json, depth_report.json
  nav/                   nav.json, occupancy.png, nav_report.json, pois.json
  metricize.json         training-frame -> metric transform record
  capture_qa.json/.md    honest QA paper trail (every measured check + rationale)
  web/                   the exact bundle the browser viewer serves:
                         nav.json, pois.json, cloud.ply (250k pts),
                         splat.ksplat (11.55 MB, 480k gaussians),
                         occupancy.png, meta.json
```

## Run the twin locally

From the repo root (Node 20+):

```powershell
python tools/activate_capture.py home_v1 --label "Home 3-Room Twin — POIs & nav"
cd web
npm ci
npm run dev
```

Open <http://127.0.0.1:5173/> (or the hosted GitHub Pages viewer at
<https://sciencebanda09.github.io/topoloka/>). Drag to look, WASD/arrows to
walk, `M` for the minimap, `/` to search POIs, `B` for Sandbox barriers, `P`
to toggle the metric point cloud, and `?t=<index>` to spawn at any trajectory
frame.

## Measured reconstruction summary (`home_v1`)

| Check | Value |
|---|---|
| Input | Self-captured 3-room flat walkthrough (`home_v1_raw_full.mp4`, 98.6 s → 75.0 s indoor trim, `1280×576 @ 30 fps`) |
| Frames extracted | 375 @ 5.0 Hz (`stride=6`) |
| SfM (Apache-2.0 `DISK+LightGlue` + `pycolmap 4.2.1`) | `296/375` (`78.9%`) registered, `51,304` 3D points, `1.569 px` median reproj (continuous 293-frame 3-room loop, vs `35/225 = 15.6%` SIFT baseline) |
| Metric depth (Apache-2.0 `Depth-Anything-V2-Metric-Indoor-Small-hf`) | `296/296` fused, `24.27 M` raw → `648,579` dense voxels; `scale = 0.65836 m/unit`, `MAD = 11.88%` (`55,274` samples) |
| Metric navigation (`5 cm` grid) | `22.21 m²` walkable, `232 × 250` grid, `61,688` floor inliers, `69` outline pts, `0` geometry warnings, `camera_height = 0.868 m` |
| 3DGS (`splatfacto`, 25k iters) | `915,558` raw → pruned (`154,867` low-alpha + `396` fog-floaters/needles + `32,953` ceiling spikes) → `480,000` Gaussians in `11.55 MB` Level-1 `.ksplat` |
| Authored POIs | `9` validated POIs across `4` categories (`area`, `facility`, `landmark`, `exit`), `0` validation warnings |
| Honest QA trail | `capture_qa.md` — `PASS` on frame count, floor outline, geometry warnings, POI dataset; `WARN` on 78.9% registration; `FAIL` on 26 p10 Laplacian (soft indoor walls) & 1.569 px reproj (expected for 8px-stride CNN DISK features) |

## Reproduce the whole pipeline

The capture is assembled from the Kaggle kernels in `kaggle/kernels/` (GPU
`DISK+LightGlue` SfM in `kaggle/kernels/namma_sfm_gpu/` and T4 Depth + 3DGS in
`kaggle/kernels/namma_splat/`). All pipeline code and web viewer code are MIT
licensed; every model and library uses permissive commercial licenses (Apache 2.0 / MIT / BSD-3).
