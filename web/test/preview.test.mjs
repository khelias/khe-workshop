import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';
import { decodeReplay } from '../src/replay.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const folder = mkdtempSync(join(tmpdir(), 'workshop-preview-'));
after(() => rmSync(folder, { recursive: true, force: true }));

// A binary STL of the twelve triangles of an axis-aligned box.
function boxStl([x0, y0, z0], [x1, y1, z1]) {
  const corners = [];
  for (const x of [x0, x1]) for (const y of [y0, y1]) for (const z of [z0, z1]) corners.push([x, y, z]);
  const faces = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]];
  const bytes = Buffer.alloc(84 + faces.length * 50);
  bytes.writeUInt32LE(faces.length, 80);
  faces.forEach((face, n) => face.forEach((corner, v) => corners[corner].forEach((value, axis) => {
    bytes.writeFloatLE(value, 84 + n * 50 + 12 + v * 12 + axis * 4);
  })));
  return bytes;
}

const GCODE = `; estimated printing time (normal mode) = 10m 0s
; filament_colour = #FFFFFF;#C0201C
; total layers count = 2
T0
M83
;LAYER_CHANGE
;Z:0.2
;TYPE:Outer wall
G1 X10 Y10
G1 X20 Y10 E1
T1
G1 X20 Y20 E1
;LAYER_CHANGE
;Z:0.4
G1 X10 Y20 E1
`;

const white = boxStl([0, 0, 0], [10, 10, 10]);
const red = boxStl([0, 0, 10], [10, 10, 14]);
writeFileSync(join(folder, 'a.stl'), white);
writeFileSync(join(folder, 'b.stl'), red);
writeFileSync(join(folder, 'print.gcode'), GCODE);
writeFileSync(join(folder, 'part.json'), JSON.stringify({
  title: { et: 'Kaks kuupi', en: 'Two cubes' },
  items: [{ id: 'body', stl: 'a.stl', colour: '#ffffff' }, { id: 'top', stl: 'b.stl', colour: '#c0201c' }],
  gcode: 'print.gcode', facts: ['10 min'],
}));
const out = join(folder, 'preview.html');
execFileSync('python3', [join(root, 'scripts', 'preview.py'), join(folder, 'part.json'), '--out', out], { stdio: 'pipe' });
const page = readFileSync(out, 'utf8');
const json = (opening) => JSON.parse(page.match(new RegExp(`<script ${opening}>(.*?)</script>`, 's'))[1]);

test('an external part builds one file that links nothing outside itself', () => {
  assert.doesNotMatch(page, /\b(?:src|href)="/, 'no file is loaded from beside the page');
  assert.match(page, /<style>[^<]*\.stage/, 'the room CSS is inlined');
  assert.match(page, /<h1>Kaks kuupi<\/h1>/);
});

test('the stage shows both items in their colours, the whole model and the replay', () => {
  const config = json('type="application/json" data-stage-config');
  assert.deepEqual(config.assembly.items.map((item) => [item.stl, item.colour]), [['preview:body.stl', '#ffffff'], ['preview:top.stl', '#c0201c']]);
  assert.deepEqual(config.stageItems, [0, 1]);
  assert.equal(config.stl, 'preview:whole.stl');
  assert.equal(config.closeUp, true, 'the preview zooms with the wheel and comes close');
  assert.equal(config.plates[0].replay, 'preview:replay.bin.gz');
  const files = json('type="application/json" data-preview-files');
  assert.deepEqual(files.whole, ['body.stl', 'top.stl']);
  const unpack = (name) => gunzipSync(Buffer.from(files.data[name], 'base64'));
  assert.deepEqual(unpack('body.stl'), white);
  assert.deepEqual(unpack('top.stl'), red);
  return decodeReplay(new Uint8Array(unpack('replay.bin.gz'))).then((replay) => {
    assert.deepEqual(replay.meta.tool_colours, ['#FFFFFF', '#C0201C']);
    assert.ok(replay.tools.includes(1), 'the red tool is recorded');
  });
});

test('every module import resolves through the page import map', () => {
  const { imports } = json('type="importmap"');
  const specifier = /\b(?:from|import)\s*\(?\s*(['"])([^'"\s]+)\1/g;
  let count = 0;
  for (const url of Object.values(imports)) {
    const code = Buffer.from(url.split(',')[1], 'base64').toString('utf8');
    for (const [, , name] of code.matchAll(specifier)) {
      assert.ok(!name.startsWith('.'), `a module still imports ${name}`);
      if (!name.startsWith('khe-room/')) continue;
      assert.ok(name in imports, `${name} is not in the import map`);
      count += 1;
    }
  }
  assert.ok('khe-room/src/main.js' in imports);
  assert.ok(count >= 8, `only ${count} imports found`);
});
