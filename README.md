# Topoloka spatial twin engine

**One video in. Google Maps for indoors out — in a link.**

*Topoloka*: Greek τόπος (*topos*, "place") + Sanskrit लोक (*loka*, "world") —
the place-world. Turns a walk-through video of an indoor space into an
interactive, metric 3D digital twin served as a shareable web link: free
first-person roaming now, spatial search and obstacle-aware walking directions
next. Built for Techfest 2026-27 (IIT Bombay).

```
walk-through video ──► Kaggle pipeline ──► artifact bundle ──► web app (static link)
 (phone SOP or         frames → SfM          splat + nav graph      roam / (R2) search
  licensed clip)       → depth → 3DGS       + QA + align          and route / (R3) AR
```

## Repository layout

| Path          | What it is |
|---------------|------------|
| `capture/`    | Capture SOP + capture QA tooling (the "how to record" contract) |
| `pipeline/`   | Reconstruction pipeline (frames → SfM → geometry → depth → splat → POIs → export) |
| `web/`        | The viewer web app (roaming, minimap, navigation, splat renderer) |
| `kaggle/`     | Kaggle tooling: code dataset, kernels, push/fetch scripts |
| `docs/`       | Technical abstract, submission links, figures, demo storyboard |
| `test/`       | Redistributable sample capture + reproduction instructions |
| `tools/`      | Sample builder and figure helpers |

## Compute rule

**All pipeline runs execute on Kaggle** (CPU or GPU), driven by `kaggle/`.
The local machine only edits code, commits, and talks to the Kaggle CLI.
See `kaggle/README.md`.

## The public sample

The committed sample is a real, continuous walk through a Melbourne metro
walkway, built from public footage:

- **Source:** *Modern Melbourne Metro Walkway Urban Design* by Joolsmagool
  (Pexels License), trimmed to 86.07 s, 1920×1080 / 30 fps.
- **Bundle:** `test/metro_v1/` — 24.7 MB, 14 preview frames, SfM cloud + poses,
  depth scale, metric nav, 457,221-gaussian web splat, QA report.
- **Measured:** 216/216 frames registered, 0.403 px median reprojection,
  6.2505 m/unit (7.54% MAD), 315.05 m² walkable, QA **6/6 PASS**.

It is the same data the hosted link serves.

**Hosted twin:** <https://sciencebanda09.github.io/topoloka/?capture=metro_v1>

![The metro twin in a browser: splat, minimap, QA status](docs/fig/twin.png)

*The shipped sample twin: 457,221 Gaussian splats, the metric minimap
(red = obstacles, blue = capture path), and the QA verdict in the HUD. The
viewer now renders with the capture's own lens (68.0° horizontal / 41.6°
vertical) instead of a generic wide FOV, and hides the point-cloud debug grid
once the splat loads. Reflective walls still render softer than the tiled
floor; the geometry and sightlines are metric.*

**Locally** (Node 20+):

```powershell
# stage the committed sample where the viewer fetches artifacts
New-Item -ItemType Directory -Force web\public\artifacts\metro_v1 | Out-Null
Copy-Item -Recurse -Force test\metro_v1\web\* web\public\artifacts\metro_v1\
cd web
npm ci
npm run dev        # open http://127.0.0.1:5173/?capture=metro_v1
```

```bash
# same, on a POSIX shell
mkdir -p web/public/artifacts/metro_v1
cp -r test/metro_v1/web/. web/public/artifacts/metro_v1/
cd web && npm ci && npm run dev
```

Drag to look, **WASD/arrows** to walk, **M** toggles the minimap, **P** toggles
the point cloud behind the splat. The viewer opens at 75% of the capture path,
inside the reconstructed volume; append `?t=<index>` to spawn at a specific
trajectory point (`?t=0` is the true start, `?t=160` is the Figure 3 view), and
`?clean` to hide the click prompt and fps readout. Unobserved space is not
walkable: collision blocks it and carves a 1 m free corridor along the capture
path, which the camera proved traversable. `?route` draws the scaffolded A*
route as a thin green floor tube (20.3 m / 350 waypoints from the default
spawn), with a matching swatch in the minimap legend. On touch devices the
left half is a walk stick and the right half looks; **M** hides the map for a
full-screen view. `npm run build` produces a static `dist/` that can be served
from any web host.

**Frame budget (measured).** On an AMD Radeon integrated GPU through
ANGLE/D3D11, at a 1600×900 viewport, the adaptive renderer holds **36.8 fps
idle / 52.4 fps walking** at the default spawn (internal buffer 1155×650) and
**35.5 / 37.9 fps** at the worst corridor view `?t=90` (buffer 899×506). At
1920×1080 it holds **34.0 / 48.2 fps**. The viewer renders with
`antialias: false` — MSAA was the dominant cost on this iGPU and the splat
edges do not need it — and drops the internal buffer in 0.08 steps only when
the true frame rate falls below 32 fps (`?scale=` pins it for measurement).
The HUD reports true frame time; it previously clamped `dt` before computing
FPS, which put a fake 20 fps floor on every reading.

**Reproduce the pipeline:** the exact kernels that produced this capture are in
`kaggle/kernels/` and are driven by the scripts in `kaggle/tools/` — see
`kaggle/README.md` and `test/metro_v1/README.md`.

## Status

- [x] Repo skeleton, capture SOP, frame picking, QA gates
- [x] SfM (`pycolmap` 4.2.1) — 216/216 registered on the metro clip
- [x] Metric depth fusion (Depth Anything V2 Metric Indoor Large) + scale alignment
- [x] Geometry: floor plane, gravity align, 2.5D 5 cm costmap, outline
- [x] Splat training (nerfstudio 1.1.5 splatfacto, 25 k iters) + web `.splat` export
- [x] Web: first-person viewer, collision, minimap, splat renderer, `?t` spawn
- [x] Viewer fidelity/perf pass: capture-matched lens, adaptive resolution,
      true-FPS HUD, minimap legend, debug geometry hidden after splat load
- [x] End-to-end public run — CPU SfM 59.2 min; GPU 79.0 min total; 510,336
      gaussians exported; 315.05 m² walkable; QA 6/6 PASS
- [x] Hosted sample twin: <https://sciencebanda09.github.io/topoloka/?capture=metro_v1>
      (457,221 gaussians / 14.63 MB, 3 m volume crop, 250 k-point cloud)
- [ ] Demo video (3–5 min) — recorded after the hosted build; link goes in the abstract
- [ ] Web: POI search + user-facing pathfinding (R2; A* / route rendering already scaffolded)
- [ ] AR mode (QR-anchored relocalization, R3)

## Credit and licences

Sample footage: *Modern Melbourne Metro Walkway Urban Design* by **Joolsmagool**
on Pexels, used under the [Pexels License](https://www.pexels.com/license/) and
trimmed to 86 s. The derived sample artifacts in `test/metro_v1` are
redistributed under that licence; the code is MIT. No personal capture is
shipped.

## Deadlines

| Round | Due | Scope |
|-------|-----|-------|
| R1 | 31 Oct 2026 | SOP + 3D reconstruction + free-roam web viewer |
| R2 | 30 Nov 2026 | POIs + spatial search + desktop navigation |
| R3 | 16–17 Dec 2026 | On-site capture at IIT Bombay + live demo (+ AR bonus) |
