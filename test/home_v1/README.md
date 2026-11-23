# home_v1 -- self-captured 3-room indoor twin

Everything here was produced by the Topoloka pipeline on Kaggle from a single
team-recorded smartphone walk-through video (no LiDAR, no depth sensor, no
third-party datasets). It is compact enough to live in git so anyone can
inspect or serve it without a Kaggle account.

Self-captured 3-room indoor flat walkthrough by the Topoloka team (75 s clean
indoor trim of a 98.6 s 1280x576 @ 30 fps handheld walk covering the Entry
Study Room, Central Hall, and Master Bedroom loop; reconstructed with
Apache-2.0 Kornia DISK+LightGlue SfM + Apache-2.0 Depth-Anything-V2-Metric-Indoor-Small
+ 30k splatfacto-big 3DGS with SO3xR3 pose refinement & scale regularization + 9 authored POIs across 4 categories).

| file | size |
|---|---|
| `capture_qa.json` | 2 KB |
| `capture_qa.md` | 1 KB |
| `depth/depth_report.json` | 377 B |
| `depth/scale.json` | 184 B |
| `frames/00000.jpg` | 98 KB |
| `frames/00029.jpg` | 78 KB |
| `frames/00058.jpg` | 104 KB |
| `frames/00086.jpg` | 131 KB |
| `frames/00115.jpg` | 102 KB |
| `frames/00144.jpg` | 125 KB |
| `frames/00173.jpg` | 68 KB |
| `frames/00201.jpg` | 135 KB |
| `frames/00230.jpg` | 103 KB |
| `frames/00259.jpg` | 110 KB |
| `frames/00288.jpg` | 86 KB |
| `frames/00316.jpg` | 128 KB |
| `frames/00345.jpg` | 130 KB |
| `frames/00374.jpg` | 112 KB |
| `frames_meta.json` | 69 KB |
| `metricize.json` | 245 B |
| `nav/nav.json` | 15 KB |
| `nav/nav_report.json` | 628 B |
| `nav/occupancy.png` | 2 KB |
| `nav/poi_report.json` | 260 B |
| `nav/pois.json` | 5 KB |
| `sfm/poses.json` | 208 KB |
| `sfm/sfm_report.json` | 690 B |
| `sfm/sparse.ply` | 752 KB |
| `web/cloud.ply` | 3.58 MB |
| `web/meta.json` | 573 B |
| `web/nav.json` | 15 KB |
| `web/occupancy.png` | 2 KB |
| `web/pois.json` | 5 KB |
| `web/splat.ksplat` | 13.31 MB |

Total: **19.42 MB** (cloud decimated to 250,000 points,
Level-1 `.ksplat` pruned to 580,000 Gaussians with SO3xR3 pose refinement, scale-ratio regularization, and floater/needle/ceiling-spike
culling, 9 authored POIs across 4 categories, 14 preview frames).

## View it

Stage this folder where the viewer looks for artifacts, then start the app:

```powershell
python tools/activate_capture.py home_v1 --label "Home 3-Room Twin - POIs & nav"
cd web
npm ci
npm run dev   # open http://127.0.0.1:5173/?capture=home_v1
```

Hosted viewer: <https://sciencebanda09.github.io/topoloka/?capture=home_v1>

Drag to look, WASD/arrows to walk, M toggles the minimap, `/` searches POIs,
`B` opens the Sandbox barrier tool, P toggles the metric point cloud behind
the splat.

## What each piece proves

- `nav/nav.json` -- the metric navigation contract: 5 cm occupancy grid
  (`21.71 m^2` walkable), 69-point floor outline, 293-pose continuous 3-room
  loop trajectory with captured look yaws/pitches, camera intrinsics, and the
  `align` block mapping SfM coordinates into metres.
- `nav/pois.json` and `web/pois.json` -- 9 authored POIs across all 3 rooms
  (4 categories: `area`, `facility`, `landmark`, `exit`), validated with zero
  warnings against the 5 cm free-space grid.
- `web/cloud.ply` -- the same metric geometry in the nav frame; open it in any
  viewer to check that "up" is up and a metre is a metre.
- `web/splat.ksplat` -- the Level-1 compressed Gaussian-splat twin (`13.95 MB`,
  580,000 splats) exactly as the browser viewer loads it.
- `sfm/`, `depth/`, `capture_qa.*` -- the honest paper trail: every quality
  number the pipeline measured, including the ones that triggered warnings/fails
  (such as 1.569 px median reprojection error inherent to 8px-stride CNN DISK
  keypoints vs sub-pixel SIFT, and 26 p10 Laplacian sharpness on soft indoor walls).
