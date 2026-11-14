# Topoloka — Data Capture Standard Operating Procedure (SOP)

**Version:** `1.0` · **Scope:** Multi-room and multi-floor smartphone capture for metric 3D reconstruction

This SOP defines a deterministic field capture procedure so any operator with an ordinary smartphone can record reproducible footage that passes the automated QA gate (`capture_qa.json`) and reconstructs cleanly without floaters, blur, or scale drift.

---

## 1. Equipment & Environmental Preparation

| Parameter | Mandatory Requirement | Why It Matters |
|---|---|---|
| **Capture Device** | Modern smartphone (12 MP+ main 1x wide lens, Android/iOS). Team reference device: OnePlus (Android). | Single calibrated-intrinsics main sensor keeps `pycolmap` `CameraMode.SINGLE` exact. |
| **Capture App** | Native camera app or **Sensor Logger** (Android, free) | Sensor Logger logs synchronized MP4 + IMU (`sensors.csv`) + settings (`capture_info.json`) for motion-blur QA. |
| **Resolution / FPS** | **4K (3840×2160) @ 30 fps** (minimum fallback: 1080p @ 30 fps) | Crisp feature extraction for SfM & sharp splat textures; 30 fps provides high overlap without thermal throttling. |
| **Stabilization (EIS)** | **OFF** (Android mandatory; on iOS avoid rapid pans) | EIS warps frames non-rigidly per frame, breaking epipolar rigidity and elevating reprojection error (> 1 px). |
| **Exposure & Focus** | **AE / AF LOCKED** on a neutrally lit textured wall before walking (Flash OFF) | Prevents brightness pumping and focus breathing during slow doorway transitions. |
| **Orientation** | **Landscape (16:9)** | Wider horizontal FOV increases parallax overlap across adjacent walls and doorways. |
| **Lighting Conditions** | All room overhead lights **ON** + daylight curtains open; avoid direct sun-in-lens glare | Uniform diffuse lighting (> 150 lux) prevents dark under-exposed shadow noise and blown-out windows. |
| **Room & Path Prep** | Clear walkways, open connecting doors fully, remove moving people/pets; reserve ≥ 2 GB free space per 10 min | Dynamic actors cause ghost floaters; fixed door leaves anchor inter-room alignment. |
| **AR QR Anchors (Optional)** | 2–4 printed A4 QR markers (`150 × 150 mm` code) taped on flat walls at ~1.2 m height | Holds 3+ seconds in frame during Pass 2 to register absolute AR relocalization anchors. |

---

## 2. Camera Geometry, Distances & Movement Pace

| Rule | Specification | Tolerance / Failure Mode |
|---|---|---|
| **Walking Speed** | **`0.4 m/s`** (~half normal stroll; slow to `0.3 m/s` through doorways and stairs) | > 0.7 m/s introduces stride blur and drops consecutive overlap below 60%. |
| **Wall Stand-Off Distance** | **`1.2 m – 2.0 m`** from perimeter walls (in narrow corridors `< 1.5 m` wide, walk down the centerline) | < 0.8 m starves SfM baselines and creates grazing-angle splat streaking. |
| **Frame Overlap** | **`60% – 70%`** visual overlap between adjacent keyframes (`2.5 Hz` extracted keyframes) | Guaranteed automatically at `0.4 m/s` + `30°/s` max angular rate. |
| **Turn Rate** | **`≤ 30°/s`** slow rotational pan (no snap turns) | Fast yaw spins trigger rolling-shutter skew and SIFT matching failures. |
| **Camera Height & Tilt** | **Chest height (`1.3 – 1.4 m`)**: Pass 1 tilted **`+10°` up**, Pass 2 tilted **`-20°` down** | Dual-tilt captures both ceiling/signage topology and floor-wall obstacle boundaries. |

---

## 3. Room, Corner, Multi-Room & Multi-Floor Capture Sequence

Record **one continuous video take (`90–240 s`)** per space without stopping between rooms:

1. **Start & Baseline Hold (Anchor Origin):** Stand in the **largest primary room** facing an open corner or textured wall (`1.5–2.0 m` away). Lock AE/AF, press record, and **hold completely stationary for 5 seconds** to establish crisp initial triangulation baselines.
2. **Pass 1 — Perimeter Walls & Upper Topology (`+10°` tilt):** Walk clockwise along a continuous closed loop `1.2–2.0 m` from walls at `0.4 m/s`. Aim so both wall features and ceiling lines stay visible.
3. **Every-Corner Coverage Protocol (Mandatory):** Do **not** cut corners diagonally. At each corner of every room:
   - Approach along Wall A up to `1.5 m` from the corner vertex.
   - Pivot smoothly (`≤ 30°/s`) in a 1 m radius arc keeping the **vertical corner seam + floor junction centered for ≥ 3 seconds** across `45°–60°` viewing angles onto both Wall A and Wall B before walking along Wall B.
4. **Doorways & Multi-Room Transitions:** Walk straight-on toward open doorways (`0.3 m/s`), hold center framing as you cross the threshold, pause 1 second on the far side, and pan gently `±25°` so frames inside Room B share common features with frames through the doorway from Room A. Walk the next room's loop using the exact same corner protocol, then exit back through the doorway.
5. **Multi-Floor Stairwell Transitions (When Capturing 2+ Floors):**
   - Approach the stair landing straight-on; keep handrails, steps, and adjacent landing wall in frame simultaneously.
   - Ascend/descend smoothly at **`0.25–0.35 m/s`**, pitching camera slightly downward (`-15°`) on ascent or level (`0°`) with gentle yaw toward the inner landing wall so consecutive keyframes never drop below 65% overlap on featureless risers.
   - Complete the upper floor room loop and return down the same stairs back to Floor 1.
6. **Pass 2 — Floor, Furniture & Fine Detail (`-20°` tilt):** Reverse loop direction tilting `-20°` down to cover floor seams, table legs, walkways, and any printed AR QR markers (`≥ 3 s` steady view per marker).
7. **Loop Closure Hold:** Return to the exact starting spot and camera heading from Step 1; **hold completely stationary for 5 seconds**, then stop recording.

---

## 4. Optional 2D Floor Plan & Scale Calibration Photos

Topoloka derives its **2.5D metric occupancy grid (`nav.json`) automatically** from SfM + Apache-2.0 foundation metric depth without requiring an existing CAD plan. However, when a 2D architectural floor plan or physical scale verification photos are captured alongside the video, follow these strict rules:

1. **2D Floor Plan Image Capture:** Place the printed architectural plan flat on a matte table under diffuse overhead light (zero glare). Hold the phone strictly parallel (`0°` tilt, grid-lines aligned orthogonally to frame edges), include all four plan corners plus a readable **metric scale bar or doorway dimension label**, and export as lossless PNG/JPEG (`≥ 2000 px` wide).
2. **Metric Reference Scale Photos (Ground-Truth Check):** Tape or lay a rigid carpenter's ruler / tape measure (`≥ 2.00 m`) flat across a doorway threshold or corridor tile edge. Take 3 sharp photos squarely (`±15°` normal) showing both the `0.00 m` and `2.00 m` marks and adjacent fixed wall corners in full focus.

---

## 5. Automated Post-Capture QA Gate (`python -m namma.cli qa`)

Every video pass must clear all 6 automated checks in `capture_qa.json` before reconstruction deployment:

| QA Check | Pass Threshold | Action on Failure |
|---|---|---|
| Frame sharpness | Laplacian variance `p10 ≥ 100` | Recapture poorly lit / fast-panned segment |
| Registered camera views | `≥ 60%` of keyframes registered | Slow down through failed doorway/corridor |
| Median reprojection error | `≤ 1.0 px` | Verify EIS was turned **OFF** and recapture |
| Video stabilization | EIS **OFF** | Recapture (non-rigid warps cannot be fixed cleanly) |
| Walkable area coverage | `≥ 80%` floor polygon covered | Add missing corner or Pass 2 down-tilt coverage |
| Gyro motion blur (when IMU logged) | `p90 ≤ 4 px` | Improve lighting & walk at `0.4 m/s` |

---

## 6. Actual Team Capture Examples & Raw Videos

> **Team Submission Slot (Self-Captured Multi-Room / Multi-Floor Space):**
> Follow Sections 1–5 to record your continuous loop walkthrough video (`my_space_raw.mp4`/`.mov`), run `kaggle/tools/push_video.ps1`, extract 6 sample raw keyframes (`capture/examples/`), and update the table below + public release link before Round 2 submission.

| Capture Asset | Format / Specs | Public Link / Repo Path |
|---|---|---|
| Raw Continuous Capture Video | Unedited phone MP4/MOV (`4K/30` or `1080p/30`, EIS OFF) | `[To be populated with user capture GitHub Release / Drive URL]` |
| Extracted Raw Frame Previews | 6–14 keyframes covering corners, doorway, stairwell | `test/<team_capture>/frames/` |
| Automated Capture QA Report | 6/6 QA thresholds + scale MAD report | `test/<team_capture>/capture_qa.md` |
