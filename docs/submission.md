# R1 submission checklist (due Oct 31, 2026)

Round 1 deliverables and their exact state. Update status as items land.

## 1. Technical abstract PDF (≤ 5 pages)

- [x] Draft: `docs/abstract.md` (narrative, architecture, novelty, honest
      limitations, roadmap)
- [ ] Fill `[RESULT]` placeholders from the first end-to-end run
      (`capture_qa.md`, `sfm/sfm_report.json`, `depth/scale.json`,
      `splat/splat_convert_report.json`)
- [ ] Convert to PDF (pandoc or browser print-to-PDF), check page count
- [ ] Add 2–3 figures: pipeline diagram (reuse abstract §4), viewer
      screenshot, occupancy grid vs splat overlay
- [ ] Proofread once out loud; numbers must match the repo artifacts

## 2. Free-roam web viewer link

- [x] Viewer app works locally (`web/`, synthetic fixture verified)
- [ ] Real artifacts synced (`sync_artifacts.ps1`) and visually verified
- [ ] Deployed to static hosting (see `web/README.md`: Vercel / CF Pages /
      GitHub Pages)
- [ ] Link tested from a fresh browser profile (cold cache first-load time)
- [ ] Link + QR (same URL) added to the abstract

## 3. Demo video (3–5 min)

- [ ] Follow `docs/demo_script.md` shot list
- [ ] Record with the real twin (house capture), not the synthetic fixture
- [ ] Show QA file + occupancy grid on screen (trust layer is a judging edge)
- [ ] Upload unlisted (YouTube), link in abstract

## 4. Code repo (setup + sample data)

- [x] Pipeline stages documented (`pipeline/README.md`)
- [x] Kaggle workflow scripts (`kaggle/tools/*`) with config template
- [x] Capture SOP (`capture/SOP.md`)
- [x] Local unit test for the splat converter
- [ ] `test/` sample capture: picked frames + artifacts + one-command
      reproduction stub
- [ ] Repo pushed to GitHub (public), license, README top-to-bottom read
- [ ] Fresh-clone check: `git clone` → follow README → `npm run dev` shows
      the sample twin without any Kaggle run

## 5. Budget / dependencies

- [x] All compute on Kaggle free tier (no paid services anywhere)
- [x] No LiDAR / no extra hardware: OnePlus phone + laptop only
- [x] No dmx repo modifications (read-only reference honored)

## Delivery mechanics

- Abstract + video link + repo link via the Techfest submission portal
- Keep a `docs/submission_notes.md` log of what was submitted when
  (portal screenshots on failure are the only defense)
