# R1 submission checklist (due Oct 31, 2026)

Round 1 deliverables and their exact state. Numbers below trace to
`test/guildhall-v1/` (the R1 public stand-in), `test/metro_v1/` (second
sample), and the Kaggle outputs they were assembled from.

## 1. Technical abstract PDF (≤ 5 pages)

- [x] `docs/abstract.md` rewritten around two public captures (narrative,
      architecture, novelty, measured results, honest limitations, roadmap);
      Guildhall is the R1 stand-in, metro the second sample
- [x] All numbers sourced from artifacts: Guildhall 218/218 registered,
      0.515 px median, 3.8204 m/unit (8.29% MAD), 14.46 M cloud points,
      458.81 m² walkable, 688,558 full / 632,993 sample gaussians, 76.2 min
      GPU; metro 216/216, 0.403 px, 6.2505 m/unit (7.54% MAD), 10.28 M,
      315.05 m², 510,336 / 457,221, 79.0 min
- [x] Figures: pipeline stage map (Fig. 1), Guildhall metric occupancy map
      (Fig. 2), metro GPU-rendered twin still (Fig. 3)
- [x] Rebuilt `docs/abstract.pdf` (5 pages, 2.48 MB, `tools/build_pdf.ps1`) on
      2026-10-29 with the Guildhall results, both viewer links, and the demo
      link
- [x] Re-checked every number against `test/guildhall-v1/` and
      `test/metro_v1/` artifacts (2026-10-29)

## 2. Free-roam web viewer link

- [x] Viewer app works locally with the committed samples:
      `?capture=metro_v1` → splat 0.46 M, 315.05 m², QA PASS;
      `?capture=guildhall-v1` → splat 0.63 M, 458.81 m², QA PASS
- [x] Real bundles synced into `web/public/artifacts/` and visually verified on
      a hardware GPU (ANGLE/D3D11) for metro: splat, minimap, HUD, collision
- [x] Pages workflow stages every committed `test/*/web` sample; the viewer
      selector switches samples without separate hosted links.
- [x] Single hosted viewer: <https://sciencebanda09.github.io/topoloka/>
      (improved Guildhall v2 is the default; choose any saved sample in the menu).
      HTTPS checks return 200 for `meta.json` (QA PASS), `nav.json`, and the
      selected sample's `splat.splat` after deployment.
- [x] Cold-load test from a fresh browser profile on the live Pages URL
      (metro): 18.4 MB web payload (14.63 MB splat + 3.75 MB cloud + nav),
      GPU-rendered splat 0.46 M, QA PASS; cold ready 19.2 s (13.96 MB splat +
      3.38 MB cloud transferred); 24.7 MB sample folder including preview
      frames. Guildhall cold load is not yet measured.
- [x] Walkable route verified: unknown space blocked, 1 m free carve along the
      walked path, A* = 350 waypoints / 20.3 m from the default spawn (renders
      in 3D and on the minimap)

## 3. Demo video (3–5 min)

- [x] `docs/demo_script.md` shot list and the shipped 3:33 cut
- [x] Record the **hosted** twin in a hardware-accelerated browser
      (ANGLE/D3D11); software WebGL stretches the splats
- [x] QA numbers and the metric occupancy figure on screen (cards built from
      the shipped reports; no invented values)
- [x] Hosted as a GitHub release asset (41.0 MB), linked from
      `docs/abstract.md` and the rebuilt PDF:
      <https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4>
- [x] 3:33 · 1920×1080 / 30 fps · H.264 + AAC; captions and source credit on
      screen
- [x] The shipped cut uses the metro sample; the abstract labels it as such.
      A Guildhall re-cut is optional and requires recording the hosted twin in
      a hardware-accelerated browser (user action; no local browser runs).

## 4. Code repo (setup + sample data)

- [x] Pipeline stages documented (`pipeline/README.md`)
- [x] Kaggle workflow scripts (`kaggle/tools/*`) with config template
- [x] Capture SOP (`capture/SOP.md`)
- [x] `test/metro_v1/`: 24.7 MB sample (14 preview frames, SfM cloud + poses,
      depth scale, metric nav, 457,221-gaussian web splat, 250 k-point cloud,
      QA 6/6 PASS) with a generated README that reproduces the local viewer
- [x] `test/guildhall-v1/`: 31.0 MB R1 stand-in sample (14 preview frames,
      SfM cloud + poses, depth scale, metric nav, 632,993-gaussian web splat,
      250 k-point cloud, QA 6/6 PASS), with CC BY-SA 4.0 attribution in
      `README.md` and `LICENSE`
- [x] Repo public (MIT), README quickstart + hosted links + controls; both
      source clips credited (Pexels License, CC BY-SA 4.0)
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
