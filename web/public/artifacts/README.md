# Artifacts served by the viewer

Folders here are **generated pipeline output** (gitignored) and are not part
of the source tree. The viewer reads `?capture=<name>` and fetches the bundle
from `artifacts/<name>/`.

Contents of a bundle (produced by the pipeline's `package` stage):

| File | Contract |
|---|---|
| `nav.json` | version, cell_m, origin [x,y], base64 PNG grid (0 free / 1 obstacle / 2 unknown), outline polygon (m), trajectory (m, z-up), `align` = scene→nav transform `p_nav = s·Rᵀ(p_scene−origin)` |
| `cloud.ply` | binary little-endian PLY, xyz float32 (meters, nav frame) + rgb uchar |
| `splat.splat` | optional; 32 B/gaussian (pos f32×3, scale f32×3, rgba u8×4, rot u8×4 `w,x,y,z`); placed with `nav.json.align` |
| `occupancy.png` | debug image of the costmap grid |
| `meta.json` | capture summary: point count, walkable area, splat stats, QA overall |

Generate a bundle outside Kaggle for a quick smoke test (from the repo root):

```powershell
.venv\Scripts\python.exe web\tools\make_synthetic.py
```

…or sync the real thing from a fetched kernel run:

```powershell
powershell -File web\tools\sync_artifacts.ps1 -Kernel namma_splat -Capture house_v1
```
