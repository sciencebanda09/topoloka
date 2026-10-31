# home_v1 -- sample capture

Everything here was produced by the Topoloka pipeline on Kaggle from a single
walk-through video (no LiDAR, no depth sensor). It is small enough to
live in git so anyone can inspect or serve it without a Kaggle account.

Captured on smartphone following capture/SOP.md (landscape 1080p, two-pass room walkthrough).

| file | size |
|---|---|
| `capture_qa.json` | 2 KB |
| `capture_qa.md` | 873 B |
| `frames_meta.json` | 30 KB |
| `metricize.json` | 246 B |
| `frames/00000.jpg` | 312 KB |
| `frames/00012.jpg` | 228 KB |
| `frames/00024.jpg` | 232 KB |
| `frames/00036.jpg` | 259 KB |
| `frames/00048.jpg` | 251 KB |
| `frames/00060.jpg` | 331 KB |
| `frames/00072.jpg` | 254 KB |
| `frames/00083.jpg` | 246 KB |
| `frames/00095.jpg` | 224 KB |
| `frames/00107.jpg` | 341 KB |
| `frames/00119.jpg` | 329 KB |
| `frames/00131.jpg` | 226 KB |
| `frames/00143.jpg` | 215 KB |
| `frames/00155.jpg` | 228 KB |
| `sfm/poses.json` | 88 KB |
| `sfm/sfm_report.json` | 1 KB |
| `sfm/sparse.ply` | 527 KB |
| `depth/depth_report.json` | 331 B |
| `depth/scale.json` | 148 B |
| `nav/nav.json` | 8 KB |
| `nav/nav_report.json` | 567 B |
| `nav/occupancy.png` | 3 KB |
| `web/cloud.ply` | 3.75 MB |
| `web/meta.json` | 398 B |
| `web/nav.json` | 8 KB |
| `web/occupancy.png` | 3 KB |
| `web/splat.splat` | 22.51 MB |

Total: **30.6 MB** (cloud decimated to 250,000
points, splat pruned to 703,564 gaussians; preview frames: 14).

## View it

Stage this folder where the viewer looks for artifacts, then start the app:

```powershell
New-Item -ItemType Directory -Force ..\..\web\public\artifacts\home_v1 | Out-Null
Copy-Item -Recurse -Force .\* ..\..\web\public\artifacts\home_v1\
cd ..\..\web
npm ci
npm run dev   # open http://127.0.0.1:5173/?capture=home_v1
```

Hosted viewer: <https://sciencebanda09.github.io/topoloka/?capture=home_v1> (Indoor Home Capture).

Drag to look, WASD/arrows to walk, M toggles the minimap, P toggles the
point cloud behind the splat. (Internal refreshes from fresh kernel outputs:
`web/tools/sync_artifacts.ps1` performs the same copy.)

## What each piece proves

- `nav/nav.json` -- the metric navigation contract: 5 cm occupancy grid,
  floor outline, camera trajectory, and the `align` block that maps the SfM
  frame into metres (scale source + rotation + origin).
- `web/cloud.ply` -- the same geometry in the nav frame; open it in any
  viewer to check that "up" is up and a metre is a metre.
- `web/splat.splat` -- the Gaussian-splat twin exactly as the web viewer
  loads it (32 bytes per gaussian).
- `sfm/`, `depth/`, `capture_qa.*` -- the honest paper trail: every quality
  number the pipeline measured, including the ones that did not pass.
