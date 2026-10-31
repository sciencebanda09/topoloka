/**
 * First-person walk controls: pointer-lock look + WASD, colliding with the
 * costmap so you cannot walk through walls/furniture (walk speed ~1.5 m/s,
 * shift ~3.2 m/s). Y stays at eye height -- this is a walkthrough, not a flycam.
 *
 * Mobile: drag to look; a virtual stick appears bottom-left once any touch
 * lands there (R1 pending device testing).
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

  constructor(
    canvas: HTMLCanvasElement,
    private camera: THREE.PerspectiveCamera,
    costmap: Costmap,
    spawn: { position: [number, number, number]; yaw: number; pitch?: number },
  ) {
    this.canvas = canvas;
    this.costmap = costmap;
    this.position = [...spawn.position];
    this.yaw = spawn.yaw;
    this.pitch = spawn.pitch ?? 0;

    canvas.addEventListener('click', () => {
      if (document.pointerLockElement !== canvas) canvas.requestPointerLock();
    });
    document.addEventListener('mousemove', (e) => {
      if (document.pointerLockElement !== canvas) return;
      this.applyLook(e.movementX, e.movementY);
    });
    window.addEventListener('keydown', (e) => this.keys.add(e.code));
    window.addEventListener('keyup', (e) => this.keys.delete(e.code));
    this.setupTouch();
    this.syncCamera();
  }

  get heading(): number {
    const f = new THREE.Vector3();
    this.camera.getWorldDirection(f);
    return Math.atan2(-f.z, f.x); // nav-plane heading in radians (nav x/y)
  }

  update(dt: number): void {
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
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
