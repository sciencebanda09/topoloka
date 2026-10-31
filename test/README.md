# test — sample captures for reviewers and fresh clones

Four committed, redistributable samples; the Splatfacto v3 experiment is kept
separate. All are complete end-to-end runs of
the pipeline on **public** walk-through clips, small enough to live in git so
anyone can serve the twin and inspect every artifact without a Kaggle account
or a GPU.

| Sample | Source | Size | QA |
|---|---|---|---|
| `metro_v1/` | *Modern Melbourne Metro Walkway Urban Design* by Joolsmagool (Pexels License), 86.07 s | 24.7 MB | 6/6 PASS |
| `guildhall-v1/` | *Guildhall City of London England interior walkaround video* by Acabashi (CC BY-SA 4.0), 90.0 s trim | 31.0 MB | 6/6 PASS |
| `guildhall-v2/` | Same public source, sharper 91.925 s trim beginning near 94 s (CC BY-SA 4.0) | 41.34 MB | 6/6 PASS; 204/230 registered; 878,891 splats |
| `guildhall-mvs/` | Same sharp Guildhall trim, dense COLMAP MVS and photo-textured mesh | 105.5 MB | 5.52M dense points, 650k faces, 89.54% textured-face coverage |
| `guildhall-v3` (pending) | Same Guildhall source with a higher quality Splatfacto Big training pass | running on Kaggle | kept as a separate experiment |

`guildhall-v1` is the R1 public stand-in: a real indoor venue capture, but
**not the team's own venue**. The source is credited in
`guildhall-v1/README.md` and `guildhall-v1/LICENSE`; the derived sample data
inherits CC BY-SA 4.0.

`guildhall-v2` is a sharper alternate trim of the same public source. Its SfM
report records partial registration (204/230 frames) and two disconnected
models; see its `README.md` and `capture_qa.md` for the measurements and limits.
The improved Guildhall v2 web bundle retains 878,891 splats and uses recorded
camera headings for its default starting view. The Splatfacto Big v3 run remains
a separate Kaggle experiment. The new MVS sample uses a photo-textured triangle
mesh by default and keeps the Gaussian splat and point cloud selectable.

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

test/guildhall-v2/
  README.md              source, measured results, SfM limitation, menu name
  LICENSE                CC BY-SA 4.0 attribution and change notice
  frames/                14 preview frames (full run used 230)
  frames_meta.json      source timing, selected frames, sharpness
  transforms.json       training camera transforms
  metricize.json        training-to-metric transform record
  SOURCE.md             source and segment notes
  sfm/                  poses, sparse cloud, reconstruction report
  depth/                scale and depth-fusion reports
  nav/                  metric grid, occupancy image, navigation report
  capture_qa.json/.md   the six quality checks and compensation notes
  web/                  viewer bundle: 250 k-point cloud, 878,891 splats,
                        204 captured camera headings, meta.json
```

## Run a twin locally

From the repo root (Node 20+):

```powershell
foreach ($sampleDir in Get-ChildItem test -Directory) {
  $bundlePath = Join-Path $sampleDir.FullName 'web'
  if (Test-Path $bundlePath) {
    $artifactPath = Join-Path 'web\public\artifacts' $sampleDir.Name
    New-Item -ItemType Directory -Force $artifactPath | Out-Null
    Copy-Item -Recurse -Force (Join-Path $bundlePath '*') $artifactPath
  }
}
cd web
npm ci
npm run dev
```

Open <http://127.0.0.1:5173/>. Melbourne Metro is the default public sample.
Guildhall bundles remain in the repository for pipeline reference. Drag to look, WASD/arrows
to walk, M for the minimap, P to toggle the point cloud, and `?t=<index>` to
choose a spawn point.

The hosted viewer opens Melbourne Metro. Guildhall outputs remain available in
the repository but are excluded from the deployed viewer.

```bash
# POSIX equivalent
for web_bundle in test/*/web; do
  sample_name="$(basename "$(dirname "$web_bundle")")"
  mkdir -p "web/public/artifacts/$sample_name"
  cp -r "$web_bundle"/. "web/public/artifacts/$sample_name"/
done
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

### guildhall-v2

| Check | Value |
|---|---|
| Input | 91.925 s public segment starting near 94 s, 3840x2160/29.97 (CC BY-SA 4.0) |
| Frames used | 230 at 1600x900, 2.5 Hz |
| Sharpness scan | p10 1582.84 versus 418.56 for the older 305-395 s window, same source scan method |
| SfM | 204/230 registered, 137,703 points, 0.554 px median; two disconnected models found and the smaller excluded |
| Metric scale | 1.82931 m/unit, MAD 8.7% |
| Depth fusion | 31.85 M raw -> 7.78 M voxel points |
| Walkable | 23.4 m2 free, grid 248 x 633 at 5 cm, 169 outline points |
| Splat | 878,891 gaussians in the shipped sample after capture-volume crop |
| Camera | 204 captured headings; default spawn at trajectory point 106 |
| Bundle | 41.34 MB total; 28.12 MB `.splat`; 250,000-point web cloud |
| QA | 6/6 PASS (`capture_qa.md`); this includes a thresholded partial-registration check |

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
- **guildhall-v2** — the same source with a stream-copied 91.925 s segment
  beginning near 94 s. It is also distributed under CC BY-SA 4.0; see
  `guildhall-v2/LICENSE`.
- **guildhall-v3** — the same source and licensed segment, currently in a
  higher quality Kaggle training run. It will retain the same CC BY-SA 4.0
  terms when its bundle is packaged.

The derived artifacts in each folder are redistributed under the source
licence; the pipeline code is MIT. No personal capture is shipped.
