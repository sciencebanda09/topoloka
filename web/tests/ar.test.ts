import { describe, expect, it } from 'vitest';
import { arGuidance, relocalizeFromAnchor, type Anchor } from '../src/ar';

describe('R3 AR relocalization and guidance', () => {
  it('places the user in front of a QR wall anchor facing it', () => {
    const anchor: Anchor = { id: 'qr-gate-a', x: 4, y: 2, normal: [0, 1, 0] };
    const pose = relocalizeFromAnchor(anchor, 1.5);
    expect(pose.position[0]).toBeCloseTo(4);
    expect(pose.position[1]).toBeCloseTo(3.5);
    // Camera forward is (-sin yaw, cos yaw); facing -Y requires yaw = pi (or -pi).
    expect(Math.abs(Math.abs(pose.yaw) - Math.PI)).toBeLessThan(1e-5);
  });

  it('computes straight, left, and right turn guidance in nav axes', () => {
    // yaw = 0 -> camera forward is nav (0, +1)
    const straight = arGuidance([0, 0], 0, [0, 10]);
    expect(straight.distanceM).toBeCloseTo(10);
    expect(straight.label).toBe('Straight ahead');

    const left = arGuidance([0, 0], 0, [-5, 0]);
    expect(left.turnDeg).toBeCloseTo(90);
    expect(left.label).toBe('Turn left 90°');

    const right = arGuidance([0, 0], 0, [5, 0]);
    expect(right.turnDeg).toBeCloseTo(-90);
    expect(right.label).toBe('Turn right 90°');
  });

  it('steers AR arrow along walkable corridor lookahead around walls while showing true remaining distance', () => {
    // Target lies straight ahead across a wall (+Y), but walkable corridor goes right (+X)
    const g = arGuidance([0, 0], 0, [0, 12], {
      lookahead: [3, 0],
      routeRemainingM: 16.5,
    });
    expect(g.distanceM).toBeCloseTo(16.5);
    expect(g.turnDeg).toBeCloseTo(-90);
    expect(g.label).toBe('Turn right 90°');
  });
});
