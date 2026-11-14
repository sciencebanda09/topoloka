import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchSplatBlob, SplatLayer, type SplatLoadProgress } from '../src/splat';
import type { NavData } from '../src/artifacts';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('fetchSplatBlob', () => {
  it('streams chunks, clamps compressed Content-Length overruns to 99%, and finishes at 100%', async () => {
    const encoder = new Uint8Array([1, 2, 3, 4, 5, 6]);
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.subarray(0, 3));
        controller.enqueue(encoder.subarray(3, 6));
        controller.close();
      },
    });
    // Simulate GitHub Pages gzip Content-Length smaller than decompressed bytes (4 < 6).
    const mockRes = new Response(stream, {
      status: 200,
      headers: { 'content-length': '4' },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockRes));

    const updates: SplatLoadProgress[] = [];
    const { blob, loadedBytes } = await fetchSplatBlob('/fake.splat', undefined, (p) => updates.push(p));

    expect(loadedBytes).toBe(6);
    expect(blob.size).toBe(6);
    expect(updates[0].percent).toBe(0);
    // Clamped below 100 while still streaming despite decompressed > content-length.
    for (const mid of updates.slice(1, -1)) {
      expect(mid.percent).not.toBeNull();
      expect(mid.percent!).toBeLessThanOrEqual(99);
    }
    expect(updates[updates.length - 1]).toMatchObject({ phase: 'downloading', percent: 100, loadedBytes: 6 });
  });

  it('rejects cleanly when the HTTP request fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 404, statusText: 'Not Found' })));
    await expect(fetchSplatBlob('/missing.splat')).rejects.toThrow('splat fetch failed: 404 Not Found');
  });
});

describe('SplatLayer.placementMatrix', () => {
  it('returns null when alignment metadata is absent', () => {
    const nav = { align: {} } as unknown as NavData;
    expect(SplatLayer.placementMatrix(nav)).toBeNull();
  });
});
