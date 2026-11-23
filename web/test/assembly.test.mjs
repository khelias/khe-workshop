import assert from 'node:assert/strict';
import { test } from 'node:test';
import { pathAt, reach } from '../src/assembly.js';

const RISE_THEN_SPREAD = [[0, 0, 0, 0], [0.3, 0, 0, 0], [0.6, 0, 0, 45], [1, 30, -40, 45]];

test('pathAt holds the first row before 0 and the last after 1', () => {
  assert.deepEqual(pathAt(RISE_THEN_SPREAD, -0.5), [0, 0, 0]);
  assert.deepEqual(pathAt(RISE_THEN_SPREAD, 0), [0, 0, 0]);
  assert.deepEqual(pathAt(RISE_THEN_SPREAD, 1), [30, -40, 45]);
  assert.deepEqual(pathAt(RISE_THEN_SPREAD, 1.5), [30, -40, 45]);
});

function near(actual, expected) {
  actual.forEach((value, axis) => assert.ok(Math.abs(value - expected[axis]) < 1e-9, `${actual} is not ${expected}`));
}

test('pathAt is linear between the rows around t', () => {
  near(pathAt(RISE_THEN_SPREAD, 0.2), [0, 0, 0]);
  near(pathAt(RISE_THEN_SPREAD, 0.45), [0, 0, 22.5]);
  near(pathAt(RISE_THEN_SPREAD, 0.8), [15, -20, 45]);
});

test('an item without a path stays put', () => {
  assert.deepEqual(pathAt(undefined, 0.7), [0, 0, 0]);
  assert.deepEqual(pathAt([], 0.7), [0, 0, 0]);
});

test('reach covers every item at every row of its path', () => {
  const box = reach([
    { min: [-29, -29, 0], max: [29, 29, 38], path: undefined },
    { min: [-29, -29, 37], max: [29, 29, 73], path: [[0, 0, 0, 0], [0.3, 0, 0, 75], [1, 0, 0, 75]] },
    { min: [-15, -15, 16], max: [5, 5, 26], path: RISE_THEN_SPREAD },
  ]);
  assert.deepEqual(box, { min: [-29, -55, 0], max: [35, 29, 148] });
});
