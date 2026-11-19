// Reads a binary STL into flat triangle arrays with face normals.

export function parseStl(bytes) {
  if (bytes.length < 84) throw new Error('This file is not a binary STL.');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const count = view.getUint32(80, true);
  if (count === 0 || bytes.length !== 84 + count * 50) throw new Error('This file is not a binary STL.');
  const positions = new Float32Array(count * 9);
  const normals = new Float32Array(count * 9);
  for (let i = 0; i < count; i += 1) {
    const record = 84 + i * 50 + 12;
    for (let v = 0; v < 9; v += 1) positions[i * 9 + v] = view.getFloat32(record + v * 4, true);
    const at = i * 9;
    const ux = positions[at + 3] - positions[at];
    const uy = positions[at + 4] - positions[at + 1];
    const uz = positions[at + 5] - positions[at + 2];
    const vx = positions[at + 6] - positions[at];
    const vy = positions[at + 7] - positions[at + 1];
    const vz = positions[at + 8] - positions[at + 2];
    const nx = uy * vz - uz * vy;
    const ny = uz * vx - ux * vz;
    const nz = ux * vy - uy * vx;
    const length = Math.sqrt(nx * nx + ny * ny + nz * nz) || 1;
    for (let corner = 0; corner < 9; corner += 3) {
      normals[at + corner] = nx / length;
      normals[at + corner + 1] = ny / length;
      normals[at + corner + 2] = nz / length;
    }
  }
  return { positions, normals, count };
}

// Moves the part, in place, to the bed's centre resting on it. Triangles reaching above
// splitAboveZ come back apart as `top`, for geometry printed in another colour.
export function placeOnBed(mesh, splitAboveZ) {
  const { positions, normals, count } = mesh;
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < positions.length; i += 3) {
    for (let axis = 0; axis < 3; axis += 1) {
      min[axis] = Math.min(min[axis], positions[i + axis]);
      max[axis] = Math.max(max[axis], positions[i + axis]);
    }
  }
  const shift = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, min[2]];
  for (let i = 0; i < positions.length; i += 1) positions[i] -= shift[i % 3];
  const size = [max[0] - min[0], max[1] - min[1], max[2] - min[2]];
  const whole = { positions, normals };
  if (splitAboveZ === null) return { whole, body: whole, top: { positions: new Float32Array(0), normals: new Float32Array(0) }, size };
  const isTop = (t) => Math.max(positions[t * 9 + 2], positions[t * 9 + 5], positions[t * 9 + 8]) > splitAboveZ;
  let topCount = 0;
  for (let t = 0; t < count; t += 1) if (isTop(t)) topCount += 1;
  const body = { positions: new Float32Array((count - topCount) * 9), normals: new Float32Array((count - topCount) * 9) };
  const top = { positions: new Float32Array(topCount * 9), normals: new Float32Array(topCount * 9) };
  let bodyAt = 0;
  let topAt = 0;
  for (let t = 0; t < count; t += 1) {
    const target = isTop(t) ? top : body;
    const at = target === top ? topAt++ : bodyAt++;
    target.positions.set(positions.subarray(t * 9, t * 9 + 9), at * 9);
    target.normals.set(normals.subarray(t * 9, t * 9 + 9), at * 9);
  }
  return { whole, body, top, size };
}
