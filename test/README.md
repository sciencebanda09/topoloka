# test — sample captures for reviewers and fresh clones

Two committed, redistributable samples. Both are complete end-to-end runs of
the pipeline on **public** walk-through clips, small enough to live in git so
anyone can serve the twin and inspect every artifact without a Kaggle account
or a GPU.

| Sample | Source | Size | QA |
|---|---|---|---|
| `metro_v1/` | *Modern Melbourne Metro Walkway Urban Design* by Joolsmagool (Pexels License), 86.07 s | 24.7 MB | 6/6 PASS |
| `guildhall-v1/` | *Guildhall City of London England interior walkaround video* by Acabashi (CC BY-SA 4.0), 90.0 s trim | 31.0 MB | 6/6 PASS |

`guildhall-v1` is the R1 public stand-in: a real indoor venue capture, but
**not the team's own venue**. The source is credited in
`guildhall-v1/README.md` and `guildhall-v1/LICENSE`; the derived sample data
inherits CC BY-SA 4.0.

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

test/guildhall-v1/
  README.md              generated file list + exact commands
  LICENSE                CC BY-SA 4.0 attribution and change notice
  frames/               14 preview frames (full run used 218)
  frames_meta.json      source timing, picked frames, sharpness
  sfm/                  poses.json, sparse.ply, sfm_report.json
  depth/                scale.json, depth_report.json
  nav/                  nav.json, occupancy.png, nav_report.json
  metricize.json        training-frame -> metric transform record
  capture_qa.json/.md   the honesty surface: 6/6 PASS
  web/                  the exact bundle the viewer serves
                        nav.json, cloud.ply (250 k pts), splat.splat
                        (632,993 gaussians), occupancy.png, meta.json
```

## Run a twin locally

From the repo root (Node 20+):

```powershell
New-Item -ItemType Directory -Force web\public\artifacts\metro_v1 | Out-Null
Copy-Item -Recurse -Force test\metro_v1\web\* web\public\artifacts\metro_v1\
cd web
npm ci
npm run dev
```

Open <http://127.0.0.1:5173/?capture=metro_v1>. For Guildhall, substitute
`guildhall-v1` in both paths and open
<http://127.0.0.1:5173/?capture=guildhall-v1>. Drag to look, WASD/arrows to
walk, M for the minimap, P to toggle the point cloud, `?t=<index>` to spawn at
a trajectory point, `?clean` to hide the prompt/fps.

```bash
# POSIX equivalent
mkdir -p web/public/artifacts/guildhall-v1
cp -r test/guildhall-v1/web/. web/public/artifacts/guildhall-v1/
cd web && npm ci && npm run dev
```

## What each sample proves (measured)

### metro_v1

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

### guildhall-v1

| Check | Value |
|---|---|
| Input | 90.0 s public clip, 1920×1080/29 (CC BY-SA 4.0) |
| Frames used | 218 at 1600×900, 2.5 Hz |
| SfM | 218/218 registered, 126,890 pts, 0.515 px median |
| Metric scale | 3.8204 m/unit, MAD 8.29% (112,479 samples) |
| Depth fusion | 25.97 M raw → 14.46 M voxel points |
| Walkable | 458.81 m² free, grid 1048 × 530 @ 5 cm |
| Capture path | 218 poses, 86.33 m walked, trajectory height 1.83–2.67 m |
| Splat | 688,558 full export; 632,993 sample after 3 m crop |
| Bundle | 31.0 MB total; 20.26 MB `.splat` |
| QA | 6/6 PASS (`capture_qa.md`) |

## Reproduce the whole pipeline

The captures are assembled from the Kaggle kernels in `kaggle/kernels/`, driven
by the scripts in `kaggle/tools/`; see `kaggle/README.md` and
`docs/submission_notes.md` for the exact sequence. `tools/make_sample.py`
rebuilds either folder from fetched kernel outputs.

## Credit

- **metro_v1** — *Modern Melbourne Metro Walkway Urban Design* by
  **Joolsmagool** on Pexels, used under the
  [Pexels License](https://www.pexels.com/license/) and trimmed to 86.07 s.
- **guildhall-v1** — *Guildhall City of London England interior walkaround
  video* by **Acabashi**, Wikimedia Commons, used under
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) and trimmed
  to 305–395 s. See `guildhall-v1/LICENSE`.

The derived artifacts in each folder are redistributed under the source
licence; the pipeline code is MIT. No personal capture is shipped.
