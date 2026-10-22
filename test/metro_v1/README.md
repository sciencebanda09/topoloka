# metro_v1 -- sample capture

Everything here was produced by the Topoloka pipeline on Kaggle from a single
walk-through video (no LiDAR, no depth sensor). It is small enough to
live in git so anyone can inspect or serve it without a Kaggle account.

Source: *Modern Melbourne Metro Walkway Urban Design* by Joolsmagool (Pexels License), trimmed to 86 s (1920x1080/30).

| file | size |
|---|---|
| `capture_qa.json` | 2 KB |
| `capture_qa.md` | 878 B |
| `frames_meta.json` | 41 KB |
| `metricize.json` | 244 B |
| `README.md` | 3 KB |
| `frames/00000.jpg` | 373 KB |
| `frames/00017.jpg` | 388 KB |
| `frames/00033.jpg` | 316 KB |
| `frames/00050.jpg` | 302 KB |
| `frames/00066.jpg` | 389 KB |
| `frames/00083.jpg` | 380 KB |
| `frames/00099.jpg` | 395 KB |
| `frames/00116.jpg` | 373 KB |
| `frames/00132.jpg` | 357 KB |
| `frames/00149.jpg` | 373 KB |
| `frames/00165.jpg` | 385 KB |
| `frames/00182.jpg` | 398 KB |
| `frames/00198.jpg` | 375 KB |
| `frames/00215.jpg` | 363 KB |
| `sfm/poses.json` | 155 KB |
| `sfm/sfm_report.json` | 1 KB |
| `sfm/sparse.ply` | 775 KB |
| `depth/depth_report.json` | 334 B |
| `depth/scale.json` | 146 B |
| `nav/nav.json` | 41 KB |
| `nav/nav_report.json` | 582 B |
| `nav/occupancy.png` | 24 KB |
| `web/cloud.ply` | 3.75 MB |
| `web/meta.json` | 401 B |
| `web/nav.json` | 41 KB |
| `web/occupancy.png` | 24 KB |
| `web/splat.splat` | 14.63 MB |

Total: **24.7 MB** (cloud decimated to 250,000
points, splat pruned to 457,221 gaussians; preview frames: 14).

## View it

Stage this folder where the viewer looks for artifacts, then start the app:

```powershell
New-Item -ItemType Directory -Force ..\..\web\public\artifacts\metro_v1 | Out-Null
Copy-Item -Recurse -Force .\* ..\..\web\public\artifacts\metro_v1\
cd ..\..\web
npm ci
npm run dev   # open http://127.0.0.1:5173/?capture=metro_v1
```

Hosted twin (same data): <https://sciencebanda09.github.io/topoloka/?capture=metro_v1>

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
