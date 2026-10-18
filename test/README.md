# test — sample capture for reviewers and fresh clones

This folder will hold a **small, redistributable** capture so anyone can run
the viewer and inspect every pipeline artifact without a Kaggle account or GPU.

Planned layout (filled during R1 packaging):

```
test/
  README.md              <- this file, updated with exact commands
  house_v1/
    frames/              <- ~30 picked frames (subset, for inspection)
    frames_meta.json
    sfm/                 <- poses.json, sfm_report.json, sparse.ply (small)
    depth/               <- scale.json, depth_report.json
    nav/                 <- nav.json, occupancy.png, nav_report.json
    capture_qa.json/.md  <- the honesty surface judges will read
    web/                 <- the exact bundle the viewer serves (nav.json +
                            cloud.ply + splat.splat if size allows)
```

Size policy: keep the folder under ~100 MB (the full splat may ship as a
link instead if it exceeds that; the point cloud alone proves the geometry).

Reproduction stub (to be verified at packaging):

```powershell
# viewer only (no Kaggle needed)
powershell -File web\tools\sync_artifacts.ps1 -Kernel namma_splat
cd web; npm install; npm run dev
# http://localhost:5173/?capture=house_v1

# full pipeline reproduction (needs a Kaggle account + the video input)
# see README.md "Kaggle workflow"
```
