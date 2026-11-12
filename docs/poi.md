# Points of interest: contract, index, search and routes

R2 turns the twin from a free-roam visualisation into a queryable map. A POI
is a named place on the metric floor with an optional camera pose. The browser
loads the authored set, builds a spatial + lexical index in memory, and uses the
same 5 cm costmap as collision for turn-by-turn routing.

- Authoring contract: `<capture>/nav/pois.json`
- Staged web bundle: `<capture>/web/pois.json` (beside `nav.json`)
- Runtime types and index: `web/src/pois.ts`
- Validation / packaging: `pipeline/namma/pois.py`
- UI wiring: `web/src/ui.ts`, `web/src/main.ts`

The sample dataset is `test/metro_v1/nav/pois.json`: **7 POIs across 5
categories** (`area` 2, `landmark` 2, `facility` 1, `exit` 1, `platform` 1),
all on known free floor, all with a camera view.

## 1. Schema (`version: 1`)

```json
{
  "version": 1,
  "capture": "metro_v1",
  "pois": [
    {
      "id": "tunnel-walkway",
      "name": "Tunnel Walkway",
      "category": "area",
      "aliases": ["tunnel", "walkway", "corridor", "passage"],
      "description": "Long, level tiled walkway under the curved ceiling, with tactile paving at the edges.",
      "x": 1.422,
      "y": -11.216,
      "z": 0.0,
      "radius_m": 1.6,
      "view": {
        "x": 2.393,
        "y": -11.573,
        "z": 1.754,
        "yaw": 0.4418,
        "pitch": 0.0
      }
    }
  ]
}
```

| Field | Required | Rules |
|---|---|---|
| `version` | yes | must be `1` |
| `capture` | no | if present, must match the folder/capture name |
| `pois[].id` | yes | `[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}`, unique in the file |
| `pois[].name` | yes | non-empty, collapsed whitespace, at most 80 chars |
| `pois[].category` | no | non-empty string, lowercased; defaults to `place` |
| `pois[].aliases` | no | up to 20 non-empty strings, deduplicated |
| `pois[].description` | no | string, truncated to 240 chars |
| `pois[].x`, `.y` | yes | finite metres in the nav frame; must lie inside the nav grid |
| `pois[].z` | no | finite metres, defaults to `0` (floor) |
| `pois[].radius_m` | no | `0.1`–`20`, defaults to `1.0`; marker/selection radius |
| `pois[].view` | no | `{x, y, z, yaw, pitch}`; camera pose for **Jump here** and deep links |
| `pois[].zone` | no | polygon in nav metres; reserved for room/zone labels |

Coordinates use the same frame as `nav.json`: **x/y horizontal, z up, metres**.
`yaw` is the viewer camera yaw (camera forward = nav `(-sin yaw, cos yaw)`), so
a view authored from the live editor reproduces the same look direction.

Runtime adds `source: "authored" | "local"`; it is not written to the file.

## 2. Validation: hard errors vs warnings

`python -m namma.cli pois <capture>` (and `package`, which calls the same
validator) refuses to ship an ambiguous index:

| Severity | Conditions |
|---|---|
| **hard error** | wrong version; missing `pois` array; more than 10,000 POIs; malformed/duplicate id; empty name; non-finite or out-of-grid x/y; non-finite z; `radius_m` outside 0.1–20; non-string alias/description |
| **warning** | duplicate display names; POI on a blocked/unknown cell (route snaps to nearby floor); missing `view` (jump uses the POI position) |

Warnings are written to `nav/poi_report.json` and printed. The Metro dataset
has **0 warnings**.

## 3. Authoring from the viewer

1. Open the viewer and press **E** (or use the **+ Tag** button). The editor
   drawer opens; sandbox mode must be off.
2. Click the floor to place the POI. Coordinates and floor height fill in.
3. Enter a name, category, aliases/description as needed.
4. **Save POI** stores it in this browser's `localStorage` for the capture and
   adds it to the live index immediately. It is marked `local`.
5. **Export pois.json** downloads `{capture}-pois.json` with the same schema.
6. Copy that file to `<capture>/nav/pois.json` and run:

   ```powershell
   cd pipeline
   python -m namma.cli pois ..\test\metro_v1 --source ..\test\metro_v1\nav\pois.json
   python -m namma.cli package ..\test\metro_v1
   ```

`pois` normalises the document and writes `nav/poi_report.json`; `package`
validates again and stages `web/pois.json`. The QA stage adds a
`poi_dataset` check with the count and category histogram. Local tags never
mutate the hosted bundle; they are a browser convenience until exported and
committed.

## 4. In-browser spatial and lexical index

The browser does not filter an array per keystroke. `PoiIndex` builds:

- **Position index:** uniform grid of **1 m buckets** keyed `"bx,by"`.
  `within(x, y, r)` visits only overlapping buckets; `nearest()` expands rings
  and stops when the next ring cannot beat the best distance. Category filters
  run inside the same search (e.g. nearest exit).
- **Text index:** an inverted index from normalised tokens (name, category,
  aliases) to POI ids, plus the token vocabulary. Prefix and substring queries
  expand through the vocabulary, which is much smaller than a full scan.
- **Fuzzy matching:** Levenshtein distance with an early cutoff, `<= 2`, also
  over vocabulary tokens (so a typo does not need to match a full name).

`normalizeText()` lowercases, strips diacritics and punctuation, and collapses
whitespace, so `"Town-Hall"` and `"town hall"` normalise identically.

### Ranking

Best match wins, with a bounded proximity boost when a player origin exists:

| Match | Base score |
|---|---|
| exact name | 1000 |
| name prefix | 840 |
| word prefix in name | 760 |
| name substring | 640 |
| alias exact / prefix / word / substring | 600 / 520 / 470 / 420 |
| category exact / prefix | 400 / 330 |
| fuzzy token (`d <= 2`) | 250 − 55·d |

A proximity term adds up to **+34** at 0 m, decaying linearly to 0 at 80 m.
It is a tie-breaker, never a way to hide an exact textual match. Multi-word
queries require every word to match some token. `nearest …`, `closest …`, and
`near me …` re-sort results by distance.

## 5. Search and navigation UX

| Action | Result |
|---|---|
| `/` or `Ctrl/Cmd+K` | focus search; typing never moves the player |
| type a name, alias, category, or typo | ranked results with category, distance and matched field |
| click a result / POI marker / minimap dot | select and highlight only; camera stays put |
| **Jump here** | fly the walker to the POI's `view` pose (or its position) |
| **Navigate** | plan an A* route from the current position to the POI |
| **✕** in the nav banner | stop navigation |
| `?q=<query>` | open the viewer with search populated |
| `?poi=<id>` | select the POI and jump to its view (explicit deep link) |

Search deliberately separates **selection** from **camera motion**: typing or
clicking a result highlights the POI, draws its minimap label, and shows the
card, but does not teleport the visitor. Only **Jump here** or `?poi=` moves the
camera.

## 6. Routing on the costmap

`Costmap.plan()` in `web/src/nav.ts` runs A* on the 5 cm grid:

1. **Blocked cells:** out-of-bounds, obstacle and unknown cells are not
   walkable. The walked trajectory is carved free (0.4 m of stale obstacle
   cells, 0.85 m of unknown cells) because the camera proved it traversable.
2. **Clearance:** the planning copy is dilated by **0.10 m**, so a route keeps
   pedestrian clearance instead of grazing a wall cell.
3. **Snapping:** start and goal snap to the nearest standable cell within
   **2.5 m**; if either cannot be reached the planner returns `null` and the UI
   says `No walkable route to <name>`.
4. **Smoothing:** raw grid paths are string-pulled with a clearance-checked
   line of sight, so the drawn polyline cannot bow through a wall.
5. **Tracker:** `RouteTracker` projects the player onto the route, reports
   remaining distance/ETA, emits turn instructions, and triggers reroute after
   **1.2 m** off-route for a sustained period.
6. **Arrival:** within **0.7 m** of the goal (or the last 0.4 m with a wider
   radius), navigation stops and the toast says `Arrived at <name>`.

The planner also accepts a dynamic obstacle layer (`setDynamicObstacles`) used
by the sandbox, so placing a barrier can change the route without touching the
scanned costmap.

## 7. Evidence

- `cd web && npm test` — 50 Vitest tests across `pois`, `nav`, `navigation`,
  including bucket/ring queries, fuzzy ranking, carving, dynamic footprints,
  route smoothing, reroute and arrival.
- `python -m pytest -s pipeline/tests` — 21 tests, including `test_pois.py`
  hard-error/warning cases and packaging.
- Runtime smoke test: search `curved` → **Curved Passage** at 1.7 m; walking
  forward fires `Arrived at Curved Passage`; `?poi=town-hall-sign` selects and
  jumps; minimap dot click selects; editor save/export round-trips.
- Obstacle evidence: two barriers across the Metro corridor change the
  Tunnel Walkway route from **31.66 m** to **31.86 m** (see
  [`r2_evidence.md`](r2_evidence.md)).
