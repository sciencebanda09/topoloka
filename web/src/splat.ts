/**
 * Gaussian splat layer: wraps @mkkellogg/gaussian-splats-3d in drop-in mode
 * (renders into our scene / renderer / camera).
 *
 * Frame math -- the splat is trained in the reconstruction frame (the same
 * frame as transforms.json / the raw sparse cloud). nav.json carries the
 * exact alignment:
 *
 *     p_nav = scale * R^T @ (p_scene - origin)      (nav: x/y ground, z up, m)
 *     p_three = A @ p_nav,  A = [[1,0,0],[0,0,1],[0,-1,0]]   (three.js Y-up)
 *
 * so the splat scene transform is  p_three = A * scale * R^T @ (p_scene - origin).
 * (Training runs with nerfstudio's auto-orient/center/scale DISABLED, otherwise
 * the trainer would write its own hidden transform into the exported splat.)
 */

import * as GaussianSplats3D from '@mkkellogg/gaussian-splats-3d';
import * as THREE from 'three';
import type { NavData } from './artifacts';

export interface SplatOptions {
  /** Ignore gaussians below this alpha byte (0-255) at load. */
  alphaThreshold?: number;
  /** Clamp screen-space splat diameter; huge off-path splats are fill-rate poison. */
  maxScreenSpaceSplatSize?: number;
}

export class SplatLayer {
  loaded = false;
  gaussianCount = 0;

  private viewer: GaussianSplats3D.Viewer;
  private options: Required<SplatOptions>;

  constructor(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.Camera,
              options: SplatOptions = {}) {
    this.options = {
      alphaThreshold: options.alphaThreshold ?? 40,
      maxScreenSpaceSplatSize: options.maxScreenSpaceSplatSize ?? 1024,
    };
    this.viewer = new GaussianSplats3D.Viewer({
      threeScene: scene,
      selfDrivenMode: false,
      renderer,
      camera,
      useBuiltInControls: false,
      // static hosting (Vercel/CF Pages) does not send COOP/COEP headers,
      // so SharedArrayBuffer-based sorting is unavailable -- keep both off.
      sharedMemoryForWorkers: false,
      gpuAcceleratedSort: false,
      sphericalHarmonicsDegree: 0,
      sceneRevealMode: GaussianSplats3D.SceneRevealMode.Instant,
      logLevel: GaussianSplats3D.LogLevel.None,
      focalAdjustment: 1.0,
      maxScreenSpaceSplatSize: this.options.maxScreenSpaceSplatSize,
    });
  }

  static placementMatrix(nav: NavData): THREE.Matrix4 | null {
    const a = nav.align;
    if (!a || !a.R_row_major) return null;
    // row-major input -> Matrix3 (which is column-major): load then transpose
    const R = new THREE.Matrix3().fromArray(a.R_row_major.flat() as number[]).transpose();
    const Rt = R.clone().transpose();
    const A = new THREE.Matrix3().set(1, 0, 0, 0, 0, 1, 0, -1, 0);
    const M3 = A.multiply(Rt).multiplyScalar(a.scale_m_per_unit); // A * s * R^T
    const M = new THREE.Matrix4().setFromMatrix3(M3);
    const origin = new THREE.Vector3(a.origin[0], a.origin[1], a.origin[2]);
    M.setPosition(origin.clone().applyMatrix3(M3).multiplyScalar(-1));
    return M;
  }

  async load(url: string, nav: NavData): Promise<void> {
    const m = SplatLayer.placementMatrix(nav);
    const position = new THREE.Vector3();
    const rotation = new THREE.Quaternion();
    const scale = new THREE.Vector3(1, 1, 1);
    if (m) m.decompose(position, rotation, scale);

    // Fetch the .splat ourselves and hand the library a blob: URL.
    // GitHub Pages serves .splat with Content-Encoding: gzip, and the library
    // sizes its staging buffer from the Content-Length header -- which is then
    // the *compressed* size -- so the decoded stream overruns it mid-download
    // ("RangeError: Invalid typed array length"). A blob URL carries the exact
    // byte length (or none, in which case the library safely buffers first).
    const res = await fetch(url);
    if (!res.ok) throw new Error(`splat fetch failed: ${res.status} ${res.statusText}`);
    const bytes = await res.arrayBuffer();
    const blobUrl = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }));

    try {
      // The library's custom AbortablePromise ignores rejection callbacks, so a
      // failed load would hang this await forever; race it against a timeout.
      await withTimeout(
        this.viewer.addSplatScene(blobUrl, {
          format: GaussianSplats3D.SceneFormat.Splat, // blob URLs carry no extension
          showLoadingUI: false,
          splatAlphaRemovalThreshold: this.options.alphaThreshold,
          position: position.toArray(),
          rotation: rotation.toArray(), // xyzw
          scale: scale.toArray(),
        }) as unknown as Promise<void>,
        180_000,
        'splat build timed out',
      );
    } finally {
      URL.revokeObjectURL(blobUrl);
    }
    this.loaded = true;
  }

  update(): void {
    this.viewer.update();
  }

  render(): void {
    this.viewer.render();
  }
}

/** Settle `p`, or reject if it takes longer than `ms` (see AbortablePromise note above). */
function withTimeout<T>(p: Promise<T>, ms: number, message: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), ms);
    p.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err) => {
        clearTimeout(timer);
        reject(err);
      },
    );
  });
}
