# house_v1 -- sample capture

Everything here was produced by the Topoloka pipeline on Kaggle from a single
phone walk-through video (no LiDAR, no depth sensor). It is small enough to
live in git so anyone can inspect or serve it without a Kaggle account.

| file | size |
|---|---|
| `capture_qa.json` | 2 KB |
| `capture_qa.md` | 876 B |
| `frames_meta.json` | 31 KB |
| `metricize.json` | 246 B |
| `README.md` | 3 KB |
| `frames/00000.jpg` | 391 KB |
| `frames/00012.jpg` | 407 KB |
| `frames/00024.jpg` | 332 KB |
| `frames/00036.jpg` | 407 KB |
| `frames/00048.jpg` | 494 KB |
| `frames/00060.jpg` | 357 KB |
| `frames/00072.jpg` | 428 KB |
| `frames/00085.jpg` | 335 KB |
| `frames/00097.jpg` | 459 KB |
| `frames/00109.jpg` | 262 KB |
| `frames/00121.jpg` | 491 KB |
| `frames/00133.jpg` | 418 KB |
| `frames/00145.jpg` | 397 KB |
| `frames/00157.jpg` | 392 KB |
| `sfm/poses.json` | 113 KB |
| `sfm/sfm_report.json` | 748 B |
| `sfm/sparse.ply` | 823 KB |
| `depth/depth_report.json` | 331 B |
| `depth/scale.json` | 148 B |
| `nav/nav.json` | 9 KB |
| `nav/nav_report.json` | 568 B |
| `nav/occupancy.png` | 3 KB |
| `web/cloud.ply` | 3.75 MB |
| `web/meta.json` | 395 B |
| `web/nav.json` | 9 KB |
| `web/occupancy.png` | 3 KB |
| `web/splat.splat` | 11.75 MB |

Total: **22.1 MB** (cloud decimated to 250,000
points, splat pruned to 367,254 gaussians; preview frames: 14).

## View it

Stage this folder where the viewer looks for artifacts, then start the app:

```powershell
New-Item -ItemType Directory -Force ..\..\web\public\artifacts\house_v1 | Out-Null
Copy-Item -Recurse -Force .\* ..\..\web\public\artifacts\house_v1\
cd ..\..\web
npm ci
npm run dev   # open http://127.0.0.1:5173/?capture=house_v1
```

Hosted twin (same data): <https://sciencebanda09.github.io/topoloka/?capture=house_v1>

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
