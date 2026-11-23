# Capture QA -- home_v1

**Overall: FAIL** (2026-11-23 18:08:24)

| Check | Status | Detail | Compensation |
|---|---|---|---|
| frame_sharpness | FAIL | p10 Laplacian 26 (threshold 100) | watch the demo video for soft zones; recapture the worst rooms in brighter light |
| frame_count | PASS | 375 frames kept (stride 6) | fewer views -> weaker splat around fast-motion areas |
| sfm_registered_fraction | WARN | 296/375 frames registered | unregistered stretches get no texture; walk slower with more overlap there |
| sfm_reprojection_error | FAIL | median 1.569px (threshold 1.0) | check video stabilization is OFF; EIS warps break rigid geometry |
| floor_outline | PASS | 69 outline points, 21.71 m2 walkable | sparse cloud can under-draw the footprint; the depth stage densifies it |
| geometry_warnings | PASS | none | see nav_report.json for details |
| poi_dataset | PASS | 9 POIs across 4 categories | indexed by the viewer at load time |
| video_stabilization | SKIP | capture_info.json EIS flag not present |  |
| imu_motion_blur | SKIP | sensors.csv / Gyroscope.csv not found |  |
| qr_anchors | SKIP | nav/anchors.json not found | run `namma anchors` when QR markers are recorded for R3 AR |
