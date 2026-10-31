/** Three.js scene for the twin: point cloud, floor grid, outline, trajectory.

 * The pipeline's world frame is x/y horizontal + z up (meters).
 * Three.js is Y-up, so the mapping is: three = (x, z, -y).
 */

import * as THREE from 'three';
import type { NavData } from './artifacts';

export const navToThree = (x: number, y: number, z: number): THREE.Vector3 =>
  new THREE.Vector3(x, z, -y);

const DEFAULT_HFOV_DEG = 68; // fallback when a capture has no intrinsics

export class Viewer {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene: THREE.Scene;
  readonly camera: THREE.PerspectiveCamera;
  pointsVisible = true;
  private routeLine: THREE.Mesh | null = null;
  private pointsObj: THREE.Points | null = null;
  private trajectory: THREE.Line | null = null;
  private groundGrid: THREE.GridHelper | null = null;
  private outline: THREE.LineLoop | null = null;
  private renderScale: number;
  private hFovRad = THREE.MathUtils.degToRad(DEFAULT_HFOV_DEG);

  constructor(canvas: HTMLCanvasElement, renderScale = 1) {
    this.renderScale = Math.min(1, Math.max(0.4, renderScale));
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' });
    // Draw at CSS resolution (x renderScale), not devicePixelRatio: a 2x
    // retina buffer is 4x the splat fill cost on integrated laptop GPUs.
    this.renderer.setPixelRatio(1);
    this.resizeRenderer();

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b0d10);
    this.scene.fog = new THREE.Fog(0x0b0d10, 18, 42);

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
    this.scene.add(points);
    return n;
  }

  setPointsVisible(visible: boolean): void {
    this.pointsVisible = visible;
    if (this.pointsObj) this.pointsObj.visible = visible;
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

  /** R2-ready: draw a route polyline (world x/y) slightly above the floor. */
  setRoute(waypoints: [number, number][]): void {
    if (this.routeLine) {
      this.scene.remove(this.routeLine);
      this.routeLine.geometry.dispose();
      this.routeLine = null;
    }
    if (waypoints.length < 2) return;
    // A one-pixel WebGL line disappears against the floor splat; a thin tube
    // reads as a route in the free-roam view and in a 1080p recording.
    const pts = waypoints.map(([x, y]) => navToThree(x, y, 0.06));
    const curve = new THREE.CatmullRomCurve3(pts);
    const geo = new THREE.TubeGeometry(curve, Math.min(500, Math.max(16, pts.length * 2)), 0.022, 5, false);
    const mat = new THREE.MeshBasicMaterial({ color: 0x40ff9a, transparent: true, opacity: 0.95 });
    this.routeLine = new THREE.Mesh(geo, mat);
    this.scene.add(this.routeLine);
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
}
