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

export interface SplatHit {
  point: THREE.Vector3;
  normal: THREE.Vector3;
  distance: number;
}

export interface SplatLoadProgress {
  phase: 'downloading' | 'building';
  percent: number | null;
  loadedBytes: number;
  totalBytes: number;
}

export type SplatFileFormat = 'ksplat' | 'splat';

export interface SplatLoadOptions {
  format?: SplatFileFormat;
  signal?: AbortSignal;
  onProgress?: (progress: SplatLoadProgress) => void;
  buildTimeoutMs?: number;
}

export function inferSplatFormat(url: string, explicit?: SplatFileFormat): SplatFileFormat {
  if (explicit) return explicit;
  return url.split('?')[0].toLowerCase().endsWith('.ksplat') ? 'ksplat' : 'splat';
}

/**
 * Stream a `.splat` response into a Blob while reporting byte progress.
 * GitHub Pages sends `Content-Encoding: gzip`, so `Content-Length` may reflect
 * compressed wire bytes while `getReader()` yields decompressed bytes; clamp
 * streamed percentages at 99% until EOF to avoid >100% glitches.
 */
export async function fetchSplatBlob(
  url: string,
  signal?: AbortSignal,
  onProgress?: (progress: SplatLoadProgress) => void,
): Promise<{ blob: Blob; loadedBytes: number; totalBytes: number }> {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`splat fetch failed: ${res.status} ${res.statusText}`);

  const rawLength = Number(res.headers.get('content-length'));
  const totalBytes = Number.isFinite(rawLength) && rawLength > 0 ? rawLength : 0;

  if (!res.body) {
    const bytes = await res.arrayBuffer();
    const loadedBytes = bytes.byteLength;
    onProgress?.({ phase: 'downloading', percent: 100, loadedBytes, totalBytes: totalBytes || loadedBytes });
    return {
      blob: new Blob([bytes], { type: 'application/octet-stream' }),
      loadedBytes,
      totalBytes: totalBytes || loadedBytes,
    };
  }

  const reader = res.body.getReader();
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let loadedBytes = 0;
  let lastReported = -1;

  onProgress?.({ phase: 'downloading', percent: totalBytes ? 0 : null, loadedBytes: 0, totalBytes });
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value && value.byteLength > 0) {
        chunks.push(new Uint8Array(value));
        loadedBytes += value.byteLength;
        const percent = totalBytes > 0
          ? Math.min(99, Math.round((loadedBytes / Math.max(totalBytes, loadedBytes)) * 100))
          : null;
        if (percent !== lastReported || percent === null) {
          lastReported = percent ?? -1;
          onProgress?.({ phase: 'downloading', percent, loadedBytes, totalBytes });
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  onProgress?.({ phase: 'downloading', percent: 100, loadedBytes, totalBytes: Math.max(totalBytes, loadedBytes) });
  return {
    blob: new Blob(chunks, { type: 'application/octet-stream' }),
    loadedBytes,
    totalBytes: Math.max(totalBytes, loadedBytes),
  };
}

interface RawSplatHit {
  origin: THREE.Vector3;
  normal: THREE.Vector3;
  distance: number;
}

interface ViewerRaycaster {
  ray: { origin: THREE.Vector3; direction: THREE.Vector3 };
  intersectSplatMesh(mesh: unknown, out?: RawSplatHit[]): void;
}

export class SplatLayer {
  loaded = false;
  gaussianCount = 0;

  private viewer: GaussianSplats3D.Viewer;
  private options: Required<SplatOptions>;

  constructor(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.Camera,
              options: SplatOptions = {}) {
    this.options = {
      alphaThreshold: options.alphaThreshold ?? 5,
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
      dynamicScene: true,
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

  async load(url: string, nav: NavData, loadOptions: SplatLoadOptions = {}): Promise<void> {
    const { format, signal, onProgress, buildTimeoutMs = 120_000 } = loadOptions;
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const resolvedFormat = inferSplatFormat(url, format);
    const sceneFormat = resolvedFormat === 'ksplat'
      ? GaussianSplats3D.SceneFormat.KSplat
      : GaussianSplats3D.SceneFormat.Splat;

    const m = SplatLayer.placementMatrix(nav);
    const position = new THREE.Vector3();
    const rotation = new THREE.Quaternion();
    const scale = new THREE.Vector3(1, 1, 1);
    if (m) m.decompose(position, rotation, scale);

    // Fetch the splat ourselves and hand the library a blob: URL.
    // Static hosts serve .splat/.ksplat with Content-Encoding: gzip, and the library
    // sizes its staging buffer from the Content-Length header -- which is then
    // the *compressed* size -- so the decoded stream overruns it mid-download
    // ("RangeError: Invalid typed array length"). A blob URL carries the exact
    // byte length (or none, in which case the library safely buffers first).
    const { blob, loadedBytes, totalBytes } = await fetchSplatBlob(url, signal, onProgress);
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');

    onProgress?.({ phase: 'building', percent: null, loadedBytes, totalBytes });
    // Yield a macrotask so the DOM paints "building scene..." before SplatBuffer init runs.
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const blobUrl = URL.createObjectURL(blob);

    try {
      // The library's custom AbortablePromise ignores rejection callbacks, so a
      // failed load would hang this await forever; race it against timeout + abort.
      await withTimeoutAndAbort(
        this.viewer.addSplatScene(blobUrl, {
          format: sceneFormat, // blob URLs carry no extension
          showLoadingUI: false,
          splatAlphaRemovalThreshold: this.options.alphaThreshold,
          position: position.toArray(),
          rotation: rotation.toArray(), // xyzw
          scale: scale.toArray(),
        }) as unknown as Promise<void>,
        buildTimeoutMs,
        'splat build timed out',
        signal,
      );
    } finally {
      URL.revokeObjectURL(blobUrl);
    }
    this.loaded = true;
  }

  dispose(): void {
    this.loaded = false;
    try {
      const view = this.viewer as unknown as { dispose?: () => Promise<void> | void };
      void Promise.resolve(view.dispose?.()).catch(() => { /* ignore shutdown errors */ });
    } catch {
      /* ignore shutdown errors */
    }
  }

  /**
   * Cast an arbitrary world ray against the splat BVH. The library builds the
   * tree for its own focal-point picker; we reuse it so sandbox props land on
   * the real floor instead of an assumed flat plane.
   */
  raycastRay(origin: THREE.Vector3, direction: THREE.Vector3): SplatHit | null {
    if (!this.loaded) return null;
    const view = this.viewer as unknown as { raycaster?: ViewerRaycaster; splatMesh?: unknown };
    if (!view.raycaster || !view.splatMesh) return null;
    try {
      view.raycaster.ray.origin.copy(origin);
      view.raycaster.ray.direction.copy(direction).normalize();
      const hits: RawSplatHit[] = [];
      view.raycaster.intersectSplatMesh(view.splatMesh, hits);
      let hit: RawSplatHit | null = null;
      for (const h of hits) {
        if (h.distance < 0) continue;
        if (!hit || h.distance < hit.distance) hit = h;
      }
      if (!hit) return null;
      return {
        point: hit.origin.clone(),
        normal: hit.normal.clone(),
        distance: hit.distance,
      };
    } catch {
      return null;
    }
  }

  update(): void {
    this.viewer.update();
  }

  setVisible(visible: boolean): void {
    const view = this.viewer as unknown as { splatMesh?: THREE.Object3D };
    if (view.splatMesh) view.splatMesh.visible = visible;
  }

  setExtraTransform(rxDeg: number, ryDeg: number, rzDeg: number, oyMeters: number, pivot?: THREE.Vector3): void {
    const view = this.viewer as unknown as { splatMesh?: THREE.Mesh };
    if (!view.splatMesh) return;
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

    view.splatMesh.position.copy(pos);
    view.splatMesh.quaternion.copy(quat);
    view.splatMesh.scale.copy(scale);
    view.splatMesh.updateMatrix();
    view.splatMesh.updateMatrixWorld(true);
  }

  render(): void {
    this.viewer.render();
  }
}

/** Settle `p`, or reject if aborted or taking longer than `ms` (see AbortablePromise note above). */
function withTimeoutAndAbort<T>(
  p: Promise<T>,
  ms: number,
  message: string,
  signal?: AbortSignal,
): Promise<T> {
  if (signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
  return new Promise<T>((resolve, reject) => {
    const cleanup = () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    };
    const onAbort = () => {
      cleanup();
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error(message));
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
    p.then(
      (value) => {
        cleanup();
        resolve(value);
      },
      (err) => {
        cleanup();
        reject(err);
      },
    );
  });
}
