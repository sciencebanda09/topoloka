# Sandbox: pick-and-place props (R2 preview)

The sandbox is an **additive** layer on the hosted viewer. It is off by
default and runs on the hosted Melbourne Metro sample.

**Preview link:**
<https://sciencebanda09.github.io/topoloka/?v=20261031-clean>

Press **G** to enter the sandbox (or add `&sandbox=1` to the viewer URL).

## What it does

Pick up and place small virtual props in the twin:

| Key | Action |
|---|---|
| `1` | add a traffic cone |
| `2` | add a barrier |
| `3` | add a crate |
| `4` | add a wet-floor sign |
| click / tap | pick up an aimed prop, or place the carried one |
| `R` / `Shift+R` | rotate the carried prop ±15° |
| `Del` | remove the aimed placed prop |
| `T` | toggle the route to the end of the capture |
| `G` | enter / leave the sandbox |
| `Esc` | cancel the current carry (restores a picked-up prop) |

While carrying, a green or red preview sits on the floor. Green means the
footprint is on free nav space, clear of the player and other props; red means
the map blocks it, it is too close, or there is no floor hit. On touch, use
the panel's **Place**, **Rotate**, and **Cancel** buttons.

On desktop the pointer is locked while walking, so press **Esc** to release
the mouse before clicking panel-only actions (**Clear**, **Copy link**); the
rest have keyboard shortcuts. Re-pick a carried prop after cancelling.

Placed props persist in `localStorage` per capture. **Copy link** encodes the
layout into `?props=`, so a layout can be opened on another machine.

## Dynamic obstacles and routing

Each placed prop is rasterized into the 5 cm costmap's dynamic layer. Player
collision and A* both see it. With a route active (`?route`, `T`, or the
panel's route button), placing a barrier recomputes the path from the current
position; removing it restores the old path. If the route is severed, the tube
and minimap line disappear and the HUD says `route: no path`.

This is the R2-relevant part: the twin is not just a picture, it is a navigable
model whose obstacles can be edited.

## What is and is not being picked up

The props are **real meshes**, not scanned geometry. The splat remains
read-only. This is deliberate:

- A Gaussian splat is a baked radiance field with no object graph.
- Cutting an object out of the splat and moving it leaves a hole where the
  wall/floor behind it was never observed, and the object's backside does not
  exist.
- Moving the scanned geometry would need per-object segmentation plus
  inpainting/re-synthesis; that is R3 research, not a reliable R2 feature.

The props render correctly in the same scene as the splat: the viewer
composites `threeScene` first (props write depth), then the splat pass. Splats
behind a prop fail the depth test; splats in front blend over it. Placement
raycasts the splat's own BVH (the tree the library builds for its focal-point
picker), so props sit on the reconstructed floor rather than a guessed plane.

## Implementation

- `web/src/props.ts` — procedural prop geometry and shared materials.
- `web/src/sandbox.ts` — carry/place state, splat raycasts, validity checks,
  persistence, share links, keyboard/touch input.
- `web/src/nav.ts` — `setDynamicObstacles()` overlay + `Footprint` rasterizer.
- `web/src/splat.ts` — `raycastRay()` wrapper over the library BVH.
- `web/src/minimap.ts` — prop markers.
- `web/src/main.ts` — route refresh and sandbox boot (`?sandbox=1`).

No new assets or runtime dependencies; the props are built from three.js
primitives and canvas textures.

## Verification

- `cd web && npm run build` — TypeScript strict + Vite production build.
- Dynamic costmap test (headless): barrier severs a corridor, clearing it
  restores the route, and a blocked A* start escapes to a free cell.
- R1 regression by construction: with no `?sandbox`/`?props`, the sandbox
  group stays invisible (props/lights inert), the panel and reticle stay
  hidden, and the dynamic obstacle layer is empty, so the default HUD, route,
  and rendering path are unchanged. The extra hidden DOM is inert.
- Deployed Pages build checked over HTTPS: the viewer HTML contains the hidden
  sandbox panel, the JS bundle contains the sandbox and splat-raycast code, and
  `nav.json` / `splat.splat` return 200 for `metro_v1`.

## Not in this pass

- POI database/search cards (R2 next).
- Wall-mounted placement and surface-normal snapping.
- Moving scanned objects (see above).
- Multi-user sync; layouts are local or link-shared, not server-backed.
