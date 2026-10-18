# Demo video — storyboard (3–5 min, R1)

Goal: prove the claim "one video in → Google Maps for indoors out, in a link"
in under 5 minutes, with zero hand-waving. Every number shown must come from
the artifact files, not from a slide.

## Shot list

| # | Time | Shot | What it proves |
|---|---|---|---|
| 1 | 0:00–0:25 | Phone in hand walking through the house (10 s real capture footage from the original run). Text overlay: "One walk. One phone. No LiDAR." | The input is honest: a normal handheld video. |
| 2 | 0:25–0:55 | Terminal: `push_code.ps1` → `push_kernel.ps1 namma_pipeline` → show the Kaggle kernel running; cut to GPU kernel (`namma_splat`). Speed-ramp the waits. | All compute runs on Kaggle free tier; reproducible from the repo's tooling. |
| 3 | 0:55–1:25 | Artifacts landing in the repo: `nav.json`, `occupancy.png`, `capture_qa.md` scrolled on screen. Read 2–3 QA numbers out loud (registered %, reprojection px, scale source). | The QA/trust layer is real; scale is solved, not assumed. |
| 4 | 1:25–2:45 | **The money shot.** Browser opens the viewer link: pointer-lock, walk with WASD through the splat twin. Turn the minimap corner. Walk into a wall, stop; explains collision from the metric costmap. | Free-roam, photorealistic, collision-honest twin in a link. |
| 5 | 2:45–3:15 | Type a route (`?route` dev flag or search bar in R2): A* path renders in 3D + minimap with distance. | Navigation is metric and computed, not faked. |
| 6 | 3:15–3:45 | Quick zoom-out animation of `occupancy.png` grid vs the splat's real geometry overlay (align transform). Blur the honesty slide: "where it's weak" (mirrors, low texture). | Frame conventions and limitations are handled, not hidden. |
| 7 | 3:45–4:15 | Roadmap punch card: R2 POI search ("where's the washroom" on-screen demo mock), R3 on-site campus + QR AR. Close on the title card + repo URL. | The story continues beyond R1. |

## Recording notes

- Record at 1080p60; OBS or Win+G. Do a silent run-through first.
- One continuous screen take for the viewer section — jump cuts in a free-roam
  demo read as faked.
- Keep the pointer visible; viewers need to see the walk is player-driven.
- Zoom the terminal font to ~16 pt; speed-ramp only the pip-install waits.
- Voice-over live while walking (not a post-dub) — breaths sell the scale.
- Export H.264, ≤ 500 MB, upload unlisted YouTube; link goes in the abstract.

## Numbers to have on hand (fill from `capture_qa.md`)

- frames kept / registered fraction / median reprojection error
- metric scale + source (`depth-scale` vs fallback) + MAD
- walkable area (m²), costmap cell 5 cm
- splat gaussians + web payload MB + viewer load time (stopwatch it)
- pipeline wall time: CPU kernel min + GPU kernel min
