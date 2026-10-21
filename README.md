# Topoloka — spatial twin engine

**One video in. Google Maps for indoors out — in a link.**

*Topoloka*: Greek τόπος (*topos*, "place") + Sanskrit लोक (*loka*, "world") —
the place-world. Turns an ordinary phone capture of an indoor space into a
photorealistic, interactive 3D digital twin served as a shareable web link:
free first-person roaming, spatial search, and obstacle-aware walking
directions. Built for Techfest 2026-27 (IIT Bombay).

```
phone capture ──► Kaggle pipeline ──► artifact bundle ──► web app (static link)
 video + IMU      frames → SfM           splat + nav graph      roam / search / route
 (our SOP)        → depth → 3DGS         + POIs + trust         (+ AR on-site)
```

## Repository layout

| Path          | What it is |
|---------------|------------|
| `capture/`    | Capture SOP + capture QA tooling (the "how to record" contract) |
| `pipeline/`   | Reconstruction pipeline (frames → SfM → geometry → depth → splat → POIs → export) |
| `web/`        | The viewer web app (roaming, search, navigation, minimap) |
| `kaggle/`     | Kaggle tooling: code dataset, kernels, push/fetch scripts |
| `docs/`       | Technical abstract, submission links, planning notes |
| `test/`       | Sample capture data + reproduction instructions |

## Compute rule

**All pipeline runs execute on Kaggle** (CPU or GPU), driven by `kaggle/`.
The local machine only edits code, commits, and talks to the Kaggle CLI.
See `kaggle/README.md`.

## Quickstart (viewer + sample data)

The committed sample capture is a real house walk, decimated so the repo stays
light: `test/house_v1/` (14 preview frames, SfM cloud, metric nav, splat,
`capture_qa.md`). It is the same data the hosted link serves.

**Hosted twin:** <https://sciencebanda09.github.io/topoloka/?capture=house_v1>

**Locally** (Node 20+):

```powershell
# stage the committed sample where the viewer fetches artifacts
New-Item -ItemType Directory -Force web/public/artifacts/house_v1 | Out-Null
Copy-Item -Recurse -Force test/house_v1/web/* web/public/artifacts/house_v1/
cd web
npm ci
npm run dev        # open http://127.0.0.1:5173/?capture=house_v1
```

```bash
# same, on a POSIX shell
mkdir -p web/public/artifacts/house_v1
cp -r test/house_v1/web/. web/public/artifacts/house_v1/
cd web && npm ci && npm run dev
```

Drag to look, **WASD/arrows** to walk, **M** toggles the minimap, **P** toggles
the point cloud behind the splat. `npm run build` produces a static `dist/`
that can be served from any web host.

**Reproduce the pipeline:** the exact kernels that produced this capture are
in `kaggle/kernels/` and are driven by the scripts in `kaggle/tools/` — see
`kaggle/README.md` and `test/house_v1/README.md`.

## Status

- [x] Repo skeleton, capture fixture (house video)
- [x] Stage 1: frame picking (`pipeline/namma/frames.py`)
- [x] Stage 2: SfM (`pipeline/namma/sfm.py`) — Kaggle run in progress
- [x] Stage 3: geometry — floor plane, gravity align, 2.5D costmap (`pipeline/namma/geometry.py`)
- [x] Stage 4: depth — Depth Anything V2 metric fusion + scale alignment (`pipeline/namma/depth.py`)
- [x] Stage 5: capture QA (`pipeline/namma/qa.py`)
- [x] Stage 6: splat training kernel (nerfstudio splatfacto) + web conversion
- [x] Stage 7: web bundle packaging (`pipeline/namma/package.py`)
- [x] Web: first-person viewer + minimap + splat renderer (synthetic fixture verified)
- [ ] First end-to-end run on the house capture (kernels in flight)
- [ ] Web: search + pathfinding + route rendering (R2)
- [ ] AR mode (QR-anchored relocalization, R3)

## Deadlines

| Round | Due | Scope |
|-------|-----|-------|
| R1 | 31 Oct 2026 | SOP + 3D reconstruction + free-roam web viewer |
| R2 | 30 Nov 2026 | POIs + spatial search + desktop navigation |
| R3 | 16–17 Dec 2026 | On-site capture at IIT Bombay + live demo (+ AR bonus) |
