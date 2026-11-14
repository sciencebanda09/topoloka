#!/usr/bin/env node
/**
 * Convert an uncompressed `.splat` file (32 bytes/gaussian) into a compressed,
 * spatially bucketed `.ksplat` file using `@mkkellogg/gaussian-splats-3d`.
 *
 * Pre-building the SplatBuffer into `.ksplat` cuts payload size ~35-45%
 * (at compressionLevel=1) and eliminates main-thread partition/quantization
 * work inside the browser on load.
 */

import fs from 'node:fs';
import path from 'node:path';
import {
  SplatBufferGenerator,
  SplatParser,
} from '@mkkellogg/gaussian-splats-3d';

const ROW_BYTES = 32;

function parseArgs(argv) {
  const args = { input: '', output: '', minAlpha: 5, level: 1, maxGaussians: 0 };
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--min-alpha') args.minAlpha = Number(argv[++i]);
    else if (a === '--level') args.level = Number(argv[++i]);
    else if (a === '--max-gaussians') args.maxGaussians = Number(argv[++i]);
    else positional.push(a);
  }
  args.input = positional[0] ?? '';
  args.output = positional[1] ?? '';
  if (!args.input || !args.output) {
    console.error('Usage: convert_to_ksplat.mjs <in.splat> <out.ksplat> [--min-alpha 5] [--level 1] [--max-gaussians 0]');
    process.exit(2);
  }
  return args;
}

/** Keep the most visually significant splats when pruning to a web budget. */
function filterAndBudgetSplat(rawBuf, minAlpha, maxGaussians) {
  const n = Math.floor(rawBuf.byteLength / ROW_BYTES);
  const dv = new DataView(rawBuf.buffer, rawBuf.byteOffset, n * ROW_BYTES);
  const candidates = [];
  for (let i = 0; i < n; i++) {
    const off = i * ROW_BYTES;
    const alpha = rawBuf[off + 27];
    if (alpha < minAlpha) continue;
    if (maxGaussians > 0) {
      const sx = dv.getFloat32(off + 12, true);
      const sy = dv.getFloat32(off + 16, true);
      const sz = dv.getFloat32(off + 20, true);
      const maxS = Math.max(sx, sy, sz);
      if (!Number.isFinite(maxS)) continue;
      candidates.push({ i, score: alpha * Math.min(maxS, 2.0) });
    } else {
      candidates.push({ i, score: 1 });
    }
  }

  let selected = candidates;
  if (maxGaussians > 0 && candidates.length > maxGaussians) {
    candidates.sort((a, b) => b.score - a.score);
    selected = candidates.slice(0, maxGaussians);
    // Preserve spatial coherence order
    selected.sort((a, b) => a.i - b.i);
  }

  const out = new Uint8Array(selected.length * ROW_BYTES);
  for (let k = 0; k < selected.length; k++) {
    const srcOff = selected[k].i * ROW_BYTES;
    out.set(rawBuf.subarray(srcOff, srcOff + ROW_BYTES), k * ROW_BYTES);
  }
  return { nIn: n, nOut: selected.length, buffer: out.buffer };
}

const args = parseArgs(process.argv.slice(2));
const raw = fs.readFileSync(args.input);
const { nIn, nOut, buffer } = filterAndBudgetSplat(raw, args.minAlpha, args.maxGaussians);

const splatArray = SplatParser.parseStandardSplatToUncompressedSplatArray(buffer);
const generator = SplatBufferGenerator.getStandardGenerator(args.minAlpha, args.level);
const splatBuffer = generator.generateFromUncompressedSplatArray(splatArray);

fs.mkdirSync(path.dirname(path.resolve(args.output)), { recursive: true });
fs.writeFileSync(args.output, Buffer.from(splatBuffer.bufferData));

const outBytes = fs.statSync(args.output).size;
console.log(JSON.stringify({
  input: args.input,
  output: args.output,
  gaussians_in: nIn,
  gaussians_out: nOut,
  final_splat_count: splatBuffer.getSplatCount(),
  bytes_in: raw.byteLength,
  bytes_out: outBytes,
  compression_level: args.level,
}));
