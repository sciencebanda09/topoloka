/** Three.js scene for the twin: point cloud, floor grid, outline, trajectory,
 * POI markers and the animated navigation route.

 * The pipeline's world frame is x/y horizontal + z up (meters).
 * Three.js is Y-up, so the mapping is: three = (x, z, -y).
 */

import * as THREE from 'three';
import type { NavData } from './artifacts';
import type { Poi } from './pois';

export const navToThree = (x: number, y: number, z: number): THREE.Vector3 =>
  new THREE.Vector3(x, z, -y);

const DEFAULT_HFOV_DEG = 68; // fallback when a capture has no intrinsics
const ROUTE_WIDTH_M = 0.16;
const ROUTE_UNDERLAY_M = 0.30;
const ROUTE_TEXTURE_TILE_M = 0.9;

const POI_COLORS: Record<string, number> = {
  landmark: 0x7fd4ff,
  platform: 0xffb347,
  exit: 0x40ff9a,
  facility: 0xc39bff,
  area: 0x7fd4ff,
  retail: 0xff8fc7,
};

function poiColor(category: string): number {
  return POI_COLORS[category] ?? 0x7fd4ff;
}

function roundedLabel(text: string, color: number): THREE.Sprite {
  const dpr = 2;
  const width = 512, height = 128;
  const canvas = document.createElement('canvas');
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext('2d')!;
  ctx.scale(dpr, dpr);
  const css = `#${color.toString(16).padStart(6, '0')}`;

  // Subtle ambient shadow behind the floating pill
  ctx.save();
  ctx.shadowColor = 'rgba(0, 0, 0, 0.65)';
  ctx.shadowBlur = 14;
  ctx.shadowOffsetY = 4;
  ctx.fillStyle = 'rgba(8, 13, 19, 0.88)';
  roundRect(ctx, 10, 24, width - 20, 76, 38);
  ctx.fill();
  ctx.restore();

  // Subtle glass top highlight + category accent border
  const grad = ctx.createLinearGradient(0, 24, 0, 100);
  grad.addColorStop(0, 'rgba(255, 255, 255, 0.08)');
  grad.addColorStop(0.45, 'rgba(255, 255, 255, 0.0)');
  grad.addColorStop(1, 'rgba(0, 0, 0, 0.16)');
  ctx.fillStyle = grad;
  roundRect(ctx, 10, 24, width - 20, 76, 38);
  ctx.fill();

  ctx.strokeStyle = css;
  ctx.lineWidth = 2.2;
  roundRect(ctx, 10, 24, width - 20, 76, 38);
  ctx.stroke();

  const clipped = text.length > 26 ? `${text.slice(0, 25)}…` : text;
  ctx.font = "600 31px 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif";
  const textW = ctx.measureText(clipped).width;
  const dotR = 7;
  const gap = 14;
  const groupW = dotR * 2 + gap + textW;
  const startX = (width - groupW) / 2;

  // Glowing category indicator dot
  ctx.save();
  ctx.shadowColor = css;
  ctx.shadowBlur = 10;
  ctx.fillStyle = css;
  ctx.beginPath();
  ctx.arc(startX + dotR, 62, dotR, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  ctx.fillStyle = '#f2f7fc';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(clipped, startX + dotR * 2 + gap, 63);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  const material = new THREE.SpriteMaterial({
    map: texture, transparent: true, depthWrite: false, fog: false, toneMapped: false,
  });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(1.9, 0.475, 1);
  return sprite;
}

function roundRect(
  ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number,
): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

interface PoiMarker {
  poi: Poi;
  group: THREE.Group;
  ring: THREE.Mesh;
  outerRing: THREE.Mesh;
  dot: THREE.Mesh;
  stem: THREE.Mesh;
  pick: THREE.Mesh;
  label: THREE.Sprite;
  material: THREE.MeshBasicMaterial;
  haloMaterial: THREE.MeshBasicMaterial;
  color: number;
}

export class Viewer {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene: THREE.Scene;
  readonly camera: THREE.PerspectiveCamera;
  pointsVisible = true;
  private modelRoot = new THREE.Group();
  private routeRoot = new THREE.Group();
  private overlayScene = new THREE.Scene();
  private routeMesh: THREE.Mesh | null = null;
  private routeUnderlay: THREE.Mesh | null = null;
  private destination: THREE.Group | null = null;
  private destinationRing: THREE.Mesh | null = null;
  private pointsObj: THREE.Points | null = null;
  private meshRoot: THREE.Group | null = null;
  private trajectory: THREE.Line | null = null;
  private groundGrid: THREE.GridHelper | null = null;
  private outline: THREE.LineLoop | null = null;
  private renderScale: number;
  private hFovRad = THREE.MathUtils.degToRad(DEFAULT_HFOV_DEG);
  private poiRoot = new THREE.Group();
  private markers = new Map<string, PoiMarker>();
  private selectedPoi: string | null = null;
  private pulse = 0;
  private routeTexture: THREE.CanvasTexture | null = null;
  private readonly labelProbe = new THREE.Vector3();
  private readonly labelEdge = new THREE.Vector3();
  private readonly labelRight = new THREE.Vector3();
  private readonly labelUp = new THREE.Vector3();
  private labelExclusion: { x0: number; y0: number; x1: number; y1: number } | null = null;

  constructor(canvas: HTMLCanvasElement, renderScale = 1) {
    this.renderScale = Math.min(1, Math.max(0.4, renderScale));
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' });
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    // Draw at CSS resolution (x renderScale), not devicePixelRatio: a 2x
    // retina buffer is 4x the splat fill cost on integrated laptop GPUs.
    this.renderer.setPixelRatio(1);
    this.resizeRenderer();

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x080b10);
    this.scene.fog = new THREE.Fog(0x080b10, 18, 42);
    this.scene.add(this.modelRoot);
    this.poiRoot.name = 'poi-markers';
    this.routeRoot.name = 'navigation-route';
    // POIs and routes are wayfinding overlays: draw them after the splat in a
    // second pass so the splat's paint-over-everything pass cannot hide them.
    this.overlayScene.add(this.poiRoot, this.routeRoot);

    this.camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.05, 200);
    this.applyFov();

    window.addEventListener('resize', () => {
      this.camera.aspect = window.innerWidth / window.innerHeight;
      this.applyFov();
      this.resizeRenderer();
    });
  }

  private resizeRenderer(): void {
    this.renderer.setSize(
      Math.round(window.innerWidth * this.renderScale),
      Math.round(window.innerHeight * this.renderScale),
      false,
    );
  }

  /** Adaptive quality: lower the internal buffer, upscale via CSS. */
  setRenderScale(scale: number): void {
    const next = Math.min(1, Math.max(0.4, scale));
    if (Math.abs(next - this.renderScale) < 0.005) return;
    this.renderScale = next;
    this.resizeRenderer();
  }

  /**
   * Use the capture's horizontal FOV. A 72° vertical viewer FOV against a
   * 41.6° vertical capture stretches every anisotropic splat and reveals
   * unobserved ceiling; the same lens makes the twin look like the video.
   */
  setNavCamera(nav: NavData): void {
    const c = nav.camera;
    if (c?.w && c?.fl_x) {
      this.hFovRad = 2 * Math.atan(c.w / (2 * c.fl_x));
    }
    this.applyFov();
  }

  private applyFov(): void {
    const aspect = Math.max(window.innerWidth / window.innerHeight, 0.05);
    let v = 2 * Math.atan(Math.tan(this.hFovRad / 2) / aspect);
    // Preserve the capture's horizontal FOV in landscape. On a portrait
    // phone that would imply a ~110° vertical FOV and show the unobserved
    // ceiling; cap the vertical lens instead so the phone stays inside the
    // captured shell.
    if (aspect < 1) v = Math.min(v, THREE.MathUtils.degToRad(50));
    this.camera.fov = THREE.MathUtils.radToDeg(v);
    this.camera.updateProjectionMatrix();
  }

  addPointCloud(positions: Float32Array, colors: Uint8Array): number {
    const n = positions.length / 3;
    const pos = new Float32Array(n * 3);
    const col = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const x = positions[i * 3], y = positions[i * 3 + 1], z = positions[i * 3 + 2];
      pos[i * 3 + 0] = x; pos[i * 3 + 1] = z; pos[i * 3 + 2] = -y;   // nav -> three
      col[i * 3 + 0] = colors[i * 3 + 0] / 255;
      col[i * 3 + 1] = colors[i * 3 + 1] / 255;
      col[i * 3 + 2] = colors[i * 3 + 2] / 255;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
    const mat = new THREE.PointsMaterial({
      size: 0.022, sizeAttenuation: true, vertexColors: true,
    });
    const points = new THREE.Points(geo, mat);
    points.frustumCulled = false;
    this.pointsObj = points;
    this.modelRoot.add(points);
    return n;
  }

  setPointsVisible(visible: boolean): void {
    this.pointsVisible = visible;
    if (this.pointsObj) this.pointsObj.visible = visible;
  }

  /** Load the photo-textured MVS surface in navigation coordinates (z up). */
  async addTexturedMesh(url: string): Promise<void> {
    const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
    const gltf = await new GLTFLoader().loadAsync(url);
    const root = new THREE.Group();
    root.rotation.x = -Math.PI / 2; // nav (x,y,z-up) -> Three.js (x,z,-y)
    root.add(gltf.scene);
    gltf.scene.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      const photoMaterials = materials.map((material) => {
        const map = material instanceof THREE.MeshStandardMaterial || material instanceof THREE.MeshBasicMaterial
          ? material.map
          : null;
        if (map) {
          map.colorSpace = THREE.SRGBColorSpace;
          map.anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
        }
        // Keep captured colors bright and stable regardless of scene lighting.
        return new THREE.MeshBasicMaterial({
          map,
          color: 0xffffff,
          side: THREE.DoubleSide,
          fog: false,
          toneMapped: false,
        });
      });
      object.material = Array.isArray(object.material) ? photoMaterials : photoMaterials[0];
      object.frustumCulled = false;
    });
    root.visible = false;
    this.meshRoot = root;
    this.modelRoot.add(root);
  }

  setExtraTransform(rxDeg: number, ryDeg: number, rzDeg: number, oyMeters: number, pivot?: THREE.Vector3): void {
    const p = pivot ?? new THREE.Vector3(0, 0, 0);
    const rot = new THREE.Euler(
      THREE.MathUtils.degToRad(rxDeg),
      THREE.MathUtils.degToRad(ryDeg),
      THREE.MathUtils.degToRad(rzDeg),
      'YXZ',
    );
    const extraR = new THREE.Matrix4().makeRotationFromEuler(rot);
    const toCenter = new THREE.Matrix4().makeTranslation(-p.x, -p.y, -p.z);
    const fromCenter = new THREE.Matrix4().makeTranslation(p.x, p.y + oyMeters, p.z);
    const mExtra = new THREE.Matrix4().multiply(fromCenter).multiply(extraR).multiply(toCenter);

    const pos = new THREE.Vector3();
    const quat = new THREE.Quaternion();
    const scale = new THREE.Vector3();
    mExtra.decompose(pos, quat, scale);

    this.modelRoot.position.copy(pos);
    this.modelRoot.quaternion.copy(quat);
    this.modelRoot.scale.copy(scale);
    this.modelRoot.updateMatrix();
    this.modelRoot.updateMatrixWorld(true);
  }

  setMeshVisible(visible: boolean): void {
    if (this.meshRoot) this.meshRoot.visible = visible;
  }

  addOutline(points: [number, number][]): void {
    if (points.length < 3) return;
    const pts = points.map(([x, y]) => navToThree(x, y, 0.01));
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const mat = new THREE.LineBasicMaterial({ color: 0x7fd4ff, transparent: true, opacity: 0.85 });
    this.outline = new THREE.LineLoop(geo, mat);
    this.scene.add(this.outline);
  }

  addTrajectory(points: [number, number, number][]): void {
    if (points.length < 2) return;
    const pts = points.map(([x, y, z]) => navToThree(x, y, z + 0.02));
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const mat = new THREE.LineBasicMaterial({ color: 0x5c6874, transparent: true, opacity: 0.9 });
    this.trajectory = new THREE.Line(geo, mat);
    this.scene.add(this.trajectory);
  }

  /** The minimap already shows the path; inside a splat it reads as a wire. */
  setTrajectoryVisible(visible: boolean): void {
    if (this.trajectory) this.trajectory.visible = visible;
  }

  addGroundGrid(extent = 30): void {
    const grid = new THREE.GridHelper(extent, extent * 2, 0x22303c, 0x161d24);
    grid.position.y = 0;
    this.groundGrid = grid;
    this.scene.add(grid);
  }

  /** Hide point-cloud-only debug geometry once a splat supplies the surface. */
  setDebugVisible(visible: boolean): void {
    if (this.groundGrid) this.groundGrid.visible = visible;
    if (this.outline) this.outline.visible = visible;
  }

  // ---- POI markers -------------------------------------------------------

  setPois(pois: Poi[]): void {
    this.clearPois();
    for (const poi of pois) this.addPoi(poi);
  }

  private addPoi(poi: Poi): void {
    const color = poiColor(poi.category);
    const floorZ = poi.z ?? 0;
    const group = new THREE.Group();
    group.name = `poi:${poi.id}`;

    const material = new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: 0.92, depthWrite: false, side: THREE.DoubleSide,
      toneMapped: false,
    });
    const haloMaterial = new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: 0.34, depthWrite: false, side: THREE.DoubleSide,
      toneMapped: false,
    });
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.25, 0.34, 40), material);
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(poi.x, floorZ + 0.025, -poi.y);
    const outerRing = new THREE.Mesh(new THREE.RingGeometry(0.41, 0.45, 44), haloMaterial);
    outerRing.rotation.x = -Math.PI / 2;
    outerRing.position.set(poi.x, floorZ + 0.023, -poi.y);
    const dot = new THREE.Mesh(new THREE.CircleGeometry(0.085, 24), material);
    dot.rotation.x = -Math.PI / 2;
    dot.position.set(poi.x, floorZ + 0.028, -poi.y);

    // Subtle vertical beacon pin tying the floor anchor visually to the floating pill
    const stem = new THREE.Mesh(
      new THREE.CylinderGeometry(0.008, 0.018, 1.32, 10, 1, true),
      haloMaterial,
    );
    stem.position.set(poi.x, floorZ + 0.70, -poi.y);

    // A tall invisible cylinder makes aiming forgiving, especially on mobile.
    const pick = new THREE.Mesh(
      new THREE.CylinderGeometry(0.5, 0.5, 2.0, 12, 1, true),
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide }),
    );
    pick.position.set(poi.x, floorZ + 1.0, -poi.y);
    pick.userData.poiId = poi.id;

    const label = roundedLabel(poi.name, color);
    label.position.set(poi.x, floorZ + 1.55, -poi.y);

    group.add(outerRing, ring, dot, stem, pick, label);
    group.userData.poiId = poi.id;
    this.poiRoot.add(group);
    this.markers.set(poi.id, {
      poi, group, ring, outerRing, dot, stem, pick, label, material, haloMaterial, color,
    });
  }

  private clearPois(): void {
    for (const marker of this.markers.values()) {
      marker.group.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.geometry.dispose();
          const mats = Array.isArray(object.material) ? object.material : [object.material];
          for (const m of mats) m.dispose();
        } else if (object instanceof THREE.Sprite) {
          object.material.map?.dispose();
          object.material.dispose();
        }
      });
      this.poiRoot.remove(marker.group);
    }
    this.markers.clear();
    this.selectedPoi = null;
  }

  /** Replace marker positions (the editor adds/renames POIs live). */
  refreshPois(pois: Poi[]): void {
    const selected = this.selectedPoi;
    this.setPois(pois);
    if (selected) this.highlightPoi(selected);
  }

  highlightPoi(id: string | null): void {
    this.selectedPoi = id;
    for (const [markerId, marker] of this.markers) {
      const active = markerId === id;
      marker.material.color.setHex(active ? 0xffffff : marker.color);
      marker.material.opacity = active ? 1 : 0.88;
      marker.haloMaterial.color.setHex(active ? 0xffffff : marker.color);
      marker.haloMaterial.opacity = active ? 0.62 : 0.34;
      marker.label.material.opacity = active ? 1 : 0.86;
    }
  }

  /** Keep world labels out of an open UI panel, given in CSS pixels. */
  setLabelExclusion(rect: { left: number; top: number; right: number; bottom: number } | null): void {
    if (!rect) {
      this.labelExclusion = null;
      return;
    }
    const canvas = this.renderer.domElement.getBoundingClientRect();
    const w = canvas.width || 1;
    const h = canvas.height || 1;
    this.labelExclusion = {
      x0: ((rect.left - canvas.left) / w) * 2 - 1,
      x1: ((rect.right - canvas.left) / w) * 2 - 1,
      y0: 1 - ((rect.bottom - canvas.top) / h) * 2,
      y1: 1 - ((rect.top - canvas.top) / h) * 2,
    };
  }

  /** Ray-pick a POI label or marker from canvas/client coordinates. */
  pickPoi(clientX: number, clientY: number): Poi | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    );
    return this.pickPoiNdc(ndc);
  }

  pickPoiNdc(ndc: THREE.Vector2): Poi | null {
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    ray.far = 80;
    const targets: THREE.Object3D[] = [];
    for (const marker of this.markers.values()) targets.push(marker.pick, marker.label);
    const hits = ray.intersectObjects(targets, false);
    for (const hit of hits) {
      let object: THREE.Object3D | null = hit.object;
      while (object && !object.userData.poiId) object = object.parent;
      const id = object?.userData.poiId as string | undefined;
      if (id) return this.markers.get(id)?.poi ?? null;
    }
    // Sprites can be small at distance; fall back to the nearest marker within
    // 22 px of the click, which is how map pins usually behave.
    const markerPx = 22;
    let best: { poi: Poi; d: number } | null = null;
    for (const marker of this.markers.values()) {
      const v = new THREE.Vector3(marker.poi.x, (marker.poi.z ?? 0) + 0.7, -marker.poi.y).project(this.camera);
      if (v.z > 1 || v.z < -1) continue;
      const sx = (v.x * 0.5 + 0.5) * this.renderer.domElement.clientWidth;
      const sy = (-v.y * 0.5 + 0.5) * this.renderer.domElement.clientHeight;
      const d = Math.hypot(sx - (ndc.x * 0.5 + 0.5) * this.renderer.domElement.clientWidth,
        sy - (-ndc.y * 0.5 + 0.5) * this.renderer.domElement.clientHeight);
      if (d <= markerPx && (!best || d < best.d)) best = { poi: marker.poi, d };
    }
    return best?.poi ?? null;
  }

  // ---- route -------------------------------------------------------------

  /**
   * Draw a flat, dashed route ribbon. A tube would need a spline; a spline
   * overshoots corners and can visually cut through a wall even when the grid
   * path is clear. A ribbon follows the exact waypoints.
   */
  setRoute(waypoints: [number, number][], target?: { x: number; y: number }): void {
    this.clearRoute();
    if (waypoints.length >= 2) {
      const geometry = this.ribbonGeometry(waypoints, ROUTE_WIDTH_M);
      const texture = this.routeTexture ?? (this.routeTexture = routeTexture());
      const material = new THREE.MeshBasicMaterial({
        map: texture, transparent: true, opacity: 0.98, side: THREE.DoubleSide,
        depthWrite: false, toneMapped: false, fog: false,
        polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
      });
      this.routeMesh = new THREE.Mesh(geometry, material);
      this.routeMesh.renderOrder = 3;
      this.routeMesh.frustumCulled = false;
      this.routeRoot.add(this.routeMesh);

      const underGeo = this.ribbonGeometry(waypoints, ROUTE_UNDERLAY_M);
      const underMat = new THREE.MeshBasicMaterial({
        color: 0x0f3b28, transparent: true, opacity: 0.42, side: THREE.DoubleSide,
        depthWrite: false, toneMapped: false, fog: false,
        polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
      });
      this.routeUnderlay = new THREE.Mesh(underGeo, underMat);
      this.routeUnderlay.renderOrder = 2;
      this.routeUnderlay.frustumCulled = false;
      this.routeRoot.add(this.routeUnderlay);
    }
    if (target) {
      const ringMat = new THREE.MeshBasicMaterial({
        color: 0x40ff9a, transparent: true, opacity: 0.92, side: THREE.DoubleSide,
        depthWrite: false, toneMapped: false,
      });
      this.destinationRing = new THREE.Mesh(new THREE.RingGeometry(0.42, 0.52, 48), ringMat);
      this.destinationRing.rotation.x = -Math.PI / 2;
      this.destinationRing.position.set(target.x, 0.036, -target.y);
      this.destinationRing.renderOrder = 3;

      const coreMat = new THREE.MeshBasicMaterial({
        color: 0x40ff9a, transparent: true, opacity: 0.24, side: THREE.DoubleSide,
        depthWrite: false, toneMapped: false,
      });
      const coreDisc = new THREE.Mesh(new THREE.CircleGeometry(0.38, 36), coreMat);
      coreDisc.rotation.x = -Math.PI / 2;
      coreDisc.position.set(target.x, 0.034, -target.y);
      coreDisc.renderOrder = 2;

      const beamMat = new THREE.MeshBasicMaterial({
        color: 0x40ff9a, transparent: true, opacity: 0.20, side: THREE.DoubleSide,
        depthWrite: false, toneMapped: false,
      });
      const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.12, 1.35, 18, 1, true), beamMat);
      beam.position.set(target.x, 0.71, -target.y);
      beam.renderOrder = 2;

      this.destination = new THREE.Group();
      this.destination.add(this.destinationRing, coreDisc, beam);
      this.routeRoot.add(this.destination);
    }
  }

  private clearRoute(): void {
    const disposables = [this.routeMesh, this.routeUnderlay];
    for (const object of disposables) {
      if (!object) continue;
      this.routeRoot.remove(object);
      object.geometry.dispose();
      const mats = Array.isArray(object.material) ? object.material : [object.material];
      for (const m of mats) m.dispose();
    }
    if (this.destination) {
      this.destination.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.geometry.dispose();
          const mats = Array.isArray(object.material) ? object.material : [object.material];
          for (const m of mats) m.dispose();
        }
      });
      this.routeRoot.remove(this.destination);
    }
    this.routeMesh = null;
    this.routeUnderlay = null;
    this.destinationRing = null;
    this.destination = null;
  }

  /** Animate chevrons toward the destination and pulse the target ring. */
  update(dt: number): void {
    this.pulse += dt;
    if (this.routeTexture) this.routeTexture.offset.x -= dt * 1.6;
    if (this.destinationRing) {
      const s = 1 + 0.12 * Math.sin(this.pulse * 4);
      this.destinationRing.scale.setScalar(s);
      (this.destinationRing.material as THREE.MeshBasicMaterial).opacity = 0.65 + 0.25 * Math.sin(this.pulse * 4);
    }
    const selected = this.selectedPoi ? this.markers.get(this.selectedPoi) : null;
    if (selected) {
      const s = 1 + 0.18 * Math.sin(this.pulse * 5);
      selected.ring.scale.setScalar(s);
      selected.outerRing.scale.setScalar(1 + 0.10 * Math.cos(this.pulse * 5));
      selected.dot.scale.setScalar(s);
    } else if (this.markers.size) {
      // reset any previously selected marker scale
      for (const marker of this.markers.values()) {
        marker.ring.scale.setScalar(1);
        marker.outerRing.scale.setScalar(1);
        marker.dot.scale.setScalar(1);
      }
    }
    // Labels live in the after-splat overlay pass, so they cannot rely on the
    // splat to occlude them. Keep them roughly constant on screen, hide the
    // one you are standing next to, and declutter: while navigating, only the
    // target label is shown; otherwise nearby on-screen labels only.
    const cam = this.camera.position;
    const navigating = this.destination !== null;
    const basis = this.camera.matrixWorld.elements;
    this.labelRight.set(basis[0], basis[1], basis[2]).normalize();
    this.labelUp.set(basis[4], basis[5], basis[6]).normalize();
    const candidates: {
      marker: PoiMarker;
      distance: number;
      x: number;
      y: number;
      halfW: number;
      halfH: number;
      focused: boolean;
    }[] = [];
    for (const marker of this.markers.values()) {
      const label = marker.label;
      const distance = Math.hypot(
        cam.x - label.position.x, cam.y - label.position.y, cam.z - label.position.z,
      );
      const scale = Math.min(2.4, Math.max(0.25, distance / 12));
      label.scale.set(1.9 * scale, 0.475 * scale, 1);
      this.labelProbe.copy(label.position).project(this.camera);
      // Check the projected sprite bounds, not just its centre, so a wide
      // label near the viewport edge cannot be clipped mid-word.
      this.labelEdge.copy(label.position)
        .addScaledVector(this.labelRight, label.scale.x / 2).project(this.camera);
      const halfW = Math.abs(this.labelEdge.x - this.labelProbe.x);
      this.labelEdge.copy(label.position)
        .addScaledVector(this.labelUp, label.scale.y / 2).project(this.camera);
      const halfH = Math.abs(this.labelEdge.y - this.labelProbe.y);
      const onScreen = this.labelProbe.z > -1 && this.labelProbe.z < 1
        && Math.abs(this.labelProbe.x) + halfW < 0.98
        && Math.abs(this.labelProbe.y) + halfH < 0.98;
      // Do not slide a label under the open POI card; it reads as clipped text.
      const underCard = this.labelExclusion !== null
        && this.labelProbe.x + halfW > this.labelExclusion.x0
        && this.labelProbe.x - halfW < this.labelExclusion.x1
        && this.labelProbe.y + halfH > this.labelExclusion.y0
        && this.labelProbe.y - halfH < this.labelExclusion.y1;
      const focused = navigating && marker.poi.id === this.selectedPoi;
      const eligible = onScreen && !underCard && distance > 3
        && (focused || (!navigating && distance < 24));
      if (!eligible) {
        label.visible = false;
        continue;
      }
      candidates.push({
        marker, distance,
        x: this.labelProbe.x, y: this.labelProbe.y, halfW, halfH, focused,
      });
    }
    // Prefer the selected label, then the nearest one, and drop any label
    // whose projected box would collide with one already placed.
    candidates.sort((a, b) => {
      if (a.focused !== b.focused) return a.focused ? -1 : 1;
      const aSelected = a.marker.poi.id === this.selectedPoi;
      const bSelected = b.marker.poi.id === this.selectedPoi;
      if (aSelected !== bSelected) return aSelected ? -1 : 1;
      return a.distance - b.distance;
    });
    const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
    const pad = 0.008;
    for (const c of candidates) {
      const box = {
        x0: c.x - c.halfW - pad, y0: c.y - c.halfH - pad,
        x1: c.x + c.halfW + pad, y1: c.y + c.halfH + pad,
      };
      const collides = placed.some((p) =>
        box.x0 < p.x1 && box.x1 > p.x0 && box.y0 < p.y1 && box.y1 > p.y0);
      c.marker.label.visible = !collides;
      if (!collides) placed.push(box);
    }
  }

  /** Build a continuous miter-clamped triangle strip along a polyline (nav x/y). */
  private ribbonGeometry(waypoints: [number, number][], width: number): THREE.BufferGeometry {
    const half = width / 2;
    const positions: number[] = [];
    const uvs: number[] = [];
    const indices: number[] = [];
    let travelled = 0;
    for (let i = 0; i < waypoints.length; i++) {
      const [x, y] = waypoints[i];
      let nx = 0, ny = 0;
      let miterHalf = half;
      if (i > 0 && i < waypoints.length - 1) {
        const [px0, py0] = waypoints[i - 1];
        const [nx0, ny0] = waypoints[i + 1];
        let dx1 = x - px0, dy1 = y - py0;
        const l1 = Math.hypot(dx1, dy1) || 1;
        dx1 /= l1; dy1 /= l1;
        let dx2 = nx0 - x, dy2 = ny0 - y;
        const l2 = Math.hypot(dx2, dy2) || 1;
        dx2 /= l2; dy2 /= l2;
        const n1x = -dy1, n1y = dx1;
        const n2x = -dy2, n2y = dx2;
        nx = n1x + n2x;
        ny = n1y + n2y;
        const nl = Math.hypot(nx, ny);
        if (nl > 1e-4) {
          nx /= nl; ny /= nl;
          const cosHalf = Math.max(0.45, nx * n1x + ny * n1y);
          miterHalf = Math.min(half * 1.65, half / cosHalf);
        } else {
          nx = n1x; ny = n1y;
        }
      } else {
        const prev = waypoints[Math.max(0, i - 1)];
        const next = waypoints[Math.min(waypoints.length - 1, i + 1)];
        let dx = next[0] - prev[0], dy = next[1] - prev[1];
        const len = Math.hypot(dx, dy) || 1;
        dx /= len; dy /= len;
        nx = -dy; ny = dx;
      }
      const px = nx * miterHalf, py = ny * miterHalf;
      if (i > 0) travelled += Math.hypot(x - waypoints[i - 1][0], y - waypoints[i - 1][1]);
      // left and right edges
      positions.push(x + px, 0.045, -(y + py));
      positions.push(x - px, 0.045, -(y - py));
      const u = travelled / ROUTE_TEXTURE_TILE_M;
      uvs.push(u, 0, u, 1);
      if (i > 0) {
        const a = (i - 1) * 2;
        indices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geo.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
    geo.setIndex(indices);
    return geo;
  }

  spawnAt(nav: NavData, at?: number): { position: [number, number, number]; yaw: number; pitch: number } {
    const traj = nav.trajectory;
    let pos: [number, number, number] = [0, 0, 1.6];
    let yaw = 0;
    let pitch = 0;
    if (traj.length >= 2) {
      const last = traj.length - 1;
      // The first capture frame sits at the reconstruction boundary, where the
      // splat is thinnest. Default to the middle of the walk (inside the space);
      // ?t=0 still starts at the true beginning.
      const defaultIndex = Number.isFinite(nav.default_spawn)
        ? nav.default_spawn!
        : Math.floor(last * 0.75);
      const requestedIndex = at !== undefined && Number.isFinite(at) ? at : defaultIndex;
      const i = Math.max(0, Math.min(last - 1, Math.floor(requestedIndex)));
      // trajectory z is the captured camera height; honour it on ramps and
      // slopes instead of pinning every spawn to a fixed 1.6 m.
      pos = [traj[i][0], traj[i][1], traj[i][2]];
      const capturedYaw = nav.trajectory_yaws?.[i];
      if (Number.isFinite(capturedYaw)) {
        yaw = capturedYaw!;
        pitch = nav.trajectory_pitches?.[i] ?? 0;
      } else {
        // Older captures lack recorded look directions; approximate them by
        // the path tangent while retaining their original behavior.
        const ahead = traj[Math.min(i + 10, last)];
        const dx = ahead[0] - pos[0], dy = ahead[1] - pos[1];
        yaw = Math.atan2(-dx, dy);
      }
    } else if (nav.outline.length) {
      const cx = nav.outline.reduce((s, p) => s + p[0], 0) / nav.outline.length;
      const cy = nav.outline.reduce((s, p) => s + p[1], 0) / nav.outline.length;
      pos = [cx, cy, 1.6];
    }
    return { position: pos, yaw, pitch };
  }

  render(): void {
    this.renderer.render(this.scene, this.camera);
  }

  /**
   * Draw wayfinding overlays (POI markers, selected ring, route ribbon and
   * destination ring) after the splat pass. Gaussian splats are rendered
   * separately from the three.js scene and paint over transparent scene
   * objects, so overlays need their own pass with a fresh depth buffer.
   */
  renderOverlay(): void {
    const autoClear = this.renderer.autoClear;
    this.renderer.autoClear = false;
    this.renderer.clearDepth();
    this.renderer.render(this.overlayScene, this.camera);
    this.renderer.autoClear = autoClear;
  }
}

/** Glowing multi-layer chevron stripe texture, repeated along the route. */
function routeTexture(): THREE.CanvasTexture {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, size, size);

  // Soft luminous emerald edge rails
  const railGrad = ctx.createLinearGradient(0, 0, 0, size);
  railGrad.addColorStop(0.0, 'rgba(64, 255, 154, 0.0)');
  railGrad.addColorStop(0.08, 'rgba(64, 255, 154, 0.42)');
  railGrad.addColorStop(0.18, 'rgba(64, 255, 154, 0.08)');
  railGrad.addColorStop(0.82, 'rgba(64, 255, 154, 0.08)');
  railGrad.addColorStop(0.92, 'rgba(64, 255, 154, 0.42)');
  railGrad.addColorStop(1.0, 'rgba(64, 255, 154, 0.0)');
  ctx.fillStyle = railGrad;
  ctx.fillRect(0, 0, size, size);

  // Soft emerald glow chevron
  ctx.save();
  ctx.shadowColor = '#40ff9a';
  ctx.shadowBlur = 14;
  ctx.strokeStyle = 'rgba(64, 255, 154, 0.96)';
  ctx.lineWidth = 14;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.beginPath();
  ctx.moveTo(28, 24);
  ctx.lineTo(78, 64);
  ctx.lineTo(28, 104);
  ctx.stroke();
  ctx.restore();

  // Crisp bright white-mint highlight apex
  ctx.strokeStyle = 'rgba(220, 255, 238, 0.85)';
  ctx.lineWidth = 5;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.beginPath();
  ctx.moveTo(36, 30);
  ctx.lineTo(78, 64);
  ctx.lineTo(36, 98);
  ctx.stroke();

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  return texture;
}
