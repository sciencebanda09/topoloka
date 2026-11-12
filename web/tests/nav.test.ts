import { describe, expect, it } from 'vitest';
import type { NavData } from '../src/artifacts';
import { Costmap } from '../src/nav';

/** 40 x 40 grid of 10 cm cells: 4 m square, world origin at (0, 0). */
function makeGrid(
  w: number,
  h: number,
  blocked: (x: number, y: number) => boolean = () => false,
  value = 0,
): { w: number; h: number; data: Uint8Array } {
  const data = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) data[y * w + x] = blocked(x, y) ? 1 : value;
  }
  return { w, h, data };
}

function makeNav(trajectory: [number, number, number][] = []): NavData {
  return {
    version: 1,
    units: 'm',
    cell_m: 0.1,
    origin: [0, 0],
    grid: { w: 40, h: 40, encoding: 'png', legend: {}, data_b64: '' },
    outline: [[0, 0], [4, 0], [4, 4], [0, 4]],
    trajectory,
  } as unknown as NavData;
}

function pathStaysClear(costmap: Costmap, path: [number, number][]): boolean {
  for (let i = 1; i < path.length; i++) {
    const [ax, ay] = path[i - 1];
    const [bx, by] = path[i];
    const steps = Math.ceil(Math.hypot(bx - ax, by - ay) / (costmap.cell * 0.5));
    for (let s = 0; s <= steps; s++) {
      const t = steps ? s / steps : 0;
      if (costmap.isBlocked(ax + (bx - ax) * t, ay + (by - ay) * t)) return false;
    }
  }
  return true;
}

describe('Costmap basics', () => {
  it('maps world coordinates to cells and back', () => {
    const costmap = new Costmap(makeNav(), makeGrid(40, 40));
    expect(costmap.toCell(0.05, 0.05)).toEqual([0, 0]);
    expect(costmap.toCell(1.25, 2.35)).toEqual([12, 23]);
    expect(costmap.toWorld(12, 23)).toEqual([1.25, 2.35]);
  });

  it('treats out-of-bounds and unknown space as blocked', () => {
    const grid = makeGrid(40, 40, () => false, 2);
    const costmap = new Costmap(makeNav(), grid);
    expect(costmap.valueAtWorld(-1, 0)).toBe(1);
    expect(costmap.isBlocked(-1, 0)).toBe(true);
    expect(costmap.isBlocked(1, 1)).toBe(true);
  });

  it('blocks a footprint radius', () => {
    const grid = makeGrid(40, 40, (x) => x === 20);
    const costmap = new Costmap(makeNav(), grid);
    expect(costmap.isBlocked(1.95, 1)).toBe(false);
    expect(costmap.isBlockedRadius(1.95, 1, 0.12)).toBe(true);
    expect(costmap.isStandable(1.95, 1)).toBe(false);
  });

  it('carves unknown floor and stale obstacle cells along the walked route', () => {
    const grid = makeGrid(40, 40, () => false, 2);
    // Mark one obstacle cell at the trajectory midpoint.
    grid.data[20 * 40 + 20] = 1;
    const nav = makeNav([[1.95, 2.05, 1.5], [2.05, 2.05, 1.5]]);
    const costmap = new Costmap(nav, grid);
    expect(costmap.isBlocked(2.05, 2.05)).toBe(false);
    // Unknown floor 0.85 m away is carved; 1.2 m away stays unknown.
    expect(costmap.isBlocked(2.05, 2.85)).toBe(false);
    expect(costmap.isBlocked(2.05, 3.3)).toBe(true);
  });

  it('does not carve mapped walls outside the 0.4 m walk corridor', () => {
    const grid = makeGrid(40, 40, (x) => x === 26);
    const nav = makeNav([[1.95, 2.05, 1.5], [2.05, 2.05, 1.5]]);
    const costmap = new Costmap(nav, grid);
    // 0.6 m to the right of the trajectory: outside the stale-obstacle carve.
    expect(costmap.isBlocked(2.65, 2.05)).toBe(true);
  });
});

describe('Costmap nearest standable', () => {
  it('returns the same point when already free', () => {
    const costmap = new Costmap(makeNav(), makeGrid(40, 40));
    expect(costmap.nearestStandable(1, 1)).toEqual([1, 1]);
  });

  it('finds a bounded nearby free cell and gives up beyond its cap', () => {
    const grid = makeGrid(40, 40, (x, y) => Math.max(Math.abs(x - 20), Math.abs(y - 20)) <= 5);
    const costmap = new Costmap(makeNav(), grid);
    const snap = costmap.nearestStandable(2.05, 2.05, 1.5);
    expect(snap).not.toBeNull();
    expect(costmap.isStandable(snap![0], snap![1])).toBe(true);
    expect(costmap.nearestStandable(2.05, 2.05, 0.2)).toBeNull();
  });
});

describe('Costmap pathfinding', () => {
  it('walks straight across open floor', () => {
    const costmap = new Costmap(makeNav(), makeGrid(40, 40));
    const path = costmap.findPath([0.3, 0.3], [3.6, 3.6]);
    expect(path).not.toBeNull();
    expect(path!.length).toBeGreaterThanOrEqual(2);
    expect(Costmap.pathLength(path!)).toBeCloseTo(Math.hypot(3.3, 3.3), 1);
    expect(pathStaysClear(costmap, path!)).toBe(true);
  });

  it('routes around a wall instead of through it', () => {
    // Vertical wall at x = 2 m for y < 3.2 m; walk around the bottom.
    const grid = makeGrid(40, 40, (x, y) => x === 20 && y < 32);
    const costmap = new Costmap(makeNav(), grid);
    const path = costmap.findPath([0.5, 0.5], [3.5, 0.5]);
    expect(path).not.toBeNull();
    expect(pathStaysClear(costmap, path!)).toBe(true);
    const passesBelow = path!.some(([, y]) => y > 3.2);
    expect(passesBelow).toBe(true);
    expect(Costmap.pathLength(path!)).toBeGreaterThan(3);
  });

  it('returns null between disconnected free regions', () => {
    const grid = makeGrid(40, 40, (x) => x === 20);
    const costmap = new Costmap(makeNav(), grid);
    expect(costmap.findPath([0.5, 0.5], [3.5, 3.5])).toBeNull();
  });

  it('snaps a blocked start and goal onto nearby floor', () => {
    const grid = makeGrid(40, 40, (x, y) => (x === 5 && y === 5) || (x === 34 && y === 34));
    const costmap = new Costmap(makeNav(), grid);
    const path = costmap.findPath([0.55, 0.55], [3.45, 3.45]);
    expect(path).not.toBeNull();
    expect(pathStaysClear(costmap, path!)).toBe(true);
  });

  it('keeps the exact requested endpoints when they are standable', () => {
    const costmap = new Costmap(makeNav(), makeGrid(40, 40));
    const from: [number, number] = [0.63, 0.47];
    const to: [number, number] = [3.37, 3.52];
    const path = costmap.findPath(from, to, { smooth: false });
    expect(path![0]).toEqual(from);
    expect(path![path!.length - 1]).toEqual(to);
  });

  it('smooths a jagged grid path without crossing walls', () => {
    const grid = makeGrid(40, 40, (x, y) => (x === 20 && y < 30) || (x === 10 && y > 12));
    const costmap = new Costmap(makeNav(), grid);
    const raw = costmap.findPath([0.5, 0.5], [3.5, 3.5], { smooth: false });
    const smooth = costmap.findPath([0.5, 0.5], [3.5, 3.5]);
    expect(raw).not.toBeNull();
    expect(smooth).not.toBeNull();
    expect(smooth!.length).toBeLessThan(raw!.length);
    expect(pathStaysClear(costmap, smooth!)).toBe(true);
  });

  it('replans when a dynamic sandbox obstacle blocks the direct route', () => {
    const costmap = new Costmap(makeNav(), makeGrid(40, 40));
    const direct = costmap.findPath([0.5, 2], [3.5, 2])!;
    costmap.setDynamicObstacles([{ x: 2, y: 2, hw: 0.06, hh: 1.2, rot: 0 }]);
    const detour = costmap.findPath([0.5, 2], [3.5, 2]);
    expect(direct).not.toBeNull();
    expect(detour).not.toBeNull();
    expect(pathStaysClear(costmap, detour!)).toBe(true);
    expect(Costmap.pathLength(detour!)).toBeGreaterThan(Costmap.pathLength(direct));

    costmap.setDynamicObstacles([]);
    expect(Costmap.pathLength(costmap.findPath([0.5, 2], [3.5, 2])!))
      .toBeCloseTo(Costmap.pathLength(direct), 1);
  });

  it('supports rotated dynamic footprints', () => {
    const costmap = new Costmap(makeNav(), makeGrid(40, 40));
    costmap.setDynamicObstacles([{ x: 2, y: 2, hw: 1.2, hh: 0.06, rot: Math.PI / 2 }]);
    expect(costmap.isBlocked(2, 3.1)).toBe(true);
    expect(costmap.isBlocked(3.1, 2)).toBe(false);
  });

  it('measures polyline length', () => {
    expect(Costmap.pathLength([[0, 0], [3, 4], [3, 5]])).toBeCloseTo(6);
    expect(Costmap.pathLength([])).toBe(0);
    expect(Costmap.pathLength([[1, 1]])).toBe(0);
  });
});
