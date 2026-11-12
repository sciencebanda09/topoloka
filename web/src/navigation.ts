/**
 * Destination navigation: route plans, turn-by-turn instructions, progress,
 * reroute detection and arrival.
 *
 * This module is deliberately independent of three.js and the DOM so the
 * behaviour (paths, instructions, arrival thresholds) can be unit tested.
 */

import { Costmap } from './nav';
import type { Poi } from './pois';

export const WALK_SPEED_MPS = 1.4;
export const ARRIVAL_RADIUS_M = 0.7;
export const OFF_ROUTE_RADIUS_M = 1.2;

export type InstructionKind = 'start' | 'left' | 'right' | 'straight' | 'arrive';

export interface RouteInstruction {
  kind: InstructionKind;
  /** Distance along the route where this instruction applies. */
  atMeters: number;
  /** Pre-formatted wording, without the distance prefix. */
  text: string;
}

export interface RoutePlan {
  targetId: string;
  targetName: string;
  waypoints: [number, number][];
  distanceM: number;
  etaSeconds: number;
  instructions: RouteInstruction[];
}

export interface NavState {
  remainingM: number;
  etaSeconds: number;
  deviationM: number;
  /** Fraction of the planned distance covered, clamped to [0, 1]. */
  progress: number;
  instruction: RouteInstruction | null;
  /** Distance to the next instruction (0 when it is due now). */
  distanceToInstructionM: number;
  arrived: boolean;
  needsReroute: boolean;
}

export function planRoute(
  costmap: Costmap,
  from: [number, number],
  target: Poi,
  opts: { speed?: number } = {},
): RoutePlan | null {
  const waypoints = costmap.findPath(from, [target.x, target.y]);
  if (!waypoints || waypoints.length < 2) return null;
  const distanceM = Costmap.pathLength(waypoints);
  if (distanceM < 0.05) return null;
  return {
    targetId: target.id,
    targetName: target.name,
    waypoints,
    distanceM,
    etaSeconds: distanceM / (opts.speed ?? WALK_SPEED_MPS),
    instructions: buildInstructions(waypoints, target.name),
  };
}

function cumulative(path: [number, number][]): number[] {
  const out = [0];
  for (let i = 1; i < path.length; i++) {
    out.push(out[i - 1] + Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]));
  }
  return out;
}

const normalizeAngle = (a: number): number => {
  let v = a;
  while (v > Math.PI) v -= Math.PI * 2;
  while (v < -Math.PI) v += Math.PI * 2;
  return v;
};

const bearing = (a: [number, number], b: [number, number]): number =>
  Math.atan2(b[1] - a[1], b[0] - a[0]);

/**
 * Turn instructions at every meaningful corner. Bearing deltas below 25° are
 * treated as straight: the smoothed path intentionally drops grid stair-steps,
 * and a banner that says "turn 3°" is noise.
 */
export function buildInstructions(path: [number, number][], targetName: string): RouteInstruction[] {
  const cum = cumulative(path);
  const out: RouteInstruction[] = [
    { kind: 'start', atMeters: 0, text: `Head toward ${targetName}` },
  ];
  for (let i = 1; i < path.length - 1; i++) {
    const inBearing = bearing(path[i - 1], path[i]);
    const outBearing = bearing(path[i], path[i + 1]);
    const delta = normalizeAngle(outBearing - inBearing);
    if (Math.abs(delta) < (25 * Math.PI) / 180) continue;
    // Positive delta rotates counter-clockwise in the nav x/y plane: left.
    out.push({
      kind: delta > 0 ? 'left' : 'right',
      atMeters: cum[i],
      text: delta > 0 ? 'Turn left' : 'Turn right',
    });
  }
  out.push({
    kind: 'arrive',
    atMeters: cum[cum.length - 1],
    text: `Arrive at ${targetName}`,
  });
  return out;
}

/** Wording for the navigation banner at a given travelled distance. */
export function instructionText(plan: RoutePlan, state: Pick<NavState, 'instruction' | 'distanceToInstructionM'>): string {
  const inst = state.instruction;
  if (!inst) return `Continue to ${plan.targetName}`;
  if (inst.kind === 'arrive') return `Arrive at ${plan.targetName}`;
  if (inst.kind === 'start') return `Head toward ${plan.targetName}`;
  const d = state.distanceToInstructionM;
  if (d <= 1.2) return `${inst.text} now`;
  return `In ${formatDistance(d)}, ${inst.text.toLowerCase()}`;
}

export function formatDistance(m: number): string {
  if (m < 1) return `${Math.max(1, Math.round(m * 100))} cm`;
  if (m < 10) return `${m.toFixed(1)} m`;
  return `${Math.round(m)} m`;
}

export function formatEta(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rest = s % 60;
  return rest ? `${m}m ${rest}s` : `${m}m`;
}

/**
 * Tracks a walker along a plan. Progress is monotonic: crossing back over a
 * previous segment (stepping aside) does not reset the distance walked.
 */
export class RouteTracker {
  readonly plan: RoutePlan;
  private cum: number[];
  private segment = 0;
  private progressM = 0;
  private offTimer = 0;
  private arrived = false;
  private done = false;

  constructor(plan: RoutePlan) {
    this.plan = plan;
    this.cum = cumulative(plan.waypoints);
  }

  get finished(): boolean {
    return this.done;
  }

  update(pos: [number, number], heading: number, dt: number): NavState {
    void heading;
    const path = this.plan.waypoints;
    let bestDist = Infinity;
    let bestSegment = this.segment;
    let bestProgress = this.cum[this.segment] ?? 0;

    // Allow looking one segment back so sidesteps do not trigger a reroute.
    const first = Math.max(0, this.segment - 1);
    for (let i = first; i < path.length - 1; i++) {
      const [ax, ay] = path[i];
      const [bx, by] = path[i + 1];
      const dx = bx - ax, dy = by - ay;
      const len2 = dx * dx + dy * dy;
      const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((pos[0] - ax) * dx + (pos[1] - ay) * dy) / len2));
      const px = ax + dx * t, py = ay + dy * t;
      const d = Math.hypot(pos[0] - px, pos[1] - py);
      if (d < bestDist) {
        bestDist = d;
        bestSegment = i;
        bestProgress = this.cum[i] + t * Math.sqrt(len2);
      }
    }

    // An off-route walker should not "teleport" to 100% progress: only
    // advance while the projection is plausibly on this corridor. Arrival is
    // still measured directly from the goal below.
    if (bestDist <= OFF_ROUTE_RADIUS_M) {
      this.segment = Math.max(this.segment, bestSegment);
      this.progressM = Math.max(this.progressM, bestProgress, this.cum[this.segment] ?? 0);
    }
    const progressM = this.progressM;
    const goal = path[path.length - 1];
    const goalDist = Math.hypot(pos[0] - goal[0], pos[1] - goal[1]);
    const remainingM = Math.max(0, this.plan.distanceM - progressM);

    if (!this.arrived && (goalDist <= ARRIVAL_RADIUS_M
      || (remainingM <= 0.4 && goalDist <= ARRIVAL_RADIUS_M * 1.6))) {
      this.arrived = true;
      this.done = true;
    }

    const deviationM = bestDist;
    if (deviationM > OFF_ROUTE_RADIUS_M) this.offTimer += dt;
    else this.offTimer = Math.max(0, this.offTimer - dt * 2);

    const next = this.nextInstruction(progressM);
    return {
      remainingM,
      etaSeconds: remainingM / WALK_SPEED_MPS,
      deviationM,
      progress: Math.max(0, Math.min(1, this.plan.distanceM ? progressM / this.plan.distanceM : 0)),
      instruction: next.instruction,
      distanceToInstructionM: next.distance,
      arrived: this.arrived,
      needsReroute: !this.arrived && this.offTimer > 0.8,
    };
  }

  private nextInstruction(progressM: number): { instruction: RouteInstruction | null; distance: number } {
    for (const inst of this.plan.instructions) {
      if (inst.kind === 'arrive') continue;
      if (inst.atMeters > progressM + 0.25) {
        return { instruction: inst, distance: inst.atMeters - progressM };
      }
    }
    const arrive = this.plan.instructions[this.plan.instructions.length - 1] ?? null;
    const remaining = Math.max(0, this.plan.distanceM - progressM);
    // On a long straight corridor the next instruction is technically
    // "arrive", but a banner that says "Arrive in 52 m" from the first step
    // is noise. Keep "Head toward X" until the destination is close.
    if (arrive && arrive.kind === 'arrive' && remaining > 3) {
      const start = this.plan.instructions[0];
      if (start?.kind === 'start') return { instruction: start, distance: 0 };
    }
    return { instruction: arrive, distance: remaining };
  }
}
