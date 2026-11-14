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
  /** Cumulative turn deflection in signed degrees (+left, -right) if a bend. */
  angleDeg?: number;
  /** Nearest line-of-sight landmark POI anchoring this decision point. */
  landmarkName?: string;
}

export interface InstructionOptions {
  /** Scene POIs used for visibility-weighted landmark anchoring at turns. */
  pois?: readonly Poi[];
  /** Costmap used for wall-occlusion checks when scoring candidate landmarks. */
  costmap?: Costmap;
  /** Target POI id excluded from landmark anchoring (already the goal). */
  targetId?: string;
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
  /** True when camera heading diverges strongly (>~115 deg) from corridor tangent. */
  wrongWay: boolean;
  /** Signed heading error relative to active corridor tangent, degrees. */
  headingErrorDeg: number;
  /** Exponential-moving-average walking pace in m/s. */
  paceMps: number;
  /** Pure-Pursuit geodesic lookahead point along remaining corridor (nav x/y). */
  lookaheadPoint: [number, number];
}

export function planRoute(
  costmap: Costmap,
  from: [number, number],
  target: Poi,
  opts: { speed?: number; pois?: readonly Poi[] } = {},
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
    instructions: buildInstructions(waypoints, target.name, {
      pois: opts.pois,
      costmap,
      targetId: target.id,
    }),
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

const LANDMARK_WEIGHT: Record<string, number> = {
  exit: 1.35,
  landmark: 1.3,
  platform: 1.25,
  retail: 1.15,
  facility: 1.1,
  area: 0.9,
};

interface TurnCluster {
  startIdx: number;
  endIdx: number;
  vertexSpan: number;
  maxAbs: number;
  apexIndex: number;
  atMeters: number;
  deltaRad: number;
  isSmoothArc: boolean;
}

function maxPerpToChord(
  path: [number, number][],
  fromIdx: number,
  toIdx: number,
  a: [number, number],
  b: [number, number],
): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy);
  if (len < 1e-6) return Infinity;
  let maxD = 0;
  for (let k = fromIdx; k <= toIdx; k++) {
    const d = Math.abs((path[k][0] - a[0]) * dy - (path[k][1] - a[1]) * dx) / len;
    if (d > maxD) maxD = d;
  }
  return maxD;
}

function pointAtArc(path: [number, number][], cum: number[], s: number): [number, number] {
  if (s <= 0) return path[0];
  const total = cum[cum.length - 1];
  if (s >= total) return path[path.length - 1];
  for (let i = 0; i < cum.length - 1; i++) {
    if (cum[i + 1] >= s) {
      const span = cum[i + 1] - cum[i];
      const t = span > 1e-6 ? (s - cum[i]) / span : 0;
      return [
        path[i][0] + (path[i + 1][0] - path[i][0]) * t,
        path[i][1] + (path[i + 1][1] - path[i][1]) * t,
      ];
    }
  }
  return path[path.length - 1];
}

function pickLandmark(
  path: [number, number][],
  cum: number[],
  turnArcM: number,
  turnPt: [number, number],
  opts: InstructionOptions | undefined,
  usedLandmarks: Set<string>,
): Poi | null {
  const pois = opts?.pois;
  if (!pois?.length) return null;
  const radius = 6.5;
  const radiusSq = radius * radius;
  const approachPt = pointAtArc(path, cum, Math.max(0, turnArcM - 1.8));
  const ax = turnPt[0] - approachPt[0];
  const ay = turnPt[1] - approachPt[1];
  const aLen = Math.hypot(ax, ay);
  const ux = aLen > 1e-4 ? ax / aLen : 0;
  const uy = aLen > 1e-4 ? ay / aLen : 0;

  let best: Poi | null = null;
  let bestScore = 0.22;
  for (const poi of pois) {
    if (opts?.targetId && poi.id === opts.targetId) continue;
    const dx = poi.x - turnPt[0];
    const dy = poi.y - turnPt[1];
    const dSq = dx * dx + dy * dy;
    if (dSq > radiusSq) continue;
    const dist = Math.sqrt(dSq);
    const catWeight = LANDMARK_WEIGHT[poi.category] ?? 1.0;

    let approachBonus = 1.0;
    if (aLen > 1e-4) {
      const vx = poi.x - approachPt[0];
      const vy = poi.y - approachPt[1];
      const dot = vx * ux + vy * uy;
      approachBonus = dot > 0 ? 1.35 : 0.85;
    }

    let losBonus = 1.0;
    if (opts?.costmap) {
      losBonus = opts.costmap.hasLineOfSight(approachPt, [poi.x, poi.y]) ? 1.4 : 0.25;
    }

    const repeatPenalty = usedLandmarks.has(poi.id) ? 0.45 : 1.0;
    const score = (catWeight / (1 + 0.55 * dist)) * approachBonus * losBonus * repeatPenalty;
    if (score > bestScore) {
      bestScore = score;
      best = poi;
    }
  }
  if (best) usedLandmarks.add(best.id);
  return best;
}

/**
 * Visibility-Curvature Cognitive Wayfinding (VCCW):
 * 1. Computes both vertex turning angles and multi-vertex same-sign curvature
 *    clusters so smooth curved corridors (multiple 12-22 deg segments summing
 *    to >= 28 deg) are emitted instead of silently dropped.
 * 2. Suppresses opposite-sign micro-chicanes (|delta| < 45 deg, net deflection
 *    < 22 deg within 2.6 m) caused by brief obstacle sidesteps.
 * 3. Anchors each turn to the highest-salience line-of-sight POI ahead of the
 *    turn when scene POIs / costmap are provided.
 */
export function buildInstructions(
  path: [number, number][],
  targetName: string,
  opts?: InstructionOptions,
): RouteInstruction[] {
  const cum = cumulative(path);
  const out: RouteInstruction[] = [
    { kind: 'start', atMeters: 0, text: `Head toward ${targetName}` },
  ];
  if (path.length < 3) {
    out.push({ kind: 'arrive', atMeters: cum[cum.length - 1], text: `Arrive at ${targetName}` });
    return out;
  }

  const deltas: number[] = new Array(path.length).fill(0);
  for (let i = 1; i < path.length - 1; i++) {
    const inB = bearing(path[i - 1], path[i]);
    const outB = bearing(path[i], path[i + 1]);
    deltas[i] = normalizeAngle(outB - inB);
  }

  const MIN_VERTEX_NOISE = (6 * Math.PI) / 180;
  const MIN_TURN_RAD = (25 * Math.PI) / 180;
  const ATOM_MIN_RAD = (15 * Math.PI) / 180;
  const clusters: TurnCluster[] = [];

  let i = 1;
  while (i < path.length - 1) {
    const d = deltas[i];
    if (Math.abs(d) < MIN_VERTEX_NOISE) {
      i++;
      continue;
    }
    const sign = d > 0 ? 1 : -1;
    let sum = d;
    let maxAbs = Math.abs(d);
    let apex = i;
    let j = i + 1;
    while (j < path.length - 1) {
      const dj = deltas[j];
      if (dj * sign <= 0 || Math.abs(dj) < MIN_VERTEX_NOISE) break;
      if (cum[j] - cum[i] > 4.8) break;
      sum += dj;
      if (Math.abs(dj) > maxAbs) {
        maxAbs = Math.abs(dj);
        apex = j;
      }
      j++;
    }
    // Keep candidate atoms down to 15 deg so dipole chicane filtering sees both
    // the outbound dodge and the return bend before final emission thresholding.
    const vertexSpan = j - i;
    if (Math.abs(sum) >= ATOM_MIN_RAD) {
      // Weighted apex toward the center of curvature mass for multi-vertex bends
      if (vertexSpan > 1) {
        const half = Math.abs(sum) * 0.5;
        let acc = 0;
        for (let k = i; k < j; k++) {
          acc += Math.abs(deltas[k]);
          if (acc >= half) {
            apex = k;
            break;
          }
        }
      }
      clusters.push({
        startIdx: i,
        endIdx: j - 1,
        vertexSpan,
        maxAbs,
        apexIndex: apex,
        atMeters: cum[apex],
        deltaRad: sum,
        isSmoothArc: vertexSpan > 1 && maxAbs < MIN_TURN_RAD,
      });
    }
    i = j;
  }

  // Filter minor opposite-sign obstacle-dodging chicanes via outer-chord lateral
  // tube gating while preserving genuine >=50 deg S-bends, then apply final turn threshold.
  const filtered: TurnCluster[] = [];
  for (let k = 0; k < clusters.length; k++) {
    const cur = clusters[k];
    const next = clusters[k + 1];
    if (
      next
      && cur.deltaRad * next.deltaRad < 0
      && cum[next.endIdx] - cum[cur.startIdx] <= 5.5
      && Math.abs(cur.deltaRad) < (50 * Math.PI) / 180
      && Math.abs(next.deltaRad) < (50 * Math.PI) / 180
      && Math.abs(cur.deltaRad + next.deltaRad) < (26 * Math.PI) / 180
      && maxPerpToChord(
        path,
        cur.startIdx,
        next.endIdx,
        path[Math.max(0, cur.startIdx - 1)],
        path[Math.min(path.length - 1, next.endIdx + 1)],
      ) < 0.90
    ) {
      k++; // skip narrow obstacle swerve pair
      continue;
    }
    const emitThreshold = cur.vertexSpan > 1 ? (28 * Math.PI) / 180 : MIN_TURN_RAD;
    if (Math.abs(cur.deltaRad) >= emitThreshold) {
      filtered.push(cur);
    }
  }

  const usedLandmarks = new Set<string>();
  for (const c of filtered) {
    const isLeft = c.deltaRad > 0;
    const absDeg = Math.abs((c.deltaRad * 180) / Math.PI);
    const verb = c.isSmoothArc && absDeg < 75
      ? (isLeft ? 'Curve left' : 'Curve right')
      : (isLeft ? 'Turn left' : 'Turn right');
    const landmark = pickLandmark(path, cum, c.atMeters, path[c.apexIndex], opts, usedLandmarks);
    const text = landmark ? `${verb} past ${landmark.name}` : verb;
    // Positive delta rotates counter-clockwise in the nav x/y plane: left.
    out.push({
      kind: isLeft ? 'left' : 'right',
      atMeters: c.atMeters,
      text,
      angleDeg: Math.round((c.deltaRad * 180) / Math.PI),
      landmarkName: landmark?.name,
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
export function instructionText(
  plan: RoutePlan,
  state: Pick<NavState, 'instruction' | 'distanceToInstructionM'> & { wrongWay?: boolean },
): string {
  if (state.wrongWay) return `Turn around toward ${plan.targetName}`;
  const inst = state.instruction;
  if (!inst) return `Continue to ${plan.targetName}`;
  if (inst.kind === 'arrive') return `Arrive at ${plan.targetName}`;
  if (inst.kind === 'start') return `Head toward ${plan.targetName}`;
  const d = state.distanceToInstructionM;
  if (d <= 1.2) return `${inst.text} now`;
  const lowerLead = inst.text.charAt(0).toLowerCase() + inst.text.slice(1);
  return `In ${formatDistance(d)}, ${lowerLead}`;
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
const LOOKAHEAD_M = 2.8;

export class RouteTracker {
  readonly plan: RoutePlan;
  private cum: number[];
  private segment = 0;
  private progressM = 0;
  private offTimer = 0;
  private arrived = false;
  private done = false;
  private lastPos: [number, number] | null = null;
  private paceMps = WALK_SPEED_MPS;
  private lookahead: [number, number];

  constructor(plan: RoutePlan) {
    this.plan = plan;
    this.cum = cumulative(plan.waypoints);
    const total = this.cum[this.cum.length - 1] ?? 0;
    this.lookahead = pointAtArc(plan.waypoints, this.cum, Math.min(total, LOOKAHEAD_M));
  }

  get finished(): boolean {
    return this.done;
  }

  get currentLookahead(): [number, number] {
    return this.lookahead;
  }

  update(pos: [number, number], heading: number, dt: number): NavState {
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

    // Update filtered walking pace from actual motion when moving coherently.
    if (this.lastPos && dt > 1e-3 && dt <= 1.0) {
      const instSpeed = Math.hypot(pos[0] - this.lastPos[0], pos[1] - this.lastPos[1]) / dt;
      if (instSpeed > 0.25 && instSpeed < 5.0) {
        this.paceMps = this.paceMps * 0.85 + instSpeed * 0.15;
      } else {
        // Decay smoothly toward nominal pace when stopped at a glance.
        this.paceMps = this.paceMps * 0.96 + WALK_SPEED_MPS * 0.04;
      }
    }
    this.lastPos = [pos[0], pos[1]];

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

    // Pure-Pursuit geodesic lookahead point along remaining route corridor.
    this.lookahead = pointAtArc(
      path,
      this.cum,
      Math.min(this.cum[this.cum.length - 1] ?? 0, progressM + LOOKAHEAD_M),
    );

    // Corridor tangent vs camera heading alignment.
    const segIdx = Math.min(path.length - 2, bestSegment);
    const tangentAngle = segIdx >= 0 ? bearing(path[segIdx], path[segIdx + 1]) : heading;
    const headingErr = normalizeAngle(tangentAngle - heading);
    const headingErrorDeg = Math.round((headingErr * 180) / Math.PI);
    const wrongWay = remainingM > 1.5 && Math.cos(headingErr) < -0.45;

    if (!this.arrived && (goalDist <= ARRIVAL_RADIUS_M
      || (remainingM <= 0.4 && goalDist <= ARRIVAL_RADIUS_M * 1.6))) {
      this.arrived = true;
      this.done = true;
    }

    const deviationM = bestDist;
    if (deviationM > OFF_ROUTE_RADIUS_M) this.offTimer += dt;
    else this.offTimer = Math.max(0, this.offTimer - dt * 2);

    // Add realistic slowdown (~0.55s) per upcoming significant turn ahead.
    let turnPenaltyS = 0;
    for (const inst of this.plan.instructions) {
      if ((inst.kind === 'left' || inst.kind === 'right') && inst.atMeters > progressM) {
        const deg = Math.abs(inst.angleDeg ?? 45);
        if (deg >= 40) turnPenaltyS += 0.55;
      }
    }

    const next = this.nextInstruction(progressM);
    return {
      remainingM,
      etaSeconds: remainingM / Math.max(0.5, this.paceMps) + turnPenaltyS,
      deviationM,
      progress: Math.max(0, Math.min(1, this.plan.distanceM ? progressM / this.plan.distanceM : 0)),
      instruction: next.instruction,
      distanceToInstructionM: next.distance,
      arrived: this.arrived,
      needsReroute: !this.arrived && this.offTimer > 0.8,
      wrongWay,
      headingErrorDeg,
      paceMps: this.paceMps,
      lookaheadPoint: this.lookahead,
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
