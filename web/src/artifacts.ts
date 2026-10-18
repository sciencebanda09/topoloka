/** Types + loaders for the pipeline's artifact bundle (nav.json, cloud.ply). */

export interface NavGrid {
  w: number;
  h: number;
  encoding: string;
  legend: Record<string, string>;
  data_b64: string;
}

export interface NavData {
  version: number;
  units: string;
  cell_m: number;
  origin: [number, number];
  grid: NavGrid;
  outline: [number, number][];
  trajectory: [number, number, number][];
  scale_m_per_unit: number;
  cam_height_units: number;
  down_axis_source: string;
}

export const FREE = 0, OBSTACLE = 1, UNKNOWN = 2;

export async function loadNav(base: string): Promise<NavData> {
  const res = await fetch(`${base}/nav.json`);
  if (!res.ok) throw new Error(`nav.json: HTTP ${res.status}`);
  return (await res.json()) as NavData;
}

/** Decode the base64 PNG grid into {w, h, data} of palette indices (0/1/2). */
export async function decodeGrid(grid: NavGrid): Promise<{ w: number; h: number; data: Uint8Array }> {
  const img = new Image();
  img.src = `data:image/png;base64,${grid.data_b64}`;
  await img.decode();
  const canvas = new OffscreenCanvas(img.width, img.height);
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('no 2d context');
  ctx.drawImage(img, 0, 0);
  const px = ctx.getImageData(0, 0, img.width, img.height).data;
  const data = new Uint8Array(img.width * img.height);
  for (let i = 0; i < data.length; i++) data[i] = px[i * 4]; // grayscale: R holds the value
  return { w: img.width, h: img.height, data };
}

export async function loadCloud(base: string): Promise<{ positions: Float32Array; colors: Uint8Array } | null> {
  try {
    const res = await fetch(`${base}/cloud.ply`);
    if (!res.ok) return null;
    return parsePlyBinary(await res.arrayBuffer());
  } catch {
    return null;
  }
}

/** Binary little-endian PLY with xyz float32 + rgb uint8 (our pipeline's format). */
export function parsePlyBinary(buf: ArrayBuffer): { positions: Float32Array; colors: Uint8Array } {
  const bytes = new Uint8Array(buf);
  const headerEnd = findHeaderEnd(bytes);
  const header = new TextDecoder('ascii').decode(bytes.subarray(0, headerEnd));
  const m = header.match(/element vertex (\d+)/);
  if (!m) throw new Error('PLY: no vertex count');
  const n = parseInt(m[1], 10);
  const hasRgb = /property uchar red/.test(header);
  const stride = 3 * 4 + (hasRgb ? 3 : 0);
  const body = new DataView(buf, headerEnd);
  const positions = new Float32Array(n * 3);
  const colors = new Uint8Array(n * 3);
  for (let i = 0; i < n; i++) {
    const off = i * stride;
    positions[i * 3 + 0] = body.getFloat32(off + 0, true);
    positions[i * 3 + 1] = body.getFloat32(off + 4, true);
    positions[i * 3 + 2] = body.getFloat32(off + 8, true);
    if (hasRgb) {
      colors[i * 3 + 0] = body.getUint8(off + 12);
      colors[i * 3 + 1] = body.getUint8(off + 13);
      colors[i * 3 + 2] = body.getUint8(off + 14);
    } else {
      colors[i * 3 + 0] = colors[i * 3 + 1] = colors[i * 3 + 2] = 200;
    }
  }
  return { positions, colors };
}

function findHeaderEnd(bytes: Uint8Array): number {
  const marker = 'end_header\n';
  const text = new TextDecoder('ascii').decode(bytes.subarray(0, Math.min(bytes.length, 4096)));
  const idx = text.indexOf(marker);
  if (idx < 0) throw new Error('PLY: end_header not found');
  return idx + marker.length;
}
