/**
 * Costmap access + A* pathfinding on the nav grid.
 * World is the pipeline's metric frame: x/y horizontal, z up (meters).
 */

import { FREE, type NavData, OBSTACLE } from './artifacts';

export class Costmap {
  readonly w: number;
  readonly h: number;
  readonly cell: number;
  readonly origin: [number, number];
  readonly data: Uint8Array;

  constructor(nav: NavData, grid: { w: number; h: number; data: Uint8Array }) {
    this.w = grid.w;
    this.h = grid.h;
    this.cell = nav.cell_m;
    this.origin = nav.origin;
    this.data = grid.data;
  }

  valueAtWorld(x: number, y: number): number {
    const cx = Math.floor((x - this.origin[0]) / this.cell);
    const cy = Math.floor((y - this.origin[1]) / this.cell);
    if (cx < 0 || cy < 0 || cx >= this.w || cy >= this.h) return OBSTACLE; // outside = blocked
    return this.data[cy * this.w + cx];
  }

  isBlocked(x: number, y: number): boolean {
    return this.valueAtWorld(x, y) === OBSTACLE;
  }

  /** blocked test with a small radius (4 samples around the point) */
  isBlockedRadius(x: number, y: number, r = 0.18): boolean {
    if (this.isBlocked(x, y)) return true;
    return (
      this.isBlocked(x + r, y) || this.isBlocked(x - r, y) ||
      this.isBlocked(x, y + r) || this.isBlocked(x, y - r)
    );
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
  findPath(from: [number, number], to: [number, number]): [number, number][] | null {
    const [sx, sy] = this.toCell(...from);
    let [tx, ty] = this.toCell(...to);
    if (!this.inBounds(sx, sy) || !this.inBounds(tx, ty)) return null;
    if (this.blocked(tx, ty)) [tx, ty] = this.nearestFree(tx, ty);
    if (this.blocked(sx, sy)) {
      const [nx, ny] = this.nearestFree(sx, sy);
      return this.findPath(this.toWorld(nx, ny), to);
    }

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

    while (heap.size) {
      const cur = heap.pop();
      if (cur === goal) return this.reconstruct(came, cur);
      if (closed[cur]) continue;
      closed[cur] = 1;
      const cx = cur % this.w, cy = (cur / this.w) | 0;

      for (const [dx, dy, cost] of DIRS) {
        const nx = cx + dx, ny = cy + dy;
        if (!this.inBounds(nx, ny) || this.blocked(nx, ny)) continue;
        // no diagonal corner cutting
        if (dx !== 0 && dy !== 0 && (this.blocked(cx + dx, cy) || this.blocked(cx, cy + dy))) continue;
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
    return this.data[y * this.w + x] === OBSTACLE;
  }

  private nearestFree(cx: number, cy: number): [number, number] {
    for (let r = 1; r < 40; r++) {
      for (let dy = -r; dy <= r; dy++) {
        for (let dx = -r; dx <= r; dx++) {
          if (Math.abs(dx) !== r && Math.abs(dy) !== r) continue;
          const nx = cx + dx, ny = cy + dy;
          if (this.inBounds(nx, ny) && this.data[ny * this.w + nx] === FREE) return [nx, ny];
        }
      }
    }
    return [cx, cy];
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
