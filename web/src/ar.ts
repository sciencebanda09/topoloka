/**
 * Round 3 AR mode: QR-anchored relocalization and live camera wayfinding HUD.
 *
 * Uses `anchors.json` (exported by `python -m namma.cli anchors <capture>`)
 * to map a scanned physical QR marker into the twin's metric `nav` frame,
 * then renders directional AR guidance toward the active destination POI.
 *
 * Pure relocalization and guidance helpers are exported without DOM dependencies
 * so they can be unit-tested in Vitest.
 */

import type { WalkPose } from './controls';
import { formatDistance } from './navigation';

export interface Anchor {
  id: string;
  x: number;
  y: number;
  z?: number;
  normal?: [number, number, number];
  yaw?: number;
  marker_size_m?: number;
}

export interface AnchorsFile {
  version: number;
  capture?: string;
  marker_size_m?: number;
  anchors: Anchor[];
}

export interface ArGuidance {
  distanceM: number;
  turnRad: number;
  turnDeg: number;
  label: string;
}

const normalizeAngle = (rad: number): number => {
  let v = rad;
  while (v > Math.PI) v -= Math.PI * 2;
  while (v < -Math.PI) v += Math.PI * 2;
  return v;
};

/** Fetch optional `anchors.json`; missing file returns an empty anchor list. */
export async function loadAnchors(base: string): Promise<AnchorsFile> {
  try {
    const res = await fetch(`${base}/anchors.json`);
    if (!res.ok) return { version: 1, anchors: [] };
    const type = res.headers.get('content-type') ?? '';
    if (!type.includes('json')) return { version: 1, anchors: [] };
    const doc = (await res.json()) as AnchorsFile;
    const anchors = Array.isArray(doc.anchors)
      ? doc.anchors.filter((a) => a && typeof a.id === 'string' && Number.isFinite(a.x) && Number.isFinite(a.y))
      : [];
    return { version: doc.version ?? 1, capture: doc.capture, marker_size_m: doc.marker_size_m, anchors };
  } catch {
    return { version: 1, anchors: [] };
  }
}

/**
 * Compute a metric `nav` walker pose in front of a QR wall anchor.
 * `normal` points out from the wall into the corridor; the user stands
 * `distanceM` in front of the wall looking toward the anchor (plus optional offset).
 */
export function relocalizeFromAnchor(
  anchor: Anchor,
  distanceM = 1.2,
  bearingOffsetRad = 0,
  eyeHeightM = 1.6,
): WalkPose {
  let nx = anchor.normal?.[0] ?? 0;
  let ny = anchor.normal?.[1] ?? 1;
  const nLen = Math.hypot(nx, ny);
  if (nLen > 1e-6) {
    nx /= nLen;
    ny /= nLen;
  } else if (Number.isFinite(anchor.yaw)) {
    nx = -Math.sin(anchor.yaw!);
    ny = Math.cos(anchor.yaw!);
  } else {
    nx = 0;
    ny = 1;
  }
  const px = anchor.x + nx * distanceM;
  const py = anchor.y + ny * distanceM;
  // Viewer yaw where camera forward = (-sin yaw, cos yaw) faces the anchor (-nx, -ny).
  const faceAnchorYaw = Math.atan2(nx, -ny);
  return {
    position: [px, py, eyeHeightM],
    yaw: normalizeAngle(faceAnchorYaw + bearingOffsetRad),
    pitch: 0,
  };
}

/**
 * Relative bearing & turn prompt from a localized pose.
 * When `lookahead` (geodesic corridor carrot) is supplied, steering aims along
 * the walkable corridor rather than pointing straight through curved walls,
 * while reporting `routeRemainingM` (or Euclidean distance fallback).
 */
export function arGuidance(
  userPos: [number, number],
  userYaw: number,
  target: [number, number],
  opts?: { lookahead?: [number, number] | null; routeRemainingM?: number | null },
): ArGuidance {
  const dxTarget = target[0] - userPos[0];
  const dyTarget = target[1] - userPos[1];
  const straightM = Math.hypot(dxTarget, dyTarget);
  const distanceM = opts?.routeRemainingM != null && Number.isFinite(opts.routeRemainingM)
    ? opts.routeRemainingM
    : straightM;
  const steerPt = opts?.lookahead ?? target;
  const dx = steerPt[0] - userPos[0];
  const dy = steerPt[1] - userPos[1];
  // Camera forward in nav x/y is (-sin yaw, cos yaw); heading angle in atan2(y, x) is yaw + pi/2.
  const userHeading = Math.atan2(Math.cos(userYaw), -Math.sin(userYaw));
  const targetBearing = Math.hypot(dx, dy) > 1e-4 ? Math.atan2(dy, dx) : Math.atan2(dyTarget, dxTarget);
  // Positive delta = target is counter-clockwise (to the left) of current heading.
  const turnRad = normalizeAngle(targetBearing - userHeading);
  const turnDeg = Math.round((turnRad * 180) / Math.PI);
  const absDeg = Math.abs(turnDeg);

  let label = 'Straight ahead';
  if (distanceM < 0.7) label = 'Arrived at destination';
  else if (absDeg > 135) label = 'Turn around';
  else if (absDeg >= 18) label = turnDeg > 0 ? `Turn left ${absDeg}°` : `Turn right ${absDeg}°`;

  return { distanceM, turnRad, turnDeg, label };
}

interface BarcodeLike {
  rawValue?: string;
}

interface BarcodeDetectorLike {
  detect(source: ImageBitmapSource): Promise<BarcodeLike[]>;
}

export interface ArControllerOptions {
  anchors: Anchor[];
  getPose: () => { position: [number, number, number]; yaw: number };
  getTarget: () => { name: string; x: number; y: number } | null;
  getLookahead?: () => [number, number] | null;
  getRemainingM?: () => number | null;
  onRelocalize: (pose: WalkPose, anchor: Anchor) => void;
  onActiveChange?: (active: boolean) => void;
  toast: (msg: string) => void;
}

export class ArModeController {
  private readonly opts: ArControllerOptions;
  private anchors: Anchor[];
  private active = false;
  private stream: MediaStream | null = null;
  private scanTimer = 0;
  private lastAnchorId: string | null = null;

  private readonly overlay = document.getElementById('ar-overlay');
  private readonly video = document.getElementById('ar-video') as HTMLVideoElement | null;
  private readonly arrow = document.getElementById('ar-arrow');
  private readonly statusEl = document.getElementById('ar-status');
  private readonly targetEl = document.getElementById('ar-target-info');
  private readonly selectEl = document.getElementById('ar-anchor-select') as HTMLSelectElement | null;
  private readonly toggleBtn = document.getElementById('ar-toggle');

  constructor(opts: ArControllerOptions) {
    this.opts = opts;
    this.anchors = opts.anchors;
    this.populateAnchors();
    this.toggleBtn?.addEventListener('click', () => {
      void this.setActive(!this.active);
    });
    document.getElementById('ar-close')?.addEventListener('click', () => {
      void this.setActive(false);
    });
    document.getElementById('ar-sim-relocalize')?.addEventListener('click', () => {
      this.relocalizeSelected();
    });
  }

  get isActive(): boolean {
    return this.active;
  }

  setAnchors(anchors: Anchor[]): void {
    this.anchors = anchors;
    this.populateAnchors();
  }

  private populateAnchors(): void {
    if (!this.selectEl) return;
    this.selectEl.replaceChildren();
    if (!this.anchors.length) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'No QR anchors in bundle (using current pose)';
      this.selectEl.append(opt);
      return;
    }
    for (const a of this.anchors) {
      const opt = document.createElement('option');
      opt.value = a.id;
      opt.textContent = `QR: ${a.id} (${a.x.toFixed(1)}, ${a.y.toFixed(1)})`;
      this.selectEl.append(opt);
    }
  }

  private relocalizeSelected(): void {
    const id = this.selectEl?.value;
    const anchor = this.anchors.find((a) => a.id === id);
    if (!anchor) {
      this.opts.toast('No QR anchors in this capture — run `namma anchors` after recording markers');
      return;
    }
    const pose = relocalizeFromAnchor(anchor);
    this.lastAnchorId = anchor.id;
    this.opts.onRelocalize(pose, anchor);
    if (this.statusEl) {
      this.statusEl.textContent = `Relocalized at QR “${anchor.id}” (${pose.position[0].toFixed(1)}, ${pose.position[1].toFixed(1)})`;
    }
    this.opts.toast(`AR locked to QR “${anchor.id}”`);
  }

  async setActive(on: boolean): Promise<void> {
    if (this.active === on) return;
    this.active = on;
    this.toggleBtn?.classList.toggle('active', on);
    this.overlay?.classList.toggle('hidden', !on);
    document.body.classList.toggle('ar-active', on);
    this.opts.onActiveChange?.(on);

    if (!on) {
      this.stopCamera();
      return;
    }

    if (this.statusEl) {
      this.statusEl.textContent = this.anchors.length
        ? `${this.anchors.length} QR anchor(s) loaded · scan marker or pick below`
        : 'Preview mode · add QR anchors via `namma anchors` for live relocalization';
    }
    await this.startCamera();
    this.update();
  }

  private async startCamera(): Promise<void> {
    if (!this.video || !navigator.mediaDevices?.getUserMedia) {
      if (this.statusEl) {
        this.statusEl.textContent = 'Camera unavailable in this browser — using twin-synced AR HUD';
      }
      return;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } },
        audio: false,
      });
      this.video.srcObject = this.stream;
      await this.video.play();
      this.startQrLoop();
    } catch {
      if (this.statusEl) {
        this.statusEl.textContent = 'Camera permission skipped — twin-synced AR preview active';
      }
    }
  }

  private stopCamera(): void {
    window.clearInterval(this.scanTimer);
    this.scanTimer = 0;
    if (this.stream) {
      for (const track of this.stream.getTracks()) track.stop();
      this.stream = null;
    }
    if (this.video) this.video.srcObject = null;
  }

  private startQrLoop(): void {
    const Detector = (window as unknown as { BarcodeDetector?: new (opts: { formats: string[] }) => BarcodeDetectorLike })
      .BarcodeDetector;
    if (!Detector || !this.video) return;
    let detector: BarcodeDetectorLike;
    try {
      detector = new Detector({ formats: ['qr_code'] });
    } catch {
      return;
    }
    this.scanTimer = window.setInterval(async () => {
      if (!this.active || !this.video || this.video.readyState < 2) return;
      try {
        const codes = await detector.detect(this.video);
        for (const code of codes) {
          const val = code.rawValue?.trim();
          if (!val || val === this.lastAnchorId) continue;
          const anchor = this.anchors.find((a) => a.id === val);
          if (anchor) {
            this.lastAnchorId = val;
            const pose = relocalizeFromAnchor(anchor);
            this.opts.onRelocalize(pose, anchor);
            if (this.statusEl) {
              this.statusEl.textContent = `QR locked: ${anchor.id}`;
            }
            this.opts.toast(`AR relocalized at ${anchor.id}`);
            break;
          }
        }
      } catch {
        /* ignore transient detector errors */
      }
    }, 450);
  }

  update(): void {
    if (!this.active) return;
    const target = this.opts.getTarget();
    if (!target) {
      if (this.targetEl) {
        this.targetEl.textContent = 'Select a POI and click Navigate to see AR turn guidance';
      }
      if (this.arrow) this.arrow.style.transform = 'rotate(0deg)';
      return;
    }
    const { position, yaw } = this.opts.getPose();
    const g = arGuidance([position[0], position[1]], yaw, [target.x, target.y], {
      lookahead: this.opts.getLookahead?.() ?? null,
      routeRemainingM: this.opts.getRemainingM?.() ?? null,
    });
    if (this.arrow) {
      // CSS rotate is clockwise; positive turnRad is left (counter-clockwise).
      this.arrow.style.transform = `rotate(${-g.turnDeg}deg)`;
    }
    if (this.targetEl) {
      this.targetEl.textContent = `${target.name} · ${formatDistance(g.distanceM)} · ${g.label}`;
    }
  }
}
