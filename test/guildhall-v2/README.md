# guildhall-v2 -- improved Hall sample

This sample is an end-to-end Topoloka reconstruction produced on Kaggle from
public walk-through footage. It contains no personal capture or LiDAR data.

Source: *Guildhall City of London England interior walkaround video* by
**Acabashi**, Wikimedia Commons. The source is licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); its original
file is [available on Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Guildhall_City_of_London_England_interior_walkaround_video.webm).
This sample uses a stream-copied segment beginning at approximately 94 seconds
and lasting 91.925 seconds (3840x2160, 29.97 fps). The derived sample artifacts
are shared under CC BY-SA 4.0. See `LICENSE` for attribution and terms.

The segment was selected by scanning the source for sharpness. Its 90-second
window has a 1582.84 p10 Laplacian score, versus 418.56 for the earlier
305-395-second window, using the same 480x270 source scan. This is a relative
sharpness measure, not a promise that every part of the video is in focus.

## View it

This historical sample is kept in the repository but is not published on the
hosted viewer. To inspect it, run the local viewer with `?capture=guildhall-v2`.

Drag to look; W/S walk forward or backward, A/D sidestep around objects, and
the arrow keys provide the same movement. Press M to toggle the minimap and P
to toggle the point cloud behind the splat. Stage the sample bundle below for
local development using the instructions in `test/README.md`.

## Measured reconstruction

| Check | Result |
|---|---|
| Input | 91.925 s public 4K video segment, 29.97 fps |
| Frames | 230 at 1600x900, 2.5 Hz; 14 preview frames included |
| Frame sharpness | p10 1533 (pipeline QA threshold: 100) |
| SfM | 204/230 registered (88.7%); 137,703 points; 0.554 px median reprojection error |
| SfM note | Two disconnected models were found; the smaller model was not included in the shipped map |
| Depth fusion | 31.85 M raw points -> 7.78 M voxel points across 204 frames |
| Metric scale | 1.82931 m/unit, 8.7% relative MAD |
| Walkable area | 23.4 m2; 248 x 633 grid at 5 cm; 169 outline points |
| Web splat | 878,891 gaussians, 28.12 MB after capture-volume crop |
| Starting view | captured camera heading at trajectory point 106 |
| Web cloud | 250,000 points |
| QA | 6/6 PASS (`capture_qa.md`); the frame-registration check allows partial registration |
| Bundle | 35 files including this README, 41.34 MB |

QA passed its configured thresholds. In particular, 6/6 PASS does not mean
every input frame registered: the bundle reports the 204/230 result and the
disconnected model warning above.

## Bundle contents

- `frames/`, `frames_meta.json` -- 14 preview images and timing/sharpness data
- `sfm/` -- camera poses, sparse point cloud, and reconstruction report
- `depth/` -- depth-fusion report and metric scale estimate
- `nav/` -- metric navigation grid, occupancy image, and report
- `web/` -- viewer bundle: navigation data, 250k-point cloud, splat, occupancy,
  and metadata
- `capture_qa.json`, `capture_qa.md` -- quality checks and compensation notes
- `transforms.json`, `metricize.json` -- training and metric alignment records
- `LICENSE` -- source attribution and redistribution terms

## Reproduce

The sharpness scan, trim, pipeline, and sample-packaging kernels are under
`kaggle/kernels/`; Kaggle tooling is in `kaggle/tools/`. See
[`kaggle/README.md`](../../kaggle/README.md) for the Kaggle-only workflow.
