# Topoloka — Human-Voice Narration Script (`home_v1`, Rule 9 Compliance)

> **Mandatory Competition Rule (Rule 9):** AI-generated voiceovers are strictly prohibited and cause direct elimination. Record this script in **your own voice** (using your laptop/phone mic in a quiet room) while screen-recording Chrome exploring our live reconstructed 3-room flat (`home_v1` at `https://sciencebanda09.github.io/topoloka/`), then mux cleanly with `docs/demo/mux_submission_video.py`.
>
> Target length: **~3 minutes 15 seconds (~450 words @ ~140 wpm)** covering **both Technical Approach and Live 3D Walkthrough**.

---

## Part 1 — Problem, Own Capture & SOP (~0:00 – 0:50)

*(Screen: Show Title Card + 10 s clip of raw handheld video `home_v1_raw_full.mp4` + `capture/SOP.md` / `docs/fig/pipeline.png`)*

"Hi, I'm Shashank from team Topoloka for Namma Space Round 2.

Mapping indoor spaces today either requires $10,000 LiDAR rigs or creates heavy 500-megabyte meshes that choke mobile browsers. Topoloka turns one continuous smartphone video into a photorealistic, metric 3D Gaussian Splatting digital twin with spatial POI search and obstacle-aware navigation — delivered in a zero-backend web link.

For Round 2, we purged every public and third-party dataset and captured our own 3-room flat in one unbroken handheld landscape take — walking from the Entry Study Room through the Central Hall, looping completely around the Master Bedroom, and closing the loop back into the Central Hall. Our deterministic Capture SOP codifies single-lens framing, EIS off, locked exposure, diffuse lighting, slow 0.4 m/s walking pace, 3-second corner sweeps, smooth doorway crossings, and automated QA reporting."

---

## Part 2 — Reconstruction Pipeline, Ablation, Licensing & Cost (~0:50 – 1:50)

*(Screen: Show `docs/fig/pipeline.png` + `docs/fig/nav.png` + `test/home_v1/capture_qa.md` + Cost table in `docs/abstract.pdf`)*

"On narrow indoor doorways and plain painted walls, standard SIFT Structure-from-Motion fragmented badly — registering only 15.6% of frames across 10 broken sub-models. By integrating commercially licensed **Kornia DISK and LightGlue** (Apache 2.0) with `pycolmap 4.2.1` on GPU at 5 Hz, continuous registration jumped to **78.9% — 296 of 375 frames** with 51,304 3D points and an unbroken 293-frame loop across all three rooms.

To recover real-world metric scale without LiDAR or non-commercial weights, we fuse **Depth Anything V2 Metric Indoor Small** (Apache 2.0) across all 296 views — yielding 648,000 dense voxels and a global scale factor of 0.658 meters per unit. Our custom gravity-prior RANSAC floor aligner explicitly rejects mid-height beds and tables so the floor snaps cleanly to Z equals zero, calibrating camera height to 0.87 meters and carving a 5-centimeter 2.5D occupancy costmap with 22.21 square meters of walkable area and zero geometry warnings.

We then train 25,000 iterations of `nerfstudio splatfacto` (Apache 2.0), prune low-alpha haze, oversized fog floaters, spiky needle splats, and ceiling outliers, and pack spatial-sorted **Level-1 `.ksplat`** — just **11.55 megabytes** for 480,000 Gaussians. Because every dependency is commercially licensed under MIT, BSD-3, or Apache 2.0, self-hosting on cloud GPUs costs roughly 50 to 56 cents per scene versus 2.50 to 5.50 dollars on commercial 3D APIs — with zero per-viewer runtime cost on static GitHub Pages."

---

## Part 3 — Live Browser 3D Walkthrough (`home_v1`) (~1:50 – 3:15)

*(Screen: Live Chrome window at `https://sciencebanda09.github.io/topoloka/` — walk, search, jump, navigate, and drop Sandbox barriers!)*

"Now let's explore our reconstructed 3-room flat live in Chrome.

Notice how the viewer instantly streams the metric point cloud before swapping smoothly into full Gaussian splats at over **50 frames per second**, with vertical FOV clamped to our phone's lens so there are no black ceiling voids. Using WASD and mouse look, I can walk smoothly across the Central Hall past the refrigerator, washbasin, bathroom door, and utility cabinet — tracked live on the 2D metric minimap, with collision preventing walking through walls.

Pressing `/` opens our 1-meter spatial-bucket and fuzzy POI search across all 9 validated POIs in the 3 rooms. Even if I misspell **'wardobe'**, Levenshtein fuzzy matching ranks **Wooden Wardrobe** number one. Selecting it highlights the minimap and card without jolting the camera; clicking **Jump here** flies smoothly into the Master Bedroom right in front of the patterned wooden wardrobe.

Now let's route across all three rooms — from the **Entry Study Desk** to the **Bedroom Alcove and Beds**. Clicking **Navigate** runs clearance-weighted A* across the 5-centimeter costmap, drawing an animated green floor ribbon with landmark-anchored instructions: *'In 3.9 meters, turn left past Refrigerator — 9.8 meters left.'*

Finally, pressing `G` opens the **Interactive Sandbox**. When I drop barriers blocking the Wooden Wardrobe corridor, watch the minimap and green floor path immediately reroute **Central Hall to Bedroom Alcove** from **6.5 meters to 7.7 meters** — looping all the way around the opposite side of the Master Bedroom past the Dressing Mirror. Visitors can also press `E` to tag new POIs on the floor and export `pois.json`, or toggle **AR Mode** for QR-anchored guidance.

Thank you — every link, test, raw video, and QA report is public in our repository and submission folder."

---

## Muxing Your Voiceover into the Final Submission MP4

Once you record your screen walkthrough (`walkthrough.mp4`) and your own-voice audio (`my_voice.m4a` or `.wav`), run our loudness-normalized 1080p30 submission muxer (zero TTS):

```powershell
python docs\demo\mux_submission_video.py --video walkthrough.mp4 --audio my_voice.m4a --out docs\demo\topoloka_r2_submission.mp4
```
