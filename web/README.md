# web — the twin viewer (static site, no backend)

Vite + TypeScript + three.js + `@mkkellogg/gaussian-splats-3d`.
Serves a capture's artifact bundle (`web/` from the pipeline package stage):

```
artifacts/<capture>/
  nav.json        costmap (png+base64), outline, trajectory, align transform,
                  and the capture camera intrinsics (`camera`)
  pois.json       authored POI dataset (optional; validated by the pipeline)
  cloud.ply       point cloud in the nav frame (fallback / debug view, key: P)
  splat.splat     gaussian splat (optional; placed via nav.json.align)
  mesh.glb        photo-textured MVS mesh (optional; preferred when present)
  occupancy.png   debug grid image
  meta.json       capture summary shown in the HUD
```

The hosted viewer currently serves the Melbourne Metro sample with its 10
authored POIs. **VIEW MODEL** switches between its Gaussian splat and point
cloud; **VIEW SAMPLE** switches to the Studio Room visual benchmark (its
costmap is synthetic all-free space, so it is not a navigation demo). The
default public URL opens Metro.

## Develop

```powershell
npm install
# either: a synthetic fixture that verifies the viewer + splat placement math
..\.venv\Scripts\python.exe tools\make_synthetic.py
# or: real artifacts fetched from a Kaggle run
powershell -File tools\sync_artifacts.ps1 -Kernel namma_splat
npm run dev            # http://localhost:5173/?capture=synthetic
```

Query params: `?capture=<name>` picks the artifact folder, `?model=mesh|splat|points`
selects a representation, `?route` computes
an A* path from the spawn point to the capture's last trajectory point and
draws it in the 3D scene and the minimap (pathfinding smoke test), `?t=<index>`
spawns at a trajectory sample, `?clean` hides the prompt/FPS for stills, and
`?scale=<0.4..1>` pins the internal render scale (otherwise the viewer adapts
to keep the true frame rate near 32 fps).

R2 query params: `?q=<query>` opens search with that query, `?poi=<id>`
selects the POI and flies to its authored view, `?sandbox=1` opens the prop
sandbox, and `?props=<base64url JSON>` restores a shared prop layout.

## POIs, search and navigation (R2)

The viewer fetches `pois.json` beside `nav.json`, builds an in-memory index, and
renders a marker per record. The index is not a linear filter:

- 1 m position buckets for `nearest()` / `within()` queries (including
  nearest-in-category);
- inverted token postings over names, aliases, and categories;
- vocabulary-wide prefix/substring expansion and Levenshtein fuzzy matching
  (`<= 2`);
- deterministic ranking with a bounded proximity tie-breaker.

`/` or `Ctrl/Cmd+K` focuses search. Selecting a result, a 3D marker, or a
minimap dot only highlights the POI; the camera moves only on **Jump here** or
`?poi=`. **Navigate** plans a route on the same 5 cm costmap used for
collision: unknown/obstacle cells are blocked, the walked path is carved free,
planning adds 0.10 m clearance, and the tracker emits instructions, reroutes
after 1.2 m off-route, and stops within 0.7 m of the goal.

Press **E** to author a POI: click the floor, fill the name/category/aliases,
and save. Local tags persist in `localStorage` per capture and **Export
pois.json** downloads the validated schema. The contract, validation rules, and
ranking table are in [`../docs/poi.md`](../docs/poi.md).

Tests (Node 20+):

```powershell
npm test          # 50 Vitest tests: pois, nav, navigation
npm run typecheck # tsc --noEmit
npm run build     # strict TS + Vite production build
```

## Lens and frame budget

`nav.json.camera` carries the pinhole intrinsics of the capture frames. The
viewer derives the horizontal FOV from `w` and `fl_x` and matches it, instead
of using a generic wide lens that stretches anisotropic gaussians and reveals
unobserved ceiling. On portrait screens the vertical FOV is capped at 50° so a
phone does not stare into the ceiling void. Rendering runs at CSS resolution ×
the adaptive scale (no device-pixel-ratio multiplier), with
`antialias: false`; both are deliberate fill-rate choices for integrated GPUs.
The debug ground grid and floor outline are hidden as soon as the splat loads
(they otherwise show through holes as black seams); **P** still reveals the
point cloud, and the minimap keeps the occupancy/path legend.

## Build + deploy (static hosting)

```powershell
npm run build          # -> dist/ ; base './' so it works at any path
```

Deploy `dist/` anywhere static:

- **Vercel**: `npx vercel deploy --prod dist` (or connect the repo; framework
  preset Vite, output `dist`).
- **Cloudflare Pages**: `npx wrangler pages deploy dist`.
- **GitHub Pages**: push `dist/` to a `gh-pages` branch, or use the provided
  workflow (`.github/workflows/web-pages.yml`) which builds and deploys.
  Note: `web/public/artifacts/*` is gitignored, so for a Pages deploy either
  commit a demo capture (see `tools/sync_artifacts.ps1`) or have CI fetch it.

SharedArrayBuffer-based splat sorting is deliberately disabled (COOP/COEP
headers are not available on plain static hosting), so the viewer works on
any host with zero configuration.

## Controls

W/S forward/back | A/D sidestep around objects | mouse look (click to capture pointer) | Shift faster |
`/` search (or `Ctrl/Cmd+K`) | `E` tag a POI | click marker/result to select |
**Jump here** / **Navigate** on the POI card | `M` toggle minimap | `P` toggle
point cloud | touch: left half virtual stick, right half look. The minimap
legend is free / obstacle / unknown / path / POI, plus route when one is
active and prop when the sandbox is on.
