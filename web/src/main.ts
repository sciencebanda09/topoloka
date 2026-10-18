/// <reference types="vite/client" />
/**
 * Namma Space viewer entry point.
 * Loads the artifact bundle (nav.json + cloud.ply + optional splat.splat),
 * builds the scene, spawns the walker on the capture's first trajectory point,
 * and runs the loop. The splat, when present, renders in our scene/camera;
 * the costmap drives collision, the minimap mirrors both.
 */

import { decodeGrid, loadCloud, loadNav, type NavData } from './artifacts';
import { WalkControls } from './controls';
import { Minimap } from './minimap';
import { Costmap } from './nav';
import { SplatLayer } from './splat';
import { Viewer } from './viewer';

const CAPTURE = new URLSearchParams(location.search).get('capture') ?? 'house_v1';
const BASE = `${import.meta.env.BASE_URL}artifacts/${CAPTURE}`;

const subtitle = document.getElementById('subtitle') as HTMLDivElement;
const hint = document.getElementById('center-hint') as HTMLDivElement;
const canvas = document.getElementById('view') as HTMLCanvasElement;
const minimapCanvas = document.getElementById('minimap') as HTMLCanvasElement;

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
  subtitle.textContent = `${CAPTURE} · fetching artifacts…`;
  const [nav, meta] = await Promise.all([loadNav(BASE), loadMeta()]);
  const grid = await decodeGrid(nav.grid);
  const costmap = new Costmap(nav, grid);

  const viewer = new Viewer(canvas);
  viewer.addGroundGrid(40);
  viewer.addOutline(nav.outline);
  viewer.addTrajectory(nav.trajectory);

  const cloud = await loadCloud(BASE);
  const nPoints = cloud ? viewer.addPointCloud(cloud.positions, cloud.colors) : 0;

  // splat, when the pipeline has produced one: render in our scene/camera
  let splat: SplatLayer | null = null;
  try {
    const head = await fetch(`${BASE}/splat.splat`, { method: 'HEAD' });
    if (head.ok && head.headers.get('content-length') !== '0') {
      subtitle.textContent = `${CAPTURE} · loading splat…`;
      splat = new SplatLayer(viewer.renderer, viewer.scene, viewer.camera);
      await splat.load(`${BASE}/splat.splat`, nav);
      viewer.setPointsVisible(false); // splat carries the visuals; P re-shows points
    }
  } catch (err) {
    console.warn('splat load failed, falling back to points:', err);
    splat = null;
  }

  const spawn = viewer.spawnAt(nav);
  const controls = new WalkControls(canvas, viewer.camera, costmap, spawn);
  const minimap = new Minimap(minimapCanvas, nav, grid);

  // dev: ?route draws an A* path from spawn to the capture's final trajectory point
  if (new URLSearchParams(location.search).has('route') && nav.trajectory.length > 2) {
    const last = nav.trajectory[nav.trajectory.length - 1];
    const path = costmap.findPath([spawn.position[0], spawn.position[1]], [last[0], last[1]]);
    if (path) {
      viewer.setRoute(path);
      minimap.setRoute(path);
      let meters = 0;
      for (let i = 1; i < path.length; i++) {
        meters += Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]);
      }
      subtitle.textContent = `${CAPTURE} · route ${path.length} wp · ${meters.toFixed(1)} m`;
    } else {
      subtitle.textContent = `${CAPTURE} · route: no path found`;
    }
  }

  document.addEventListener('pointerlockchange', () => {
    const locked = document.pointerLockElement === canvas;
    hint.classList.toggle('hidden', locked);
  });
  window.addEventListener('keydown', (e) => {
    if (e.code === 'KeyP') viewer.setPointsVisible(!viewer.pointsVisible);
  });

  let last = performance.now();
  let fps = 0;
  let statTimer = 0;
  const free = grid.data.reduce((s, v) => s + (v === 0 ? 1 : 0), 0);
  const walkable = meta.walkable_area_m2 ?? (free * nav.cell_m * nav.cell_m);

  function statLine(): string {
    const parts = [`${CAPTURE}`];
    if (splat?.loaded) {
      parts.push(meta.splat?.gaussians ? `splat ${(meta.splat.gaussians / 1e6).toFixed(2)}M` : 'splat');
    } else if (nPoints) {
      parts.push(`${nPoints.toLocaleString()} pts${viewer.pointsVisible ? '' : ' (hidden)'}`);
    }
    parts.push(`${walkable} m² walkable`, `${fps.toFixed(0)} fps`);
    if (meta.qa_overall) parts.push(`QA ${meta.qa_overall}`);
    return parts.join(' · ');
  }

  function loop(now: number): void {
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    fps = fps ? fps * 0.92 + (1 / Math.max(dt, 1e-4)) * 0.08 : 1 / Math.max(dt, 1e-4);

    controls.update(dt);
    if (splat?.loaded) {
      splat.update();
      splat.render();
    } else {
      viewer.render();
    }
    minimap.draw(controls.position, controls.heading);

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
