# Capture QA -- house_v1

**Overall: PASS** (2026-10-21 15:27:23)

| Check | Status | Detail | Compensation |
|---|---|---|---|
| frame_sharpness | PASS | p10 Laplacian 367 (threshold 100) | watch the demo video for soft zones; recapture the worst rooms in brighter light |
| frame_count | PASS | 158 frames kept (stride 12) | fewer views -> weaker splat around fast-motion areas |
| sfm_registered_fraction | PASS | 157/158 frames registered | unregistered stretches get no texture; walk slower with more overlap there |
| sfm_reprojection_error | PASS | median 0.563px (threshold 1.0) | check video stabilization is OFF; EIS warps break rigid geometry |
| floor_outline | PASS | 56 outline points, 13.89 m2 walkable | sparse cloud can under-draw the footprint; the depth stage densifies it |
| geometry_warnings | PASS | none | see nav_report.json for details |
