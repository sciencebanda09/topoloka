# pipeline — one video in, a navigable twin out

Every stage is a pure function of the previous stage's files. Each writes a
machine-readable `*_report.json` that states what happened — including what
went wrong and what the pipeline did about it ("report, never lie").

```
<capture>/
  frames/            stage 1  picked frames + frames_meta.json
  sfm/               stage 2  poses.json, sparse model, sparse.ply, transforms.json
  depth/             stage 3  metric scale + dense map.npz (GPU)
  nav/               stage 4  nav.json (costmap, outline, trajectory, align)
  capture_qa.*       stage 5  QA checks (never blocks, always reports)
  splat/             stage 6  splat.splat (GPU; web format)
  web/               stage 7  the artifact bundle the viewer serves
```

| Stage | Command | Runs on | What it does |
|---|---|---|---|
| frames | `python -m namma.cli frames <video> <capture> --target-rate 2.5 --max-width 1600` | Kaggle CPU | keeps the sharpest frame per stride window (footfall shake removal) |
| sfm | `python -m namma.cli sfm <capture>` | Kaggle CPU | pycolmap SIFT + matching + incremental mapping; exports poses, PLY, transforms.json |
| depth | `python -m namma.cli depth <capture>` | **GPU** | Depth Anything V2 (metric indoor); aligns metric depth to arbitrary-scale SfM via `median(depth_m / sparse_camera_z)`; fuses a dense 3 cm cloud in meters |
| geometry | `python -m namma.cli geometry <capture>` | Kaggle CPU | gravity from camera up-axis mean → RANSAC floor plane → z-up metric frame → 5 cm 2.5D costmap → floor outline polygon |
| qa | `python -m namma.cli qa <capture>` | anywhere | capture QA table (sharpness, registration, reprojection, footprint) |
| splat training | `kaggle/kernels/namma_splat` | **GPU** | nerfstudio splatfacto (auto-orient/center/scale disabled — the nav frame is the contract) |
| splat-convert | `python -m namma.cli splat-convert <ply> <out.splat>` | anywhere | 3DGS PLY → 32-byte-per-gaussian web format (DC colors) |
| package | `python -m namma.cli package <capture>` | Kaggle | assembles `web/` (nav.json, cloud.ply in nav frame, splat.splat, meta.json) |

## Frame conventions (the part that bites)

- **COLMAP/scene frame**: arbitrary scale, arbitrary orientation (raw SfM).
- **nav frame**: x/y horizontal, **z up**, origin on the floor under the camera
  mean, **meters**. `nav.json.align` documents the exact transform from the
  scene frame: `p_nav_m = scale * R^T @ (p_scene_units - origin)`.
- **three.js frame** (web): `(x, z, -y)` — done once in `web/src/viewer.ts`.
- The splat trains in the **scene frame** (nerfstudio's own normalization is
  disabled) and is placed in the viewer by `nav.json.align` (`web/src/splat.ts`).

## Running on Kaggle

All runs go through the `kaggle/` tooling — never on the dev machine:

```powershell
powershell -File kaggle\tools\push_code.ps1                  # sync pipeline source
powershell -File kaggle\tools\push_kernel.ps1 namma_pipeline # CPU: frames→sfm→geometry→qa→package
powershell -File kaggle\tools\fetch_output.ps1 namma_pipeline -Watch
powershell -File kaggle\tools\push_capture.ps1               # stage capture for the GPU kernel
powershell -File kaggle\tools\push_kernel.ps1 namma_splat    # GPU: depth→nav→splat→package
powershell -File kaggle\tools\fetch_output.ps1 namma_splat -Watch
powershell -File web\tools\sync_artifacts.ps1 -Kernel namma_splat
```

Environment variables a kernel honors: `NM_TARGET_RATE` (default 2.5 kept
frames/s), `NM_MAX_W` (default 1600 px), `NM_ITERS` (splat iterations, default
15000).
