# guildhall-v1 -- sample capture

Everything here was produced by the Topoloka pipeline on Kaggle from a single
walk-through video (no LiDAR, no depth sensor). It is small enough to
live in git so anyone can inspect or serve it without a Kaggle account.

Source: *Guildhall City of London England interior walkaround video* by **Acabashi** (Wikimedia Commons, **CC BY-SA 4.0**), trimmed to 305-395 s (90.0 s) and scaled to 1920x1080/29. This is a public stand-in capture, not the team's venue. See LICENSE in this folder for the attribution and share-alike terms.

| file | size |
|---|---|
| `capture_qa.json` | 2 KB |
| `capture_qa.md` | 882 B |
| `frames_meta.json` | 42 KB |
| `LICENSE` | 1 KB |
| `metricize.json` | 245 B |
| `frames/00000.jpg` | 398 KB |
| `frames/00017.jpg` | 379 KB |
| `frames/00033.jpg` | 391 KB |
| `frames/00050.jpg` | 372 KB |
| `frames/00067.jpg` | 378 KB |
| `frames/00083.jpg` | 396 KB |
| `frames/00100.jpg` | 384 KB |
| `frames/00117.jpg` | 284 KB |
| `frames/00134.jpg` | 318 KB |
| `frames/00150.jpg` | 255 KB |
| `frames/00167.jpg` | 281 KB |
| `frames/00184.jpg` | 244 KB |
| `frames/00200.jpg` | 309 KB |
| `frames/00217.jpg` | 318 KB |
| `sfm/poses.json` | 157 KB |
| `sfm/sfm_report.json` | 745 B |
| `sfm/sparse.ply` | 1.90 MB |
| `depth/depth_report.json` | 335 B |
| `depth/scale.json` | 147 B |
| `nav/nav.json` | 63 KB |
| `nav/nav_report.json` | 583 B |
| `nav/occupancy.png` | 40 KB |
| `web/cloud.ply` | 3.75 MB |
| `web/meta.json` | 405 B |
| `web/nav.json` | 63 KB |
| `web/occupancy.png` | 40 KB |
| `web/splat.splat` | 20.26 MB |

Total: **31.0 MB** (cloud decimated to 250,000
points, splat pruned to 632,993 gaussians; preview frames: 14).

## View it

Stage this folder where the viewer looks for artifacts, then start the app:

```powershell
New-Item -ItemType Directory -Force ..\..\web\public\artifacts\guildhall-v1 | Out-Null
Copy-Item -Recurse -Force .\* ..\..\web\public\artifacts\guildhall-v1\
cd ..\..\web
npm ci
npm run dev   # open http://127.0.0.1:5173/?capture=guildhall-v1
```

Open the single hosted viewer and choose **Guildhall · original** in the
**View sample** menu.

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
