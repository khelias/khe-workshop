import assert from 'node:assert/strict';
import { test } from 'node:test';
import { corners, fitPoints, pinchDelta } from '../src/frame.js';

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

// Where each corner of the box lands in the view, from -1 to 1 on each axis.
function project(cloud, azimuth, fov, aspect, fit) {
  const right = [Math.cos(azimuth), 0, -Math.sin(azimuth)];
  const tanV = Math.tan((fov * Math.PI) / 360);
  return cloud.map((point) => {
    const depth = fit.distance - dot(point, fit.back);
    return [dot(point, right) / (depth * tanV * aspect), (dot(point, fit.up) - fit.lift) / (depth * tanV)];
  });
}

test('points fill the view to the edge they meet first and sit in its middle', () => {
  const egg = [...corners([-185, -36, -70], [-45, 37, 70]), ...corners([-45, -36, -55], [55, -16, 55]), ...corners([55, -36, -55], [185, -16, 55])];
  for (const [cloud, aspect] of [[egg, 1.6], [egg, 0.5], [corners([-60, -60, -60], [60, 60, 60]), 1], [corners([-200, -124, -100], [200, 124, 100]), 0.8]]) {
    const fit = fitPoints(cloud, 0.62, 0.32, 30, aspect, 0.9);
    const points = project(cloud, 0.62, 30, aspect, fit);
    const xs = points.map(([x]) => x);
    const ys = points.map(([, y]) => y);
    assert.ok(Math.max(...xs.map(Math.abs), ...ys.map(Math.abs)) <= 0.9 + 1e-6, 'every corner is in view');
    assert.ok(Math.max(...xs.map(Math.abs)) > 0.89 || Math.max(...ys) - Math.min(...ys) > 1.79, 'the box meets an edge');
    assert.ok(Math.abs(Math.max(...ys) + Math.min(...ys)) < 1e-6, 'the box is in the middle of the view');
  }
});

test('a pinch passed on as a wheel with Ctrl zooms the camera by the pinch', async () => {
  const THREE = await import('../vendor/three/three.module.js');
  const { OrbitControls } = await import('../vendor/three/OrbitControls.js');
  const quiet = () => {};
  const element = {
    style: {}, clientWidth: 400, clientHeight: 300, addEventListener: quiet, removeEventListener: quiet,
    ownerDocument: { addEventListener: quiet, removeEventListener: quiet },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 300 }),
    getRootNode: () => ({}),
  };
  const camera = new THREE.PerspectiveCamera(24, 4 / 3, 1, 4000);
  camera.position.set(0, 0, 300);
  const controls = new OrbitControls(camera, element);
  controls.update();
  for (const scale of [1.5, 0.8]) {
    const before = camera.position.length();
    controls._onMouseWheel({ deltaY: pinchDelta(scale), deltaMode: 0, ctrlKey: true, clientX: 200, clientY: 150, preventDefault: quiet });
    assert.ok(Math.abs(before / camera.position.length() - scale) < 1e-9, `a pinch of ${scale} moves the camera to 1/${scale} of its distance`);
  }
});
