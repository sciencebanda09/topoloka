# Artifacts served by the viewer

Folders here are **generated pipeline output** (gitignored) and are not part
of the source tree. The viewer reads `?capture=<name>` and fetches the bundle
from `artifacts/<name>/` (default: `home_v1`).

Contents of a bundle (produced by the pipeline's `package` stage):

| File | Contract |
|---|---|
| `nav.json` | version, cell_m, origin [x,y], base64 PNG grid (0 free / 1 obstacle / 2 unknown), outline polygon (m), trajectory (m, z-up) with captured yaws/pitches, camera intrinsics, `align` = scene→nav transform `p_nav = s·Rᵀ(p_scene−origin)` |
| `pois.json` | authored POIs with floor coordinates, category, aliases, description, and captured camera `view` poses |
| `cloud.ply` | binary little-endian PLY, xyz float32 (meters, nav frame) + rgb uchar |
| `splat.ksplat` | Level-1 compressed 3D Gaussian Splat (or `.splat`); placed with `nav.json.align` |
| `occupancy.png` | debug image of the costmap grid |
| `meta.json` | capture summary: point count, walkable area, splat stats, POI count, QA overall |

Stage the committed self-captured twin (`home_v1`) from the repo root:

```powershell
python tools/activate_capture.py home_v1 --label "Home 3-Room Twin — POIs & nav"
```

Or generate a synthetic smoke-test bundle outside Kaggle:

```powershell
python web\tools\make_synthetic.py
```
