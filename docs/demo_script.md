# Demo video — storyboard (3–5 min, R1)

Goal: prove the claim "one video in → Google Maps for indoors out, in a link"
in under 5 minutes, with zero hand-waving. Every number shown must come from
the artifact files, not from a slide.

## Shot list

| # | Time | Shot | What it proves |
|---|---|---|---|
| 1 | 0:00–0:25 | The source walk-through: 10 s of the metro corridor clip (public Pexels footage, credited on screen). Text overlay: "One walk-through. One ordinary video. No LiDAR." | The input is honest: a single RGB clip, no depth sensor. |
| 2 | 0:25–0:55 | Terminal: `push_code.ps1` → `push_kernel.ps1 namma_pipeline` → show the Kaggle kernel running; cut to GPU kernel (`namma_splat`). Speed-ramp the waits. | All compute runs on Kaggle free tier; reproducible from the repo's tooling. |
| 3 | 0:55–1:25 | Artifacts landing in the repo: `nav.json`, `occupancy.png`, `capture_qa.md` scrolled on screen. Read 2–3 QA numbers out loud: 216/216 registered, 0.403 px median, 6.2505 m/unit, 315.05 m² walkable. | The QA/trust layer is real; scale is solved, not assumed. |
| 4 | 1:25–2:45 | **The money shot.** Browser opens the viewer link: pointer-lock, walk with WASD down the tiled corridor, past the ad screens, toward the green exit sign. Point out that the view matches the source lens (68° horizontal, not a wide-angle stretch). Toggle **M** to show/hide the minimap and its legend. Walk into a wall, stop; explain collision from the metric costmap. | Free-roam twin + collision-honest navigation in a link, no install. |
| 5 | 2:45–3:15 | Append `?route` to the default link (dev flag; user-facing search lands in R2): the green A* route tube renders on the floor and on the minimap with its metric length — 350 waypoints, 20.3 m to the far end of the captured walk. | Navigation is metric and computed, not faked. |
| 6 | 3:15–3:45 | Zoom-out of `occupancy.png` vs the splat geometry; overlay the align transform. Honesty slide: reflective walls are soft, DC-only splat, and the top of the frame is clamped to the capture's observed shell. | Frame conventions and limitations are handled, not hidden. |
| 7 | 3:45–4:15 | Roadmap punch card: R2 POI search ("where's the washroom" mock), R3 on-site campus + QR AR. Close on the title card + repo URL. | The story continues beyond R1. |

## Recording notes

- **Hardware acceleration is mandatory.** Headless/software WebGL (SwiftShader)
  stretches anisotropic gaussians and makes the twin look smeared. Check
  `chrome://gpu` shows "Hardware accelerated", then record in normal Chrome.
- **Exact URLs.** Default walk: <https://sciencebanda09.github.io/topoloka/?capture=metro_v1>
  (opens inside the corridor, 20.3 m to the far end of the walk; turn around
  and walk back to show the long leg). Route shot: append `&route&clean`. Use
  `&t=160` only for a still; `&clean` hides the click prompt and fps. The
  route is a 2.2 cm green floor tube now, so it survives 1080p compression;
  the minimap legend hides its route swatch unless `?route` is active.
- Record at 1080p60; OBS or Win+G. Do a silent run-through first.
- One continuous screen take for the viewer section — jump cuts in a free-roam
  demo read as faked.
- Keep the pointer visible; viewers need to see the walk is player-driven.
- Zoom the terminal font to ~16 pt; speed-ramp only the pip-install waits.
- Voice-over live while walking (not a post-dub) — breaths sell the scale.
- Export H.264, ≤ 500 MB, upload unlisted YouTube; link goes in the abstract.

## Numbers to have on hand (from `test/metro_v1/capture_qa.md`, `nav_report.json`, `train_report.json`)

- 216 frames kept at 2.5 Hz; 216/216 registered (100%); median reprojection 0.403 px (mean 0.613)
- SfM: 51,677 points, 3,553 s (59.2 min) on Kaggle CPU
- Metric scale 6.2505 m/unit; MAD 7.54% over 37,844 depth samples
- Depth: 31.2 M raw → 10.28 M voxel points; 216/216 frames fused
- Nav: 929,436 floor inliers; camera height 1.588 m; 315.05 m² walkable (126,020 free cells); grid 1188 × 1259 @ 5 cm; nav stage 61 s
- Splat: 25,000 iters at 1600×900; full export 510,336 gaussians / 16.33 MB; hosted sample 457,221 / 14.63 MB after the 3 m crop
- Web payload 18.4 MB (14.63 MB splat + 3.75 MB cloud + nav); full sample folder 24.7 MB with frames/reports; cold ready **19.2 s** in a fresh profile (13.96 MB splat + 3.38 MB cloud transferred)
- Viewer default spawn is 75% of the path; A* route is 350 waypoints / 20.3 m (unknown space blocked, 1 m walked-path carve)
- Viewer performance (live Pages build): AMD Radeon integrated GPU via
  ANGLE/D3D11, 1600×900, adaptive buffer — **51.0 fps idle / 60.1 fps walking**
  at spawn and **43.0 / 40.2 fps** at worst view `?t=90` (1155×650 in both);
  **59.9 / 60.2 fps** in a 390×844 DPR2 mobile layout with touch emulation
  (desktop GPU; layout/input validation only). Frame rate is the true RAF
  rate, not the old clamped-dt reading.
- Render lens: capture intrinsics 1600×900, `fl_x=fl_y=1186.56` → **67.98°
  horizontal / 41.6° vertical**; debug grid/outline hidden after splat load;
  pitch clamped to −0.85..+0.35 rad.
- Pipeline wall time: CPU 59.2 min (SfM) + 61 s (nav); GPU 79.0 min total (depth, gsplat JIT, train, export)
- Source clip: "Modern Melbourne Metro Walkway Urban Design", Joolsmagool,
  Pexels License; trimmed to 86.07 s, 1920×1080 / 30 fps
