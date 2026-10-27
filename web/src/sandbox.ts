/**
 * Pick-and-place sandbox for the twin.
 *
 * Props are real meshes, not scanned geometry. They render inside the same
 * three.js scene the splat viewer composites before its splat pass, so props
 * write depth and are correctly occluded by splats in front of them.
 *
 * Placement raycasts the splat BVH for the floor and writes an oriented
 * footprint into the costmap's dynamic layer, so collision and A* react to
 * what the user places. Layouts persist in localStorage and can be shared.
 */

import * as THREE from 'three';
import { FREE, type NavData } from './artifacts';
import type { Costmap, Footprint } from './nav';
import {
  PROP_DEFS, buildProp, disposeProp, isPropType, propFootprint,
  type PropTransform, type PropType,
} from './props';
import type { SplatLayer } from './splat';

export interface SandboxOptions {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  canvas: HTMLCanvasElement;
  costmap: Costmap;
  nav: NavData;
  splat: SplatLayer | null;
  capture: string;
  getPlayer: () => [number, number, number];
  onChange: () => void;
}

interface PlacedProp extends PropTransform {
  group: THREE.Group;
}

interface Placement {
  x: number;
  y: number;
  z: number;
  rot: number;
  valid: boolean;
  reason: string;
  footprint: Footprint;
}

interface Carrying {
  type: PropType;
  rot: number;
  original: PropTransform | null;
  ghost: THREE.Group;
  ring: THREE.Mesh;
  ghostMat: THREE.MeshBasicMaterial;
  ringMat: THREE.MeshBasicMaterial;
}

const ROT_STEP = Math.PI / 12;

export class Sandbox {
  readonly touch = window.matchMedia('(pointer: coarse)').matches || navigator.maxTouchPoints > 0;
  readonly autoEnable: boolean;

  private readonly opts: SandboxOptions;
  private readonly root = new THREE.Group();
  private readonly placed: PlacedProp[] = [];
  private readonly pickRay = new THREE.Raycaster();
  private readonly ndc = new THREE.Vector2();
  private readonly storageKey: string;
  private carrying: Carrying | null = null;
  private placement: Placement | null = null;
  private nextId = 1;
  private enabled = false;
  private loadedSaved = false;
  private urlLoaded = false;
  private hoverTimer = 0;
  private placeTimer = 0;
  private toastTimer = 0;
  private pointerDown: { x: number; y: number; t: number } | null = null;

  private panel: HTMLDivElement | null = null;
  private carryActions: HTMLDivElement | null = null;
  private carryHint: HTMLDivElement | null = null;
  private reticle: HTMLDivElement | null = null;
  private reticleLabel: HTMLDivElement | null = null;
  private toastEl: HTMLDivElement | null = null;
  private countEl: HTMLSpanElement | null = null;

  constructor(opts: SandboxOptions) {
    this.opts = opts;
    this.storageKey = `topoloka.sandbox.v1.${opts.capture}`;
    this.root.name = 'sandbox-props';
    this.root.visible = false;
    opts.scene.add(this.root);
    this.addLights();

    this.cacheUi();
    this.wireUi();
    this.wireInput();

    const params = new URLSearchParams(location.search);
    const encoded = params.get('props');
    if (encoded) {
      this.urlLoaded = true;
      this.decodeProps(encoded);
    }
    this.autoEnable = params.has('sandbox') || !!encoded;
  }

  get isEnabled(): boolean {
    return this.enabled;
  }

  get propCount(): number {
    return this.placed.length;
  }

  setEnabled(on: boolean): void {
    if (this.enabled === on) return;
    this.enabled = on;
    if (on) {
      this.loadSavedOnce();
      this.root.visible = true;
      document.body.classList.add('sandbox-on');
      this.panel?.classList.remove('hidden');
      this.reticle?.classList.remove('hidden');
      document.getElementById('center-hint')?.classList.add('hidden');
      this.syncDynamic();
      this.toast(this.touch ? 'Tap a prop, then tap Place' : 'Pick a prop with 1–4, then click the floor');
    } else {
      this.cancelCarry(true, false);
      this.stopHover();
      this.root.visible = false;
      document.body.classList.remove('sandbox-on');
      this.panel?.classList.add('hidden');
      this.reticle?.classList.add('hidden');
      this.carryHint?.classList.add('hidden');
      if (document.pointerLockElement !== this.opts.canvas) {
        document.getElementById('center-hint')?.classList.remove('hidden');
      }
      this.syncDynamic();
    }
    this.updateUi();
  }

  toggle(): void {
    this.setEnabled(!this.enabled);
  }

  update(dt: number): void {
    if (!this.enabled) return;
    if (this.carrying) {
      // Each preview costs two splat-BVH casts; keep touch devices slower so
      // dragging the camera stays smooth.
      this.placeTimer += dt;
      if (this.placeTimer >= (this.touch ? 0.14 : 0.07)) {
        this.placeTimer = 0;
        this.updatePlacement();
      }
    } else {
      this.hoverTimer += dt;
      if (this.hoverTimer >= 0.10) {
        this.hoverTimer = 0;
        this.updateHover();
      }
    }
  }

  /** Visible props only; used by the minimap and the route label. */
  transforms(): PropTransform[] {
    if (!this.enabled) return [];
    return this.placed.map(({ id, type, x, y, z, rot }) => ({ id, type, x, y, z, rot }));
  }

  // ---- placement ---------------------------------------------------------

  private startCarry(type: PropType, rot: number, original: PropTransform | null): void {
    this.stopCarry();
    const ghostMat = new THREE.MeshBasicMaterial({ color: 0x40ff9a, depthWrite: true });
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0x40ff9a, side: THREE.DoubleSide, depthWrite: true,
    });
    const ghost = buildProp(type, ghostMat);
    ghost.userData.ghost = true;
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.42, 0.50, 32), ringMat);
    ring.rotation.x = -Math.PI / 2;
    this.root.add(ghost, ring);
    this.carrying = { type, rot, original, ghost, ring, ghostMat, ringMat };
    this.updateUi();
    this.updatePlacement();
  }

  private stopCarry(): void {
    const c = this.carrying;
    if (!c) return;
    this.root.remove(c.ghost, c.ring);
    disposeProp(c.ghost);
    c.ring.geometry.dispose();
    c.ghostMat.dispose();
    c.ringMat.dispose();
    this.carrying = null;
    this.placement = null;
    this.carryHint?.classList.add('hidden');
    this.updateUi();
  }

  private spawn(type: PropType): void {
    if (!this.enabled) this.setEnabled(true);
    if (this.carrying) {
      this.cancelCarry(true, false);
      this.syncDynamic();
    }
    this.startCarry(type, 0, null);
    this.syncDynamic();
    if (!this.touch && document.pointerLockElement !== this.opts.canvas) {
      try {
        const pending = this.opts.canvas.requestPointerLock() as unknown;
        if (pending && typeof (pending as Promise<void>).catch === 'function') {
          (pending as Promise<void>).catch(() => {});
        }
      } catch {
        /* pointer lock is optional; the canvas click also requests it */
      }
    }
  }

  private pick(prop: PlacedProp): void {
    const original: PropTransform = {
      id: prop.id, type: prop.type, x: prop.x, y: prop.y, z: prop.z, rot: prop.rot,
    };
    this.removePlaced(prop);
    this.syncDynamic(); // its footprint must disappear before the ghost is judged
    this.startCarry(prop.type, prop.rot, original);
    this.toast(`${PROP_DEFS[prop.type].label} picked up`);
  }

  private place(): void {
    const c = this.carrying;
    if (!c) return;
    const p = this.placement;
    if (!p || !p.valid) {
      this.toast(p ? `Can't place: ${p.reason}` : 'Aim at the floor');
      return;
    }
    const id = c.original?.id ?? this.nextId++;
    this.addPlaced({
      id, type: c.type, x: p.x, y: p.y, z: p.z, rot: p.rot,
    });
    this.stopCarry();
    this.syncDynamic();
    this.toast(`${PROP_DEFS[c.type].label} placed`);
  }

  private cancelCarry(restore: boolean, notify = true): void {
    const c = this.carrying;
    if (!c) return;
    const original = c.original;
    this.stopCarry();
    if (restore && original) this.restorePlaced(original);
    if (notify) this.syncDynamic();
  }

  /**
   * Put a picked-up prop back. The player can walk while carrying, so the
   * original slot may now be occupied by them; in that case try rings of
   * increasing radius and, if nothing fits, leave the prop removed rather
   * than restoring a blocked cell inside the walker.
   */
  private restorePlaced(original: PropTransform): void {
    const def = PROP_DEFS[original.type];
    const [px, py] = this.opts.getPlayer();
    const clearance = Math.max(def.hw, def.hh) + 0.35;
    const fits = (x: number, y: number): boolean => {
      if (Math.hypot(x - px, y - py) < clearance) return false;
      return this.footprintFree({ x, y, hw: def.hw, hh: def.hh, rot: original.rot });
    };
    if (fits(original.x, original.y)) {
      this.addPlaced(original);
      return;
    }
    for (let r = 0.3; r <= 2.1; r += 0.3) {
      for (let i = 0; i < 12; i++) {
        const a = (i / 12) * Math.PI * 2;
        const x = original.x + Math.cos(a) * r;
        const y = original.y + Math.sin(a) * r;
        if (fits(x, y)) {
          this.addPlaced({ ...original, x, y });
          this.toast(`${def.label} set down nearby`);
          return;
        }
      }
    }
    this.toast(`${def.label} removed: no room to set it back`);
  }

  private rotate(delta: number): void {
    if (!this.carrying) return;
    const twoPi = Math.PI * 2;
    this.carrying.rot = (this.carrying.rot + delta + twoPi) % twoPi;
    this.updatePlacement();
  }

  private removeAimed(): void {
    if (this.carrying) return;
    const prop = this.propAt();
    if (!prop) {
      this.toast('Aim at a placed prop to remove it');
      return;
    }
    this.removePlaced(prop);
    this.syncDynamic();
    this.toast(`${PROP_DEFS[prop.type].label} removed`);
  }

  private clearAll(): void {
    this.cancelCarry(true, false);
    for (const p of [...this.placed]) this.removePlaced(p);
    this.syncDynamic();
    this.toast('Sandbox cleared');
  }

  // ---- geometry / raycasts ----------------------------------------------

  private updatePlacement(): void {
    const c = this.carrying;
    if (!c) return;
    const p = this.computePlacement();
    this.placement = p;
    if (!p) {
      c.ghost.visible = false;
      c.ring.visible = false;
      this.setCarryHint(null);
      return;
    }
    const def = PROP_DEFS[c.type];
    c.ghost.visible = true;
    c.ring.visible = true;
    c.ghost.position.set(p.x, p.z, -p.y);
    c.ghost.rotation.y = p.rot;
    c.ring.position.set(p.x, p.z + 0.012, -p.y);
    c.ring.scale.setScalar((Math.max(def.hw, def.hh) + 0.12) / 0.5);
    const color = p.valid ? 0x40ff9a : 0xff5d5d;
    c.ghostMat.color.setHex(color);
    c.ringMat.color.setHex(color);
    this.setCarryHint(p);
  }

  private computePlacement(): Placement | null {
    const c = this.carrying;
    if (!c) return null;
    const camera = this.opts.camera;
    const forward = new THREE.Vector3();
    camera.getWorldDirection(forward);
    const horiz = new THREE.Vector3(forward.x, 0, forward.z);
    if (horiz.lengthSq() < 1e-4) return null;
    horiz.normalize();

    const cam = camera.position;
    const player = this.opts.getPlayer();
    const def = PROP_DEFS[c.type];
    let dist = 1.8;
    const wall = this.raySplat(
      cam.clone().add(new THREE.Vector3(0, -0.20, 0)),
      horiz,
    );
    if (wall && wall.distance < dist + 0.7) dist = Math.max(0.65, wall.distance - 0.35);

    const tx = cam.x + horiz.x * dist;
    const tz = cam.z + horiz.z * dist;
    const navX = tx;
    const navY = -tz;
    if (!this.lineOfSight(navX, navY)) return null;

    const down = this.raySplat(
      new THREE.Vector3(tx, cam.y + 0.8, tz),
      new THREE.Vector3(0, -1, 0),
    );
    let floorY = cam.y - this.opts.nav.cam_height_units;
    let floorOk = true;
    if (down && down.distance < 5) {
      floorY = down.point.y;
      // The library's default picker intersects bounding spheres, so its
      // normal is not a true surface normal. Require the hit to be clearly
      // below eye level; the nav grid still has the final say.
      floorOk = floorY < cam.y - 0.35;
    }

    const footprint: Footprint = { x: navX, y: navY, hw: def.hw, hh: def.hh, rot: c.rot };
    const mapFree = this.footprintFree(footprint);
    const nearPlayer = Math.hypot(navX - player[0], navY - player[1])
      < 0.55 + Math.max(def.hw, def.hh) * 0.5;
    const heightOk = floorY > player[2] - 2.6 && floorY < player[2] - 0.25;

    let valid = true;
    let reason = '';
    if (!floorOk) { valid = false; reason = 'aim at the floor'; }
    else if (!mapFree) { valid = false; reason = 'blocked by the map'; }
    else if (nearPlayer) { valid = false; reason = 'too close to you'; }
    else if (!heightOk) { valid = false; reason = 'not a floor surface'; }

    return { x: navX, y: navY, z: floorY, rot: c.rot, valid, reason, footprint };
  }

  private footprintFree(fp: Footprint): boolean {
    const c = Math.cos(fp.rot), s = Math.sin(fp.rot);
    const nx = Math.max(2, Math.ceil((fp.hw * 2) / 0.14));
    const ny = Math.max(2, Math.ceil((fp.hh * 2) / 0.14));
    for (let iy = 0; iy <= ny; iy++) {
      const ly = -fp.hh + (iy / ny) * 2 * fp.hh;
      for (let ix = 0; ix <= nx; ix++) {
        const lx = -fp.hw + (ix / nx) * 2 * fp.hw;
        const x = fp.x + lx * c - ly * s;
        const y = fp.y + lx * s + ly * c;
        if (this.opts.costmap.isBlocked(x, y)) return false;
      }
    }
    return true;
  }

  /** Walls block placement and picking; other props do not (see isBlocked). */
  private lineOfSight(x: number, y: number): boolean {
    const [px, py] = this.opts.getPlayer();
    const dx = x - px, dy = y - py;
    const steps = Math.max(1, Math.ceil(Math.hypot(dx, dy) / 0.12));
    for (let i = 1; i < steps; i++) {
      const t = i / steps;
      if (this.opts.costmap.valueAtWorld(px + dx * t, py + dy * t) !== FREE) return false;
    }
    return true;
  }

  private raySplat(origin: THREE.Vector3, direction: THREE.Vector3) {
    return this.opts.splat?.raycastRay(origin, direction) ?? null;
  }

  private propAt(clientX?: number, clientY?: number): PlacedProp | null {
    if (this.placed.length === 0) return null;
    if (clientX !== undefined && clientY !== undefined) {
      const rect = this.opts.canvas.getBoundingClientRect();
      this.ndc.set(
        ((clientX - rect.left) / rect.width) * 2 - 1,
        -((clientY - rect.top) / rect.height) * 2 + 1,
      );
    } else {
      this.ndc.set(0, 0);
    }
    this.pickRay.setFromCamera(this.ndc, this.opts.camera);
    this.pickRay.far = 5;
    const hits = this.pickRay.intersectObjects(this.placed.map((p) => p.group), true);
    const hit = hits[0];
    if (!hit) return null;
    // A splat surface closer than the prop means a wall is in the way.
    const wall = this.opts.splat?.raycastRay(this.pickRay.ray.origin, this.pickRay.ray.direction);
    // Floor hits near a prop's base can be slightly closer than the prop
    // surface; only a substantially nearer splat counts as a wall.
    if (wall && hit.distance > wall.distance + 0.45) return null;
    let obj: THREE.Object3D | null = hit.object;
    while (obj && obj.userData.propId === undefined) obj = obj.parent;
    if (!obj) return null;
    return this.placed.find((p) => p.id === obj!.userData.propId) ?? null;
  }

  // ---- hover / UI -------------------------------------------------------

  private updateHover(): void {
    if (this.touch || !this.enabled || this.carrying) {
      this.stopHover();
      return;
    }
    const prop = this.propAt();
    if (!prop) {
      this.stopHover();
      return;
    }
    this.reticle?.classList.add('active');
    if (this.reticleLabel) {
      this.reticleLabel.textContent = `${PROP_DEFS[prop.type].label} · ${this.touch ? 'tap' : 'click'} to pick up · Del remove`;
      this.reticleLabel.classList.remove('hidden');
    }
  }

  private stopHover(): void {
    this.reticle?.classList.remove('active');
    this.reticleLabel?.classList.add('hidden');
  }

  private setCarryHint(p: Placement | null): void {
    if (!this.carryHint || !this.carrying) return;
    const label = PROP_DEFS[this.carrying.type].label;
    const line = p
      ? (p.valid ? `${label} · click to place` : `${label} · ${p.reason}`)
      : `${label} · aim at the floor`;
    const how = this.touch ? 'tap Place' : 'click';
    this.carryHint.innerHTML = `<b>${line}</b><span>${how} · R rotate · Esc cancel</span>`;
    this.carryHint.classList.remove('hidden');
  }

  private updateUi(): void {
    this.carryActions?.classList.toggle('hidden', !this.carrying);
    if (this.countEl) this.countEl.textContent = `${this.placed.length} placed`;
    this.panel?.querySelectorAll<HTMLButtonElement>('[data-prop]').forEach((b) => {
      b.classList.toggle('active', this.carrying?.type === b.dataset.prop);
    });
  }

  private toast(message: string): void {
    if (!this.toastEl) return;
    this.toastEl.textContent = message;
    this.toastEl.classList.add('show');
    window.clearTimeout(this.toastTimer);
    this.toastTimer = window.setTimeout(() => this.toastEl?.classList.remove('show'), 2200);
  }

  // ---- persistence ------------------------------------------------------

  private rows(): (string | number)[][] {
    const r = (v: number) => Math.round(v * 1000) / 1000;
    return this.placed.map((p) => [p.type, r(p.x), r(p.y), r(p.z), r(p.rot)]);
  }

  private save(): void {
    try {
      localStorage.setItem(this.storageKey, JSON.stringify({ v: 1, p: this.rows() }));
    } catch {
      /* private mode / quota: layout is session-only */
    }
  }

  private loadSavedOnce(): void {
    if (this.loadedSaved) return;
    this.loadedSaved = true;
    if (this.urlLoaded) return;
    try {
      const raw = localStorage.getItem(this.storageKey);
      if (!raw) return;
      const obj = JSON.parse(raw) as { v?: number; p?: unknown };
      if (obj.v === 1 && Array.isArray(obj.p)) this.restore(obj.p);
    } catch {
      /* ignore corrupt storage */
    }
  }

  private decodeProps(encoded: string): void {
    try {
      const b64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
      const pad = '='.repeat((4 - (b64.length % 4)) % 4);
      const obj = JSON.parse(atob(b64 + pad)) as { v?: number; p?: unknown };
      if (obj.v === 1 && Array.isArray(obj.p)) this.restore(obj.p);
    } catch {
      /* ignore malformed share link */
    }
  }

  private encodeProps(): string {
    const json = JSON.stringify({ v: 1, p: this.rows() });
    return btoa(json).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }

  private restore(items: unknown[]): void {
    const [px, py] = this.opts.getPlayer();
    for (const row of items.slice(0, 50)) {
      if (!Array.isArray(row) || row.length < 5) continue;
      const [type, x, y, z, rot] = row as [unknown, unknown, unknown, unknown, unknown];
      if (typeof type !== 'string' || !isPropType(type)) continue;
      if (![x, y, z, rot].every((v) => typeof v === 'number' && Number.isFinite(v))) continue;
      const p = { x: x as number, y: y as number, z: z as number, rot: rot as number };
      if (this.opts.costmap.valueAtWorld(p.x, p.y) !== FREE) continue;
      if (Math.hypot(p.x - px, p.y - py) < 0.8) continue;
      this.addPlaced({ id: this.nextId++, type, x: p.x, y: p.y, z: p.z, rot: p.rot });
    }
  }

  private addPlaced(t: PropTransform): void {
    const group = buildProp(t.type);
    group.position.set(t.x, t.z, -t.y);
    group.rotation.y = t.rot;
    group.userData.propId = t.id;
    this.root.add(group);
    this.placed.push({ ...t, group });
    this.nextId = Math.max(this.nextId, t.id + 1);
    this.updateUi();
  }

  private removePlaced(prop: PlacedProp): void {
    const i = this.placed.indexOf(prop);
    if (i >= 0) this.placed.splice(i, 1);
    this.root.remove(prop.group);
    disposeProp(prop.group);
    this.updateUi();
  }

  private syncDynamic(): void {
    this.opts.costmap.setDynamicObstacles(this.enabled ? this.placed.map(propFootprint) : []);
    this.save();
    this.opts.onChange();
  }

  private share(): void {
    const url = new URL(location.href);
    url.searchParams.set('sandbox', '1');
    const data = this.encodeProps();
    if (data) url.searchParams.set('props', data);
    else url.searchParams.delete('props');
    const text = url.toString();
    const fallback = () => window.prompt('Copy this layout link', text);
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(
        () => this.toast('Layout link copied'),
        fallback,
      );
    } else {
      fallback();
    }
  }

  // ---- input ------------------------------------------------------------

  private cacheUi(): void {
    this.panel = document.getElementById('sandbox') as HTMLDivElement | null;
    this.carryActions = document.getElementById('sandbox-carry-actions') as HTMLDivElement | null;
    this.carryHint = document.getElementById('carry-hint') as HTMLDivElement | null;
    this.reticle = document.getElementById('reticle') as HTMLDivElement | null;
    this.reticleLabel = document.getElementById('reticle-label') as HTMLDivElement | null;
    this.toastEl = document.getElementById('toast') as HTMLDivElement | null;
    this.countEl = document.getElementById('sandbox-count') as HTMLSpanElement | null;
  }

  private wireUi(): void {
    this.panel?.querySelectorAll<HTMLButtonElement>('[data-prop]').forEach((b) => {
      b.addEventListener('click', () => {
        const type = b.dataset.prop;
        if (type && isPropType(type)) this.spawn(type);
      });
    });
    document.getElementById('sandbox-close')?.addEventListener('click', () => this.setEnabled(false));
    document.getElementById('sandbox-clear')?.addEventListener('click', () => this.clearAll());
    document.getElementById('sandbox-share')?.addEventListener('click', () => this.share());
    document.getElementById('sandbox-place')?.addEventListener('click', () => this.place());
    document.getElementById('sandbox-rotate')?.addEventListener('click', () => this.rotate(ROT_STEP));
    document.getElementById('sandbox-cancel')?.addEventListener('click', () => this.cancelCarry(true));
  }

  private wireInput(): void {
    window.addEventListener('keydown', (e) => {
      if (this.isTyping(e)) return;
      if (e.code === 'KeyG' && !e.repeat) {
        e.preventDefault();
        this.toggle();
        return;
      }
      if (!this.enabled) return;
      if (e.repeat) return;
      const digit = Number(e.key);
      if (digit >= 1 && digit <= 4) {
        e.preventDefault();
        const type = (['cone', 'barrier', 'crate', 'sign'] as PropType[])[digit - 1];
        this.spawn(type);
      } else if (e.code === 'KeyR') {
        e.preventDefault();
        this.rotate(e.shiftKey ? -ROT_STEP : ROT_STEP);
      } else if (e.code === 'Escape') {
        if (this.carrying) {
          e.preventDefault();
          this.cancelCarry(true);
        }
      } else if (e.code === 'Delete' || e.code === 'Backspace') {
        if (!this.carrying) {
          e.preventDefault();
          this.removeAimed();
        }
      }
    });

    this.opts.canvas.addEventListener('click', () => {
      if (!this.enabled) return;
      if (document.pointerLockElement !== this.opts.canvas) return;
      if (this.carrying) this.place();
      else {
        const prop = this.propAt();
        if (prop) this.pick(prop);
      }
    });

    const canvas = this.opts.canvas;
    canvas.addEventListener('pointerdown', (e) => {
      if (!this.enabled || e.pointerType === 'mouse') return;
      this.pointerDown = { x: e.clientX, y: e.clientY, t: performance.now() };
    });
    canvas.addEventListener('pointerup', (e) => {
      if (!this.enabled || e.pointerType === 'mouse' || !this.pointerDown) return;
      const down = this.pointerDown;
      this.pointerDown = null;
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      if (moved > 10 || performance.now() - down.t > 700) return;
      if (this.carrying) return; // mobile placement uses the Place button
      const prop = this.propAt(e.clientX, e.clientY);
      if (prop) this.pick(prop);
    });
  }

  private isTyping(e: KeyboardEvent): boolean {
    const t = e.target as HTMLElement | null;
    return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
  }

  private addLights(): void {
    const hemi = new THREE.HemisphereLight(0xffffff, 0x3a424c, 1.15);
    const key = new THREE.DirectionalLight(0xffffff, 1.5);
    key.position.set(4, 9, 5);
    const fill = new THREE.DirectionalLight(0xffffff, 0.5);
    fill.position.set(-5, 4, -4);
    this.root.add(hemi, key, fill);
  }
}
