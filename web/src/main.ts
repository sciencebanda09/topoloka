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
import { Sandbox } from './sandbox';
import { SplatLayer } from './splat';
import { Viewer } from './viewer';

const params = new URLSearchParams(location.search);
const CAPTURE = params.get('capture') ?? 'metro_v1';
const BASE = `${import.meta.env.BASE_URL}artifacts/${CAPTURE}`;
// Render close to CSS resolution (1.9 MP) instead of upscaling a 0.75 MP
// buffer: at 1080p the old budget drew 0.60x and stretched it 1.66x, which
// reads as "blurry" on every display. Adaptive quality may still drop, but
// never below 0.6x. ?scale=1 pins full resolution; ?scale=0.5 is the escape
// hatch for a very slow machine.
const RENDER_PIXELS = 1_900_000;
const MIN_ADAPTIVE_SCALE = 0.6;
const requestedScale = Number(params.get('scale'));
const MANUAL_SCALE = Number.isFinite(requestedScale) && requestedScale > 0;
const INITIAL_SCALE = MANUAL_SCALE
  ? Math.min(1, Math.max(0.35, requestedScale))
  : Math.min(1, Math.max(0.5, Math.sqrt(RENDER_PIXELS / (window.innerWidth * window.innerHeight))));
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

  // Routing is shared by ?route and the sandbox's "Route to end" button.
  // A placed prop changes the dynamic costmap, so refresh from the current
  // player position rather than the original spawn.
  const routeBtn = document.getElementById('sandbox-route') as HTMLButtonElement | null;
  const legendRoute = document.getElementById('legend-route');
  const legendProp = document.getElementById('legend-prop');
  const routeEnd: [number, number] | null = nav.trajectory.length > 2
    ? [nav.trajectory[nav.trajectory.length - 1][0], nav.trajectory[nav.trajectory.length - 1][1]]
    : null;
  let routeGoal: [number, number] | null = null;
  let routeLabel = '';

  function clearRoute(): void {
    viewer.setRoute([]);
    minimap.setRoute(null);
    routeLabel = '';
    if (legendRoute) legendRoute.style.display = 'none';
    if (routeBtn) {
      routeBtn.textContent = 'Route to end';
      routeBtn.classList.remove('active');
    }
  }

  function refreshRoute(): void {
    if (!routeGoal) {
      clearRoute();
      return;
    }
    const path = costmap.findPath([controls.position[0], controls.position[1]], routeGoal);
    if (!path || path.length < 2) {
      viewer.setRoute([]);
      minimap.setRoute(null);
      routeLabel = 'route: no path';
      if (legendRoute) legendRoute.style.display = 'none';
      if (routeBtn) {
        routeBtn.textContent = 'Clear route';
        routeBtn.classList.add('active');
      }
      return;
    }
    viewer.setRoute(path);
    minimap.setRoute(path);
    let meters = 0;
    for (let i = 1; i < path.length; i++) {
      meters += Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]);
    }
    routeLabel = `route ${path.length} wp · ${meters.toFixed(1)} m`;
    if (legendRoute) legendRoute.style.display = 'inline-flex';
    if (routeBtn) {
      routeBtn.textContent = 'Clear route';
      routeBtn.classList.add('active');
    }
  }

  function setRouteGoal(goal: [number, number] | null): void {
    routeGoal = goal;
    refreshRoute();
  }

  const sandbox = new Sandbox({
    scene: viewer.scene,
    camera: viewer.camera,
    canvas,
    costmap,
    nav,
    splat,
    capture: CAPTURE,
    getPlayer: () => controls.position,
    onChange: () => {
      minimap.setProps(sandbox.transforms());
      if (legendProp) legendProp.style.display = sandbox.isEnabled ? 'inline-flex' : 'none';
      refreshRoute();
    },
  });

  routeBtn?.addEventListener('click', () => {
    if (routeGoal) setRouteGoal(null);
    else if (routeEnd) setRouteGoal(routeEnd);
  });
  if (params.has('route') && routeEnd) setRouteGoal(routeEnd);
  if (sandbox.autoEnable) sandbox.setEnabled(true);

  document.addEventListener('pointerlockchange', () => {
    const locked = document.pointerLockElement === canvas;
    hint.classList.toggle('hidden', locked);
  });
  window.addEventListener('keydown', (e) => {
    if (e.code === 'KeyP') viewer.setPointsVisible(!viewer.pointsVisible);
    if (e.code === 'KeyM') mapWrap.classList.toggle('hidden');
    if (e.code === 'KeyT' && sandbox.isEnabled) {
      if (routeGoal) setRouteGoal(null);
      else if (routeEnd) setRouteGoal(routeEnd);
    }
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
    if (sandbox.isEnabled) parts.push(`sandbox ${sandbox.propCount}`);
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
    sandbox.update(dt);
    if (splat?.loaded) {
      splat.update();
      splat.render();
    } else {
      viewer.render();
    }
    minimap.draw(controls.position, controls.heading);

    // Dynamic resolution: the splat is fill-rate bound. Only step down when we
    // are clearly below 24 fps (a 30 Hz panel must not trigger it), and stop at
    // 0.6x so the twin never turns into an upscaled blur. A manual ?scale wins.
    if (!MANUAL_SCALE && splat?.loaded) {
      adaptTimer += rawDt;
      if (adaptTimer > 1.0) {
        if (fps < 24 && renderScale > MIN_ADAPTIVE_SCALE) {
          renderScale = Math.max(MIN_ADAPTIVE_SCALE, renderScale - 0.08);
          viewer.setRenderScale(renderScale);
        } else if (fps > 50 && renderScale < INITIAL_SCALE) {
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
