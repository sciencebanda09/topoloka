# test — sample capture for reviewers and fresh clones

`metro_v1/` is the committed, redistributable sample: a complete end-to-end
run of the pipeline on a **public** walk-through clip, small enough to live in
git so anyone can serve the twin and inspect every artifact without a Kaggle
account or a GPU.

Size: **24.7 MB** (14.63 MB splat + 3.75 MB cloud + nav/QA/frames).

## Layout

```
test/metro_v1/
  README.md              generated file list + exact commands
  frames/               14 preview frames (full run used 216)
  frames_meta.json      source timing, picked frames, sharpness
  sfm/                  poses.json, sparse.ply, sfm_report.json
  depth/                scale.json, depth_report.json
  nav/                  nav.json, occupancy.png, nav_report.json
  metricize.json        training-frame -> metric transform record
  capture_qa.json/.md   the honesty surface: 6/6 PASS
  web/                  the exact bundle the viewer serves
                        nav.json, cloud.ply (250 k pts), splat.splat
                        (457,221 gaussians), occupancy.png, meta.json
```

## Run the twin locally

From the repo root (Node 20+):

```powershell
New-Item -ItemType Directory -Force web\public\artifacts\metro_v1 | Out-Null
Copy-Item -Recurse -Force test\metro_v1\web\* web\public\artifacts\metro_v1\
cd web
npm ci
npm run dev
```

Open <http://127.0.0.1:5173/?capture=metro_v1>. Drag to look, WASD/arrows to
walk, M for the minimap, P to toggle the point cloud, `?t=<index>` to spawn at
a trajectory point, `?clean` to hide the prompt/fps.

```bash
# POSIX equivalent
mkdir -p web/public/artifacts/metro_v1
cp -r test/metro_v1/web/. web/public/artifacts/metro_v1/
cd web && npm ci && npm run dev
```

## What it proves (measured)

| Check | Value |
|---|---|
| Input | 86.07 s public clip, 1920×1080/30 (Pexels License) |
| Frames used | 216 at 1600×900, 2.5 Hz |
| SfM | 216/216 registered, 51,677 pts, 0.403 px median |
| Metric scale | 6.2505 m/unit, MAD 7.54% (37,844 samples) |
| Depth fusion | 31.2 M raw → 10.28 M voxel points |
| Walkable | 315.05 m² free, grid 1188 × 1259 @ 5 cm |
| Splat | 510,336 full export; 457,221 sample after 3 m crop |
| Bundle | 24.7 MB total; 14.63 MB `.splat` |
| QA | 6/6 PASS (`capture_qa.md`) |

## Reproduce the whole pipeline

The capture is assembled from the Kaggle kernels in `kaggle/kernels/`, driven
by the scripts in `kaggle/tools/`; see `kaggle/README.md` and
`docs/submission_notes.md` for the exact sequence. `tools/make_sample.py`
rebuilds this folder from fetched kernel outputs.

## Credit

Source: *Modern Melbourne Metro Walkway Urban Design* by **Joolsmagool** on
Pexels, used under the [Pexels License](https://www.pexels.com/license/) and
trimmed to 86.07 s. The derived artifacts in this folder are redistributed
under that licence; the pipeline code is MIT. No personal capture is shipped.
