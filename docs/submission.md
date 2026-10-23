# R1 submission checklist (due Oct 31, 2026)

Round 1 deliverables and their exact state. Numbers below trace to
`test/metro_v1/` and the Kaggle outputs it was assembled from.

## 1. Technical abstract PDF (≤ 5 pages)

- [x] `docs/abstract.md` rewritten for the public metro capture (narrative,
      architecture, novelty, measured results, honest limitations, roadmap)
- [x] All numbers sourced from artifacts: 216/216 registered, 0.403 px median,
      6.2505 m/unit (7.54% MAD), 10.28 M cloud points, 315.05 m² walkable,
      510,336 full / 457,221 sample gaussians, 79.0 min GPU wall time
- [x] Figures: pipeline stage map (Fig. 1), metric occupancy map (Fig. 2),
      GPU-rendered twin still (Fig. 3)
- [x] Rebuilt `docs/abstract.pdf` (5 pages, `tools/build_pdf.ps1`)
- [x] Proofread and re-checked every number against the artifacts (2026-10-23)
- [ ] Replace `Demo video: **pending upload**` with the upload link

## 2. Free-roam web viewer link

- [x] Viewer app works locally with the committed sample:
      `?capture=metro_v1` → splat 0.46 M, 315.05 m², QA PASS
- [x] Real bundle synced into `web/public/artifacts/metro_v1` and visually
      verified on a hardware GPU (ANGLE/D3D11): splat, minimap, HUD, collision
- [x] Pages workflow stages `test/metro_v1/web`; default capture is
      `?capture=metro_v1`
- [x] Pages deploy verified serving the metro sample (run 39928019529; sample
      first deployed in 39863541101):
      <https://sciencebanda09.github.io/topoloka/?capture=metro_v1>
- [x] Cold-load test from a fresh browser profile on the live Pages URL:
      18.4 MB web payload (14.63 MB splat + 3.75 MB cloud + nav), GPU-rendered
      splat 0.46 M, QA PASS; 24.7 MB sample folder including preview frames
- [x] Walkable route verified: unknown space blocked, 1 m free carve along the
      walked path, A* = 350 waypoints / 20.3 m from the default spawn (renders
      in 3D and on the minimap)

## 3. Demo video (3–5 min)

- [x] `docs/demo_script.md` shot list with the measured numbers on hand
- [ ] Record with the **hosted** twin in a hardware-accelerated browser
      (software WebGL stretches the splats)
- [ ] Show the QA file + occupancy grid on screen (trust layer is a judging edge)
- [ ] Upload unlisted (YouTube), put the link in `docs/abstract.md` and rebuild the PDF

## 4. Code repo (setup + sample data)

- [x] Pipeline stages documented (`pipeline/README.md`)
- [x] Kaggle workflow scripts (`kaggle/tools/*`) with config template
- [x] Capture SOP (`capture/SOP.md`)
- [x] `test/metro_v1/`: 24.7 MB sample (14 preview frames, SfM cloud + poses,
      depth scale, metric nav, 457,221-gaussian web splat, 250 k-point cloud,
      QA 6/6 PASS) with a generated README that reproduces the local viewer
- [x] Repo public (MIT), README quickstart + hosted link + controls; source
      clip credited (Pexels License)
- [x] Old private capture removed from HEAD; it is not shipped or referenced
      by the deliverables
- [x] Committed + pushed the metro sample and doc rewrite (`b0e5283`, `b53c431`)
- [x] Fresh-clone check: `git clone` → README steps → `npm ci` + `npm run build`
      served the sample twin (18.4 MB web payload, no Kaggle run)

## 5. Budget / dependencies

- [x] All compute on Kaggle free tier (no paid services anywhere)
- [x] No LiDAR / no extra hardware: phone + laptop only
- [x] No dmx repo modifications (read-only reference honored)

## Delivery mechanics

- Abstract + video link + repo link via the Techfest submission portal
- Keep a `docs/submission_notes.md` log of what was submitted when
  (portal screenshots on failure are the only defense)
