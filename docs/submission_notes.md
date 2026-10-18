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
