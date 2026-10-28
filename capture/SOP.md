# Namma Space — Capture SOP (Standard Operating Procedure)

Version: **0.1 (draft)** · Applies to: smartphone video captures of indoor spaces
Owner: Namma Space team · Status: to be validated against captures, then frozen for R1

Phone file → hosted twin: see `capture/phone-to-twin.md` for the one-command
Kaggle path and the live-vs-offline boundary.

The SOP exists because reconstruction quality is decided **at capture time**.
Every rule below traces to a failure mode of the pipeline; every capture ends
with a QA report that says pass/fail per check — with the compensation applied.

---

## 1. Equipment

| Item | Requirement | Notes |
|------|-------------|-------|
| Phone | Any modern Android/iOS, single lens is fine | OnePlus (primary device for this team) |
| Capture app | **Sensor Logger** (Android, free) | Records `video` + IMU (`sensors.csv`) + capture settings (`capture_info.json`) with aligned clocks — exactly the bundle our pipeline parses |
| Lighting | All room lights ON, curtains open (daylight) | Avoid capturing after sunset; avoid direct sun glare in frame |
| Room prep | Clear the walking path; people out of frame | Moving people are masked, but fewer is better |
| (R2+/R3) QR anchors | 2–4 printed A4 QR markers + tape | Placed per §3.4; they power AR relocalization |

## 2. Phone settings (lock these before recording)

| Setting | Value | Why |
|---|---|---|
| Resolution / FPS | 4K 30fps (fallback 1080p 30fps) | Splat detail comes from pixels; 30fps is plenty for 0.4 m/s walking |
| **Video stabilization (EIS)** | **OFF** | EIS warps frames non-rigidly → camera poses and geometry drift. This is the #1 silent killer |
| Auto exposure / focus | **LOCK** before walking | Prevents focus hunting and exposure pulsing mid-video |
| Portrait vs landscape | **Landscape** | Wider horizontal FOV per frame → better overlap tracking |
| Flash | OFF | — |
| Storage check | ≥ 2 GB free per 10 minutes of 4K | — |

## 3. Capture protocol

### 3.1 The two-pass loop (per room / zone)

Walk **one continuous loop** around the space; do not cross your own path except to close the loop.

- **Pass 1 — walls & ceiling**: phone at chest height (~1.3–1.4 m), landscape, tilted ~10° up. Walk the perimeter at **~0.4 m/s** (half normal walking speed).
- **Pass 2 — fine detail**: same loop reversed, tilted ~20° down. Pause 2 seconds and slowly pan across feature areas: work desks, sofas, appliances, signage.
- **Loop closure**: return to the exact starting spot, **hold still 5 seconds**, then stop recording. The still tail anchors the loop closure.

### 3.2 Framing rules

- Keep **60–70% frame overlap** between consecutive positions (at 0.4 m/s with 30fps this is automatic — the risk is walking too fast).
- Aim the camera so **both wall and floor** appear together at turns; corners must be seen from at least two angles.
- **Slow, deliberate turns** (≈30°/s). Fast pans are the top source of motion blur.
- Avoid: mirrors head-on (skip or pass at an angle), pure blank walls for long stretches (pan through them slowly), direct window glare.

### 3.3 Room-by-room flow

1. Largest room first (it sets the coordinate frame), then corridors, then small rooms.
2. **Doorways**: approach straight-on from both sides, slow. The doorway is the stitch point between zones.
3. Do not stop recording between rooms — one video per capture session, one final loop closure at the start point.

### 3.4 QR anchors (for R2/R3 AR)

- Print 2–4 QR markers (A4, 150 mm × 150 mm data area), place on a wall at ~1.2 m height, one per major zone.
- **Show each marker clearly in the video for ≥ 3 seconds** during Pass 2 — this is how the pipeline learns the marker's 3D position.
- Record marker IDs + placement in `capture_notes.md` (zone, wall).

## 4. After capture — the QA gate

Run (on Kaggle): `python -m namma.cli qa <capture_dir>` → `capture_qa.json`

| Check | Threshold | If failed |
|---|---|---|
| Frame sharpness | p10 Laplacian ≥ 100 | Recapture the worst zones (QA reports timestamps) |
| Registered fraction (post-SfM) | ≥ 60% | Walk slower through failed zones; add a second pass there |
| Median reprojection error | ≤ 1.0 px | Usually EIS left on — check settings, recapture |
| Video stabilization | OFF | Recapture (mandatory — no software fix) |
| Coverage volume | ≥ 80% of walkable area | Add missing zone passes |
| Motion blur p90 | ≤ 4 px (gyro-derived, when logs present) | Walk slower, brighter light |

**Rule: recapture, don't patch.** A bad capture costs 10 minutes; a bad
reconstruction costs the whole round.

## 5. Why these rules (rationale for judges / Q&A)

- **EIS off**: EIS applies time-varying non-rigid warps; multi-view geometry assumes a rigid camera. Keeping EIS off makes SfM and 3DGS treat frames as honest rigid projections.
- **Sharpest-frame picking**: footfall shake is periodic (~2 Hz walk cadence). Picking the sharpest frame inside each stride window removes most motion blur without gyro; when gyro logs exist, we can later pick by least rotational blur instead.
- **Loop closure with still tail**: gives SfM a hard constraint to close drift — the single biggest accuracy win in monocular indoor reconstruction.
- **Two-pass (up/down tilt)**: 3DGS needs floor coverage and wall coverage; one chest-height pass under-covers both. Two cheap passes fix it.
- **4K**: splat fidelity is bounded by texture detail; 1080p is a fallback, not the target.

## 6. Version log

| Version | Date | Change |
|---------|------|--------|
| 0.1 | 2026-10-18 | Initial draft (two-pass loop protocol, settings lock, QA gate) |
