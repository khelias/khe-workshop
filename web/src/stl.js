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

// The lowest and highest corner of a flat position array.
export function bounds(positions) {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < positions.length; i += 1) {
    const axis = i % 3;
    min[axis] = Math.min(min[axis], positions[i]);
    max[axis] = Math.max(max[axis], positions[i]);
  }
  return { min, max };
}

// Moves a mesh, in place, by the shift placeOnBed returned for the part it belongs to.
export function moveBy(mesh, shift) {
  for (let i = 0; i < mesh.positions.length; i += 1) mesh.positions[i] -= shift[i % 3];
}

// The triangles whose three heights pass `keep`, as a mesh of their own.
export function trianglesWhere(mesh, keep) {
  const { positions, normals } = mesh;
  const count = positions.length / 9;
  const kept = [];
  for (let t = 0; t < count; t += 1) if (keep(positions[t * 9 + 2], positions[t * 9 + 5], positions[t * 9 + 8])) kept.push(t);
  const part = { positions: new Float32Array(kept.length * 9), normals: new Float32Array(kept.length * 9) };
  kept.forEach((t, at) => {
    part.positions.set(positions.subarray(t * 9, t * 9 + 9), at * 9);
    part.normals.set(normals.subarray(t * 9, t * 9 + 9), at * 9);
  });
  return part;
}

// Moves the part, in place, to the bed's centre resting on it. Triangles reaching above
// splitAboveZ come back apart as `top`, for geometry printed in another colour.
export function placeOnBed(mesh, splitAboveZ) {
  const { min, max } = bounds(mesh.positions);
  const shift = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, min[2]];
  moveBy(mesh, shift);
  const size = [max[0] - min[0], max[1] - min[1], max[2] - min[2]];
  const whole = { positions: mesh.positions, normals: mesh.normals };
  if (splitAboveZ === null) return { whole, body: whole, top: { positions: new Float32Array(0), normals: new Float32Array(0) }, size, shift };
  const body = trianglesWhere(whole, (a, b, c) => Math.max(a, b, c) <= splitAboveZ);
  const top = trianglesWhere(whole, (a, b, c) => Math.max(a, b, c) > splitAboveZ);
  return { whole, body, top, size, shift };
}
