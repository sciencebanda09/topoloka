/**
 * Costmap access + A* pathfinding on the nav grid.
 * World is the pipeline's metric frame: x/y horizontal, z up (meters).
 *
 * Robustness notes
 * ----------------
 * - The recorded walk is physically traversable, so cells along it are cleared
 *   of unknown space (0.85 m) and of stale geometry false-positives (0.4 m).
 *   The wider unknown-only carve lets a visitor sidestep around props without
 *   opening walls: obstacle cells farther than 0.4 m stay blocked.
 * - Pathfinding uses a small inflated copy of the costmap, so paths keep a
 *   pedestrian clearance instead of grazing a wall cell.
 * - Start/goal snapping is a bounded search, never recursive. If nothing is
 *   reachable within the snap radius we return null and the UI says so.
 * - Raw grid paths are string-pulled with a clearance-checked line of sight;
 *   the rendered route is a polyline, so it cannot bow through a wall.
 */

import { FREE, type NavData, OBSTACLE, UNKNOWN } from './artifacts';

/** Clear stale obstacle cells within this radius of the walked route. */
const WALKED_PATH_CLEAR_RADIUS_M = 0.4;
/** Open unknown floor a little wider so viewers can sidestep. */
const WALKED_PATH_UNKNOWN_RADIUS_M = 0.85;
/** Pedestrian clearance used by A* and smoothing. */
const PATH_CLEARANCE_M = 0.10;
/** Bound for snapping a blocked start/goal back onto navigable floor. */
const MAX_SNAP_M = 2.5;
/** Node budget: a pathological query returns null instead of freezing a tab. */
const MAX_EXPANSIONS = 900_000;

/** Oriented footprint in the nav frame (x/y horizontal, radians). */
export interface Footprint {
  x: number;
  y: number;
  hw: number;
  hh: number;
  rot: number;
}

export interface FindPathOptions {
  /** Disable string-pulling for tests that want the raw grid path. */
  smooth?: boolean;
  /** Ignore the pedestrian clearance layer (used as a last-resort fallback). */
  tight?: boolean;
}

export class Costmap {
  readonly w: number;
  readonly h: number;
  readonly cell: number;
  readonly origin: [number, number];
  readonly data: Uint8Array;
  /** Sandbox props: editable obstacles layered over the measured grid. */
  private dynamic: Uint8Array;
  /** data + dynamic, dilated by PATH_CLEARANCE_M for route planning. */
  private inflated: Uint8Array;
  /** Offsets (in cells) inside the clearance radius. */
  private readonly clearanceOffsets: [number, number][];
  private readonly clearanceCells: number;

  constructor(nav: NavData, grid: { w: number; h: number; data: Uint8Array }) {
    this.w = grid.w;
    this.h = grid.h;
    this.cell = nav.cell_m;
    this.origin = nav.origin;
    this.data = new Uint8Array(grid.data);
    this.dynamic = new Uint8Array(this.w * this.h);
    this.clearanceCells = Math.max(1, Math.ceil(PATH_CLEARANCE_M / this.cell));
    const offsets: [number, number][] = [];
    for (let dy = -this.clearanceCells; dy <= this.clearanceCells; dy++) {
      for (let dx = -this.clearanceCells; dx <= this.clearanceCells; dx++) {
        if (dx * dx + dy * dy <= this.clearanceCells * this.clearanceCells) offsets.push([dx, dy]);
      }
    }
    this.clearanceOffsets = offsets;
    this.inflated = new Uint8Array(this.w * this.h);
    this.carveWalkedPath(nav.trajectory);
    this.rebuildInflation();
  }

  /**
   * Replace the sandbox obstacle layer. Rasterizes oriented rectangles at the
   * 5 cm grid, slightly inflated so A* does not thread a corner through a foot.
   */
  setDynamicObstacles(obstacles: Footprint[]): void {
    this.dynamic.fill(0);
    for (const f of obstacles) {
      const hw = f.hw + 0.04;
      const hh = f.hh + 0.04;
      const ext = Math.hypot(hw, hh);
      const minX = Math.max(0, Math.floor((f.x - ext - this.origin[0]) / this.cell));
      const maxX = Math.min(this.w - 1, Math.ceil((f.x + ext - this.origin[0]) / this.cell));
      const minY = Math.max(0, Math.floor((f.y - ext - this.origin[1]) / this.cell));
      const maxY = Math.min(this.h - 1, Math.ceil((f.y + ext - this.origin[1]) / this.cell));
      const c = Math.cos(f.rot), s = Math.sin(f.rot);
      for (let cy = minY; cy <= maxY; cy++) {
        const wy = this.origin[1] + (cy + 0.5) * this.cell;
        for (let cx = minX; cx <= maxX; cx++) {
          const wx = this.origin[0] + (cx + 0.5) * this.cell;
          const dx = wx - f.x, dy = wy - f.y;
          const lx = dx * c + dy * s;
          const ly = -dx * s + dy * c;
          if (Math.abs(lx) <= hw && Math.abs(ly) <= hh) this.dynamic[cy * this.w + cx] = 1;
        }
      }
    }
    this.rebuildInflation();
  }

  /**
   * Clear the walked route: unknown space 0.85 m, stale measured obstacles
   * 0.4 m. The route is where a human actually walked, so both are safe to
   * open; mapped walls further away are never touched.
   */
  private carveWalkedPath(trajectory: [number, number, number][]): void {
    const clearSpan = Math.ceil(WALKED_PATH_CLEAR_RADIUS_M / this.cell);
    const unknownSpan = Math.ceil(WALKED_PATH_UNKNOWN_RADIUS_M / this.cell);
    for (let pass = 0; pass < 2; pass++) {
      const span = pass === 0 ? clearSpan : unknownSpan;
      const allowed = pass === 0 ? null : UNKNOWN;
      for (const [x, y] of trajectory) {
        const [cx, cy] = this.toCell(x, y);
        for (let dy = -span; dy <= span; dy++) {
          for (let dx = -span; dx <= span; dx++) {
            if (dx * dx + dy * dy > span * span) continue;
            const nx = cx + dx, ny = cy + dy;
            if (!this.inBounds(nx, ny)) continue;
            const i = ny * this.w + nx;
            if (this.data[i] === FREE) continue;
            if (allowed !== null && this.data[i] !== allowed) continue;
            this.data[i] = FREE;
          }
        }
      }
    }
  }

  private rebuildInflation(): void {
    const n = this.w * this.h;
    if (this.inflated.length !== n) this.inflated = new Uint8Array(n);
    this.inflated.fill(0);
    for (let y = 0; y < this.h; y++) {
      for (let x = 0; x < this.w; x++) {
        const i = y * this.w + x;
        if (this.data[i] === FREE && this.dynamic[i] !== 1) continue;
        for (const [dx, dy] of this.clearanceOffsets) {
          const nx = x + dx, ny = y + dy;
          if (nx >= 0 && ny >= 0 && nx < this.w && ny < this.h) this.inflated[ny * this.w + nx] = 1;
        }
      }
    }
  }

  valueAtWorld(x: number, y: number): number {
    const cx = Math.floor((x - this.origin[0]) / this.cell);
    const cy = Math.floor((y - this.origin[1]) / this.cell);
    if (cx < 0 || cy < 0 || cx >= this.w || cy >= this.h) return OBSTACLE; // outside = blocked
    return this.data[cy * this.w + cx];
  }

  /** Unknown space is not walkable: no collision against a void. */
  isBlocked(x: number, y: number): boolean {
    if (this.valueAtWorld(x, y) !== FREE) return true;
    const cx = Math.floor((x - this.origin[0]) / this.cell);
    const cy = Math.floor((y - this.origin[1]) / this.cell);
    return this.dynamic[cy * this.w + cx] === 1;
  }

  /** Small avatar clearance so narrow gaps between nearby objects stay usable. */
  isBlockedRadius(x: number, y: number, r = 0.12): boolean {
    if (this.isBlocked(x, y)) return true;
    return (
      this.isBlocked(x + r, y) || this.isBlocked(x - r, y) ||
      this.isBlocked(x, y + r) || this.isBlocked(x, y - r)
    );
  }

  /** True when the walker can stand here (raw grid + avatar radius). */
  isStandable(x: number, y: number, r = 0.12): boolean {
    return !this.isBlockedRadius(x, y, r);
  }

  /** Bounded search for a standable world point (meters). */
  nearestStandable(x: number, y: number, maxM = MAX_SNAP_M): [number, number] | null {
    if (this.isStandable(x, y)) return [x, y];
    const maxCell = Math.min(140, Math.ceil(maxM / this.cell));
    const [cx, cy] = this.toCell(x, y);
    for (let r = 1; r <= maxCell; r++) {
      for (let dy = -r; dy <= r; dy++) {
        for (let dx = -r; dx <= r; dx++) {
          if (Math.abs(dx) !== r && Math.abs(dy) !== r) continue;
          const nx = cx + dx, ny = cy + dy;
          if (!this.inBounds(nx, ny)) continue;
          if (this.inflated[ny * this.w + nx] === 1) continue;
          return this.toWorld(nx, ny);
        }
      }
    }
    return null;
  }

  toCell(x: number, y: number): [number, number] {
    return [Math.floor((x - this.origin[0]) / this.cell), Math.floor((y - this.origin[1]) / this.cell)];
  }

  toWorld(cx: number, cy: number): [number, number] {
    return [this.origin[0] + (cx + 0.5) * this.cell, this.origin[1] + (cy + 0.5) * this.cell];
  }

  /**
   * A* on free cells (8-connected, no corner cutting, tiny turn penalty).
   * Returns world-space [x, y] waypoints, or null if unreachable.
   */
  findPath(from: [number, number], to: [number, number], opts: FindPathOptions = {}): [number, number][] | null {
    const tight = opts.tight === true;
    let startWorld = this.nearestStandable(from[0], from[1]);
    let goalWorld = this.nearestStandable(to[0], to[1]);
    if (!startWorld || !goalWorld) return null;

    let raw = this.astar(startWorld, goalWorld, tight);
    // A POI authored a centimetre inside a mapped object can be unreachable
    // with clearance but reachable tight; try once rather than fail the demo.
    if (!raw && !tight) {
      raw = this.astar(startWorld, goalWorld, true);
      if (raw) {
        const s = this.nearestStandable(from[0], from[1]);
        if (s) startWorld = s;
      }
    }
    if (!raw || raw.length === 0) return null;

    // Keep the caller's exact start when it is on navigable floor, and the
    // exact goal when it is standable; this makes arrival checks predictable.
    if (this.isStandable(from[0], from[1])) raw[0] = [from[0], from[1]];
    if (this.isStandable(to[0], to[1])) raw[raw.length - 1] = [to[0], to[1]];
    return opts.smooth === false ? raw : this.smooth(raw, tight);
  }

  private astar(from: [number, number], to: [number, number], tight: boolean): [number, number][] | null {
    const [sx, sy] = this.toCell(from[0], from[1]);
    const [tx, ty] = this.toCell(to[0], to[1]);
    if (!this.inBounds(sx, sy) || !this.inBounds(tx, ty)) return null;
    if (this.blockedForPath(sx, sy, tight) || this.blockedForPath(tx, ty, tight)) return null;

    const n = this.w * this.h;
    const idx = (x: number, y: number) => y * this.w + x;
    const gScore = new Float32Array(n).fill(Infinity);
    const fScore = new Float32Array(n).fill(Infinity);
    const came = new Int32Array(n).fill(-1);
    const closed = new Uint8Array(n);
    const start = idx(sx, sy), goal = idx(tx, ty);
    const heap = new MinHeap();
    gScore[start] = 0;
    fScore[start] = this.hCost(sx, sy, tx, ty);
    heap.push(start, fScore[start]);

    const DIRS = [
      [1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1],
      [1, 1, Math.SQRT2], [1, -1, Math.SQRT2], [-1, 1, Math.SQRT2], [-1, -1, Math.SQRT2],
    ];

    let expansions = 0;
    while (heap.size) {
      const cur = heap.pop();
      if (cur === goal) return this.reconstruct(came, cur);
      if (closed[cur]) continue;
      closed[cur] = 1;
      if (++expansions > MAX_EXPANSIONS) return null;
      const cx = cur % this.w, cy = (cur / this.w) | 0;

      for (const [dx, dy, cost] of DIRS) {
        const nx = cx + dx, ny = cy + dy;
        if (!this.inBounds(nx, ny) || this.blockedForPath(nx, ny, tight)) continue;
        // no diagonal corner cutting
        if (dx !== 0 && dy !== 0
          && (this.blockedForPath(cx + dx, cy, tight) || this.blockedForPath(cx, cy + dy, tight))) continue;
        const ni = idx(nx, ny);
        if (closed[ni]) continue;
        const tentative = gScore[cur] + cost;
        if (tentative < gScore[ni]) {
          came[ni] = cur;
          gScore[ni] = tentative;
          fScore[ni] = tentative + this.hCost(nx, ny, tx, ty);
          heap.push(ni, fScore[ni]);
        }
      }
    }
    return null;
  }

  /** String-pull the grid path: greedy farthest visible waypoint. */
  private smooth(path: [number, number][], tight: boolean): [number, number][] {
    if (path.length <= 2) return path;
    // The raw path has every cell; a visibility test over 1.4 M cells would be
    // needlessly slow. Thin it first, then pull the remaining corners.
    const thin: [number, number][] = [path[0]];
    for (let i = 1; i < path.length - 1; i++) {
      const prev = thin[thin.length - 1];
      const next = path[i + 1];
      const d = Math.hypot(next[0] - prev[0], next[1] - prev[1]);
      if (d >= 0.28) thin.push(path[i]);
    }
    thin.push(path[path.length - 1]);

    const out: [number, number][] = [thin[0]];
    let i = 0;
    while (i < thin.length - 1) {
      let j = thin.length - 1;
      while (j > i + 1 && !this.lineClear(thin[i], thin[j], tight)) j--;
      out.push(thin[j]);
      i = j;
    }
    return out;
  }

  /** Sample a segment at half-cell steps against the planning layer. */
  private lineClear(a: [number, number], b: [number, number], tight: boolean): boolean {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const steps = Math.max(1, Math.ceil(Math.hypot(dx, dy) / (this.cell * 0.5)));
    for (let s = 1; s < steps; s++) {
      const t = s / steps;
      const cx = Math.floor((a[0] + dx * t - this.origin[0]) / this.cell);
      const cy = Math.floor((a[1] + dy * t - this.origin[1]) / this.cell);
      if (!this.inBounds(cx, cy) || this.blockedForPath(cx, cy, tight)) return false;
    }
    return true;
  }

  /** Euclidean length of a world-space route. */
  static pathLength(path: [number, number][]): number {
    let total = 0;
    for (let i = 1; i < path.length; i++) {
      total += Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]);
    }
    return total;
  }

  private hCost(x: number, y: number, tx: number, ty: number): number {
    const dx = Math.abs(x - tx), dy = Math.abs(y - ty);
    return Math.max(dx, dy) + (Math.SQRT2 - 1) * Math.min(dx, dy);
  }

  private reconstruct(came: Int32Array, cur: number): [number, number][] {
    const out: [number, number][] = [];
    let node = cur;
    while (node >= 0) {
      out.push(this.toWorld(node % this.w, (node / this.w) | 0));
      node = came[node];
    }
    return out.reverse();
  }

  private inBounds(x: number, y: number): boolean {
    return x >= 0 && y >= 0 && x < this.w && y < this.h;
  }

  private blocked(x: number, y: number): boolean {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return true;
    return this.data[y * this.w + x] !== FREE || this.dynamic[y * this.w + x] === 1;
  }

  private blockedForPath(x: number, y: number, tight: boolean): boolean {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return true;
    if (this.blocked(x, y)) return true;
    return !tight && this.inflated[y * this.w + x] === 1;
  }
}

/** Binary min-heap over flat cell indices. */
class MinHeap {
  private items: number[] = [];
  private keys: number[] = [];
  get size(): number { return this.items.length; }

  push(item: number, key: number): void {
    this.items.push(item);
    this.keys.push(key);
    let i = this.items.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.keys[p] <= this.keys[i]) break;
      this.swap(i, p);
      i = p;
    }
  }

  pop(): number {
    const top = this.items[0];
    const last = this.items.pop()!;
    const lastKey = this.keys.pop()!;
    if (this.items.length) {
      this.items[0] = last;
      this.keys[0] = lastKey;
      let i = 0;
      for (;;) {
        const l = i * 2 + 1, r = l + 1;
        let m = i;
        if (l < this.items.length && this.keys[l] < this.keys[m]) m = l;
        if (r < this.items.length && this.keys[r] < this.keys[m]) m = r;
        if (m === i) break;
        this.swap(i, m);
        i = m;
      }
    }
    return top;
  }

  private swap(a: number, b: number): void {
    [this.items[a], this.items[b]] = [this.items[b], this.items[a]];
    [this.keys[a], this.keys[b]] = [this.keys[b], this.keys[a]];
  }
}
