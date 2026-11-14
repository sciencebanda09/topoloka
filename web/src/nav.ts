/**
 * Costmap access + Clearance-Potential A* pathfinding on the nav grid.
 * World is the pipeline's metric frame: x/y horizontal, z up (meters).
 *
 * Robustness & Performance Upgrades
 * ---------------------------------
 * - Linear-time exact L2 Euclidean Distance Transform (Felzenszwalb-Huttenlocher)
 *   computes metric wall clearance at every cell in O(W*H).
 * - Static distance field is cached once; dynamic sandbox props update only a
 *   bounded dirty patch around old+new footprints in sub-millisecond time.
 * - Clearance-potential A* with generation-stamped typed buffers avoids O(W*H)
 *   clears per query and naturally centers routes away from walls while still
 *   threading tight doorways when needed.
 * - Margin-preserving string-pulling keeps shortcuts clear of wall corners.
 */

import { FREE, type NavData, OBSTACLE, UNKNOWN } from './artifacts';

/** Clear stale obstacle cells within this radius of the walked route. */
const WALKED_PATH_CLEAR_RADIUS_M = 0.4;
/** Open unknown floor a little wider so viewers can sidestep. */
const WALKED_PATH_UNKNOWN_RADIUS_M = 0.85;
/** Hard minimum pedestrian clearance from walls during normal routing. */
const PATH_CLEARANCE_M = 0.10;
/** Comfortable corridor clearance target for potential-field centering. */
const COMFORT_CLEARANCE_M = 0.50;
/** Quadratic potential weight when clearance < COMFORT_CLEARANCE_M. */
const CLEARANCE_WEIGHT = 1.8;
/** Minimum clearance preserved by string-pull shortcuts in open corridors. */
const SMOOTH_MIN_CLEARANCE_M = 0.28;
/** Bound for snapping a blocked start/goal back onto navigable floor. */
const MAX_SNAP_M = 2.5;
/** Node budget: a pathological query returns null instead of freezing a tab. */
const MAX_EXPANSIONS = 900_000;

/** 4x coarse-grid downsampling shift + corridor tube half-width in macro cells (+/-12 fine cells). */
const MACRO_SHIFT = 2;
const MACRO_SIZE = 1 << MACRO_SHIFT;
const MACRO_TUBE_RADIUS = 3;

const DX = new Int8Array([1, -1, 0, 0, 1, 1, -1, -1]);
const DY = new Int8Array([0, 0, 1, -1, 1, -1, 1, -1]);
const D_BASE = new Float32Array([1, 1, 1, 1, Math.SQRT2, Math.SQRT2, Math.SQRT2, Math.SQRT2]);
const OCTILE_K = Math.SQRT2 - 1;

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

interface DirtyBox {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

export class Costmap {
  readonly w: number;
  readonly h: number;
  readonly cell: number;
  readonly origin: [number, number];
  readonly data: Uint8Array;

  /** Sandbox props: editable obstacles layered over the measured grid. */
  private dynamic: Uint8Array;
  /** Exact static L2 clearance (meters) from static blocked cells. */
  private staticDistM: Float32Array;
  /** Exact L2 clearance (meters) from static + dynamic blocked cells. */
  private distM: Float32Array;
  private lastDynBox: DirtyBox | null = null;
  private hasDynamic = false;

  /** Reusable A* typed scratch buffers + generation stamp to avoid per-query GC/fills. */
  private seenGen: Uint32Array;
  private gScore: Float32Array;
  private came: Int32Array;
  private closedGen: Uint32Array;
  private heapPos: Int32Array;
  private gen = 0;
  private readonly heap: TypedMinHeap;

  /** Reusable 1D/2D EDT scratch arrays (avoids allocations during dynamic updates). */
  private readonly edtF: Float32Array;
  private readonly edtV: Int32Array;
  private readonly edtZ: Float32Array;
  private readonly edtTemp: Float32Array;
  private readonly edtRowFree: Uint8Array;

  /** Hierarchical 4x macro pyramid for fast long-range corridor funneling. */
  private readonly mw: number;
  private readonly mh: number;
  private readonly macroClear: Float32Array;
  private readonly macroSeenGen: Uint32Array;
  private readonly macroClosedGen: Uint32Array;
  private readonly macroG: Float32Array;
  private readonly macroCame: Int32Array;
  private readonly macroTubeStamp: Uint32Array;
  private readonly macroHeap: TypedMinHeap;
  private macroGen = 0;
  private tubeGen = 0;

  constructor(nav: NavData, grid: { w: number; h: number; data: Uint8Array }) {
    this.w = grid.w;
    this.h = grid.h;
    this.cell = nav.cell_m;
    this.origin = nav.origin;
    this.data = new Uint8Array(grid.data);
    const n = this.w * this.h;
    this.dynamic = new Uint8Array(n);
    this.staticDistM = new Float32Array(n);
    this.distM = new Float32Array(n);

    this.seenGen = new Uint32Array(n);
    this.gScore = new Float32Array(n);
    this.came = new Int32Array(n);
    this.closedGen = new Uint32Array(n);
    this.heapPos = new Int32Array(n);
    this.heap = new TypedMinHeap(Math.min(65536, Math.max(1024, n >> 3)));

    const maxDim = Math.max(this.w, this.h);
    this.edtF = new Float32Array(maxDim);
    this.edtV = new Int32Array(maxDim);
    this.edtZ = new Float32Array(maxDim + 1);
    this.edtTemp = new Float32Array(n);
    this.edtRowFree = new Uint8Array(this.h);

    this.mw = (this.w + MACRO_SIZE - 1) >> MACRO_SHIFT;
    this.mh = (this.h + MACRO_SIZE - 1) >> MACRO_SHIFT;
    const mn = this.mw * this.mh;
    this.macroClear = new Float32Array(mn);
    this.macroSeenGen = new Uint32Array(mn);
    this.macroClosedGen = new Uint32Array(mn);
    this.macroG = new Float32Array(mn);
    this.macroCame = new Int32Array(mn);
    this.macroTubeStamp = new Uint32Array(mn);
    this.macroHeap = new TypedMinHeap(Math.min(16384, Math.max(256, mn >> 2)));

    this.carveWalkedPath(nav.trajectory);
    this.computeStaticDistanceField();
    this.distM.set(this.staticDistM);
    this.rebuildMacroBox(0, 0, this.w - 1, this.h - 1);
  }

  /**
   * Exact linear-time 2D Euclidean Distance Transform (Felzenszwalb & Huttenlocher)
   * over a grid window [x0..x1, y0..y1] without closure-call overhead.
   */
  private computeBoxEDT(
    x0: number,
    y0: number,
    x1: number,
    y1: number,
    out: Float32Array,
    useDynamicLayer: boolean,
    mode: 'set' | 'min',
  ): void {
    const bw = x1 - x0 + 1;
    const bh = y1 - y0 + 1;
    const INF = 1e9;
    const temp = this.edtTemp;
    const src = useDynamicLayer ? this.dynamic : this.data;
    const targetVal = useDynamicLayer ? 1 : FREE;
    const w = this.w;
    const rowFree = this.edtRowFree;
    rowFree.fill(0, 0, bh);

    // 1D vertical binary sweep per column -> squared vertical distances
    for (let x = 0; x < bw; x++) {
      const gx = x0 + x;
      let d = INF;
      for (let y = 0; y < bh; y++) {
        const v = src[(y0 + y) * w + gx];
        const blk = useDynamicLayer ? v === targetVal : v !== targetVal;
        if (blk) {
          d = 0;
          temp[y * bw + x] = 0;
        } else {
          rowFree[y] = 1;
          d = d < INF ? d + 1 : INF;
          temp[y * bw + x] = d * d;
        }
      }
      d = INF;
      for (let y = bh - 1; y >= 0; y--) {
        const v = src[(y0 + y) * w + gx];
        const blk = useDynamicLayer ? v === targetVal : v !== targetVal;
        if (blk) {
          d = 0;
          temp[y * bw + x] = 0;
        } else {
          d = d < INF ? d + 1 : INF;
          const d2 = d * d;
          if (d2 < temp[y * bw + x]) temp[y * bw + x] = d2;
        }
      }
    }

    // 1D horizontal parabolic lower-envelope EDT per row (skip all-blocked rows in O(1))
    const f = this.edtF;
    const v = this.edtV;
    const z = this.edtZ;
    const cellM = this.cell;
    const setMode = mode === 'set';
    for (let y = 0; y < bh; y++) {
      const gyOff = (y0 + y) * w + x0;
      if (rowFree[y] === 0) {
        out.fill(0, gyOff, gyOff + bw);
        continue;
      }
      const rowOff = y * bw;
      for (let q = 0; q < bw; q++) f[q] = temp[rowOff + q];

      let k = 0;
      v[0] = 0;
      z[0] = -INF;
      z[1] = INF;
      for (let q = 1; q < bw; q++) {
        const fq = f[q] + q * q;
        let s = 0;
        for (;;) {
          const r = v[k];
          s = (fq - (f[r] + r * r)) / (2 * q - 2 * r);
          if (s <= z[k]) k--;
          else break;
        }
        k++;
        v[k] = q;
        z[k] = s;
        z[k + 1] = INF;
      }

      k = 0;
      for (let q = 0; q < bw; q++) {
        while (z[k + 1] < q) k++;
        const dx = q - v[k];
        const sq = dx * dx + f[v[k]];
        const distMeters = sq === 0 ? 0 : (sq >= INF ? 100.0 : Math.sqrt(sq) * cellM);
        const gi = gyOff + q;
        if (setMode) out[gi] = distMeters;
        else if (distMeters < out[gi]) out[gi] = distMeters;
      }
    }
  }

  private computeStaticDistanceField(): void {
    this.computeBoxEDT(0, 0, this.w - 1, this.h - 1, this.staticDistM, false, 'set');
  }

  /** Recompute 4x coarsened max-clearance summary inside a fine cell box. */
  private rebuildMacroBox(x0: number, y0: number, x1: number, y1: number): void {
    const mx0 = x0 >> MACRO_SHIFT;
    const my0 = y0 >> MACRO_SHIFT;
    const mx1 = Math.min(this.mw - 1, x1 >> MACRO_SHIFT);
    const my1 = Math.min(this.mh - 1, y1 >> MACRO_SHIFT);
    const distM = this.distM;
    const macro = this.macroClear;
    const w = this.w;
    const h = this.h;
    const mw = this.mw;

    for (let my = my0; my <= my1; my++) {
      const fy0 = my << MACRO_SHIFT;
      const fy1 = Math.min(h, fy0 + MACRO_SIZE);
      for (let mx = mx0; mx <= mx1; mx++) {
        const fx0 = mx << MACRO_SHIFT;
        const fx1 = Math.min(w, fx0 + MACRO_SIZE);
        let maxC = 0;
        for (let fy = fy0; fy < fy1; fy++) {
          const row = fy * w;
          for (let fx = fx0; fx < fx1; fx++) {
            const c = distM[row + fx];
            if (c > maxC) maxC = c;
          }
        }
        macro[my * mw + mx] = maxC;
      }
    }
  }

  /**
   * Replace the sandbox obstacle layer. Rasterizes oriented rectangles at the
   * 5 cm grid, updating ONLY the local dirty bounding box in the distance field
   * for sub-millisecond interactive prop drags on million-cell maps.
   */
  setDynamicObstacles(obstacles: Footprint[]): void {
    if (obstacles.length === 0 && !this.hasDynamic) return;

    // Restore previously dirtied region first
    if (this.lastDynBox) {
      const { minX, maxX, minY, maxY } = this.lastDynBox;
      for (let cy = minY; cy <= maxY; cy++) {
        const row = cy * this.w;
        for (let cx = minX; cx <= maxX; cx++) {
          const idx = row + cx;
          this.dynamic[idx] = 0;
          this.distM[idx] = this.staticDistM[idx];
        }
      }
      this.rebuildMacroBox(minX, minY, maxX, maxY);
      this.lastDynBox = null;
    }

    if (obstacles.length === 0) {
      this.hasDynamic = false;
      return;
    }

    this.hasDynamic = true;
    const padCells = Math.ceil(1.2 / this.cell);
    let bMinX = this.w - 1;
    let bMaxX = 0;
    let bMinY = this.h - 1;
    let bMaxY = 0;

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
        const row = cy * this.w;
        for (let cx = minX; cx <= maxX; cx++) {
          const wx = this.origin[0] + (cx + 0.5) * this.cell;
          const dx = wx - f.x, dy = wy - f.y;
          const lx = dx * c + dy * s;
          const ly = -dx * s + dy * c;
          if (Math.abs(lx) <= hw && Math.abs(ly) <= hh) this.dynamic[row + cx] = 1;
        }
      }
      bMinX = Math.min(bMinX, Math.max(0, minX - padCells));
      bMaxX = Math.max(bMaxX, Math.min(this.w - 1, maxX + padCells));
      bMinY = Math.min(bMinY, Math.max(0, minY - padCells));
      bMaxY = Math.max(bMaxY, Math.min(this.h - 1, maxY + padCells));
    }

    if (bMinX <= bMaxX && bMinY <= bMaxY) {
      this.lastDynBox = { minX: bMinX, maxX: bMaxX, minY: bMinY, maxY: bMaxY };
      this.computeBoxEDT(bMinX, bMinY, bMaxX, bMaxY, this.distM, true, 'min');
      this.rebuildMacroBox(bMinX, bMinY, bMaxX, bMaxY);
    }
  }

  /**
   * Clear the walked route: unknown space 0.85 m, stale measured obstacles
   * 0.4 m, interpolating short gaps between consecutive trajectory poses so
   * corridors stay connected even on strided keyframes.
   */
  private carveWalkedPath(trajectory: [number, number, number][]): void {
    if (!trajectory.length) return;
    const samples: [number, number][] = [[trajectory[0][0], trajectory[0][1]]];
    for (let i = 1; i < trajectory.length; i++) {
      const [ax, ay] = trajectory[i - 1];
      const [bx, by] = trajectory[i];
      const dist = Math.hypot(bx - ax, by - ay);
      if (dist > 0.22 && dist <= 3.0) {
        const steps = Math.ceil(dist / 0.2);
        for (let s = 1; s < steps; s++) {
          const t = s / steps;
          samples.push([ax + (bx - ax) * t, ay + (by - ay) * t]);
        }
      }
      samples.push([bx, by]);
    }

    const clearSpan = Math.ceil(WALKED_PATH_CLEAR_RADIUS_M / this.cell);
    const unknownSpan = Math.ceil(WALKED_PATH_UNKNOWN_RADIUS_M / this.cell);
    for (let pass = 0; pass < 2; pass++) {
      const span = pass === 0 ? clearSpan : unknownSpan;
      const allowed = pass === 0 ? null : UNKNOWN;
      for (const [x, y] of samples) {
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

  /** Euclidean clearance (meters) from nearest blocked cell at world (x, y). */
  clearanceAtWorld(x: number, y: number): number {
    const cx = Math.floor((x - this.origin[0]) / this.cell);
    const cy = Math.floor((y - this.origin[1]) / this.cell);
    if (cx < 0 || cy < 0 || cx >= this.w || cy >= this.h) return 0;
    return this.distM[cy * this.w + cx];
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
      let best: [number, number] | null = null;
      let bestClearance = -1;
      for (let dy = -r; dy <= r; dy++) {
        for (let dx = -r; dx <= r; dx++) {
          if (Math.abs(dx) !== r && Math.abs(dy) !== r) continue;
          const nx = cx + dx, ny = cy + dy;
          if (!this.inBounds(nx, ny)) continue;
          const clr = this.distM[ny * this.w + nx];
          if (clr < PATH_CLEARANCE_M - 1e-4) continue;
          if (clr > bestClearance) {
            bestClearance = clr;
            best = this.toWorld(nx, ny);
          }
        }
      }
      if (best) return best;
    }
    return null;
  }

  /**
   * Clearance-potential A* on free cells (8-connected, no corner cutting).
   * Returns world-space [x, y] waypoints, or null if unreachable.
   */
  findPath(from: [number, number], to: [number, number], opts: FindPathOptions = {}): [number, number][] | null {
    const tight = opts.tight === true;
    let startWorld = this.nearestStandable(from[0], from[1]);
    let goalWorld = this.nearestStandable(to[0], to[1]);
    if (!startWorld || !goalWorld) return null;

    // Hierarchical 4x macro-corridor funneling for medium/long paths, with exact full-grid fallback
    let raw = this.astar(startWorld, goalWorld, tight, true);
    if (!raw) raw = this.astar(startWorld, goalWorld, tight, false);
    if (!raw && !tight) {
      raw = this.astar(startWorld, goalWorld, true, true) ?? this.astar(startWorld, goalWorld, true, false);
      if (raw) {
        const s = this.nearestStandable(from[0], from[1]);
        if (s) startWorld = s;
      }
    }
    if (!raw || raw.length === 0) return null;

    if (this.isStandable(from[0], from[1])) raw[0] = [from[0], from[1]];
    if (this.isStandable(to[0], to[1])) raw[raw.length - 1] = [to[0], to[1]];
    return opts.smooth === false ? raw : this.smooth(raw, tight);
  }

  /**
   * Solve a 4x coarse corridor path and stamp a +/-12-cell band into `macroTubeStamp`.
   * Returns active stamp generation, or 0 for short/unusable routes.
   */
  private buildMacroTube(sx: number, sy: number, tx: number, ty: number, tight: boolean): number {
    if (Math.abs(tx - sx) + Math.abs(ty - sy) < 70 || this.mw < 8 || this.mh < 8) return 0;
    const msx = sx >> MACRO_SHIFT;
    const msy = sy >> MACRO_SHIFT;
    const mtx = tx >> MACRO_SHIFT;
    const mty = ty >> MACRO_SHIFT;
    const mw = this.mw;
    const mh = this.mh;
    const mStart = msy * mw + msx;
    const mGoal = mty * mw + mtx;

    const macro = this.macroClear;
    const minClr = tight ? 1e-4 : PATH_CLEARANCE_M - 1e-4;
    if (macro[mStart] < minClr || macro[mGoal] < minClr) return 0;

    this.macroGen = (this.macroGen + 1) >>> 0;
    if (this.macroGen === 0) {
      this.macroSeenGen.fill(0);
      this.macroClosedGen.fill(0);
      this.macroGen = 1;
    }
    const mg = this.macroGen;
    const mSeen = this.macroSeenGen;
    const mClosed = this.macroClosedGen;
    const mG = this.macroG;
    const mCame = this.macroCame;
    const heap = this.macroHeap;
    heap.clear();
    mSeen[mStart] = mg;
    mG[mStart] = 0;
    mCame[mStart] = -1;
    const h0x = Math.abs(msx - mtx), h0y = Math.abs(msy - mty);
    heap.push(mStart, (h0x > h0y ? h0x + OCTILE_K * h0y : h0y + OCTILE_K * h0x) * 1.1);

    let found = -1;
    while (heap.size) {
      const cur = heap.pop();
      if (cur === mGoal) {
        found = cur;
        break;
      }
      if (mClosed[cur] === mg) continue;
      mClosed[cur] = mg;
      const my = (cur / mw) | 0;
      const mx = cur - my * mw;
      const curG = mG[cur];

      for (let d = 0; d < 8; d++) {
        const dx = DX[d], dy = DY[d];
        const nx = mx + dx, ny = my + dy;
        if (nx < 0 || ny < 0 || nx >= mw || ny >= mh) continue;
        const ni = ny * mw + nx;
        if (mClosed[ni] === mg) continue;
        const clr = macro[ni];
        if (clr < minClr) continue;
        const deficit = clr < COMFORT_CLEARANCE_M ? (COMFORT_CLEARANCE_M - clr) / COMFORT_CLEARANCE_M : 0;
        const ng = curG + D_BASE[d] * (1 + CLEARANCE_WEIGHT * deficit * deficit);
        if (mSeen[ni] !== mg || ng < mG[ni]) {
          mSeen[ni] = mg;
          mG[ni] = ng;
          mCame[ni] = cur;
          const adx = Math.abs(nx - mtx), ady = Math.abs(ny - mty);
          heap.push(ni, ng + 1.15 * (adx > ady ? adx + OCTILE_K * ady : ady + OCTILE_K * adx));
        }
      }
    }
    if (found < 0) return 0;

    this.tubeGen = (this.tubeGen + 1) >>> 0;
    if (this.tubeGen === 0) {
      this.macroTubeStamp.fill(0);
      this.tubeGen = 1;
    }
    const tg = this.tubeGen;
    const stamp = this.macroTubeStamp;
    let node = found;
    while (node >= 0) {
      const ny = (node / mw) | 0;
      const nx = node - ny * mw;
      const y0 = Math.max(0, ny - MACRO_TUBE_RADIUS);
      const y1 = Math.min(mh - 1, ny + MACRO_TUBE_RADIUS);
      const x0 = Math.max(0, nx - MACRO_TUBE_RADIUS);
      const x1 = Math.min(mw - 1, nx + MACRO_TUBE_RADIUS);
      for (let y = y0; y <= y1; y++) {
        const row = y * mw;
        for (let x = x0; x <= x1; x++) stamp[row + x] = tg;
      }
      node = mCame[node];
    }
    return tg;
  }

  private astar(
    from: [number, number],
    to: [number, number],
    tight: boolean,
    useMacroTube: boolean,
  ): [number, number][] | null {
    const [sx, sy] = this.toCell(from[0], from[1]);
    const [tx, ty] = this.toCell(to[0], to[1]);
    if (!this.inBounds(sx, sy) || !this.inBounds(tx, ty)) return null;
    if (this.blockedForPath(sx, sy, tight) || this.blockedForPath(tx, ty, tight)) return null;

    const tg = useMacroTube ? this.buildMacroTube(sx, sy, tx, ty, tight) : 0;
    if (useMacroTube && tg === 0) return null;

    // Roll generation counter (rare wraparound resets arrays safely)
    this.gen = (this.gen + 1) >>> 0;
    if (this.gen === 0) {
      this.seenGen.fill(0);
      this.closedGen.fill(0);
      this.gen = 1;
    }
    const gen = this.gen;
    const w = this.w;
    const h = this.h;
    const mw = this.mw;
    const start = sy * w + sx;
    const goal = ty * w + tx;

    const heap = this.heap;
    const heapPos = this.heapPos;
    heap.clear();
    this.seenGen[start] = gen;
    this.gScore[start] = 0;
    this.came[start] = -1;
    const sdx = Math.abs(sx - tx), sdy = Math.abs(sy - ty);
    heap.pushIndexed(start, sdx > sdy ? sdx + OCTILE_K * sdy : sdy + OCTILE_K * sdx, heapPos);

    const distM = this.distM;
    const seenGen = this.seenGen;
    const closedGen = this.closedGen;
    const gScore = this.gScore;
    const came = this.came;
    const tube = tg !== 0 ? this.macroTubeStamp : null;
    const minClr = PATH_CLEARANCE_M - 1e-4;

    let expansions = 0;
    while (heap.size) {
      const cur = heap.popIndexed(heapPos);
      if (cur === goal) return this.reconstruct(came, cur);
      closedGen[cur] = gen;
      if (++expansions > MAX_EXPANSIONS) return null;
      const cy = (cur / w) | 0;
      const cx = cur - cy * w;
      const curG = gScore[cur];

      for (let d = 0; d < 8; d++) {
        const dx = DX[d], dy = DY[d];
        const nx = cx + dx, ny = cy + dy;
        if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
        if (tube !== null && tube[(ny >> MACRO_SHIFT) * mw + (nx >> MACRO_SHIFT)] !== tg) continue;
        const ni = ny * w + nx;
        if (closedGen[ni] === gen) continue;

        const clr = distM[ni];
        if (clr <= 0 || (!tight && clr < minClr)) continue;
        if (dx !== 0 && dy !== 0) {
          const adj1 = distM[cy * w + (cx + dx)];
          const adj2 = distM[(cy + dy) * w + cx];
          if (adj1 <= 0 || adj2 <= 0) continue;
          if (!tight && (adj1 < minClr || adj2 < minClr)) continue;
        }

        const deficit = clr < COMFORT_CLEARANCE_M ? (COMFORT_CLEARANCE_M - clr) * (1 / COMFORT_CLEARANCE_M) : 0;
        const stepCost = D_BASE[d] * (1 + CLEARANCE_WEIGHT * deficit * deficit);
        const tentative = curG + stepCost;
        const seen = seenGen[ni] === gen;
        if (!seen || tentative < gScore[ni]) {
          came[ni] = cur;
          gScore[ni] = tentative;
          const adx = Math.abs(nx - tx), ady = Math.abs(ny - ty);
          const fCost = tentative + 1.15 * (adx > ady ? adx + OCTILE_K * ady : ady + OCTILE_K * adx);
          if (!seen) {
            seenGen[ni] = gen;
            heap.pushIndexed(ni, fCost, heapPos);
          } else {
            const hp = heapPos[ni];
            if (hp >= 0) heap.decreaseKeyAt(hp, fCost, heapPos);
            else heap.pushIndexed(ni, fCost, heapPos);
          }
        }
      }
    }
    return null;
  }

  /**
   * Margin-preserving string-pull: removes redundant grid zig-zags while
   * refusing shortcuts that pull the route tighter to walls than a safe corridor buffer.
   */
  private smooth(path: [number, number][], tight: boolean): [number, number][] {
    if (path.length <= 2) return path;
    const thin: [number, number][] = [path[0]];
    for (let i = 1; i < path.length - 1; i++) {
      const prev = thin[thin.length - 1];
      const next = path[i + 1];
      if (Math.hypot(next[0] - prev[0], next[1] - prev[1]) >= 0.28) thin.push(path[i]);
    }
    thin.push(path[path.length - 1]);

    const out: [number, number][] = [thin[0]];
    let i = 0;
    while (i < thin.length - 1) {
      let j = thin.length - 1;
      const startClr = this.clearanceAtWorld(thin[i][0], thin[i][1]);
      while (j > i + 1) {
        const endClr = this.clearanceAtWorld(thin[j][0], thin[j][1]);
        const safeFloor = tight
          ? this.cell * 0.5
          : Math.max(
              PATH_CLEARANCE_M - 1e-4,
              Math.min(SMOOTH_MIN_CLEARANCE_M, startClr - 0.04, endClr - 0.04),
            );
        if (this.lineClear(thin[i], thin[j], tight, safeFloor)) break;
        j--;
      }
      out.push(thin[j]);
      i = j;
    }
    return out;
  }

  /** True if the straight segment between `a` and `b` is unobstructed on the nav grid. */
  hasLineOfSight(a: [number, number], b: [number, number]): boolean {
    return this.lineClear(a, b, true, 0);
  }

  /** Sample a segment at half-cell steps against the continuous clearance field. */
  private lineClear(a: [number, number], b: [number, number], tight: boolean, minClearanceM: number): boolean {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const steps = Math.max(1, Math.ceil(Math.hypot(dx, dy) / (this.cell * 0.5)));
    for (let s = 1; s < steps; s++) {
      const t = s / steps;
      const cx = Math.floor((a[0] + dx * t - this.origin[0]) / this.cell);
      const cy = Math.floor((a[1] + dy * t - this.origin[1]) / this.cell);
      if (cx < 0 || cy < 0 || cx >= this.w || cy >= this.h) return false;
      const clr = this.distM[cy * this.w + cx];
      if (clr <= 0) return false;
      if (!tight && clr < minClearanceM) return false;
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

  private reconstruct(came: Int32Array, cur: number): [number, number][] {
    const out: [number, number][] = [];
    let node = cur;
    while (node >= 0) {
      out.push(this.toWorld(node % this.w, (node / this.w) | 0));
      node = came[node];
    }
    return out.reverse();
  }

  toCell(x: number, y: number): [number, number] {
    return [Math.floor((x - this.origin[0]) / this.cell), Math.floor((y - this.origin[1]) / this.cell)];
  }

  toWorld(cx: number, cy: number): [number, number] {
    return [this.origin[0] + (cx + 0.5) * this.cell, this.origin[1] + (cy + 0.5) * this.cell];
  }

  private inBounds(x: number, y: number): boolean {
    return x >= 0 && y >= 0 && x < this.w && y < this.h;
  }

  private blockedForPath(x: number, y: number, tight: boolean): boolean {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return true;
    const clr = this.distM[y * this.w + x];
    if (clr <= 0) return true;
    return !tight && clr < PATH_CLEARANCE_M - 1e-4;
  }
}

/** Zero-GC typed binary min-heap over flat cell indices. */
class TypedMinHeap {
  private items: Int32Array;
  private keys: Float32Array;
  private n = 0;

  constructor(initialCap = 4096) {
    this.items = new Int32Array(initialCap);
    this.keys = new Float32Array(initialCap);
  }

  get size(): number { return this.n; }

  clear(): void { this.n = 0; }

  push(item: number, key: number): void {
    if (this.n === this.items.length) {
      const nextItems = new Int32Array(this.items.length * 2);
      const nextKeys = new Float32Array(this.keys.length * 2);
      nextItems.set(this.items);
      nextKeys.set(this.keys);
      this.items = nextItems;
      this.keys = nextKeys;
    }
    let i = this.n++;
    this.items[i] = item;
    this.keys[i] = key;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.keys[p] <= this.keys[i]) break;
      this.swap(i, p);
      i = p;
    }
  }

  pop(): number {
    const top = this.items[0];
    const lastIdx = --this.n;
    if (lastIdx > 0) {
      this.items[0] = this.items[lastIdx];
      this.keys[0] = this.keys[lastIdx];
      let i = 0;
      for (;;) {
        const l = i * 2 + 1, r = l + 1;
        let m = i;
        if (l < this.n && this.keys[l] < this.keys[m]) m = l;
        if (r < this.n && this.keys[r] < this.keys[m]) m = r;
        if (m === i) break;
        this.swap(i, m);
        i = m;
      }
    }
    return top;
  }

  pushIndexed(item: number, key: number, posMap: Int32Array): void {
    if (this.n === this.items.length) {
      const nextItems = new Int32Array(this.items.length * 2);
      const nextKeys = new Float32Array(this.keys.length * 2);
      nextItems.set(this.items);
      nextKeys.set(this.keys);
      this.items = nextItems;
      this.keys = nextKeys;
    }
    let i = this.n++;
    this.items[i] = item;
    this.keys[i] = key;
    posMap[item] = i;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.keys[p] <= this.keys[i]) break;
      this.swapIndexed(i, p, posMap);
      i = p;
    }
  }

  decreaseKeyAt(idx: number, key: number, posMap: Int32Array): void {
    if (key >= this.keys[idx]) return;
    this.keys[idx] = key;
    let i = idx;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.keys[p] <= this.keys[i]) break;
      this.swapIndexed(i, p, posMap);
      i = p;
    }
  }

  popIndexed(posMap: Int32Array): number {
    const top = this.items[0];
    posMap[top] = -1;
    const lastIdx = --this.n;
    if (lastIdx > 0) {
      const moved = this.items[lastIdx];
      this.items[0] = moved;
      this.keys[0] = this.keys[lastIdx];
      posMap[moved] = 0;
      let i = 0;
      for (;;) {
        const l = i * 2 + 1, r = l + 1;
        let m = i;
        if (l < this.n && this.keys[l] < this.keys[m]) m = l;
        if (r < this.n && this.keys[r] < this.keys[m]) m = r;
        if (m === i) break;
        this.swapIndexed(i, m, posMap);
        i = m;
      }
    }
    return top;
  }

  private swap(a: number, b: number): void {
    const ti = this.items[a];
    this.items[a] = this.items[b];
    this.items[b] = ti;
    const tk = this.keys[a];
    this.keys[a] = this.keys[b];
    this.keys[b] = tk;
  }

  private swapIndexed(a: number, b: number, posMap: Int32Array): void {
    const ia = this.items[a];
    const ib = this.items[b];
    this.items[a] = ib;
    this.items[b] = ia;
    posMap[ia] = b;
    posMap[ib] = a;
    const tk = this.keys[a];
    this.keys[a] = this.keys[b];
    this.keys[b] = tk;
  }
}
