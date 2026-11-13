/// <reference types="vite/client" />
/**
 * Topoloka viewer entry point.
 * Loads the artifact bundle (nav.json + pois.json + cloud.ply + optional
 * mesh.glb/splat.splat), builds the scene, spawns the walker at the capture's
 * selected camera pose, and runs the loop. The costmap drives collision, the
 * minimap mirrors it, and R2 adds POI search, fly-to, and POI navigation.
 */

import { decodeGrid, loadCloud, loadNav, type NavData } from './artifacts';
import { PRODUCT_NAME, PRODUCT_TAGLINE } from './brand';
import { WalkControls } from './controls';
import { Minimap } from './minimap';
import { Costmap } from './nav';
import {
  formatDistance, planRoute, RouteTracker, WALK_SPEED_MPS,
  type RoutePlan,
} from './navigation';
import {
  isAtPoi, loadPois, mergePois, normalizePoiFile, type Poi, type PoiView,
} from './pois';
import { Sandbox } from './sandbox';
import { SplatLayer } from './splat';
import { PoiUi } from './ui';
import { Viewer } from './viewer';
import * as THREE from 'three';

const params = new URLSearchParams(location.search);
let curRx = Number(params.get('rx')) || 0;
let curRy = Number(params.get('ry')) || 0;
let curRz = Number(params.get('rz')) || 0;
let curOy = Number(params.get('oy')) || 0;
const DEFAULT_CAPTURE = 'metro_v1';
const AVAILABLE_CAPTURES = new Set(['metro_v1', 'room']);
const requestedCapture = params.get('capture');
const cleanCapture = requestedCapture && /^[a-zA-Z0-9_-]+$/.test(requestedCapture)
  ? requestedCapture
  : null;
const captureIsAvailable = cleanCapture
  && (AVAILABLE_CAPTURES.has(cleanCapture) || import.meta.env.DEV);
const CAPTURE = captureIsAvailable ? cleanCapture : DEFAULT_CAPTURE;
if (requestedCapture && CAPTURE !== requestedCapture) {
  const cleanUrl = new URL(location.href);
  cleanUrl.searchParams.delete('capture');
  history.replaceState(null, '', cleanUrl);
}
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
  : Math.min(1, Math.max(MIN_ADAPTIVE_SCALE, Math.sqrt(RENDER_PIXELS / (window.innerWidth * window.innerHeight))));
const SPLAT_ALPHA = Math.min(255, Math.max(1, Number(params.get('alpha')) || 5));
const SPLAT_MAX_PX = Math.min(2048, Math.max(32, Number(params.get('splatpx')) || 512));

const titleEl = document.getElementById('title');
if (titleEl) titleEl.textContent = PRODUCT_NAME.toUpperCase();
document.title = `${PRODUCT_NAME} — indoor twins in a link`;
const captureSelect = document.getElementById('capture-select') as HTMLSelectElement;
if (import.meta.env.DEV && ![...captureSelect.options].some((option) => option.value === CAPTURE)) {
  const linkedSample = document.createElement('option');
  linkedSample.value = CAPTURE;
  linkedSample.textContent = `${CAPTURE} (local sample)`;
  captureSelect.add(linkedSample, 0);
}
captureSelect.value = CAPTURE;
if (captureSelect.options.length < 2) {
  document.getElementById('scene-picker')?.classList.add('hidden');
}
captureSelect.addEventListener('change', () => {
  const nextUrl = new URL(location.href);
  nextUrl.searchParams.set('capture', captureSelect.value);
  for (const key of ['t', 'route', 'rx', 'ry', 'rz', 'oy', 'q', 'poi']) {
    nextUrl.searchParams.delete(key);
  }
  location.assign(nextUrl);
});

const toastEl = document.getElementById('toast') as HTMLDivElement | null;
let toastTimer = 0;
function showToast(message: string): void {
  if (!toastEl) return;
  toastEl.textContent = message;
  toastEl.classList.add('show');
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toastEl.classList.remove('show'), 2400);
}

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
  hint.textContent = 'drag to look · slide left thumb to move · tap the search bar to explore';
  help.innerHTML = '<b>drag</b> look · <b>left thumb</b> move · <b>search</b> points of interest · <b>tap a POI</b> to open it';
  canvas.addEventListener('touchstart', () => hint.classList.add('hidden'), { passive: true, once: true });
}

interface Meta {
  capture?: string;
  cloud_points?: number;
  walkable_area_m2?: number;
  qa_overall?: string;
  splat?: { present: boolean; gaussians?: number };
  mesh?: { present: boolean; format?: string };
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

const LOCAL_KEY = `topoloka.pois.v1.${CAPTURE}`;

function readLocalPois(): Poi[] {
  try {
    const raw = localStorage.getItem(LOCAL_KEY);
    if (!raw) return [];
    const doc = normalizePoiFile(JSON.parse(raw));
    return doc.pois.map((poi) => ({ ...poi, source: 'local' as const }));
  } catch {
    return [];
  }
}

function writeLocalPois(pois: Poi[]): void {
  try {
    localStorage.setItem(LOCAL_KEY, JSON.stringify({ version: 1, capture: CAPTURE, pois }));
  } catch {
    /* private mode / quota: editor is session-only */
  }
}

async function boot(): Promise<void> {
  subtitle.textContent = `${PRODUCT_NAME} · ${PRODUCT_TAGLINE} · fetching ${CAPTURE}…`;
  const [nav, meta, poiFile] = await Promise.all([loadNav(BASE), loadMeta(), loadPois(BASE)]);
  const grid = await decodeGrid(nav.grid);
  const costmap = new Costmap(nav, grid);
  let localPois = readLocalPois();
  const authoredPois = poiFile.pois;

  let hasMesh = Boolean(meta.mesh?.present);
  const hasSplat = Boolean(meta.splat?.present);
  const requestedModel = params.get('model');
  type Representation = 'mesh' | 'splat' | 'points';
  let representation: Representation = hasMesh ? 'mesh' : hasSplat ? 'splat' : 'points';
  if (requestedModel === 'mesh' && hasMesh) representation = 'mesh';
  else if (requestedModel === 'splat' && hasSplat) representation = 'splat';
  else if (requestedModel === 'points') representation = 'points';

  // The mesh and point cloud are cheap enough to draw at native CSS resolution;
  // only the splat starts at the lower GPU budget and adapts from there.
  let renderScale = MANUAL_SCALE ? INITIAL_SCALE : representation === 'splat' ? INITIAL_SCALE : 1;

  const viewer = new Viewer(canvas, renderScale);
  viewer.setNavCamera(nav);
  viewer.addGroundGrid(40);
  viewer.addOutline(nav.outline);
  viewer.addTrajectory(nav.trajectory);

  const spawnParam = params.get('t');
  const spawn = viewer.spawnAt(nav, spawnParam ? Number(spawnParam) : undefined);
  const pivot = new THREE.Vector3(spawn.position[0], spawn.position[2], -spawn.position[1]);

  function applyOrientation(saveUrl = true): void {
    splat?.setExtraTransform(curRx, curRy, curRz, curOy, pivot);
    viewer.setExtraTransform(curRx, curRy, curRz, curOy, pivot);
    const readout = document.getElementById('orient-readout');
    if (readout) {
      const oyStr = curOy >= 0 ? `+${curOy.toFixed(1)}m` : `${curOy.toFixed(1)}m`;
      readout.textContent = `rx: ${curRx}° · ry: ${curRy}° · rz: ${curRz}° · oy: ${oyStr}`;
    }
    if (saveUrl) {
      const url = new URL(location.href);
      if (curRx) url.searchParams.set('rx', curRx.toString()); else url.searchParams.delete('rx');
      if (curRy) url.searchParams.set('ry', curRy.toString()); else url.searchParams.delete('ry');
      if (curRz) url.searchParams.set('rz', curRz.toString()); else url.searchParams.delete('rz');
      if (curOy) url.searchParams.set('oy', curOy.toFixed(1)); else url.searchParams.delete('oy');
      history.replaceState(null, '', url);
    }
  }

  const cloud = await loadCloud(BASE);
  const nPoints = cloud ? viewer.addPointCloud(cloud.positions, cloud.colors) : 0;

  // splat, when the pipeline has produced one: render in our scene/camera
  let splat: SplatLayer | null = null;
  if (hasSplat && (requestedModel === 'splat' || (!hasMesh && requestedModel !== 'points'))) {
    try {
      subtitle.textContent = 'Loading splat...';
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

  const representationWrap = document.getElementById('representation-picker');
  const representationSelect = document.getElementById('representation-select') as HTMLSelectElement;
  const modelOptions = [...representationSelect.options];
  for (const option of modelOptions) {
    option.hidden = (option.value === 'mesh' && !hasMesh)
      || (option.value === 'splat' && !hasSplat)
      || (option.value === 'points' && !nPoints);
  }
  const availableModels = Number(hasMesh) + Number(hasSplat) + Number(Boolean(nPoints));
  if (representationWrap) representationWrap.classList.toggle('hidden', availableModels < 2);
  let meshLoaded = false;

  async function ensureSplat(): Promise<void> {
    if (splat?.loaded) return;
    if (!hasSplat) throw new Error('This sample has no Gaussian splat');
    subtitle.textContent = 'Loading splat...';
    const next = new SplatLayer(viewer.renderer, viewer.scene, viewer.camera, {
      alphaThreshold: SPLAT_ALPHA,
      maxScreenSpaceSplatSize: SPLAT_MAX_PX,
    });
    await next.load(`${BASE}/splat.splat`, nav);
    splat = next;
  }

  async function activateRepresentation(next: Representation): Promise<void> {
    if (next === 'mesh') {
      if (!hasMesh) throw new Error('This sample has no photo-textured mesh');
      if (!meshLoaded) {
        subtitle.textContent = 'Loading photo-textured mesh...';
        await viewer.addTexturedMesh(`${BASE}/mesh.glb`);
        meshLoaded = true;
      }
      viewer.setMeshVisible(true);
      splat?.setVisible(false);
      viewer.setPointsVisible(false);
      viewer.setTrajectoryVisible(false);
      viewer.setDebugVisible(false);
      renderScale = MANUAL_SCALE ? INITIAL_SCALE : 1;
      viewer.setRenderScale(renderScale);
      representation = 'mesh';
      applyOrientation(false);
    } else if (next === 'splat') {
      await ensureSplat();
      splat?.setVisible(true);
      viewer.setMeshVisible(false);
      viewer.setPointsVisible(false);
      viewer.setTrajectoryVisible(false);
      viewer.setDebugVisible(false);
      renderScale = INITIAL_SCALE;
      viewer.setRenderScale(renderScale);
      representation = 'splat';
      applyOrientation(false);
    } else {
      splat?.setVisible(false);
      viewer.setMeshVisible(false);
      viewer.setPointsVisible(true);
      viewer.setTrajectoryVisible(true);
      viewer.setDebugVisible(true);
      renderScale = MANUAL_SCALE ? INITIAL_SCALE : 1;
      viewer.setRenderScale(renderScale);
      representation = 'points';
      applyOrientation(false);
    }
    representationSelect.value = representation;
    const url = new URL(location.href);
    if (representation === (hasMesh ? 'mesh' : hasSplat ? 'splat' : 'points')) {
      url.searchParams.delete('model');
    } else {
      url.searchParams.set('model', representation);
    }
    history.replaceState(null, '', url);
  }

  try {
    await activateRepresentation(representation);
  } catch (err) {
    console.warn(`${representation} load failed; using a fallback:`, err);
    if (representation === 'mesh') {
      hasMesh = false;
      const meshOption = representationSelect.querySelector<HTMLOptionElement>('option[value="mesh"]');
      if (meshOption) meshOption.hidden = true;
      if (representationWrap) {
        representationWrap.classList.toggle('hidden', Number(hasMesh) + Number(hasSplat) + Number(Boolean(nPoints)) < 2);
      }
    }
    const fallback: Representation = representation === 'mesh' && hasSplat ? 'splat' : 'points';
    await activateRepresentation(fallback);
  }
  representationSelect.addEventListener('change', () => {
    void activateRepresentation(representationSelect.value as Representation).catch((err) => {
      console.warn('could not switch representation:', err);
      representationSelect.value = representation;
    });
  });

  const controls = new WalkControls(canvas, viewer.camera, costmap, spawn);
  const minimap = new Minimap(minimapCanvas, nav,
    { w: costmap.w, h: costmap.h, data: costmap.data });

  // ---- POIs ---------------------------------------------------------------
  let mergedPois = mergePois(authoredPois, localPois);
  viewer.setPois(mergedPois);
  minimap.setPois(mergedPois);
  const poiIndexCount = mergedPois.length;

  let activeTarget: Poi | null = null;
  let activePlan: RoutePlan | null = null;
  let tracker: RouteTracker | null = null;
  let lastReroute = 0;
  let routeLabel = '';
  const legendRoute = document.getElementById('legend-route');
  const legendProp = document.getElementById('legend-prop');

  const ui = new PoiUi({
    onSelect: (poi) => selectPoi(poi),
    onJump: (poi) => jumpTo(poi),
    onNavigate: (poi) => startNavigation(poi),
    onStopNavigation: () => stopNavigation(true),
    onEditModeChange: (on) => {
      if (on && activeTarget) stopNavigation(true);
    },
    onSavePoi: (poi) => saveLocalPoi(poi),
    onDeletePoi: (id) => deleteLocalPoi(id),
    onExportPois: () => exportPois(),
    onInputModeChange: (blocking) => {
      controls.setEnabled(!blocking);
      if (blocking) controls.cancelFlight();
    },
    onCardLayoutChange: (rect) => viewer.setLabelExclusion(rect),
    getPlayer: () => [controls.position[0], controls.position[1]],
    getView: (): PoiView => ({
      x: controls.position[0],
      y: controls.position[1],
      z: controls.position[2],
      yaw: controls.yaw,
      pitch: controls.pitch,
    }),
    toast: showToast,
  });

  function refreshPois(): void {
    mergedPois = mergePois(authoredPois, localPois);
    const selected = ui.selectedPoi?.id ?? null;
    viewer.refreshPois(mergedPois);
    if (selected) viewer.highlightPoi(selected);
    minimap.setPois(mergedPois, selected);
    ui.setPois(mergedPois);
    ui.setLocalPois(localPois);
  }

  function selectPoi(poi: Poi, fly = false): void {
    viewer.highlightPoi(poi.id);
    minimap.setSelectedPoi(poi.id);
    ui.showCard(poi);
    if (fly) jumpTo(poi);
  }

  function viewPoseFor(poi: Poi): { position: [number, number, number]; yaw: number; pitch: number } {
    const fallbackZ = Number.isFinite(nav.cam_height_units) ? nav.cam_height_units : 1.6;
    let x = poi.view?.x ?? poi.x;
    let y = poi.view?.y ?? poi.y;
    const z = poi.view?.z ?? fallbackZ;
    const snap = costmap.nearestStandable(x, y, 2.0);
    const moved = snap ? Math.hypot(snap[0] - x, snap[1] - y) : 99;
    if (snap) [x, y] = snap;
    let yaw = poi.view?.yaw;
    if (!Number.isFinite(yaw) || moved > 0.25) {
      // face the POI from wherever the camera can actually stand
      yaw = Math.atan2(-(poi.x - x), poi.y - y);
    }
    return { position: [x, y, z], yaw: yaw!, pitch: poi.view?.pitch ?? 0 };
  }

  function jumpTo(poi: Poi): void {
    // A jump is a camera transition, not a teleport through walls: the target
    // pose is snapped to free floor first.
    const pose = viewPoseFor(poi);
    controls.flyTo(pose, 1.25).then(() => {
      showToast(`Jumped to ${poi.name}`);
    });
  }

  function stopNavigation(notify: boolean): void {
    const had = activeTarget !== null;
    tracker = null;
    activeTarget = null;
    activePlan = null;
    routeLabel = '';
    viewer.setRoute([]);
    minimap.setRoute(null);
    minimap.setTarget(null);
    ui.hideNavigation();
    if (legendRoute) legendRoute.style.display = 'none';
    const routeBtn = document.getElementById('sandbox-route');
    if (routeBtn) {
      routeBtn.textContent = 'Route to end';
      routeBtn.classList.remove('active');
    }
    if (notify && had) showToast('Navigation stopped');
  }

  function showRoute(plan: RoutePlan, goal: Poi): void {
    tracker = new RouteTracker(plan);
    activePlan = plan;
    activeTarget = goal;
    viewer.setRoute(plan.waypoints, { x: goal.x, y: goal.y });
    minimap.setRoute(plan.waypoints);
    minimap.setTarget([goal.x, goal.y]);
    minimap.setSelectedPoi(goal.id);
    ui.showNavigation(plan);
    routeLabel = `route ${formatDistance(plan.distanceM)}`;
    if (legendRoute) legendRoute.style.display = 'inline-flex';
    const routeBtn = document.getElementById('sandbox-route');
    if (routeBtn) {
      routeBtn.textContent = 'Clear route';
      routeBtn.classList.add('active');
    }
  }

  function startNavigation(target: Poi): void {
    const from: [number, number] = [controls.position[0], controls.position[1]];
    if (isAtPoi(target, from[0], from[1])) {
      showToast(`You are already at ${target.name}`);
      selectPoi(target);
      return;
    }
    let goal = target;
    let plan = planRoute(costmap, from, target);
    if (!plan) {
      const snapped = costmap.nearestStandable(target.x, target.y, 5);
      if (snapped) {
        goal = { ...target, x: snapped[0], y: snapped[1] };
        plan = planRoute(costmap, from, goal);
      }
    }
    if (!plan) {
      showToast(`No walkable route to ${target.name}`);
      return;
    }
    if (Math.abs(goal.x - target.x) + Math.abs(goal.y - target.y) > 0.3) {
      showToast(`Nearest reachable point to ${target.name}`);
    }
    selectPoi(goal);
    showRoute(plan, goal);
    // Face the route so W walks toward the target instead of away from it.
    // Skip the current position and any waypoints closer than 1.5 m.
    const ahead = plan.waypoints.find(
      ([wx, wy]) => Math.hypot(wx - from[0], wy - from[1]) > 1.5,
    );
    if (ahead) controls.turnTo(ahead[0], ahead[1]);
    lastReroute = performance.now();
  }

  function refreshActiveRoute(notify = false): void {
    if (!activeTarget) return;
    const from: [number, number] = [controls.position[0], controls.position[1]];
    let plan = planRoute(costmap, from, activeTarget);
    if (!plan) {
      const snapped = costmap.nearestStandable(activeTarget.x, activeTarget.y, 5);
      if (snapped) plan = planRoute(costmap, from, { ...activeTarget, x: snapped[0], y: snapped[1] });
    }
    if (!plan) {
      viewer.setRoute([]);
      minimap.setRoute(null);
      routeLabel = 'route: blocked';
      if (notify) showToast('The route is blocked — clear the obstacle or step back');
      return;
    }
    showRoute(plan, activeTarget);
    if (notify) showToast(`Route updated · ${formatDistance(plan.distanceM)}`);
  }

  function saveLocalPoi(poi: Poi): void {
    localPois = localPois.filter((p) => p.id !== poi.id);
    localPois.push({ ...poi, source: 'local' });
    writeLocalPois(localPois);
    refreshPois();
    ui.setPois(mergedPois);
    viewer.highlightPoi(poi.id);
    minimap.setSelectedPoi(poi.id);
    ui.showCard(mergedPois.find((p) => p.id === poi.id) ?? poi);
    showToast(`Saved “${poi.name}” in this browser`);
    if (activeTarget?.id === poi.id) stopNavigation(false);
  }

  function deleteLocalPoi(id: string): void {
    const removed = localPois.find((p) => p.id === id);
    localPois = localPois.filter((p) => p.id !== id);
    writeLocalPois(localPois);
    if (activeTarget?.id === id) stopNavigation(false);
    refreshPois();
    if (removed) showToast(`Deleted “${removed.name}”`);
  }

  function exportPois(): void {
    const payload = {
      version: 1,
      capture: CAPTURE,
      pois: localPois.map(({ source: _source, ...poi }) => poi),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${CAPTURE}-pois.json`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1500);
    showToast(localPois.length ? `Exported ${localPois.length} local POIs` : 'No local POIs to export');
  }

  ui.setLocalPois(localPois);
  ui.setPois(mergedPois);

  // ---- sandbox + shared route refresh ------------------------------------
  const routeEnd: Poi | null = nav.trajectory.length > 2
    ? {
      id: 'route-end',
      name: 'End of capture',
      category: 'area',
      x: nav.trajectory[nav.trajectory.length - 1][0],
      y: nav.trajectory[nav.trajectory.length - 1][1],
      z: 0,
      source: 'authored',
    }
    : null;

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
      if (activeTarget) refreshActiveRoute(false);
    },
  });

  const routeBtn = document.getElementById('sandbox-route') as HTMLButtonElement | null;
  routeBtn?.addEventListener('click', () => {
    if (activeTarget) stopNavigation(true);
    else if (routeEnd) startNavigation(routeEnd);
  });
  if (params.has('route') && routeEnd) startNavigation(routeEnd);
  if (sandbox.autoEnable) sandbox.setEnabled(true);

  // ---- canvas interaction ------------------------------------------------
  let pointerDown: { x: number; y: number; t: number } | null = null;
  canvas.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse') {
      pointerDown = { x: e.clientX, y: e.clientY, t: performance.now() };
    }
  });

  canvas.addEventListener('click', (e) => {
    if (pointerLocked() && pointerDown) {
      const moved = Math.hypot(e.clientX - pointerDown.x, e.clientY - pointerDown.y);
      if (moved > 6) return;
    }
    pointerDown = null;
    if (sandbox.isEnabled) return;

    if (ui.isEditing) {
      const floor = floorAt(e.clientX, e.clientY);
      if (!floor) {
        showToast('Aim at the floor to place a POI');
        return;
      }
      const snap = costmap.nearestStandable(floor[0], floor[1], 2.0);
      if (!snap) {
        showToast('That spot is not on walkable floor');
        return;
      }
      ui.openEditorAt(snap[0], snap[1], floor[2]);
      return;
    }

    const poi = pointerLocked()
      ? viewer.pickPoiNdc(new THREE.Vector2(0, 0))
      : viewer.pickPoi(e.clientX, e.clientY);
    if (poi) {
      selectPoi(poi);
      showToast(`${poi.name} · Navigate or Jump here`);
    }
  });

  minimapCanvas.addEventListener('click', (e) => {
    const poi = minimap.poiAt(e.clientX, e.clientY);
    if (poi) {
      selectPoi(poi);
      showToast(`${poi.name} · Navigate or Jump here`);
    }
  });

  function pointerLocked(): boolean {
    return document.pointerLockElement === canvas;
  }

  /** Raycast the splat/floor for POI authoring. Returns nav [x, y, floorZ]. */
  function floorAt(clientX: number, clientY: number): [number, number, number] | null {
    const rect = canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    );
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, viewer.camera);
    if (splat?.loaded) {
      const hit = splat.raycastRay(ray.ray.origin, ray.ray.direction);
      if (hit) {
        const navY = -hit.point.z;
        const navX = hit.point.x;
        const floorZ = hit.point.y;
        if (Math.abs(floorZ - (controls.position[2] - nav.cam_height_units)) < 1.4) {
          return [navX, navY, Math.max(0, floorZ)];
        }
      }
    }
    // fallback: intersect the z=0 nav floor (three y=0)
    const t = -ray.ray.origin.y / (ray.ray.direction.y || -1);
    if (t <= 0 || t > 40) return null;
    const point = ray.ray.origin.clone().addScaledVector(ray.ray.direction, t);
    return [point.x, -point.z, 0];
  }

  // ---- orientation controls ---------------------------------------------
  function stepAngle(cur: number, delta: number): number {
    let next = (cur + delta) % 360;
    if (next > 180) next -= 360;
    if (next < -180) next += 360;
    return next;
  }

  const btnFlip = document.getElementById('btn-flip');
  btnFlip?.addEventListener('click', () => {
    curRx = stepAngle(curRx, 180);
    applyOrientation(true);
    showToast(`Flipped 180° (rx: ${curRx}°)`);
  });

  const btnResetRot = document.getElementById('btn-reset-rot');
  btnResetRot?.addEventListener('click', () => {
    curRx = 0;
    curRy = 0;
    curRz = 0;
    curOy = 0;
    applyOrientation(true);
    showToast('Orientation reset to 0°');
  });

  const btnCopyRot = document.getElementById('btn-copy-rot');
  btnCopyRot?.addEventListener('click', () => {
    const shareUrl = new URL(location.href);
    const selected = ui.selectedPoi;
    if (selected) shareUrl.searchParams.set('poi', selected.id);
    else shareUrl.searchParams.delete('poi');
    const text = shareUrl.toString();
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text)
        .then(() => showToast('Share link copied to clipboard!'))
        .catch(() => showToast('Could not copy link'));
    } else {
      showToast(text);
    }
  });

  document.getElementById('btn-ry-m90')?.addEventListener('click', () => {
    curRy = stepAngle(curRy, -90);
    applyOrientation(true);
  });
  document.getElementById('btn-ry-p90')?.addEventListener('click', () => {
    curRy = stepAngle(curRy, 90);
    applyOrientation(true);
  });
  document.getElementById('btn-ry-m15')?.addEventListener('click', () => {
    curRy = stepAngle(curRy, -15);
    applyOrientation(true);
  });
  document.getElementById('btn-ry-p15')?.addEventListener('click', () => {
    curRy = stepAngle(curRy, 15);
    applyOrientation(true);
  });

  document.getElementById('btn-rx-m90')?.addEventListener('click', () => {
    curRx = stepAngle(curRx, -90);
    applyOrientation(true);
  });
  document.getElementById('btn-rx-p90')?.addEventListener('click', () => {
    curRx = stepAngle(curRx, 90);
    applyOrientation(true);
  });
  document.getElementById('btn-rx-m15')?.addEventListener('click', () => {
    curRx = stepAngle(curRx, -15);
    applyOrientation(true);
  });
  document.getElementById('btn-rx-p15')?.addEventListener('click', () => {
    curRx = stepAngle(curRx, 15);
    applyOrientation(true);
  });

  document.getElementById('btn-rz-m15')?.addEventListener('click', () => {
    curRz = stepAngle(curRz, -15);
    applyOrientation(true);
  });
  document.getElementById('btn-rz-p15')?.addEventListener('click', () => {
    curRz = stepAngle(curRz, 15);
    applyOrientation(true);
  });
  document.getElementById('btn-oy-up')?.addEventListener('click', () => {
    curOy = Math.round((curOy + 0.2) * 10) / 10;
    applyOrientation(true);
  });
  document.getElementById('btn-oy-down')?.addEventListener('click', () => {
    curOy = Math.round((curOy - 0.2) * 10) / 10;
    applyOrientation(true);
  });

  const orientControls = document.getElementById('orient-controls');
  const orientToggle = document.getElementById('orient-toggle');
  const setOrientMinimized = (min: boolean): void => {
    orientControls?.classList.toggle('minimized', min);
    if (orientToggle) orientToggle.textContent = min ? '+' : '−';
    document.body.classList.toggle('orient-expanded', !min);
  };
  orientToggle?.addEventListener('click', () => {
    setOrientMinimized(!orientControls?.classList.contains('minimized'));
  });
  // Phones start with the rotation panel collapsed so the scene and minimap
  // stay visible; the header toggle still opens it on demand.
  if (window.matchMedia('(max-width: 760px)').matches) setOrientMinimized(true);

  applyOrientation(false);

  document.addEventListener('pointerlockchange', () => {
    const locked = document.pointerLockElement === canvas;
    hint.classList.toggle('hidden', locked);
  });

  function isTypingTarget(target: EventTarget | null): boolean {
    const t = target as HTMLElement | null;
    if (!t) return false;
    const tag = t.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t.isContentEditable;
  }

  window.addEventListener('keydown', (e) => {
    if (isTypingTarget(e.target)) return;
    if (e.code === 'KeyP') viewer.setPointsVisible(!viewer.pointsVisible);
    if (e.code === 'KeyM') mapWrap.classList.toggle('hidden');
    if (e.code === 'KeyO') {
      curRx = stepAngle(curRx, 180);
      applyOrientation(true);
      showToast(`Flipped 180° (rx: ${curRx}°)`);
    }
    if (e.code === 'BracketLeft') {
      curRy = stepAngle(curRy, -90);
      applyOrientation(true);
      showToast(`Turned left 90° (ry: ${curRy}°)`);
    }
    if (e.code === 'BracketRight') {
      curRy = stepAngle(curRy, 90);
      applyOrientation(true);
      showToast(`Turned right 90° (ry: ${curRy}°)`);
    }
    if (e.code === 'Backslash') {
      setOrientMinimized(!orientControls?.classList.contains('minimized'));
    }
    if (e.code === 'KeyT' && sandbox.isEnabled) {
      if (activeTarget) stopNavigation(true);
      else if (routeEnd) startNavigation(routeEnd);
    }
  });

  // ---- deep links --------------------------------------------------------
  const linkedPoiId = params.get('poi');
  if (linkedPoiId) {
    const poi = mergedPois.find((p) => p.id === linkedPoiId);
    if (poi) {
      selectPoi(poi, true);
    } else {
      showToast(`Unknown POI “${linkedPoiId}”`);
    }
  }
  const linkedQuery = params.get('q');
  if (linkedQuery) ui.openSearch(linkedQuery);

  // ---- loop --------------------------------------------------------------
  let last = performance.now();
  let fps = 0;
  let statTimer = 0;
  let adaptTimer = -3; // let the first frames/sorting settle before judging
  const free = grid.data.reduce((s, v) => s + (v === 0 ? 1 : 0), 0);
  const walkable = meta.walkable_area_m2 ?? (free * nav.cell_m * nav.cell_m);

  function statLine(): string {
    const parts = [`${CAPTURE}`];
    if (representation === 'mesh') {
      parts.push('photo-textured mesh');
    } else if (representation === 'splat' && splat?.loaded) {
      parts.push(meta.splat?.gaussians ? `splat ${(meta.splat.gaussians / 1e6).toFixed(2)}M` : 'splat');
    } else if (nPoints) {
      parts.push(`${nPoints.toLocaleString()} pts${viewer.pointsVisible ? '' : ' (hidden)'}`);
    }
    parts.push(`${walkable} m² walkable`);
    parts.push(`${mergedPois.length} POIs`);
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
    ui.refreshCardDistance();

    if (tracker && activePlan) {
      const state = tracker.update(
        [controls.position[0], controls.position[1]],
        controls.heading,
        dt,
      );
      ui.updateNavigation(state, activePlan);
      routeLabel = `route ${formatDistance(state.remainingM)}`;
      if (state.arrived) {
        const name = activePlan.targetName;
        stopNavigation(false);
        showToast(`Arrived at ${name}`);
      } else if (state.needsReroute && now - lastReroute > 1200) {
        lastReroute = now;
        refreshActiveRoute(true);
      }
    }

    if (representation === 'splat' && splat?.loaded) {
      splat.update();
      splat.render();
      viewer.renderOverlay();
    } else {
      viewer.render();
      viewer.renderOverlay();
    }
    viewer.update(dt);
    minimap.draw(controls.position, controls.heading);

    // Dynamic resolution: the splat is fill-rate bound. Only step down when we
    // are clearly below 24 fps (a 30 Hz panel must not trigger it), and stop at
    // 0.6x so the twin never turns into an upscaled blur. A manual ?scale wins.
    if (!MANUAL_SCALE && representation === 'splat' && splat?.loaded) {
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

  if (import.meta.env.DEV) {
    (window as unknown as { __topoloka: unknown }).__topoloka = {
      controls,
      costmap,
      viewer,
      minimap,
      sandbox,
      state: () => ({
        position: [...controls.position],
        yaw: controls.yaw,
        pitch: controls.pitch,
        target: activeTarget?.id ?? null,
      }),
      plan: (id: string) => {
        const poi = mergedPois.find((entry) => entry.id === id);
        return poi ? planRoute(costmap, [controls.position[0], controls.position[1]], poi) : null;
      },
    };
  }

  // A quick first-run hint: the search bar is the headline R2 feature.
  window.setTimeout(() => {
    if (!linkedQuery && !linkedPoiId) {
      const touches = window.matchMedia('(pointer: coarse)').matches;
      showToast(touches
        ? `${poiIndexCount} POIs · tap Search to explore or Tag to add one`
        : `${poiIndexCount} POIs · press / to search or E to tag a place`);
    }
  }, 900);

  void WALK_SPEED_MPS; // documented speed used by the banner
  requestAnimationFrame(loop);
}

boot().catch((err) => {
  console.error(err);
  subtitle.textContent = `Could not load ${CAPTURE}`;
  hint.textContent = 'The sample could not load. Check your connection and reload.';
  hint.classList.remove('hidden');
});
