# Capture QA -- home_v1

**Overall: WARN** (2026-10-31 23:04:45)

| Check | Status | Detail | Compensation |
|---|---|---|---|
| frame_sharpness | WARN | p10 Laplacian 87 (threshold 100) | watch the demo video for soft zones; recapture the worst rooms in brighter light |
| frame_count | PASS | 156 frames kept (stride 12) | fewer views -> weaker splat around fast-motion areas |
| sfm_registered_fraction | WARN | 122/156 frames registered | unregistered stretches get no texture; walk slower with more overlap there |
| sfm_reprojection_error | PASS | median 0.638px (threshold 1.0) | check video stabilization is OFF; EIS warps break rigid geometry |
| floor_outline | PASS | 63 outline points, 8.05 m2 walkable | sparse cloud can under-draw the footprint; the depth stage densifies it |
| geometry_warnings | PASS | none | see nav_report.json for details |
