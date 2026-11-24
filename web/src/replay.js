// Decodes the replay data written by scripts/replay.py and maps time to toolpath.

const MAGIC = 'KHERPL01';
const GZIP = [0x1f, 0x8b];

export function kindNumber(meta, name) {
  return meta.kinds.indexOf(name) + 1;
}

export async function loadBytes(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} answered ${response.status}`);
  return new Uint8Array(await response.arrayBuffer());
}

// A server may already have removed the gzip layer, so both forms are accepted.
export async function inflate(bytes) {
  if (bytes[0] !== GZIP[0] || bytes[1] !== GZIP[1]) return bytes;
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export function parseReplay(bytes) {
  const magic = new TextDecoder().decode(bytes.subarray(0, MAGIC.length));
  if (magic !== MAGIC) throw new Error('This file is not replay data.');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const metaLength = view.getUint32(MAGIC.length, true);
  const metaStart = MAGIC.length + 4;
  const meta = JSON.parse(new TextDecoder().decode(bytes.subarray(metaStart, metaStart + metaLength)));
  const count = meta.records;
  const start = metaStart + metaLength;
  if (bytes.length !== start + count * 5) throw new Error('The replay data is incomplete.');
  const column = (index) => bytes.subarray(start + count * index, start + count * (index + 1));
  const kinds = column(0);
  const [dxLow, dxHigh, dyLow, dyHigh] = [column(1), column(2), column(3), column(4)];
  const xs = new Float32Array(count);
  const ys = new Float32Array(count);
  let x = 0;
  let y = 0;
  for (let i = 0; i < count; i += 1) {
    const dx = dxLow[i] | (dxHigh[i] << 8);
    const dy = dyLow[i] | (dyHigh[i] << 8);
    x += (dx >>> 1) ^ -(dx & 1);
    y += (dy >>> 1) ^ -(dy & 1);
    xs[i] = x / meta.scale;
    ys[i] = y / meta.scale;
  }
  return { meta, kinds, xs, ys };
}

export async function decodeReplay(bytes) {
  return parseReplay(await inflate(bytes));
}

// Line segments in the model's frame: the walls' centre lands on the origin, turned as printed.
// The outer walls alone are built only when asked, for phones.
export function buildToolpaths(replay, rotateDeg, colourOf, withOuter = true) {
  const { meta, kinds, xs, ys } = replay;
  const [minX, minY, maxX, maxY] = meta.walls;
  const centreX = (minX + maxX) / 2;
  const centreY = (minY + maxY) / 2;
  const angle = (rotateDeg * Math.PI) / 180;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const wallKind = kindNumber(meta, 'outer-wall');
  const rgbOfKind = [null, ...meta.kinds.map((name) => colourOf(name))];
  const bounds = [...meta.layers.map((layer) => layer[1]), meta.records];
  let drawn = 0;
  let walls = 0;
  for (let i = 1; i < meta.records; i += 1) {
    if (kinds[i]) drawn += 1;
    if (withOuter && kinds[i] === wallKind) walls += 1;
  }
  const all = { positions: new Float32Array(drawn * 6), colours: new Uint8Array(drawn * 6), layerVertex: new Uint32Array(meta.layers.length + 1) };
  const outer = { positions: new Float32Array(walls * 6), colours: new Uint8Array(walls * 6), layerVertex: new Uint32Array(meta.layers.length + 1) };
  let vertex = 0;
  let wallVertex = 0;
  const put = (target, at, x0, y0, x1, y1, z, rgb, shade) => {
    const p = target.positions;
    const c = target.colours;
    const o = at * 3;
    p[o] = x0; p[o + 1] = y0; p[o + 2] = z;
    p[o + 3] = x1; p[o + 4] = y1; p[o + 5] = z;
    c[o] = c[o + 3] = rgb[0] * shade;
    c[o + 1] = c[o + 4] = rgb[1] * shade;
    c[o + 2] = c[o + 5] = rgb[2] * shade;
  };
  for (let layer = 0; layer < meta.layers.length; layer += 1) {
    all.layerVertex[layer] = vertex;
    outer.layerVertex[layer] = wallVertex;
    const z = meta.layers[layer][0];
    for (let i = Math.max(bounds[layer], 1); i < bounds[layer + 1]; i += 1) {
      const kind = kinds[i];
      if (!kind) continue;
      const ax = xs[i - 1] - centreX;
      const ay = ys[i - 1] - centreY;
      const bx = xs[i] - centreX;
      const by = ys[i] - centreY;
      const x0 = ax * cos - ay * sin;
      const y0 = ax * sin + ay * cos;
      const x1 = bx * cos - by * sin;
      const y1 = bx * sin + by * cos;
      const length = Math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2) || 1;
      // A wall's outward direction is across its travel, which gives lines a sense of light.
      const shade = 0.4 + 0.6 * Math.abs(((y1 - y0) * 0.6 + (x1 - x0) * 0.8) / length);
      const rgb = rgbOfKind[kind];
      put(all, vertex, x0, y0, x1, y1, z, rgb, shade);
      vertex += 2;
      if (withOuter && kind === wallKind) {
        put(outer, wallVertex, x0, y0, x1, y1, z, rgb, shade);
        wallVertex += 2;
      }
    }
  }
  all.layerVertex[meta.layers.length] = vertex;
  outer.layerVertex[meta.layers.length] = wallVertex;
  return { all, outer };
}

// The layer being printed at a moment, and how far through that layer the print is.
export function layerAt(layers, totalSeconds, seconds) {
  const clamped = Math.min(Math.max(seconds, 0), totalSeconds);
  let low = 0;
  let high = layers.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (layers[middle][2] <= clamped) low = middle;
    else high = middle - 1;
  }
  const start = layers[low][2];
  const end = low + 1 < layers.length ? layers[low + 1][2] : totalSeconds;
  const fraction = end > start ? Math.min((clamped - start) / (end - start), 1) : 1;
  return { index: low, fraction: clamped < start ? 0 : fraction };
}

export function verticesAt(layerVertex, position) {
  const start = layerVertex[position.index];
  const end = layerVertex[position.index + 1];
  const count = Math.round((end - start) * position.fraction / 2) * 2;
  return { start, upTo: start + count };
}

export function formatDuration(seconds) {
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} h ${minutes % 60} min` : `${minutes} min`;
}

// The plates' replayed spans, each [start, end] in its own seconds, laid end to end on one
// slider: each one's length, the seconds of the spans before it and the sum.
export function timeline(spans) {
  const before = [];
  let total = 0;
  const lengths = spans.map(([start, end]) => {
    before.push(total);
    total += end - start;
    return end - start;
  });
  return { lengths, before, total };
}

// The plate and the time in its own print at a slider value. A boundary belongs to the plate
// that starts there; a replay from above layer 1 starts at its first layer's time.
export function plateAt(spans, value, max = 1) {
  const { lengths, before, total } = timeline(spans);
  const at = Math.min(Math.max(value / max, 0), 1) * total;
  let plate = spans.length - 1;
  while (plate > 0 && at < before[plate] - total * 1e-9) plate -= 1;
  return { plate, seconds: spans[plate][0] + Math.min(Math.max(at - before[plate], 0), lengths[plate]) };
}

// A walls box [minX, minY, maxX, maxY] turned as printed, as [width, depth].
export function turnedBox([minX, minY, maxX, maxY], rotateDeg) {
  const angle = (rotateDeg * Math.PI) / 180;
  const cos = Math.abs(Math.cos(angle));
  const sin = Math.abs(Math.sin(angle));
  const width = maxX - minX;
  const depth = maxY - minY;
  return [width * cos + depth * sin, width * sin + depth * cos];
}

// Each plate's place in one row along x, in print order and centred on the bed, so a plate
// is printed where it then stands: the x offset of each plate's centre and the row's ends.
export function rowLayout(boxes, gap = 15) {
  const width = boxes.reduce((sum, [plate]) => sum + plate, 0) + gap * (boxes.length - 1);
  let x = -width / 2;
  const offsets = boxes.map(([plate]) => {
    const centre = x + plate / 2;
    x += plate + gap;
    return centre;
  });
  return { offsets, low: -width / 2, high: width / 2 };
}
