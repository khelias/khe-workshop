// The parts view's motion: each item follows its own path of [t, dx, dy, dz] rows on one slider.

const STILL = [0, 0, 0];

// An item's offset at t, linear between the rows; before the first row it is at the first, after
// the last at the last. An item without a path stays where its source put it.
export function pathAt(path, t) {
  if (!path?.length) return STILL;
  if (t <= path[0][0]) return path[0].slice(1);
  for (let i = 1; i < path.length; i += 1) {
    const [end, ...to] = path[i];
    if (t > end) continue;
    const [begin, ...from] = path[i - 1];
    const share = (t - begin) / (end - begin);
    return from.map((value, axis) => value + (to[axis] - value) * share);
  }
  return path[path.length - 1].slice(1);
}

// The box every item stays inside over the whole slider: the motion is linear between rows, so
// its far points are at the rows.
export function reach(items) {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (const item of items) {
    for (const offset of item.path?.length ? item.path.map((row) => row.slice(1)) : [STILL]) {
      for (let axis = 0; axis < 3; axis += 1) {
        min[axis] = Math.min(min[axis], item.min[axis] + offset[axis]);
        max[axis] = Math.max(max[axis], item.max[axis] + offset[axis]);
      }
    }
  }
  return { min, max };
}
