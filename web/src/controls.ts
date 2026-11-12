/**
 * First-person walk controls: pointer-lock look + WASD, colliding with the
 * costmap so you cannot walk through walls/furniture (walk speed ~1.5 m/s,
 * shift ~3.2 m/s). Y stays at eye height -- this is a walkthrough, not a flycam.
 *
 * R2 additions: search/editor focus guards (typing never walks), held-key
 * clearing on blur, and a camera fly-to used by POI selection. The fly-to
 * moves the walker to a standable pose, not through walls.
 *
 * Mobile: drag to look; a virtual stick appears bottom-left once any touch
 * lands there.
 */

import * as THREE from 'three';
import type { Costmap } from './nav';

const WALK_SPEED = 1.5;
const RUN_SPEED = 3.2;
const LOOK_SENSITIVITY = 0.0022;
// Keep the lens inside the region the capture actually saw. Looking further
// up hits unobserved ceiling (black void); further down hits floor splats
// trained from grazing angles only.
const PITCH_MIN = -0.85;
const PITCH_MAX = 0.35;

export interface WalkPose {
  position: [number, number, number];
  yaw: number;
  pitch?: number;
}

interface Flight {
  from: WalkPose;
  to: WalkPose;
  elapsed: number;
  duration: number;
  resolve: () => void;
}

interface Turn {
  from: number;
  to: number;
  elapsed: number;
  duration: number;
}

export class WalkControls {
  position: [number, number, number];
  yaw: number;
  pitch = 0;

  private keys = new Set<string>();
  private canvas: HTMLCanvasElement;
  private costmap: Costmap;
  private touchLookId: number | null = null;
  private touchMoveId: number | null = null;
  private touchMoveStart: [number, number] = [0, 0];
  private touchMoveNow: [number, number] = [0, 0];
  private touchLast: [number, number] = [0, 0];
  private enabled = true;
  private flight: Flight | null = null;
  private turn: Turn | null = null;

  constructor(
    canvas: HTMLCanvasElement,
    private camera: THREE.PerspectiveCamera,
    costmap: Costmap,
    spawn: WalkPose,
  ) {
    this.canvas = canvas;
    this.costmap = costmap;
    this.position = [...spawn.position];
    this.yaw = spawn.yaw;
    this.pitch = clamp(spawn.pitch ?? 0, PITCH_MIN, PITCH_MAX);

    canvas.addEventListener('click', () => {
      if (!this.enabled || this.isTypingTarget(document.activeElement) || this.touchDevice) return;
      if (document.pointerLockElement !== canvas) {
        try {
          const pending = canvas.requestPointerLock() as unknown;
          if (pending && typeof (pending as Promise<void>).catch === 'function') {
            (pending as Promise<void>).catch(() => {});
          }
        } catch {
          /* pointer lock is optional */
        }
      }
    });
    document.addEventListener('mousemove', (e) => {
      if (document.pointerLockElement !== canvas || !this.enabled || this.flight) return;
      this.applyLook(e.movementX, e.movementY);
    });
    window.addEventListener('keydown', (e) => {
      if (this.isTypingEvent(e) || !this.enabled) return;
      this.keys.add(e.code);
    });
    window.addEventListener('keyup', (e) => this.keys.delete(e.code));
    window.addEventListener('blur', () => this.keys.clear());
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) this.keys.clear();
    });
    this.setupTouch();
    this.syncCamera();
  }

  get heading(): number {
    const f = new THREE.Vector3();
    this.camera.getWorldDirection(f);
    return Math.atan2(-f.z, f.x); // nav-plane heading in radians (nav x/y)
  }

  get isFlying(): boolean {
    return this.flight !== null;
  }

  get touchDevice(): boolean {
    return window.matchMedia('(pointer: coarse)').matches || navigator.maxTouchPoints > 0;
  }

  /** Disable movement (search overlay, editor, camera flight, modal UI). */
  setEnabled(on: boolean): void {
    this.enabled = on;
    if (!on) {
      this.keys.clear();
      if (document.pointerLockElement === this.canvas) document.exitPointerLock();
    }
  }

  pose(): WalkPose {
    return { position: [...this.position], yaw: this.yaw, pitch: this.pitch };
  }

  update(dt: number): void {
    if (this.flight) {
      this.stepFlight(dt);
      return;
    }
    if (this.turn) this.stepTurn(dt);
    if (!this.enabled) {
      this.syncCamera();
      return;
    }
    const fast = this.keys.has('ShiftLeft') || this.keys.has('ShiftRight');
    const speed = fast ? RUN_SPEED : WALK_SPEED;
    let mx = 0, mz = 0; // in three-space, camera-relative
    if (this.keys.has('KeyW') || this.keys.has('ArrowUp')) mz -= 1;
    if (this.keys.has('KeyS') || this.keys.has('ArrowDown')) mz += 1;
    if (this.keys.has('KeyA') || this.keys.has('ArrowLeft')) mx -= 1;
    if (this.keys.has('KeyD') || this.keys.has('ArrowRight')) mx += 1;

    // virtual stick contribution
    if (this.touchMoveId !== null) {
      const dx = this.touchMoveNow[0] - this.touchMoveStart[0];
      const dy = this.touchMoveNow[1] - this.touchMoveStart[1];
      const dead = 12;
      if (Math.abs(dx) > dead) mx += dx / 80;
      if (Math.abs(dy) > dead) mz += dy / 80;
    }

    if (mx || mz) {
      const len = Math.hypot(mx, mz);
      mx /= len; mz /= len;
      const sin = Math.sin(this.yaw), cos = Math.cos(this.yaw);
      // rotate camera-relative movement into three world (yaw around Y)
      const wx = mx * cos + mz * sin;
      const wz = -mx * sin + mz * cos;
      // three world dx,dz -> nav dx = wx, dy = -wz
      this.tryMove(wx * speed * dt, -wz * speed * dt);
    }
    this.syncCamera();
  }

  /** Face a nav-plane point without moving. */
  lookAt(x: number, y: number, pitch = this.pitch): void {
    // Camera forward maps to nav (-sin yaw, cos yaw); invert that mapping.
    this.turn = null;
    this.yaw = Math.atan2(-(x - this.position[0]), y - this.position[1]);
    this.pitch = clamp(pitch, PITCH_MIN, PITCH_MAX);
    this.syncCamera();
  }

  /**
   * Ease the camera yaw toward a nav-plane point without moving the walker.
   * Used when navigation starts so the first W press follows the route.
   */
  turnTo(x: number, y: number, duration = 0.55): void {
    const to = Math.atan2(-(x - this.position[0]), y - this.position[1]);
    if (duration <= 0.05 || Math.abs(shortestDelta(this.yaw, to)) < 0.01) {
      this.turn = null;
      this.yaw = to;
      this.syncCamera();
      return;
    }
    this.turn = { from: this.yaw, to, elapsed: 0, duration };
  }

  /** Instant placement; used by deep links and the POI editor preview. */
  teleport(pose: WalkPose): void {
    this.flight = null;
    this.turn = null;
    this.position = [...pose.position];
    this.yaw = pose.yaw;
    this.pitch = clamp(pose.pitch ?? 0, PITCH_MIN, PITCH_MAX);
    this.keys.clear();
    this.syncCamera();
  }

  /**
   * Ease to a pose over `duration` seconds. Yaw takes the shortest arc.
   * Returns a promise so callers can open a card exactly on arrival.
   */
  flyTo(pose: WalkPose, duration = 1.25): Promise<void> {
    if (duration <= 0.05) {
      this.teleport(pose);
      return Promise.resolve();
    }
    this.keys.clear();
    this.turn = null;
    return new Promise((resolve) => {
      this.flight = {
        from: this.pose(),
        to: {
          position: [...pose.position],
          yaw: pose.yaw,
          pitch: clamp(pose.pitch ?? 0, PITCH_MIN, PITCH_MAX),
        },
        elapsed: 0,
        duration,
        resolve,
      };
      if (document.pointerLockElement === this.canvas) document.exitPointerLock();
    });
  }

  /** Cancel a flight (e.g. the user starts typing a new search). */
  cancelFlight(): void {
    if (!this.flight) return;
    const resolve = this.flight.resolve;
    this.flight = null;
    resolve();
    this.syncCamera();
  }

  private stepTurn(dt: number): void {
    const turn = this.turn;
    if (!turn) return;
    turn.elapsed += dt;
    const t = clamp(turn.elapsed / turn.duration, 0, 1);
    const e = t * t * (3 - 2 * t); // smoothstep
    this.yaw = turn.from + shortestDelta(turn.from, turn.to) * e;
    if (t >= 1) {
      this.yaw = turn.to;
      this.turn = null;
    }
  }

  private stepFlight(dt: number): void {
    const f = this.flight;
    if (!f) return;
    f.elapsed += dt;
    const t = clamp(f.elapsed / f.duration, 0, 1);
    const e = t * t * (3 - 2 * t); // smoothstep
    const a = f.from.position, b = f.to.position;
    this.position = [
      a[0] + (b[0] - a[0]) * e,
      a[1] + (b[1] - a[1]) * e,
      a[2] + (b[2] - a[2]) * e,
    ];
    let delta = f.to.yaw - f.from.yaw;
    while (delta > Math.PI) delta -= Math.PI * 2;
    while (delta < -Math.PI) delta += Math.PI * 2;
    this.yaw = f.from.yaw + delta * e;
    this.pitch = (f.from.pitch ?? 0) + ((f.to.pitch ?? 0) - (f.from.pitch ?? 0)) * e;
    this.syncCamera();
    if (t >= 1) {
      this.position = [...b];
      this.yaw = f.to.yaw;
      this.pitch = f.to.pitch ?? 0;
      this.flight = null;
      this.syncCamera();
      f.resolve();
    }
  }

  private tryMove(dx: number, dy: number): void {
    const [x, y] = this.position;
    if (!this.blocked(x + dx, y + dy)) {
      this.position[0] = x + dx;
      this.position[1] = y + dy;
      return;
    }
    // slide: keep the axis that stays clear
    if (!this.blocked(x + dx, y)) this.position[0] = x + dx;
    else if (!this.blocked(x, y + dy)) this.position[1] = y + dy;
  }

  private blocked(x: number, y: number): boolean {
    return this.costmap.isBlockedRadius(x, y, 0.12);
  }

  private applyLook(mx: number, my: number): void {
    this.turn = null;
    this.yaw -= mx * LOOK_SENSITIVITY;
    this.pitch = clamp(this.pitch - my * LOOK_SENSITIVITY, PITCH_MIN, PITCH_MAX);
  }

  private syncCamera(): void {
    this.camera.position.set(this.position[0], this.position[2], -this.position[1]);
    this.camera.rotation.set(0, 0, 0);
    this.camera.rotateY(this.yaw);
    this.camera.rotateX(this.pitch);
  }

  private setupTouch(): void {
    const c = this.canvas;
    c.addEventListener('touchstart', (e) => {
      if (!this.enabled || this.flight) return;
      for (const t of Array.from(e.changedTouches)) {
        const isLeft = t.clientX < window.innerWidth / 2;
        if (isLeft && this.touchMoveId === null) {
          this.touchMoveId = t.identifier;
          this.touchMoveStart = this.touchMoveNow = [t.clientX, t.clientY];
        } else if (!isLeft && this.touchLookId === null) {
          this.touchLookId = t.identifier;
          this.touchLast = [t.clientX, t.clientY];
        }
      }
    }, { passive: true });
    c.addEventListener('touchmove', (e) => {
      if (!this.enabled || this.flight) return;
      for (const t of Array.from(e.changedTouches)) {
        if (t.identifier === this.touchMoveId) {
          this.touchMoveNow = [t.clientX, t.clientY];
        } else if (t.identifier === this.touchLookId) {
          this.applyLook((t.clientX - this.touchLast[0]) * 2.2, (t.clientY - this.touchLast[1]) * 2.2);
          this.touchLast = [t.clientX, t.clientY];
        }
      }
    }, { passive: true });
    const end = (e: TouchEvent) => {
      for (const t of Array.from(e.changedTouches)) {
        if (t.identifier === this.touchMoveId) this.touchMoveId = null;
        if (t.identifier === this.touchLookId) this.touchLookId = null;
      }
    };
    c.addEventListener('touchend', end, { passive: true });
    c.addEventListener('touchcancel', end, { passive: true });
  }

  private isTypingEvent(e: KeyboardEvent): boolean {
    return this.isTypingTarget(e.target as HTMLElement | null);
  }

  private isTypingTarget(t: Element | null): boolean {
    if (!t) return false;
    const el = t as HTMLElement;
    const tag = el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
  }
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

const shortestDelta = (from: number, to: number): number => {
  let delta = to - from;
  while (delta > Math.PI) delta -= Math.PI * 2;
  while (delta < -Math.PI) delta += Math.PI * 2;
  return delta;
};
