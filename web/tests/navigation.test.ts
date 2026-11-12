import { describe, expect, it } from 'vitest';
import type { NavData } from '../src/artifacts';
import { Costmap } from '../src/nav';
import {
  ARRIVAL_RADIUS_M,
  buildInstructions,
  formatDistance,
  formatEta,
  instructionText,
  planRoute,
  RouteTracker,
  WALK_SPEED_MPS,
  type RoutePlan,
} from '../src/navigation';
import type { Poi } from '../src/pois';

function makeGrid(w: number, h: number, blocked: (x: number, y: number) => boolean = () => false) {
  const data = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) data[y * w + x] = blocked(x, y) ? 1 : 0;
  }
  return { w, h, data };
}

function makeCostmap(blocked?: (x: number, y: number) => boolean): Costmap {
  const nav = {
    version: 1,
    units: 'm',
    cell_m: 0.1,
    origin: [0, 0],
    grid: { w: 80, h: 80, encoding: 'png', legend: {}, data_b64: '' },
    outline: [],
    trajectory: [],
  } as unknown as NavData;
  return new Costmap(nav, makeGrid(80, 80, blocked));
}

const target: Poi = {
  id: 'target',
  name: 'Lift Lobby',
  category: 'facility',
  x: 7,
  y: 0.5,
  z: 0,
};

describe('route planning', () => {
  it('plans a walkable route to a POI and computes distance and ETA', () => {
    const costmap = makeCostmap();
    const plan = planRoute(costmap, [0.5, 0.5], target);
    expect(plan).not.toBeNull();
    expect(plan!.targetId).toBe('target');
    expect(plan!.targetName).toBe('Lift Lobby');
    expect(plan!.distanceM).toBeGreaterThan(6);
    expect(plan!.distanceM).toBeLessThan(8);
    expect(plan!.etaSeconds).toBeCloseTo(plan!.distanceM / WALK_SPEED_MPS);
    expect(plan!.instructions[0].kind).toBe('start');
    expect(plan!.instructions.at(-1)?.kind).toBe('arrive');
  });

  it('honours a custom walking speed', () => {
    const plan = planRoute(makeCostmap(), [0.5, 0.5], target, { speed: 2 });
    expect(plan!.etaSeconds).toBeCloseTo(plan!.distanceM / 2);
  });

  it('returns null when the target is unreachable', () => {
    const costmap = makeCostmap((x) => x === 40);
    expect(planRoute(costmap, [0.5, 0.5], { ...target, x: 7, y: 7 })).toBeNull();
  });

  it('returns null for a target effectively underfoot', () => {
    const plan = planRoute(makeCostmap(), [0.5, 0.5], { ...target, x: 0.53, y: 0.5 });
    expect(plan).toBeNull();
  });
});

describe('turn instructions', () => {
  it('adds start, meaningful turns and arrival', () => {
    const path: [number, number][] = [[0, 0], [0, 2], [2, 2], [2, 4]];
    const instructions = buildInstructions(path, 'Platform');
    expect(instructions.map((instruction) => instruction.kind)).toEqual([
      'start', 'right', 'left', 'arrive',
    ]);
    expect(instructions[0]).toMatchObject({ atMeters: 0, text: 'Head toward Platform' });
    expect(instructions.at(-1)).toMatchObject({ atMeters: 6, text: 'Arrive at Platform' });
  });

  it('ignores tiny bearing changes from grid stair-steps', () => {
    const path: [number, number][] = [[0, 0], [1, 0.02], [2, 0], [3, 0.02]];
    expect(buildInstructions(path, 'X').map((instruction) => instruction.kind))
      .toEqual(['start', 'arrive']);
  });

  it('formats banner text', () => {
    const plan: RoutePlan = {
      targetId: 'x',
      targetName: 'Lift Lobby',
      waypoints: [[0, 0], [5, 0]],
      distanceM: 5,
      etaSeconds: 4,
      instructions: [
        { kind: 'start', atMeters: 0, text: 'Head toward Lift Lobby' },
        { kind: 'left', atMeters: 3, text: 'Turn left' },
        { kind: 'arrive', atMeters: 5, text: 'Arrive at Lift Lobby' },
      ],
    };
    expect(instructionText(plan, {
      instruction: plan.instructions[0],
      distanceToInstructionM: 0,
    })).toBe('Head toward Lift Lobby');
    expect(instructionText(plan, {
      instruction: plan.instructions[1],
      distanceToInstructionM: 4,
    })).toBe('In 4.0 m, turn left');
    expect(instructionText(plan, {
      instruction: plan.instructions[1],
      distanceToInstructionM: 1,
    })).toBe('Turn left now');
    expect(instructionText(plan, {
      instruction: plan.instructions[2],
      distanceToInstructionM: 0,
    })).toBe('Arrive at Lift Lobby');
  });

  it('formats metric distances and ETAs', () => {
    expect(formatDistance(0.004)).toBe('1 cm');
    expect(formatDistance(0.45)).toBe('45 cm');
    expect(formatDistance(4.25)).toBe('4.3 m');
    expect(formatDistance(42.6)).toBe('43 m');
    expect(formatEta(9)).toBe('9s');
    expect(formatEta(65)).toBe('1m 5s');
    expect(formatEta(120)).toBe('2m');
  });
});

describe('RouteTracker', () => {
  const plan = (): RoutePlan => ({
    targetId: 'lift',
    targetName: 'Lift Lobby',
    waypoints: [[0, 0], [10, 0]],
    distanceM: 10,
    etaSeconds: 10 / WALK_SPEED_MPS,
    instructions: buildInstructions([[0, 0], [10, 0]], 'Lift Lobby'),
  });

  it('reports progress, remaining distance and ETA', () => {
    const tracker = new RouteTracker(plan());
    const state = tracker.update([5, 0], 0, 0.016);
    expect(state.progress).toBeCloseTo(0.5);
    expect(state.remainingM).toBeCloseTo(5);
    expect(state.etaSeconds).toBeCloseTo(5 / WALK_SPEED_MPS);
    expect(state.arrived).toBe(false);
    expect(state.needsReroute).toBe(false);
  });

  it('never moves progress backwards when stepping back', () => {
    const tracker = new RouteTracker(plan());
    tracker.update([6, 0], 0, 0.016);
    const state = tracker.update([4, 0], 0, 0.016);
    expect(state.progress).toBeGreaterThanOrEqual(0.6);
  });

  it('arrives within the arrival radius and latches', () => {
    const tracker = new RouteTracker(plan());
    const state = tracker.update([10 - ARRIVAL_RADIUS_M / 2, 0], 0, 0.016);
    expect(state.arrived).toBe(true);
    expect(tracker.finished).toBe(true);
    expect(state.progress).toBeGreaterThan(0.9);
    expect(state.needsReroute).toBe(false);
  });

  it('does not arrive while merely near the line but far from the goal', () => {
    const tracker = new RouteTracker(plan());
    const state = tracker.update([15, 5], 0, 0.016);
    expect(state.arrived).toBe(false);
    expect(state.progress).toBe(0);
  });

  it('flags a sustained deviation as a reroute request', () => {
    const tracker = new RouteTracker(plan());
    expect(tracker.update([5, 3], 0, 0.5).needsReroute).toBe(false);
    expect(tracker.update([5, 3], 0, 0.5).needsReroute).toBe(true);
    expect(tracker.update([5, 0], 0, 0.2).needsReroute).toBe(false);
  });

  it('keeps "head toward" for a long straight before showing arrival', () => {
    const tracker = new RouteTracker(plan());
    const early = tracker.update([1, 0], 0, 0.016);
    expect(early.instruction?.kind).toBe('start');
    expect(early.distanceToInstructionM).toBe(0);
    const late = tracker.update([8.5, 0], 0, 0.016);
    expect(late.instruction?.kind).toBe('arrive');
    expect(late.distanceToInstructionM).toBeCloseTo(1.5);
  });

  it('points at the next instruction along the route', () => {
    const tracker = new RouteTracker({
      ...plan(),
      instructions: buildInstructions([[0, 0], [5, 0], [5, 5]], 'Lift Lobby'),
    });
    const state = tracker.update([1, 0], 0, 0.016);
    expect(state.instruction?.kind).toBe('left');
    expect(state.distanceToInstructionM).toBeCloseTo(4);
  });
});
