// Fits the camera to a set of points, such as the corners of a few boxes: how far it stands and
// how far the point it looks at is lifted, so they fill the view and sit in its middle, from a
// given direction. Scene axes, Y up, points relative to the point the camera looks at.

// The camera's back, right and up directions for an azimuth about Y and an elevation above the floor.
function basis(azimuth, elevation) {
  const [sinA, cosA, sinE, cosE] = [Math.sin(azimuth), Math.cos(azimuth), Math.sin(elevation), Math.cos(elevation)];
  return { back: [cosE * sinA, sinE, cosE * cosA], right: [cosA, 0, -sinA], up: [-sinA * sinE, cosE, -cosA * sinE] };
}

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

// Halves [low, high] until it closes on where `above` turns true, and returns its end where it is.
function bisect(low, high, above) {
  for (let step = 0; step < 40; step += 1) {
    const middle = (low + high) / 2;
    if (above(middle)) high = middle;
    else low = middle;
  }
  return high;
}

// The eight corners of a box from its low and high corner.
export function corners(low, high) {
  const found = [];
  for (const x of [low[0], high[0]]) for (const y of [low[1], high[1]]) for (const z of [low[2], high[2]]) found.push([x, y, z]);
  return found;
}

// `fill` is how much of the view's height and width the points may take.
export function fitPoints(cloud, azimuth, elevation, fovDeg, aspect, fill = 0.92) {
  const { back, right, up } = basis(azimuth, elevation);
  const points = cloud.map((corner) => ({ r: dot(corner, right), u: dot(corner, up), w: dot(corner, back) }));
  const tanV = Math.tan((fovDeg * Math.PI) / 360);
  const tanH = tanV * aspect;
  // At a distance, the lift range that keeps every corner inside the view's height, or null.
  const lifts = (distance) => {
    let low = -Infinity;
    let high = Infinity;
    for (const { r, u, w } of points) {
      const depth = distance - w;
      if (depth <= 0 || Math.abs(r) > fill * depth * tanH) return null;
      low = Math.max(low, u - fill * depth * tanV);
      high = Math.min(high, u + fill * depth * tanV);
    }
    return low <= high ? [low, high] : null;
  };
  const near = Math.max(...points.map(({ w }) => w));
  let far = Math.max(near, 0) + 1;
  while (!lifts(far)) far *= 2;
  const distance = bisect(near, far, lifts);
  // Perspective draws near corners larger, so the lift that centres the box is found by halving too.
  const below = (lift) => {
    let [top, bottom] = [-Infinity, Infinity];
    for (const { u, w } of points) {
      const y = (u - lift) / ((distance - w) * tanV);
      [top, bottom] = [Math.max(top, y), Math.min(bottom, y)];
    }
    return top + bottom <= 0;
  };
  return { distance, lift: bisect(...lifts(distance), below), back, up };
}
