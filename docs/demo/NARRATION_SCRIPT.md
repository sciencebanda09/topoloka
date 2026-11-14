# Topoloka — Human-Voice Narration Script (Rule 9 Compliance)

> **Important Competition Rule:** AI-generated voiceovers are strictly prohibited and cause direct elimination. Record this script in **your own voice** (using your laptop/phone mic in a quiet room) after we rebuild your own multi-room space capture, then share the `.wav` / `.mp3` / `.m4a` file so we can mux it cleanly into the final 1080p submission MP4.
>
> Target length: **~3 minutes (420 words @ ~140 wpm)** covering **both Technical Approach and 3D Walkthrough**.

---

## Part 1 — Problem & Capture SOP (~0:00 – 0:45)

"Hi, I’m Shashank from team Topoloka for Namma Space Round 2.

Mapping indoor spaces today either requires $10,000 LiDAR scanners or produces heavy 500-megabyte meshes that crash mobile browsers. Topoloka turns one continuous smartphone video into an interactive, metric 3D Gaussian Splatting twin that loads in seconds in any browser.

Everything starts with our standardized capture SOP. Using a single phone lens at 4K 30 fps in landscape, we lock exposure and focus, disable electronic image stabilization so frames remain geometrically rigid, and walk at 0.4 meters per second keeping 1.2 to 2 meters from walls. We record one continuous two-pass loop across multiple rooms — Pass 1 tilted slightly up for walls and ceilings, careful 3-second corner sweeps and slow doorway crossings, and Pass 2 tilted down for floors — ending with a 5-second still hold back at the start to lock loop closure."

---

## Part 2 — Reconstruction Pipeline, Licensing & Cost (~0:45 – 1:40)

"After recording, our automated QA gate rejects blurry frames using Laplacian variance and verifies camera registration and reprojection error.

Next, `pycolmap` computes sparse camera poses under a single calibrated lens model. Because monocular SfM has arbitrary scale, we fuse metric depth predictions from the commercially licensed **Depth Anything V2 Metric Indoor Small** Apache-2.0 model and solve the exact metric scale factor via median pairwise ratios.

We then run vectorized RANSAC plane fitting to align gravity and snap the floor to Y equals zero, rasterize a 5-centimeter 2.5D occupancy grid with continuous corridor carving and Euclidean distance weighting, and train a float-pruned 3D Gaussian Splat using Nerfstudio and `gsplat`. Finally, we encode the scene into Level-1 compressed `.ksplat` format — cutting payload sizes down to around 10 megabytes with zero client-side partitioning stalls.

Because every component — `pycolmap`, Depth Anything V2 Small, Nerfstudio, OpenCV, and Three.js — is permissively licensed for commercial use, self-hosting on spot cloud GPUs costs roughly 25 to 35 cents per scene versus several dollars per scan for managed commercial APIs, with zero runtime hosting cost on static pages."

---

## Part 3 — Live Browser 3D Walkthrough (~1:40 – 3:00)

"Now let’s walk through the actual reconstructed space live in Chrome.

Notice how the viewer immediately displays an interactive 3D point cloud with live download progress before seamlessly swapping into full Gaussian splats at 55 to 60 frames per second. Using WASD and mouse look, I can roam freely across rooms while the collision boundary prevents walking through walls, tracked live on the top-right metric minimap.

With the model switcher or hotkey `P`, I can inspect the underlying metric point cloud or toggle the minimap with `M`. Pressing `/` opens spatial and fuzzy POI search — clicking **Navigate** computes an obstacle-aware A* path rendered right across the floor with real-time turn-by-turn distance and ETA.

Using `E`, anyone can click the floor to tag new POIs and export `pois.json`. Pressing `G` opens the Sandbox to drop physical obstacles like cones or barriers and watch A* dynamically route around them. Finally, switching to **AR Mode** lets visitors scan an on-site QR anchor to relocalize their pose and follow directional AR turn guidance toward any room."

---

## Muxing Your Voiceover into the Final Walkthrough MP4

Once you record your narration audio (e.g. `my_voice.m4a`) and we record the 1080p walkthrough of your reconstructed space (`walkthrough.mp4`), mux them cleanly with `ffmpeg`:

```powershell
ffmpeg -y -i walkthrough.mp4 -i my_voice.m4a -c:v copy -c:a aac -b:a 192k -shortest topoloka_r2_submission.mp4
```
