#!/usr/bin/env node
/* Compute the Listen-row waveform bars from the actual sample WAVs.

   The site claims each row carries "a waveform from the local render", so the
   bar heights must come from the audio, not a generator. Run this after
   replacing any file under public/assets/voice-samples/ and paste the printed
   arrays into src/data/samples.js (`wave` fields). Node stdlib only; assumes
   16-bit PCM WAV, which is what Vocello exports. */

import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BARS = 40;
const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const dir = path.join(root, "public/assets/voice-samples");

const rmsBars = (file) => {
  const buf = readFileSync(file);
  if (buf.toString("ascii", 0, 4) !== "RIFF" || buf.toString("ascii", 8, 12) !== "WAVE") {
    throw new Error(`${path.basename(file)}: not a RIFF/WAVE file`);
  }
  let offset = 12;
  let data = null;
  let bitsPerSample = 16;
  while (offset + 8 <= buf.length) {
    const id = buf.toString("ascii", offset, offset + 4);
    const size = buf.readUInt32LE(offset + 4);
    if (id === "fmt ") bitsPerSample = buf.readUInt16LE(offset + 22);
    if (id === "data") { data = buf.subarray(offset + 8, offset + 8 + size); break; }
    offset += 8 + size + (size % 2);
  }
  if (!data) throw new Error(`${path.basename(file)}: no data chunk`);
  if (bitsPerSample !== 16) throw new Error(`${path.basename(file)}: expected 16-bit PCM`);
  const samples = data.length >> 1;
  const perBar = Math.floor(samples / BARS);
  const bars = [];
  for (let b = 0; b < BARS; b += 1) {
    let sum = 0;
    for (let i = b * perBar; i < (b + 1) * perBar; i += 1) {
      const v = data.readInt16LE(i * 2) / 32768;
      sum += v * v;
    }
    bars.push(Math.sqrt(sum / perBar));
  }
  const peak = Math.max(...bars);
  return bars.map((v) => Math.max(0.06, Number((v / peak).toFixed(2))));
};

for (const name of readdirSync(dir).filter((f) => f.endsWith(".wav")).sort()) {
  console.log(`// ${name}`);
  console.log(`wave: [${rmsBars(path.join(dir, name)).join(", ")}],`);
}
