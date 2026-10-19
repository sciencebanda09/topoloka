# Submission notes — running log

What was submitted, when, and where the canonical links live. Keep this list
append-only; the portal is the only place that matters, this file is the defense
copy.

## Links (canonical)

| Item | Link | Status |
|------|------|--------|
| Repo | https://github.com/sciencebanda09/topoloka | public, created 2026-10-18 |
| Viewer (hosted) | https://sciencebanda09.github.io/topoloka/?capture=house_v1 | live (viewer shell); real twin bundle lands after the GPU run |
| Demo video | (YouTube unlisted, filled after recording) | pending |
| Abstract PDF | `docs/abstract.pdf` in repo | draft |

## Log

- 2026-10-18 — Public repo created (GitHub Pages via Actions deployed and
  verified). Viewer hosting pipelines: committed sample under
  `test/house_v1/web/` is copied into the Pages build by
  `.github/workflows/web-pages.yml` -- no duplicated data in git.

- 2026-10-18 — R1 build sprint: pipeline v2 kernel (frames→sfm→geometry→qa→
  package) rerun after fixing code staging; GPU splat kernel prepared
  (splatfacto, 20k iters, seed points from SfM, no auto-orient/scale to keep
  the documented nav frame). Flag names audited against nerfstudio 1.1.5
  source. Kaggle quirk found: dataset versions that mix tar+zip hang during
  processing — capture dataset ships zips + plain files only.
- 2026-10-18 — Environment probes: nerfstudio 1.1.5 installs cleanly on the
  Kaggle Python 3.13 image with no torch downgrade; pycolmap 4.2.1 has a
  cp313 manylinux wheel; open3d 0.20.0 too (required by the dataparser's
  point-cloud loading).

- 2026-10-19 — Pipeline v3 ran green end-to-end (status ok, 39.7 min of
  Kaggle CPU): 158 frames kept; SfM 157/158 registered (99.4%), 54,931
  points, median reprojection error 0.563 px; geometry found 1,277 floor
  inliers and a 19.21 m² walkable outline (chest-height scale on the CPU
  path — the GPU run supersedes it with the metric depth scale). QA: WARN
  only on the geometry scale check. Three real bugs were found and fixed:
    * pycolmap 4.2.1 API drift — num_reg_images / num_points3D /
      reg_image_ids and Image.cam_from_world are METHODS now (properties in
      3.x), and Reconstruction.write()/write_text() require the target
      directory to exist. SfM itself had been healthy (99.4% registered);
      the crash was in our post-processing. Pinned by
      pipeline/tests/test_sfm_api.py.
    * PLY layout — our writers emitted "all xyz, then all rgb" while the PLY
      spec (and every reader: geometry.load_cloud, trimesh/open3d for the
      splat init, three.js PLYLoader) reads per-vertex x,y,z,r,g,b. The nav
      grid had been built from misparsed points. Writers fixed + byte-exact
      round-trip tests (pipeline/tests/test_ply_roundtrip.py).
    * one camera per capture — extraction now uses CameraMode.SINGLE (same
      as the dmx-slam reference); the 4.x default made one camera per image
      with a ±13% focal spread.
  Kernel scratch (code/, runs/, ns/) moved to /tmp so output fetches pull
  only out/; fetch script forces UTF-8 (the kaggle CLI died printing unicode)
  and retries twice.

- 2026-10-19 — Capture dataset re-shipped clean before the queued GPU run
  started: sparse.ply rebuilt from COLMAP's own text model (54,875 points
  after dropping 56 far outliers, per-vertex interleaved). namma-code and
  namma-capture-v1 re-pushed as new versions; both verified `ready`, GPU
  kernel still queued at mount time.

- 2026-10-19 (afternoon) — GPU run 1 post-mortem and fixes:
    * namma-splat v1 came back COMPLETE in 2.1 s: namma-code mounted, but
      namma-capture-v1 did not. The kernel was pushed at 23:57 while the
      capture dataset was mid-re-versioning (v2/v3 pushes overlapped), and
      the mount was resolved against that unstable state and dropped
      silently. By morning the dataset was `ready` and its file list shows
      frames/*.jpg — Kaggle unpacked frames.zip at upload, so kernel staging
      must accept both zip files and pre-extracted directories.
    * Staging hardened: the capture root is now found by content
      (transforms.json / frames.zip / frames/ / poses.json) rather than by
      mount name, and the failure path dumps the /kaggle/input tree. Kernel
      re-pushed (v2, queued 13:29 IST) with re-versioning long finished.
    * geometry cam_height sign bug fixed: the plane distance was negated, so
      every heuristic (non-fixed-scale) run was clamped to
      CHEST_HEIGHT_M / 0.2 = 6.75 regardless of camera height. Affects the
      CPU fallback path only — the GPU run uses the metric depth scale.
      Pinned by pipeline/tests/test_geometry_align.py (3 tests).
    * Local test suite green (13 tests across 5 files); abstract PDF
      toolchain re-verified (draft renders 3 pages: pandoc + headless
      Chrome).
