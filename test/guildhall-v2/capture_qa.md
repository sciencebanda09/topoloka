# Capture QA -- guildhall-v2

**Overall: PASS** (2026-10-30 21:55:45)

| Check | Status | Detail | Compensation |
|---|---|---|---|
| frame_sharpness | PASS | p10 Laplacian 1533 (threshold 100) | watch the demo video for soft zones; recapture the worst rooms in brighter light |
| frame_count | PASS | 230 frames kept (stride 12) | fewer views -> weaker splat around fast-motion areas |
| sfm_registered_fraction | PASS | 204/230 frames registered | unregistered stretches get no texture; walk slower with more overlap there |
| sfm_reprojection_error | PASS | median 0.554px (threshold 1.0) | check video stabilization is OFF; EIS warps break rigid geometry |
| floor_outline | PASS | 169 outline points, 23.4 m2 walkable | sparse cloud can under-draw the footprint; the depth stage densifies it |
| geometry_warnings | PASS | none | see nav_report.json for details |
