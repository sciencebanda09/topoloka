/** Three.js scene for the twin: point cloud, floor grid, outline, trajectory.

 * The pipeline's world frame is x/y horizontal + z up (meters).
 * Three.js is Y-up, so the mapping is: three = (x, z, -y).
 */

import * as THREE from 'three';
import type { NavData } from './artifacts';

export const navToThree = (x: number, y: number, z: number): THREE.Vector3 =>
  new THREE.Vector3(x, z, -y);

export class Viewer {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene: THREE.Scene;
  readonly camera: THREE.PerspectiveCamera;
  pointsVisible = true;
  private routeLine: THREE.Line | null = null;
  private pointsObj: THREE.Points | null = null;
  private trajectory: THREE.Line | null = null;

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(window.innerWidth, window.innerHeight);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b0d10);
    this.scene.fog = new THREE.Fog(0x0b0d10, 18, 42);

    this.camera = new THREE.PerspectiveCamera(72, window.innerWidth / window.innerHeight, 0.05, 200);

    window.addEventListener('resize', () => {
      this.camera.aspect = window.innerWidth / window.innerHeight;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(window.innerWidth, window.innerHeight);
    });
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
    this.scene.add(new THREE.LineLoop(geo, mat));
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
    this.scene.add(grid);
  }

  /** R2-ready: draw a route polyline (world x/y) slightly above the floor. */
  setRoute(waypoints: [number, number][]): void {
    if (this.routeLine) {
      this.scene.remove(this.routeLine);
      this.routeLine.geometry.dispose();
      this.routeLine = null;
    }
    if (waypoints.length < 2) return;
    const pts = waypoints.map(([x, y]) => navToThree(x, y, 0.06));
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const mat = new THREE.LineBasicMaterial({ color: 0x40e08a });
    this.routeLine = new THREE.Line(geo, mat);
    this.scene.add(this.routeLine);
  }

  spawnAt(nav: NavData, at?: number): { position: [number, number, number]; yaw: number } {
    const traj = nav.trajectory;
    let pos: [number, number, number] = [0, 0, 1.6];
    let yaw = 0;
    if (traj.length >= 2) {
      const last = traj.length - 1;
      // The first capture frame sits at the reconstruction boundary, where the
      // splat is thinnest. Default to the middle of the walk (inside the space);
      // ?t=0 still starts at the true beginning.
      const i = at !== undefined && Number.isFinite(at)
        ? Math.max(0, Math.min(last - 1, Math.floor(at)))
        : Math.floor(last * 0.75);
      pos = [traj[i][0], traj[i][1], 1.6];
      const ahead = traj[Math.min(i + 10, last)];
      const dx = ahead[0] - pos[0], dy = ahead[1] - pos[1];
      // three forward at yaw: f = (-sin(yaw), 0, -cos(yaw)); nav f = (f.x, -f.z)
      yaw = Math.atan2(-dx, dy);
    } else if (nav.outline.length) {
      const cx = nav.outline.reduce((s, p) => s + p[0], 0) / nav.outline.length;
      const cy = nav.outline.reduce((s, p) => s + p[1], 0) / nav.outline.length;
      pos = [cx, cy, 1.6];
    }
    return { position: pos, yaw };
  }

  render(): void {
    this.renderer.render(this.scene, this.camera);
  }
}
