/// <reference types="vite/client" />
/**
 * Namma Space viewer entry point.
 * Loads the artifact bundle (nav.json + cloud.ply), builds the scene,
 * spawns the walker on the capture's first trajectory point, and runs the loop.
 */

import { decodeGrid, loadCloud, loadNav } from './artifacts';
import { WalkControls } from './controls';
import { Minimap } from './minimap';
import { Costmap } from './nav';
import { Viewer } from './viewer';

const CAPTURE = new URLSearchParams(location.search).get('capture') ?? 'house_v1';
const BASE = `${import.meta.env.BASE_URL}artifacts/${CAPTURE}`;

const subtitle = document.getElementById('subtitle') as HTMLDivElement;
const hint = document.getElementById('center-hint') as HTMLDivElement;
const canvas = document.getElementById('view') as HTMLCanvasElement;
const minimapCanvas = document.getElementById('minimap') as HTMLCanvasElement;

async function boot(): Promise<void> {
  subtitle.textContent = `${CAPTURE} · fetching artifacts…`;
  const nav = await loadNav(BASE);
  const grid = await decodeGrid(nav.grid);
  const costmap = new Costmap(nav, grid);

  const viewer = new Viewer(canvas);
  viewer.addGroundGrid(40);
  viewer.addOutline(nav.outline);
  viewer.addTrajectory(nav.trajectory);

  const cloud = await loadCloud(BASE);
  const nPoints = cloud ? viewer.addPointCloud(cloud.positions, cloud.colors) : 0;

  const spawn = viewer.spawnAt(nav);
  const controls = new WalkControls(canvas, viewer.camera, costmap, spawn);
  const minimap = new Minimap(minimapCanvas, nav, grid);

  // dev: ?route draws an A* path from spawn to the capture's final trajectory point
  if (new URLSearchParams(location.search).has('route') && nav.trajectory.length > 2) {
    const last = nav.trajectory[nav.trajectory.length - 1];
    const path = costmap.findPath([spawn.position[0], spawn.position[1]], [last[0], last[1]]);
    if (path) {
      viewer.setRoute(path);
      subtitle.textContent = `${CAPTURE} · route ${path.length} waypoints`;
    } else {
      subtitle.textContent = `${CAPTURE} · route: no path found`;
    }
  }

  document.addEventListener('pointerlockchange', () => {
    const locked = document.pointerLockElement === canvas;
    hint.classList.toggle('hidden', locked);
  });

  let last = performance.now();
  let fps = 0;
  let statTimer = 0;
  const free = grid.data.reduce((s, v) => s + (v === 0 ? 1 : 0), 0);
  const walkable = (free * nav.cell_m * nav.cell_m).toFixed(1);

  function loop(now: number): void {
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    fps = fps ? fps * 0.92 + (1 / Math.max(dt, 1e-4)) * 0.08 : 1 / Math.max(dt, 1e-4);

    controls.update(dt);
    viewer.render();
    minimap.draw(controls.position, controls.heading);

    statTimer += dt;
    if (statTimer > 0.5) {
      statTimer = 0;
      subtitle.textContent =
        `${CAPTURE} · ${nPoints.toLocaleString()} pts · ${walkable} m² walkable · ${fps.toFixed(0)} fps`;
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
}

boot().catch((err) => {
  console.error(err);
  subtitle.textContent = `${CAPTURE} · failed to load: ${err.message}`;
});
