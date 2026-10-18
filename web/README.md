# web — the twin viewer (static site, no backend)

Vite + TypeScript + three.js + `@mkkellogg/gaussian-splats-3d`.
Serves a capture's artifact bundle (`web/` from the pipeline package stage):

```
artifacts/<capture>/
  nav.json        costmap (png+base64), outline, trajectory, align transform
  cloud.ply       point cloud in the nav frame (fallback / debug view, key: P)
  splat.splat     gaussian splat (optional; placed via nav.json.align)
  occupancy.png   debug grid image
  meta.json       capture summary shown in the HUD
```

## Develop

```powershell
npm install
# either: a synthetic fixture that verifies the viewer + splat placement math
..\.venv\Scripts\python.exe tools\make_synthetic.py
# or: real artifacts fetched from a Kaggle run
powershell -File tools\sync_artifacts.ps1 -Kernel namma_splat
npm run dev            # http://localhost:5173/?capture=synthetic
```

Query params: `?capture=<name>` picks the artifact folder, `?route` computes
an A* path from the spawn point to the capture's last trajectory point and
draws it in the 3D scene and the minimap (pathfinding smoke test).

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

WASD walk · mouse look (click to capture pointer) · Shift faster ·
P toggle point cloud · touch: left half virtual stick, right half look.
