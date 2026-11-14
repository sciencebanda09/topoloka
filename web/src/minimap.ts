/**
 * Minimap: floor outline, occupancy tint, trajectory, route, POIs, props and
 * the walker arrow. North-up in world axes (nav x right, nav y down), fixed fit.
 * Clicking a POI dot selects it (the main app wires the callback).
 */

import { FREE, OBSTACLE, type NavData } from './artifacts';
import type { Poi } from './pois';
import type { PropTransform } from './props';

const COLOR_UNKNOWN = [20, 25, 31, 255] as const;
const COLOR_FREE = [66, 79, 94, 255] as const;
// Muted brick, not alarm red: obstacles ring a narrow walked corridor, so a
// saturated fill makes the whole map read as "blocked".
const COLOR_OBSTACLE = [118, 52, 58, 255] as const;
const LOGICAL_SIZE = 240;

const MINIMAP_POI_COLORS: Record<string, string> = {
  landmark: '#7fd4ff',
  facility: '#c39bff',
  exit: '#40ff9a',
  platform: '#ffb347',
  area: '#7fd4ff',
  retail: '#ff8fc7',
  other: '#9fb0c0',
};

function drawPill(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

export class Minimap {
  private ctx: CanvasRenderingContext2D;
  private nav: NavData;
  private base: HTMLCanvasElement;
  private k = 1;
  private minX = 0;
  private minY = 0;
  private route: [number, number][] = [];
  private props: PropTransform[] = [];
  private pois: Poi[] = [];
  private selectedPoi: string | null = null;
  private target: [number, number] | null = null;

  constructor(canvas: HTMLCanvasElement, nav: NavData, grid: { w: number; h: number; data: Uint8Array }) {
    const dpr = Math.min(window.devicePixelRatio, 2);
    canvas.width = LOGICAL_SIZE * dpr;
    canvas.height = LOGICAL_SIZE * dpr;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('no 2d context for minimap');
    this.ctx = ctx;
    this.ctx.scale(dpr, dpr);
    this.nav = nav;

    // world bounds: outline if present, else grid extent
    const pts = nav.outline.length >= 3
      ? nav.outline
      : [[nav.origin[0], nav.origin[1]],
         [nav.origin[0] + grid.w * nav.cell_m, nav.origin[1] + grid.h * nav.cell_m]];
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    this.minX = Math.min(...xs);
    this.minY = Math.min(...ys);
    const spanX = Math.max(...xs) - this.minX;
    const spanY = Math.max(...ys) - this.minY;
    const pad = 14;
    this.k = Math.min((LOGICAL_SIZE - 2 * pad) / Math.max(spanX, 0.5), (LOGICAL_SIZE - 2 * pad) / Math.max(spanY, 0.5));
    // center the fit
    this.minX -= ((LOGICAL_SIZE / this.k) - spanX) / 2;
    this.minY -= ((LOGICAL_SIZE / this.k) - spanY) / 2;

    // pre-render occupancy at grid resolution
    this.base = document.createElement('canvas');
    this.base.width = grid.w;
    this.base.height = grid.h;
    const bctx = this.base.getContext('2d')!;
    const img = bctx.createImageData(grid.w, grid.h);
    for (let i = 0; i < grid.data.length; i++) {
      const v = grid.data[i];
      const c = v === OBSTACLE ? COLOR_OBSTACLE : v === FREE ? COLOR_FREE : COLOR_UNKNOWN;
      img.data[i * 4] = c[0];
      img.data[i * 4 + 1] = c[1];
      img.data[i * 4 + 2] = c[2];
      img.data[i * 4 + 3] = c[3];
    }
    bctx.putImageData(img, 0, 0);
  }

  private mx(x: number): number { return (x - this.minX) * this.k; }
  private my(y: number): number { return (y - this.minY) * this.k; }

  setRoute(route: [number, number][] | null): void {
    this.route = route ?? [];
  }

  setProps(props: PropTransform[]): void {
    this.props = props;
  }

  setPois(pois: Poi[], selected: string | null = null): void {
    this.pois = pois;
    this.selectedPoi = selected;
  }

  setSelectedPoi(id: string | null): void {
    this.selectedPoi = id;
  }

  setTarget(target: [number, number] | null): void {
    this.target = target;
  }

  /** Canvas client pixel -> nav world. Used by POI dot clicks. */
  worldAt(clientX: number, clientY: number): [number, number] {
    const canvas = this.ctx.canvas;
    const rect = canvas.getBoundingClientRect();
    const x = (clientX - rect.left) * (LOGICAL_SIZE / rect.width);
    const y = (clientY - rect.top) * (LOGICAL_SIZE / rect.height);
    return [this.minX + x / this.k, this.minY + y / this.k];
  }

  /** Nearest POI within `maxPx` logical pixels of a click. */
  poiAt(clientX: number, clientY: number, maxPx = 12): Poi | null {
    const canvas = this.ctx.canvas;
    const rect = canvas.getBoundingClientRect();
    const x = (clientX - rect.left) * (LOGICAL_SIZE / rect.width);
    const y = (clientY - rect.top) * (LOGICAL_SIZE / rect.height);
    let best: { poi: Poi; d: number } | null = null;
    for (const poi of this.pois) {
      const d = Math.hypot(this.mx(poi.x) - x, this.my(poi.y) - y);
      if (d <= maxPx && (!best || d < best.d)) best = { poi, d };
    }
    return best?.poi ?? null;
  }

  draw(pos: [number, number, number], headingRad: number): void {
    const { ctx, nav } = this;
    ctx.clearRect(0, 0, LOGICAL_SIZE, LOGICAL_SIZE);

    const [ox, oy] = nav.origin;
    ctx.imageSmoothingEnabled = false;
    ctx.globalAlpha = 0.9;
    ctx.drawImage(
      this.base,
      this.mx(ox), this.my(oy),
      this.base.width * nav.cell_m * this.k, this.base.height * nav.cell_m * this.k,
    );
    ctx.globalAlpha = 1;

    if (nav.outline.length >= 3) {
      ctx.beginPath();
      ctx.moveTo(this.mx(nav.outline[0][0]), this.my(nav.outline[0][1]));
      for (const [x, y] of nav.outline.slice(1)) ctx.lineTo(this.mx(x), this.my(y));
      ctx.closePath();
      ctx.strokeStyle = 'rgba(127, 212, 255, 0.55)';
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }

    if (nav.trajectory.length >= 2) {
      ctx.beginPath();
      const [x0, y0] = nav.trajectory[0];
      ctx.moveTo(this.mx(x0), this.my(y0));
      for (const [x, y] of nav.trajectory.slice(1)) ctx.lineTo(this.mx(x), this.my(y));
      ctx.strokeStyle = 'rgba(127, 212, 255, 0.95)';
      ctx.lineWidth = 1.8;
      ctx.stroke();
    }

    if (this.route.length >= 2) {
      ctx.save();
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(this.mx(this.route[0][0]), this.my(this.route[0][1]));
      for (const [x, y] of this.route.slice(1)) ctx.lineTo(this.mx(x), this.my(y));
      // Soft emerald outer glow + crisp directional core line
      ctx.strokeStyle = 'rgba(64, 255, 154, 0.25)';
      ctx.lineWidth = 6.5;
      ctx.stroke();
      ctx.strokeStyle = '#40ff9a';
      ctx.lineWidth = 2.4;
      ctx.stroke();
      ctx.restore();
    }

    if (this.target) {
      const tx = this.mx(this.target[0]);
      const ty = this.my(this.target[1]);
      ctx.beginPath();
      ctx.arc(tx, ty, 8.5, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(64, 255, 154, 0.16)';
      ctx.fill();
      ctx.beginPath();
      ctx.arc(tx, ty, 5.5, 0, Math.PI * 2);
      ctx.strokeStyle = '#40ff9a';
      ctx.lineWidth = 1.6;
      ctx.stroke();
    }

    // placed sandbox props
    for (const p of this.props) {
      const x = this.mx(p.x), y = this.my(p.y);
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(p.rot);
      ctx.fillStyle = '#ffb347';
      if (p.type === 'barrier') {
        ctx.fillRect(-5, -1.6, 10, 3.2);
      } else {
        ctx.beginPath();
        ctx.arc(0, 0, 3, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    // POI dots
    for (const poi of this.pois) {
      const x = this.mx(poi.x), y = this.my(poi.y);
      const selected = poi.id === this.selectedPoi;
      const dotColor = MINIMAP_POI_COLORS[poi.category] ?? MINIMAP_POI_COLORS.other;
      if (selected) {
        ctx.beginPath();
        ctx.arc(x, y, 7.5, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
        ctx.lineWidth = 1.4;
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(x, y, selected ? 4.2 : 3.0, 0, Math.PI * 2);
      ctx.fillStyle = selected ? '#ffffff' : dotColor;
      ctx.fill();
      ctx.strokeStyle = 'rgba(7, 12, 16, 0.92)';
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    const selectedPoi = this.pois.find((p) => p.id === this.selectedPoi);
    if (selectedPoi) {
      const x = this.mx(selectedPoi.x), y = this.my(selectedPoi.y);
      const label = selectedPoi.name.length > 20 ? `${selectedPoi.name.slice(0, 19)}…` : selectedPoi.name;
      const dotColor = MINIMAP_POI_COLORS[selectedPoi.category] ?? MINIMAP_POI_COLORS.other;
      ctx.font = "600 9.5px 'Inter', 'Segoe UI', system-ui, sans-serif";
      const w = ctx.measureText(label).width + 18;
      const lx = Math.min(LOGICAL_SIZE - w - 3, Math.max(3, x - w / 2));
      const ly = y < 22 ? y + 10 : y - 21;
      ctx.save();
      ctx.shadowColor = 'rgba(0, 0, 0, 0.55)';
      ctx.shadowBlur = 6;
      drawPill(ctx, lx, ly, w, 15, 7.5);
      ctx.fillStyle = 'rgba(8, 13, 19, 0.92)';
      ctx.fill();
      ctx.restore();
      drawPill(ctx, lx, ly, w, 15, 7.5);
      ctx.strokeStyle = 'rgba(127, 212, 255, 0.52)';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(lx + 7, ly + 7.5, 2.4, 0, Math.PI * 2);
      ctx.fillStyle = dotColor;
      ctx.fill();
      ctx.fillStyle = '#eef6ff';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, lx + 12.5, ly + 8);
    }

    // walker FOV cone + dark-rimmed arrow
    const px = this.mx(pos[0]);
    const py = this.my(pos[1]);
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate(headingRad);

    const coneRadius = 30;
    const coneHalfAngle = 0.58; // ~33 deg half-FOV matching 66 deg viewport
    const fovGrad = ctx.createRadialGradient(0, 0, 2, 0, 0, coneRadius);
    fovGrad.addColorStop(0, 'rgba(127, 212, 255, 0.28)');
    fovGrad.addColorStop(1, 'rgba(127, 212, 255, 0.0)');
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.arc(0, 0, coneRadius, -coneHalfAngle, coneHalfAngle);
    ctx.closePath();
    ctx.fillStyle = fovGrad;
    ctx.fill();

    ctx.beginPath();
    ctx.moveTo(7.5, 0);
    ctx.lineTo(-5.2, 4.8);
    ctx.lineTo(-2.6, 0);
    ctx.lineTo(-5.2, -4.8);
    ctx.closePath();
    ctx.fillStyle = '#7fd4ff';
    ctx.fill();
    ctx.strokeStyle = 'rgba(7, 12, 18, 0.9)';
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.restore();

    // Subtle North indicator pill
    ctx.save();
    ctx.font = '700 8.5px ui-monospace, monospace';
    ctx.fillStyle = 'rgba(159, 176, 192, 0.68)';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('N ↑', 7, 6);
    ctx.restore();
  }
}
