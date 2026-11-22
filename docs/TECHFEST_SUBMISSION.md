# Topoloka — Techfest 2026–27 (IIT Bombay) Round 2 Submission Sheet

---

## 1. Quick Copy-Paste Submission Sheet

| Submission Field | Details / URLs |
|---|---|
| **Project Name** | **Topoloka** |
| **Project Tagline** | *One video in. Google Maps for indoors out — in a shareable link.* |
| **Live Web App (R2 — `home_v1`)** | [https://sciencebanda09.github.io/topoloka/](https://sciencebanda09.github.io/topoloka/) |
| **GitHub Repository** | [https://github.com/sciencebanda09/topoloka](https://github.com/sciencebanda09/topoloka) (MIT License) |
| **Technical Abstract & SOP (PDF)** | [`docs/abstract.pdf`](https://github.com/sciencebanda09/topoloka/blob/main/docs/abstract.pdf) (4 pages, ≤ 5 pages) |
| **Raw Capture Video (SOP Proof)** | `home_v1_raw_full.mp4` (`98.6 s`, `1280×576 @ 30 fps` — upload to Drive & paste URL) |
| **Own-Voice R2 Demo Video (3–5 min)** | `[Record with docs/demo/NARRATION_SCRIPT.md & mux via docs/demo/mux_submission_video.py]` |
| **Compute Cost** | **$0.00** (Free Kaggle T4 GPU tier during competition; ~$0.50–$0.56/scene on self-hosted cloud GPUs) |
| **License** | MIT (100% commercially licensed open-source stack; zero `CC-BY-NC` weights) |

---

## 2. Short Submission Descriptions (For Form Limits)

### 50-Word Summary
> **Topoloka** turns a continuous smartphone indoor walkthrough video into an interactive, metric 3D digital twin served via a zero-install static web link. Combining Apache-2.0 `DISK+LightGlue` SfM, Apache-2.0 metric depth fusion, floater-pruned compressed 3D Gaussian Splats (`.ksplat`), and a 5 cm 2.5D costmap, it delivers ~51.5 FPS roaming, spatial POI search, and dynamic A\* navigation.

### 100-Word Summary
> Indoor spaces lack the metric street-view mapping available outdoors. **Topoloka** bridges this gap: record a single walk-through video following our standardized Capture SOP, and our automated pipeline builds a lightweight, metric 3D digital twin accessible in any browser. Topoloka integrates Apache-2.0 **Kornia `DISK+LightGlue`** + `pycolmap` SfM (lifting 3-room registration from 15.6% to 78.9%), **Depth Anything V2 Metric Indoor Small** (Apache 2.0), bed-rejecting RANSAC floor alignment, floater-pruned Level-1 `.ksplat` 3D Gaussian Splats (`11.55 MB`, 480k splats), and a 5 cm costmap (`22.21 m²`). Visitors explore at ~51.5 FPS with a 2D minimap, fuzzy POI search across 9 POIs, A\* routing, dynamic obstacle sandbox, and QR-AR preview.

### 250-Word Summary / Abstract
> **Problem:** Traditional indoor mapping requires expensive LiDAR rigs ($4k–$25k) or manual CAD modeling, while heavy textured meshes (300–800 MB) stall mobile WebGL browsers and lack traversability semantics.
>
> **Solution:** **Topoloka** is a hybrid spatial twin engine that converts a single continuous smartphone video into a fast, photorealistic, metric indoor twin served from static web hosting at $0/view runtime cost. Reconstructed strictly from our team's own 3-room flat walkthrough (`home_v1`), our pipeline extracts sharpest keyframes (`5 Hz`), overcomes indoor SIFT fragmentation via **Kornia `DISK + LightGlue` (Apache 2.0)** + `pycolmap 4.2.1` (`296/375` = `78.9%` vs. `15.6%` SIFT baseline), anchors metric scale via **`Depth-Anything-V2-Metric-Indoor-Small-hf` (Apache 2.0)** (`0.658 m/unit`), fits the true floor via bed-rejecting gravity-prior RANSAC (`22.21 m²` walkable, `0` warnings), trains 25k `nerfstudio splatfacto` 3DGS (Apache 2.0), prunes fog-floaters, spiky needles, and ceiling outliers, and compresses to **Level-1 `.ksplat` (`11.55 MB`, 480k splats)**.
>
> **Key Round 2 Innovations:**
> 1. **Hybrid Photorealistic + Metric Geometry:** Captured-lens VFOV clamping (`23.9°`), instant `cloud.ply` preview streaming into `~51.5 FPS` `.ksplat` 3DGS synced with a 5 cm collision grid and 2D minimap.
> 2. **Spatial + Fuzzy POI Search & Authoring:** 9 validated POIs across 3 rooms (`0` warnings), 1 m spatial buckets + inverted token + Levenshtein `≤ 2` search (`"wardobe"` → `Wooden Wardrobe`), proximity marker decluttering, and click-floor POI tagging (`E`).
> 3. **VCCW/EDT Obstacle-Aware A\* & Sandbox Loop Rerouting:** Multi-room landmark-anchored routes (Entry Study Desk → Bedroom Alcove `9.8 m`), plus live Sandbox barriers (`G`) rerouting Central Hall → Bedroom Alcove from **`6.5 m` → `7.7 m`** around the opposite side of the bedroom loop.
> 4. **Commercial Open-Source Economics:** 100% commercially permissive licenses (MIT / BSD-3 / Apache 2.0), costing ~$0.50–$0.56/scene on self-hosted GPUs (~82–90% cheaper than commercial 3D APIs) with zero per-visitor runtime fees.

---

## 3. Verification Checklist (Pre-Submission Gate)

- [x] **Self-Captured 3-Room Twin (Rule 1):** Reconstructed exclusively from team's own flat walkthrough (`test/home_v1/`, `11.55 MB` `.ksplat`, `22.21 m²`, `9` validated POIs); all public/third-party datasets (`room`, `playroom`, `guildhall-*`, `metro_v1`) permanently removed.
- [x] **Code, Tests & Live Browser E2E:** **30/30** pipeline `pytest` + **63/63** web `vitest` + strict TypeScript + Vite build + Chrome D3D11 Playwright E2E (`51.5 FPS`, `0` console/HTTP errors, verified fuzzy search + `6.5 m → 7.7 m` sandbox loop reroute).
- [x] **Commercial Licensing & Cost Analysis:** 100% Apache-2.0 / MIT / BSD-3 stack (incl. `Kornia DISK+LightGlue` & `Depth-Anything-V2-Metric-Indoor-Small-hf`) + measured API-vs-GPU cost table in 4-page `docs/abstract.pdf`.
- [x] **AI-TTS Removed:** Zero synthetic TTS scripts or audio anywhere in the repository.
- [ ] **Upload Raw Capture Video (`home_v1_raw_full.mp4`):** Upload `kaggle/staging/raw_captures/home_v1_raw_full.mp4` (`50.3 MB`) publicly to Google Drive ("Anyone with the link can view").
- [ ] **Record Human-Narrated R2 Video (Rule 9):** Record own-voice narration (`docs/demo/NARRATION_SCRIPT.md`) over a 1080p walkthrough of live `home_v1` → mux via `python docs/demo/mux_submission_video.py` → upload publicly.
- [ ] **Final Incognito Audit (Rule 12):** Paste the 2 video URLs into `docs/abstract.md`, `capture/SOP.md`, `submission/MASTER_SUBMISSION_DOCUMENT.md`, and `submission/Demonstration_Video_Link.txt`, rebuild PDFs via `python tools/build_pdf.py`, upload `submission/` to Google Drive, and verify every single link in an Incognito browser window before **30 Nov 2026**.
