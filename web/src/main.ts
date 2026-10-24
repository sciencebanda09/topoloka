/// <reference types="vite/client" />
/**
 * Topoloka viewer entry point.
 * Loads the artifact bundle (nav.json + cloud.ply + optional splat.splat),
 * builds the scene, spawns the walker on the capture's first trajectory point,
 * and runs the loop. The splat, when present, renders in our scene/camera;
 * the costmap drives collision, the minimap mirrors both.
 */

import { decodeGrid, loadCloud, loadNav, type NavData } from './artifacts';
import { PRODUCT_NAME, PRODUCT_TAGLINE } from './brand';
import { WalkControls } from './controls';
import { Minimap } from './minimap';
import { Costmap } from './nav';
import { SplatLayer } from './splat';
import { Viewer } from './viewer';

const params = new URLSearchParams(location.search);
const CAPTURE = params.get('capture') ?? 'metro_v1';
const BASE = `${import.meta.env.BASE_URL}artifacts/${CAPTURE}`;
// Keep the internal splat buffer near 0.75 MP: integrated laptop GPUs are
// fill-rate bound, and upscaling a soft splat is far cheaper than rendering
// 3x the pixels. ?scale=0.5 can override this for a very slow machine.
const RENDER_PIXELS = 750_000;
const requestedScale = Number(params.get('scale'));
const MANUAL_SCALE = Number.isFinite(requestedScale) && requestedScale > 0;
const INITIAL_SCALE = MANUAL_SCALE
  ? Math.min(1, Math.max(0.35, requestedScale))
  : Math.min(1, Math.max(0.35, Math.sqrt(RENDER_PIXELS / (window.innerWidth * window.innerHeight))));
const SPLAT_ALPHA = Math.min(255, Math.max(1, Number(params.get('alpha')) || 40));
const SPLAT_MAX_PX = Math.min(2048, Math.max(32, Number(params.get('splatpx')) || 512));

const titleEl = document.getElementById('title');
if (titleEl) titleEl.textContent = PRODUCT_NAME.toUpperCase();
document.title = `${PRODUCT_NAME} — indoor twins in a link`;

const subtitle = document.getElementById('subtitle') as HTMLDivElement;
const hint = document.getElementById('center-hint') as HTMLDivElement;
const canvas = document.getElementById('view') as HTMLCanvasElement;
const minimapCanvas = document.getElementById('minimap') as HTMLCanvasElement;
const mapWrap = document.getElementById('map-wrap') as HTMLDivElement;
const help = document.getElementById('help') as HTMLDivElement;

// ?clean hides the click-to-enter prompt and the fps readout
// (stills, README, demo recording); the fps counter is meaningless off-vsync
const CLEAN = params.has('clean');
if (CLEAN) hint.classList.add('hidden');

const TOUCH = window.matchMedia('(pointer: coarse)').matches || navigator.maxTouchPoints > 0;
if (TOUCH) {
  hint.textContent = 'drag to look · left thumb to walk';
  help.innerHTML = '<b>drag</b> look · <b>left thumb</b> walk · rotate for the full view';
  canvas.addEventListener('touchstart', () => hint.classList.add('hidden'), { passive: true, once: true });
}

interface Meta {
  capture?: string;
  cloud_points?: number;
  walkable_area_m2?: number;
  qa_overall?: string;
  splat?: { present: boolean; gaussians?: number };
}

async function loadMeta(): Promise<Meta> {
  try {
    const res = await fetch(`${BASE}/meta.json`);
    if (res.ok) return (await res.json()) as Meta;
  } catch {
    /* meta is optional */
  }
  return {};
}

async function boot(): Promise<void> {
  subtitle.textContent = `${PRODUCT_NAME} · ${PRODUCT_TAGLINE} · fetching ${CAPTURE}…`;
  const [nav, meta] = await Promise.all([loadNav(BASE), loadMeta()]);
  const grid = await decodeGrid(nav.grid);
  const costmap = new Costmap(nav, grid);

  const viewer = new Viewer(canvas, INITIAL_SCALE);
  viewer.setNavCamera(nav);
  viewer.addGroundGrid(40);
  viewer.addOutline(nav.outline);
  viewer.addTrajectory(nav.trajectory);

  const cloud = await loadCloud(BASE);
  const nPoints = cloud ? viewer.addPointCloud(cloud.positions, cloud.colors) : 0;

  // splat, when the pipeline has produced one: render in our scene/camera
  let splat: SplatLayer | null = null;
  if (meta.splat?.present) {
    try {
      subtitle.textContent = `${CAPTURE} · loading splat…`;
      splat = new SplatLayer(viewer.renderer, viewer.scene, viewer.camera, {
        alphaThreshold: SPLAT_ALPHA,
        maxScreenSpaceSplatSize: SPLAT_MAX_PX,
      });
      await splat.load(`${BASE}/splat.splat`, nav);
      viewer.setPointsVisible(false); // splat carries the visuals; P re-shows points
      viewer.setTrajectoryVisible(false); // minimap keeps the path; the 3D wire is clutter
      viewer.setDebugVisible(false); // grid/outline show through holes as black seams
    } catch (err) {
      console.warn('splat load failed, falling back to points:', err);
      splat = null;
    }
  }

  const spawnParam = new URLSearchParams(location.search).get('t');
  const spawn = viewer.spawnAt(nav, spawnParam ? Number(spawnParam) : undefined);
  const controls = new WalkControls(canvas, viewer.camera, costmap, spawn);
  const minimap = new Minimap(minimapCanvas, nav,
    { w: costmap.w, h: costmap.h, data: costmap.data });

  // dev: ?route draws an A* path from spawn to the capture's final trajectory point
  let routeLabel = '';
  if (params.has('route') && nav.trajectory.length > 2) {
    const last = nav.trajectory[nav.trajectory.length - 1];
    const path = costmap.findPath([spawn.position[0], spawn.position[1]], [last[0], last[1]]);
    if (path) {
      viewer.setRoute(path);
      minimap.setRoute(path);
      let meters = 0;
      for (let i = 1; i < path.length; i++) {
        meters += Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]);
      }
      routeLabel = `route ${path.length} wp · ${meters.toFixed(1)} m`;
      const legend = document.getElementById('legend-route');
      if (legend) legend.style.display = 'inline-flex';
    } else {
      routeLabel = 'route: no path found';
    }
  }

  document.addEventListener('pointerlockchange', () => {
    const locked = document.pointerLockElement === canvas;
    hint.classList.toggle('hidden', locked);
  });
  window.addEventListener('keydown', (e) => {
    if (e.code === 'KeyP') viewer.setPointsVisible(!viewer.pointsVisible);
    if (e.code === 'KeyM') mapWrap.classList.toggle('hidden');
  });

  let last = performance.now();
  let fps = 0;
  let statTimer = 0;
  let adaptTimer = -3; // let the first frames/sorting settle before judging
  let renderScale = INITIAL_SCALE;
  const free = grid.data.reduce((s, v) => s + (v === 0 ? 1 : 0), 0);
  const walkable = meta.walkable_area_m2 ?? (free * nav.cell_m * nav.cell_m);

  function statLine(): string {
    const parts = [`${CAPTURE}`];
    if (splat?.loaded) {
      parts.push(meta.splat?.gaussians ? `splat ${(meta.splat.gaussians / 1e6).toFixed(2)}M` : 'splat');
    } else if (nPoints) {
      parts.push(`${nPoints.toLocaleString()} pts${viewer.pointsVisible ? '' : ' (hidden)'}`);
    }
    parts.push(`${walkable} m² walkable`);
    if (routeLabel) parts.push(routeLabel);
    if (!CLEAN) parts.push(`${fps.toFixed(0)} fps`);
    if (meta.qa_overall) parts.push(`QA ${meta.qa_overall}`);
    return parts.join(' · ');
  }

  function loop(now: number): void {
    const rawDt = Math.max((now - last) / 1000, 1e-4);
    const dt = Math.min(rawDt, 0.05);
    last = now;
    // Report the true frame rate; clamp only the simulation step. (Clamping
    // dt before 1/dt puts a fake 20 fps floor on the HUD.)
    fps = fps ? fps * 0.92 + Math.min(240, 1 / rawDt) * 0.08 : 60;

    controls.update(dt);
    if (splat?.loaded) {
      splat.update();
      splat.render();
    } else {
      viewer.render();
    }
    minimap.draw(controls.position, controls.heading);

    // Dynamic resolution: the splat is fill-rate bound. Keep the walk near
    // 30 fps on integrated laptop GPUs by dropping the internal buffer in
    // steps, then recover when the view gets cheaper. A manual ?scale wins.
    if (!MANUAL_SCALE && splat?.loaded) {
      adaptTimer += rawDt;
      if (adaptTimer > 1.0) {
        if (fps < 32 && renderScale > 0.4) {
          renderScale = Math.max(0.4, renderScale - 0.08);
          viewer.setRenderScale(renderScale);
        } else if (fps > 52 && renderScale < INITIAL_SCALE) {
          renderScale = Math.min(INITIAL_SCALE, renderScale + 0.05);
          viewer.setRenderScale(renderScale);
        }
        adaptTimer = 0;
      }
    }

    statTimer += dt;
    if (statTimer > 0.5) {
      statTimer = 0;
      subtitle.textContent = statLine();
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
}

boot().catch((err) => {
  console.error(err);
  subtitle.textContent = `${CAPTURE} · failed to load: ${err.message}`;
});
