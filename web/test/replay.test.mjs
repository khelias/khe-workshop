import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { buildToolpaths, decodeReplay, formatDuration, layerAt, parseReplay, plateAt, rowLayout, timeline, turnedBox, verticesAt } from '../src/replay.js';
import { parseStl, placeOnBed } from '../src/stl.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

const SAMPLE = `; estimated printing time (normal mode) = 1h 0m 0s
; filament_colour = #000000;#FFFFFF
; total layers count = 3
; filament used [g] = 1.5, 0.5
T0
M83
G1 X1 Y1 E1
;TIME_ELAPSED:100
;LAYER_CHANGE
;Z:0.2
;TYPE:Outer wall
G1 X10 Y10 F3000
G1 X20 Y10 E1
G3 X30 Y20 I0 J10 E1
;TYPE:Sparse infill
G1 X30 Y30 E1
;TIME_ELAPSED:1100
;LAYER_CHANGE
;:0.4
;TYPE:Outer wall
G1 X10 Y30 E1
;TIME_ELAPSED:2100
;LAYER_CHANGE
;:0.6
T1
;TYPE:Outer wall
G1 X50 Y50 E1
`;

// A stamp in T0 in layers 1 and 2 under a T1 body; layer 2 ends in T0, so T1 comes back in layer 3.
const STAMPED = `; estimated printing time (normal mode) = 1h 0m 0s
; filament_colour = #FFFFFF;#C0201C
; total layers count = 4
T0
M83
;TIME_ELAPSED:100
;LAYER_CHANGE
;Z:0.2
;TYPE:Outer wall
G1 X90 Y90 E1
T1
G1 X91 Y90 E1
;TIME_ELAPSED:1100
;LAYER_CHANGE
;:0.44
G1 X93 Y93 E1
T0
G1 X92 Y92 E1
;TIME_ELAPSED:2100
;LAYER_CHANGE
;:0.68
T1
;TYPE:Outer wall
G1 X10 Y10
G1 X20 Y10 E1
;TIME_ELAPSED:3100
;LAYER_CHANGE
;:0.92
G1 X20 Y20 E1
`;

function encodeSample(lastLayer, source = SAMPLE, extra = []) {
  const folder = mkdtempSync(join(tmpdir(), 'replay-test-'));
  const file = join(folder, 'sample.txt');
  const out = join(folder, 'sample.bin.gz');
  writeFileSync(file, source);
  execFileSync('python3', [join(root, 'scripts', 'replay.py'), file, '--last-layer', String(lastLayer), '--out', out, ...extra], { stdio: 'pipe' });
  return new Uint8Array(readFileSync(out));
}

test('a replay round-trips from G-code, arcs included, and stops at the last layer', async () => {
  const { meta, kinds, xs, ys } = await decodeReplay(encodeSample(2));
  assert.equal(meta.layers.length, 2);
  assert.deepEqual(meta.layers.map((layer) => layer[0]), [0.2, 0.4]);
  assert.equal(meta.total_layers, 3);
  assert.equal(meta.seconds, 2100);
  assert.equal(meta.filament_g, 2);
  assert.equal(meta.colour, '#000000');
  assert.deepEqual(meta.colour_changes, [{ layer: 3, seconds: 2100, colour: '#FFFFFF' }]);
  const end = meta.layers[1][1] - 2;
  assert.ok(Math.abs(xs[end] - 30) < 0.011 && Math.abs(ys[end] - 20) < 0.011, 'the arc ends where the G-code says');
  assert.ok(end - meta.layers[0][1] > 3, 'the arc was tessellated');
  assert.equal(kinds[0], 0, 'the travel to the first wall is not drawn');
  assert.ok(Math.max(...xs) <= 30.01, 'nothing from the left-out layer is present');
});

test('a replay can start above layer 1, leaving the layers below out', async () => {
  const { meta, kinds, xs, ys } = await decodeReplay(encodeSample(4, STAMPED, ['--first-layer', '3']));
  assert.deepEqual(meta.layers.map((layer) => layer[0]), [0.68, 0.92]);
  assert.equal(meta.total_layers, 4);
  assert.equal(meta.first_layer, 3);
  assert.equal(meta.start_seconds, 2100);
  assert.equal(meta.colour, '#C0201C');
  assert.deepEqual(meta.colour_changes, []);
  assert.deepEqual(meta.below, { z: 0.44, colour: '#FFFFFF' });
  assert.equal(kinds[0], 0, 'the replay starts where the head was, without a line');
  assert.ok(Math.max(...xs.slice(1), ...ys.slice(1)) < 90, 'nothing from layers 1 and 2 is recorded');
  assert.equal(meta.layers[0][1], 0);
});

test('toolpaths are centred on the walls and turned as printed', async () => {
  const replay = await decodeReplay(encodeSample(2));
  const { all, outer } = buildToolpaths(replay, 90, () => [255, 255, 255]);
  assert.equal(all.layerVertex.length, 3);
  assert.equal(all.layerVertex[2], all.positions.length / 3);
  assert.ok(outer.positions.length < all.positions.length);
  const [minX, minY, maxX, maxY] = replay.meta.walls;
  const x = 10 - (minX + maxX) / 2;
  const y = 10 - (minY + maxY) / 2;
  assert.ok(Math.abs(all.positions[0] - -y) < 0.02 && Math.abs(all.positions[1] - x) < 0.02);
});

test('the slider maps time to the layer being printed', () => {
  const layers = [[0.2, 0, 100], [0.4, 10, 1100], [0.6, 20, 2100]];
  assert.deepEqual(plateAt([[0, 3100]], 500, 1000), { plate: 0, seconds: 1550 });
  assert.deepEqual(plateAt([[1923, 22802]], 0, 1000), { plate: 0, seconds: 1923 }, 'a replay from layer 4 starts at its first layer');
  assert.deepEqual(plateAt([[1923, 22802]], 1000, 1000), { plate: 0, seconds: 22802 });
  assert.deepEqual(layerAt(layers, 3100, 0), { index: 0, fraction: 0 });
  assert.deepEqual(layerAt(layers, 3100, 600), { index: 0, fraction: 0.5 });
  assert.deepEqual(layerAt(layers, 3100, 1100), { index: 1, fraction: 0 });
  assert.deepEqual(layerAt(layers, 3100, 3100), { index: 2, fraction: 1 });
  assert.deepEqual(layerAt(layers, 3100, 9999), { index: 2, fraction: 1 });
  assert.deepEqual(verticesAt(new Uint32Array([0, 10, 30, 40]), { index: 1, fraction: 0.5 }), { start: 10, upTo: 20 });
});

test('one slider runs through the plates one after another', () => {
  // Replayed spans of 100, 300 and 600 s, the first starting at its first layer's 20 s.
  const spans = [[20, 120], [0, 300], [50, 650]];
  assert.deepEqual(timeline(spans), { lengths: [100, 300, 600], before: [0, 100, 400], total: 1000 });
  assert.deepEqual(plateAt(spans, 0, 1000), { plate: 0, seconds: 20 });
  assert.deepEqual(plateAt(spans, 50, 1000), { plate: 0, seconds: 70 });
  assert.deepEqual(plateAt(spans, 100, 1000), { plate: 1, seconds: 0 }, 'a boundary starts the next plate');
  assert.deepEqual(plateAt(spans, 400, 1000), { plate: 2, seconds: 50 });
  for (const [index, seconds] of timeline(spans).before.entries()) assert.deepEqual(plateAt(spans, seconds / 1000), { plate: index, seconds: spans[index][0] });
  assert.deepEqual(plateAt(spans, 900, 1000), { plate: 2, seconds: 550 });
  assert.deepEqual(plateAt(spans, 1000, 1000), { plate: 2, seconds: 650 });
  assert.deepEqual(plateAt(spans, 1200, 1000), { plate: 2, seconds: 650 }, 'past the end is the end');
});

test('each plate has its own place in one row, centred, clear of its neighbours', () => {
  const cases = [
    [turnedBox([73.44, 89.7, 186.58, 170.32], 0), turnedBox([95.31, 100.31, 164.69, 159.69], 0), turnedBox([95.31, 100.31, 164.69, 159.69], 0)],
    [turnedBox([58.11, 48.96, 201.89, 211.04], 90), turnedBox([42.22, 42.22, 217.78, 217.78], 90)],
    [[10, 10], [200, 40], [30, 30], [5, 5]],
  ];
  assert.deepEqual(turnedBox([0, 0, 40, 10], 90).map(Math.round), [10, 40]);
  for (const boxes of cases) {
    const { offsets, low, high } = rowLayout(boxes);
    assert.equal(offsets.length, boxes.length);
    const spans = offsets.map((offset, index) => [offset - boxes[index][0] / 2, offset + boxes[index][0] / 2]);
    spans.forEach(([start], index) => {
      if (index) assert.ok(start > spans[index - 1][1], `plate ${index} is clear of plate ${index - 1}`);
    });
    assert.ok(Math.abs(spans[0][0] - low) < 1e-9 && Math.abs(spans.at(-1)[1] - high) < 1e-9, 'the row runs from its first plate to its last');
    assert.ok(Math.abs(low + high) < 1e-9, 'the row is centred on the bed');
  }
  assert.deepEqual(rowLayout([[40, 40]]), { offsets: [0], low: -20, high: 20 }, 'one plate stays at the centre');
});

test('durations read in hours and minutes', () => {
  assert.equal(formatDuration(59), '0 min');
  assert.equal(formatDuration(15120), '4 h 12 min');
});

test('a loader given the landing page reports a plain error', async () => {
  const html = new TextEncoder().encode('<!doctype html><html><body>khe.ee</body></html>');
  await assert.rejects(decodeReplay(html), /not replay data/);
  assert.throws(() => parseReplay(html), /not replay data/);
  assert.throws(() => parseStl(html), /not a binary STL/);
});

test('an STL is read and placed on the bed', () => {
  const bytes = new Uint8Array(84 + 50);
  const view = new DataView(bytes.buffer);
  view.setUint32(80, 1, true);
  [10, 10, 5, 20, 10, 5, 10, 30, 7].forEach((value, index) => view.setFloat32(84 + 12 + index * 4, value, true));
  const mesh = parseStl(bytes);
  assert.equal(mesh.count, 1);
  const placed = placeOnBed(mesh, null);
  assert.deepEqual(placed.size, [10, 20, 2]);
  assert.equal(placed.body.positions[2], 0);
  assert.equal(placed.top.positions.length, 0);
});
