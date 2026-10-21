# R1 submission checklist (due Oct 31, 2026)

Round 1 deliverables and their exact state.

## 1. Technical abstract PDF (â‰¤ 5 pages)

- [x] Draft: `docs/abstract.md` (narrative, architecture, novelty, honest
      limitations, roadmap)
- [x] Every `[RESULT]` filled from the end-to-end run (158 frames, 157/158
      registered, 0.563 px, 0.4361 m/unit, 13.89 mÂ², 903,308 gaussians,
      28.9 MB payload, CPU 39.7 min + GPU 41.9 min)
- [x] PDF renders at 4 pages (`tools/build_pdf.ps1`)
- [x] Figures: pipeline stage map (Fig. 1), metric occupancy map (Fig. 2), hosted twin still (Fig. 3)
- [ ] Proofread once out loud; numbers must match the repo artifacts
      (all numbers above trace to `test/house_v1/`)
- [ ] `Demo video:` line updated with the upload link (record first)

## 2. Free-roam web viewer link

- [x] Viewer app works locally (`web/`, synthetic fixture + real twin)
- [x] Real artifacts synced and visually verified (headless Chrome render
      of the house twin: splat, minimap, HUD)
- [x] Deployed on GitHub Pages, serving the committed sample:
      <https://sciencebanda09.github.io/topoloka/?capture=house_v1>
- [x] Link added to the abstract; loads in a clean profile (splat 0.37M, no console errors)
- [ ] Link tested from a fresh browser profile (cold cache first-load time) â€”
      first load fetches 11.8 MB splat + 3.8 MB cloud

## 3. Demo video (3â€“5 min)

- [x] `docs/demo_script.md` shot list with the measured numbers on hand
- [ ] Record with the real twin (local bundle in
      `web/public/artifacts/house_v1/` has the full 903K-gaussian splat)
- [ ] Show QA file + occupancy grid on screen (trust layer is a judging edge)
- [ ] Upload unlisted (YouTube), put the link in `docs/abstract.md`

## 4. Code repo (setup + sample data)

- [x] Pipeline stages documented (`pipeline/README.md`)
- [x] Kaggle workflow scripts (`kaggle/tools/*`) with config template
- [x] Capture SOP (`capture/SOP.md`)
- [x] `test/house_v1/`: 22 MB sample (14 frames, SfM cloud + poses, depth
      scale, metric nav, 367K-gaussian cropped splat, QA 6/6 PASS) with a
      generated README that reproduces the local viewer in two commands
- [x] Repo public (MIT), README quickstart + hosted link + controls
- [ ] Fresh-clone check: `git clone` â†’ follow README â†’ `npm run dev` shows
      the sample twin without any Kaggle run

## 5. Budget / dependencies

- [x] All compute on Kaggle free tier (no paid services anywhere)
- [x] No LiDAR / no extra hardware: OnePlus phone + laptop only
- [x] No dmx repo modifications (read-only reference honored)

## Delivery mechanics

- Abstract + video link + repo link via the Techfest submission portal
- Keep a `docs/submission_notes.md` log of what was submitted when
  (portal screenshots on failure are the only defense)
