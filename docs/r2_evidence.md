# R2 evidence: POIs, spatial search, and obstacle-aware navigation

Round 2 (due **30 Nov 2026**) asks for clickable POIs, spatial search, and
walkable path navigation from the live web app. This page is the evidence
index: what shipped, how it was verified, and what is honestly out of scope.

## Links

| Deliverable | Link |
|---|---|
| Live web app | <https://sciencebanda09.github.io/topoloka/> |
| R2 branch | <https://github.com/sciencebanda09/topoloka/tree/r2-pois-nav> |
| Main branch (merged R2) | <https://github.com/sciencebanda09/topoloka> |
| Source sample | [`test/metro_v1/`](../test/metro_v1/) |
| POI contract | [`docs/poi.md`](poi.md) |
| R1 demo video (baseline) | <https://github.com/sciencebanda09/topoloka/releases/download/r1-demo/topoloka_demo.mp4> |

The hosted viewer opens **Melbourne Metro — POIs & navigation** by default. The
Studio Room remains selectable as a visual benchmark; its costmap is synthetic
all-free space, so it is not used to claim navigation quality.

## What is clickable

- Every authored POI is a marker in the 3D scene and a dot on the minimap.
- Clicking either selects the POI, opens its card, and labels the minimap dot.
- Search results, markers, and minimap dots all select the same record.
- Selection never moves the camera. **Jump here** (or `?poi=<id>`) flies to the
  authored view pose; **Navigate** computes a route.

The Metro dataset has **7 POIs across 5 categories**:

| Category | Count | Examples |
|---|---|---|
| landmark | 2 | Town Hall Station Sign, Advertising Panels |
| area | 2 | Tunnel Walkway, Curved Passage |
| facility | 1 | Accessible Ramp |
| exit | 1 | Emergency Exit |
| platform | 1 | Platforms 1 & 2 |

## Spatial index and search

`web/src/pois.ts` builds the index at load time — it is not a linear filter:

- **1 m position buckets** for `within()` and ring-expanding `nearest()`
  queries, including nearest-in-category.
- **Inverted token postings** over names, aliases, and categories, plus a
  vocabulary for prefix and substring expansion.
- **Levenshtein fuzzy matching** (`<= 2`) over the vocabulary, not the POI list.
- **Deterministic ranking** (exact name > name prefix > word prefix >
  substring > alias > category > fuzzy) with a bounded proximity tie-breaker.
- **Distance, category and "nearest" intent** handled by the same index.

Deep links: `?q=<query>` opens search; `?poi=<id>` selects and jumps. A search
query alone never moves the visitor.

## Navigation

`web/src/nav.ts` + `web/src/navigation.ts`:

- A* on the pipeline's 5 cm costmap; unknown/obstacle/out-of-bounds cells are
  blocked, the walked trajectory is carved free, and planning dilates obstacles
  by 0.10 m for pedestrian clearance.
- Bounded start/goal snapping (2.5 m), clearance-checked string pulling, and a
  polyline route ribbon in 3D plus a line on the minimap.
- Turn-by-turn instructions, remaining distance and ETA, 1.2 m off-route
  detection, live reroute, and a 0.7 m arrival radius.
- The same planner consumes the sandbox's dynamic obstacle layer, so placed
  props change the route.

Measured route evidence (Metro, default spawn):

| Condition | Route to Tunnel Walkway | Notes |
|---|---|---|
| free costmap | **31.66 m**, 2 waypoints | direct corridor |
| two barriers across the corridor | **31.86 m**, 3 waypoints | route bends around the barrier footprint |

Barriers: `(-4.43, 3.13)` and `(-2.97, 3.67)`, rotation `0.353 rad`. The
blocked plan does not intersect either footprint; disabling the sandbox
restores 31.66 m. This is the live `?props=` path, not a unit-test mock.

## Verification runs

| Check | Command | Result |
|---|---|---|
| Web unit tests | `cd web && npm test` | **50 / 50 pass** (`pois`, `nav`, `navigation`) |
| TypeScript | `cd web && npm run typecheck` | pass (`tsc --noEmit`) |
| Production build | `cd web && npm run build` | pass (953.2 kB JS / 19.6 kB CSS; 249.8 kB JS gzip) |
| Pipeline tests | `python -m pytest -s pipeline/tests` | **21 / 21 pass** |
| POI validation | `python -m namma.cli pois ..\test\metro_v1` | 7 POIs, 5 categories, 0 warnings |
| Capture QA | `python -m namma.cli qa ..\test\metro_v1` | overall **PASS**, `poi_dataset: 7 POIs across 5 categories` |

Runtime smoke test (hardware-accelerated headless Chrome, 1440×900):

| Step | Observed |
|---|---|
| `/` then type `curved` | search focused; one hit: **Curved Passage** |
| select result | card shows **1.7 m away**; camera unchanged |
| **Jump here** | camera flies to the authored Curved Passage view |
| search `exit`, **Navigate**, hold `W` | banner distance falls 25 m → 21 m in 3 s; auto-turn follows the route |
| `E`, click floor, save `Demo Bench` | local tag stored in `localStorage`, searchable, exported |
| export | `metro_v1-pois.json`, `version: 1`, capture `metro_v1` |
| minimap dot click | selects **Town Hall Station Sign** |
| `?poi=town-hall-sign` | selects and jumps to the authored view |
| `?q=tunnel` | opens search with the query, no camera move |
| `?props=` two barriers | Tunnel Walkway route 31.66 m → 31.86 m, no footprint crossing |

Screenshots: [`fig/pois.png`](fig/pois.png) (search + card + minimap) and
[`fig/r2_route.png`](fig/r2_route.png) (active route banner).

## Demo video (shipped)

**4:11 · 1920×1080 / 30 fps · H.264 + AAC · 51.3 MB**

<https://github.com/sciencebanda09/topoloka/releases/download/r2-demo/topoloka_r2_demo.mp4>

The cut is built from live browser captures on the public Pages build plus
typographic cards. No mock UI and no invented numbers.

1. **0:00–0:27 — Intro.** Title card, then the live twin: free-roam is intact,
   the point cloud toggles, and the sandbox opens.
2. **0:27–1:17 — Contract and index.** The `pois.json` schema, the pipeline
   gate, the 1 m bucket grid, the inverted token index, and the typo fallback
   (`tunel` → Tunnel Walkway) in the live search box.
3. **1:17–1:47 — Search and selection.** `/` → `town`, ranked results, the
   category/description card, live distance, selection without a camera jump,
   then explicit **Jump here**.
4. **1:47–2:31 — Navigation.** Search `exit`, **Navigate**, walk the route,
   banner instruction/distance, 3D ribbon + minimap, then the failsafe card
   (1.2 m reroute, 0.7 m stop, 10 cm clearance) and the after-splat overlay.
5. **2:31–2:59 — Obstacles.** The two-barrier `?props=` capture: 31.66 m /
   2 waypoints → 31.86 m / 3 waypoints; clear the sandbox and the route returns.
6. **2:59–3:24 — Authoring.** `E`, click the floor, name/category/description,
   save, then **Export pois.json** with the local tag visible in the list.
7. **3:24–3:55 — Verification.** 50 web tests, 21 pipeline tests, strict
   typecheck, production build, 76 Playwright checks, 27 live Pages checks.
8. **3:55–4:11 — Close.** Live link, source branch, evidence pack, and the R3
   QR-fiducial AR roadmap.

Recorded on the hosted Pages build in a hardware-accelerated browser
(ANGLE/D3D11). The raw captures are 1600×900 VP8; the final cut is 1080p30.

## Limitations (honest)

- **Metro only for navigation claims.** The Studio Room twin has a synthetic
  all-free costmap; it is a visual benchmark, not a pathfinding demo.
- **Splat floor rays near the spawn are noisy.** Live sandbox placement in the
  narrow spawn corridor can report `aim at the floor` or `blocked by the map`
  because the splat BVH bounding spheres occlude the floor ray. Startup
  `?props=` links place reliably and are the evidence path; wall-mounted
  placement and surface-normal snapping are not implemented.
- **POIs are authored, not auto-detected.** There is no CLIP/vision tagger in
  R2. The editor + validated JSON contract is deliberate: every label is
  human-checked and every route target is on known floor.
- **Single floor.** The costmap is 2.5D; multi-storey routing is out of scope.
- **Dynamic obstacles are local/link-shared.** No multi-user sync or backend.
- **`.splat` is DC-only.** Reflective surfaces remain softer than the floor.
- **The tunnel end is under-reconstructed.** The Emergency Exit sequence stops
  before the auto-turn reaches the worst wall; the demo still shows a dark
  tunnel end, which is capture data, not a missing texture.
