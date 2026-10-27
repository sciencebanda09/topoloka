/**
 * Sandbox props: small, license-clean procedural meshes that can be picked up
 * and placed in the twin. They are not scanned geometry -- the splat stays
 * read-only -- but they sit on the real floor and can become dynamic
 * obstacles for collision and routing.
 *
 * Local convention: base at y=0, long axis along X, front along -Z.
 */

import * as THREE from 'three';
import type { Footprint } from './nav';

export type PropType = 'cone' | 'barrier' | 'crate' | 'sign';

export interface PropDef {
  label: string;
  hotkey: string;
  /** half-extent along local X, nav metres */
  hw: number;
  /** half-extent along local Y, nav metres */
  hh: number;
  height: number;
}

export const PROP_DEFS: Record<PropType, PropDef> = {
  cone: { label: 'Cone', hotkey: '1', hw: 0.24, hh: 0.24, height: 0.68 },
  barrier: { label: 'Barrier', hotkey: '2', hw: 0.80, hh: 0.28, height: 1.02 },
  crate: { label: 'Crate', hotkey: '3', hw: 0.30, hh: 0.30, height: 0.52 },
  sign: { label: 'Wet floor sign', hotkey: '4', hw: 0.30, hh: 0.26, height: 0.72 },
};

export const PROP_TYPES: PropType[] = ['cone', 'barrier', 'crate', 'sign'];

export function isPropType(value: string): value is PropType {
  return (PROP_TYPES as string[]).includes(value);
}

export interface PropTransform {
  id: number;
  type: PropType;
  /** nav frame: x/y horizontal, z is three.js floor height */
  x: number;
  y: number;
  z: number;
  /** three.js yaw, radians */
  rot: number;
}

export function propFootprint(t: PropTransform): Footprint {
  const def = PROP_DEFS[t.type];
  return { x: t.x, y: t.y, hw: def.hw, hh: def.hh, rot: t.rot };
}

interface Mats {
  dark: THREE.MeshStandardMaterial;
  orange: THREE.MeshStandardMaterial;
  white: THREE.MeshStandardMaterial;
  plank: THREE.MeshStandardMaterial;
  crate: THREE.MeshStandardMaterial;
  tape: THREE.MeshStandardMaterial;
  sign: THREE.MeshStandardMaterial;
}

let mats: Mats | null = null;
let stripeTex: THREE.CanvasTexture | null = null;
let crateTex: THREE.CanvasTexture | null = null;
let signTex: THREE.CanvasTexture | null = null;

function canvasTexture(w: number, h: number, draw: (g: CanvasRenderingContext2D) => void): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const g = c.getContext('2d');
  if (!g) throw new Error('no 2d context for prop texture');
  draw(g);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

function stripes(): THREE.CanvasTexture {
  if (stripeTex) return stripeTex;
  stripeTex = canvasTexture(256, 64, (g) => {
    g.fillStyle = '#f0b429';
    g.fillRect(0, 0, 256, 64);
    g.fillStyle = '#15181d';
    for (let x = -64; x < 320; x += 64) {
      g.beginPath();
      g.moveTo(x, 64);
      g.lineTo(x + 30, 0);
      g.lineTo(x + 62, 0);
      g.lineTo(x + 32, 64);
      g.closePath();
      g.fill();
    }
  });
  stripeTex.wrapS = THREE.RepeatWrapping;
  stripeTex.repeat.set(2, 1);
  return stripeTex;
}

function cardboard(): THREE.CanvasTexture {
  if (crateTex) return crateTex;
  crateTex = canvasTexture(256, 256, (g) => {
    g.fillStyle = '#b98a5a';
    g.fillRect(0, 0, 256, 256);
    g.strokeStyle = 'rgba(80, 50, 24, 0.35)';
    g.lineWidth = 3;
    g.strokeRect(5, 5, 246, 246);
    g.fillStyle = 'rgba(236, 218, 190, 0.85)';
    g.fillRect(108, 0, 40, 256);
    g.fillStyle = 'rgba(60, 40, 22, 0.55)';
    g.font = 'bold 22px monospace';
    g.fillText('FRAGILE', 22, 42);
    g.font = '16px monospace';
    g.fillText('THIS WAY UP', 24, 228);
  });
  return crateTex;
}

function wetFloor(): THREE.CanvasTexture {
  if (signTex) return signTex;
  signTex = canvasTexture(256, 320, (g) => {
    g.fillStyle = '#f2c318';
    g.fillRect(0, 0, 256, 320);
    g.strokeStyle = '#151515';
    g.lineWidth = 12;
    g.strokeRect(8, 8, 240, 304);
    g.fillStyle = '#151515';
    g.textAlign = 'center';
    g.font = 'bold 54px sans-serif';
    g.fillText('WET', 128, 112);
    g.fillText('FLOOR', 128, 172);
    // simple slipping figure
    g.beginPath();
    g.arc(128, 218, 15, 0, Math.PI * 2);
    g.fill();
    g.lineWidth = 11;
    g.lineCap = 'round';
    g.beginPath();
    g.moveTo(128, 236);
    g.lineTo(112, 268);
    g.moveTo(112, 268);
    g.lineTo(90, 292);
    g.moveTo(128, 240);
    g.lineTo(156, 258);
    g.stroke();
  });
  return signTex;
}

function materials(): Mats {
  if (mats) return mats;
  mats = {
    dark: new THREE.MeshStandardMaterial({ color: 0x24282e, roughness: 0.85, metalness: 0.15 }),
    orange: new THREE.MeshStandardMaterial({ color: 0xe85d17, roughness: 0.7, metalness: 0.02 }),
    white: new THREE.MeshStandardMaterial({ color: 0xe9edf1, roughness: 0.55, metalness: 0.05 }),
    plank: new THREE.MeshStandardMaterial({ map: stripes(), roughness: 0.7, metalness: 0.1 }),
    crate: new THREE.MeshStandardMaterial({ map: cardboard(), roughness: 0.9, metalness: 0.0 }),
    tape: new THREE.MeshStandardMaterial({ color: 0xd8c3a5, roughness: 0.95 }),
    sign: new THREE.MeshStandardMaterial({ map: wetFloor(), roughness: 0.75, metalness: 0.0 }),
  };
  return mats;
}

function mesh(
  parent: THREE.Group,
  geo: THREE.BufferGeometry,
  mat: THREE.Material,
  x = 0, y = 0, z = 0,
  rx = 0, ry = 0, rz = 0,
): THREE.Mesh {
  const m = new THREE.Mesh(geo, mat);
  m.position.set(x, y, z);
  m.rotation.set(rx, ry, rz);
  parent.add(m);
  return m;
}

export function buildProp(type: PropType, override?: THREE.Material): THREE.Group {
  const group = new THREE.Group();
  group.userData.propType = type;
  const mat = override;
  const m = materials();

  if (type === 'cone') {
    mesh(group, new THREE.BoxGeometry(0.44, 0.06, 0.44), mat ?? m.dark, 0, 0.03, 0);
    mesh(group, new THREE.ConeGeometry(0.20, 0.62, 24), mat ?? m.orange, 0, 0.37, 0);
    mesh(group, new THREE.CylinderGeometry(0.105, 0.135, 0.11, 24, 1, true), mat ?? m.white, 0, 0.36, 0);
  } else if (type === 'barrier') {
    for (const x of [-0.64, 0.64]) {
      mesh(group, new THREE.BoxGeometry(0.34, 0.07, 0.50), mat ?? m.dark, x, 0.035, 0);
      mesh(group, new THREE.BoxGeometry(0.07, 0.98, 0.07), mat ?? m.dark, x, 0.49, 0);
    }
    mesh(group, new THREE.BoxGeometry(1.32, 0.28, 0.06), mat ?? m.plank, 0, 0.86, 0);
    mesh(group, new THREE.BoxGeometry(1.32, 0.10, 0.05), mat ?? m.dark, 0, 0.46, 0);
  } else if (type === 'crate') {
    mesh(group, new THREE.BoxGeometry(0.56, 0.50, 0.56), mat ?? m.crate, 0, 0.25, 0);
    mesh(group, new THREE.BoxGeometry(0.58, 0.012, 0.10), mat ?? m.tape, 0, 0.506, 0);
  } else {
    // A-frame floor sign
    const panel = new THREE.BoxGeometry(0.56, 0.70, 0.025);
    mesh(group, panel, mat ?? m.sign, 0, 0.36, -0.075, -0.18, 0, 0);
    mesh(group, panel, mat ?? m.sign, 0, 0.36, 0.075, 0.18, 0, 0);
    for (const x of [-0.22, 0.22]) {
      mesh(group, new THREE.BoxGeometry(0.10, 0.05, 0.42), mat ?? m.dark, x, 0.025, 0);
    }
    mesh(group, new THREE.CylinderGeometry(0.025, 0.025, 0.60, 12), mat ?? m.dark, 0, 0.72, 0, 0, 0, Math.PI / 2);
  }
  return group;
}

/** Dispose per-prop geometries. Shared materials/textures stay cached. */
export function disposeProp(group: THREE.Group): void {
  group.traverse((o) => {
    if (o instanceof THREE.Mesh) o.geometry.dispose();
  });
}
