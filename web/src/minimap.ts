/**
 * Minimap: floor outline, occupancy tint, trajectory, and the walker arrow.
 * North-up in world axes (nav x right, nav y down), fixed fit with padding.
 */

import { FREE, OBSTACLE, type NavData } from './artifacts';

const COLOR_UNKNOWN = [38, 43, 49, 255] as const;
const COLOR_FREE = [56, 66, 78, 255] as const;
const COLOR_OBSTACLE = [214, 69, 69, 255] as const;

export class Minimap {
  private ctx: CanvasRenderingContext2D;
  private nav: NavData;
  private base: HTMLCanvasElement;
  private k = 1;
  private minX = 0;
  private minY = 0;

  constructor(canvas: HTMLCanvasElement, nav: NavData, grid: { w: number; h: number; data: Uint8Array }) {
    const dpr = Math.min(window.devicePixelRatio, 2);
    canvas.width = 240 * dpr;
    canvas.height = 240 * dpr;
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
    this.k = Math.min((240 - 2 * pad) / Math.max(spanX, 0.5), (240 - 2 * pad) / Math.max(spanY, 0.5));
    // center the fit
    this.minX -= ((240 / this.k) - spanX) / 2;
    this.minY -= ((240 / this.k) - spanY) / 2;

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

  draw(pos: [number, number, number], headingRad: number): void {
    const { ctx, nav } = this;
    ctx.clearRect(0, 0, 240, 240);

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
      ctx.strokeStyle = 'rgba(127, 212, 255, 0.85)';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    if (nav.trajectory.length >= 2) {
      ctx.beginPath();
      const [x0, y0] = nav.trajectory[0];
      ctx.moveTo(this.mx(x0), this.my(y0));
      for (const [x, y] of nav.trajectory.slice(1)) ctx.lineTo(this.mx(x), this.my(y));
      ctx.strokeStyle = 'rgba(127, 212, 255, 0.35)';
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // walker arrow
    const px = this.mx(pos[0]);
    const py = this.my(pos[1]);
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate(headingRad);
    ctx.beginPath();
    ctx.moveTo(7, 0);
    ctx.lineTo(-5, 4.6);
    ctx.lineTo(-2.5, 0);
    ctx.lineTo(-5, -4.6);
    ctx.closePath();
    ctx.fillStyle = '#7fd4ff';
    ctx.fill();
    ctx.restore();
  }
}
