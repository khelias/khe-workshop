import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { bounds, moveBy, parseStl, placeOnBed } from '../src/stl.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = '/workshop/';
const SPECIFIER = /\b(?:from|import)\s*\(?\s*(['"])([^'"\s]+)\1/g;
const PAGE_URL = /\b(?:src|href)="([^"]+)"/g;
const STAGE_CONFIG = /<script type="application\/json" data-stage-config>(.*?)<\/script>/gs;

const out = mkdtempSync(join(tmpdir(), 'workshop-site-'));
after(() => rmSync(out, { recursive: true, force: true }));
execFileSync('python3', [join(root, 'scripts', 'site_build.py'), out, '--base', BASE], { stdio: 'pipe' });
const files = readdirSync(out, { recursive: true }).map(String);

function pathOf(url) {
  return url.slice(BASE.length).split('?')[0];
}

function resolves(url) {
  const path = pathOf(url);
  return url.startsWith(BASE) && existsSync(join(out, path.endsWith('/') || path === '' ? `${path}index.html` : path));
}

test('a --base build imports every module root-relative, and three.js under one URL', () => {
  const three = new Set();
  let count = 0;
  for (const name of files.filter((file) => file.endsWith('.js'))) {
    for (const [, , specifier] of readFileSync(join(out, name), 'utf8').matchAll(SPECIFIER)) {
      assert.ok(!specifier.startsWith('.'), `${name} still imports ${specifier}`);
      // A bare name only appears in three.js' comments; the page has no import map.
      if (!specifier.startsWith('/')) continue;
      assert.ok(resolves(specifier), `${name} imports ${specifier}, which the build did not write`);
      if (specifier.endsWith('/three.module.js')) three.add(specifier);
      count += 1;
    }
  }
  assert.ok(count >= 8, `only ${count} imports found`);
  assert.deepEqual([...three], [`${BASE}assets/vendor/three/three.module.js`]);
});

test('a --base build links pages and data root-relative, data with a version', () => {
  const pages = files.filter((file) => file.endsWith('.html'));
  assert.ok(pages.length >= 4);
  for (const name of pages) {
    const page = readFileSync(join(out, name), 'utf8');
    const urls = [...page.matchAll(PAGE_URL)].map((match) => match[1].replaceAll('&amp;', '&'));
    for (const [, config] of page.matchAll(STAGE_CONFIG)) {
      const { stl, replay, inlay } = JSON.parse(config);
      urls.push(stl, replay, ...(inlay ? [inlay.stl] : []));
    }
    for (const url of urls.filter((item) => !/^(?:https:|#)/.test(item))) {
      assert.ok(resolves(url), `${name} links ${url}, which the build did not write`);
      if (/\.(?:stl|gz)(?:\?|$)/.test(url)) assert.match(url, /\?v=[0-9a-f]{10}$/, `${name}: ${url} has no version`);
    }
    assert.equal((page.match(/<link rel="alternate" hreflang="(?:et|en)"/g) ?? []).length, 2, name);
    assert.ok(!page.includes('room__lang'), `${name} has its own language link`);
  }
});

function stageConfig(name) {
  const [[, config]] = readFileSync(join(out, name), 'utf8').matchAll(STAGE_CONFIG);
  return JSON.parse(config);
}

test('a replay from above layer 1 says so, and its inlay sits in the stage mesh', () => {
  const config = stageConfig(join('yarn-bowl', 'index.html'));
  assert.equal(config.first, 4);
  assert.deepEqual(config.below, { z: 0.68, label: 'valge tempel' });
  assert.match(config.inlay.stl, /^\/workshop\/data\/yarn-bowl\/yarn-bowl-stamp\.stl\?v=[0-9a-f]{10}$/);
  assert.equal(config.inlay.colour, '#FFFFFF');
  const file = (url) => new Uint8Array(readFileSync(join(out, pathOf(url))));
  const bowl = parseStl(file(config.stl));
  const placed = placeOnBed(bowl, null);
  const stamp = parseStl(file(config.inlay.stl));
  moveBy(stamp, placed.shift);
  const { min: low, max: high } = bounds(stamp.positions);
  for (const axis of [0, 1]) {
    const half = placed.size[axis] / 2;
    assert.ok(low[axis] >= -half && high[axis] <= half, `the stamp is inside the bowl on axis ${axis}`);
  }
  assert.ok(Math.abs(low[2]) < 0.001 && Math.abs(high[2] - 0.68) < 0.001, 'the stamp fills the bottom 0.68 mm');
  assert.equal(stageConfig(join('capsule-tower', 'index.html')).first, 1);
});

test('index layer counts use Estonian partitive singular kihti and English layers', () => {
  const etIndex = readFileSync(join(out, 'index.html'), 'utf8');
  const enIndex = readFileSync(join(out, 'en', 'index.html'), 'utf8');
  assert.match(etIndex, /\b\d+ kihti,/);
  assert.doesNotMatch(etIndex, /\b\d+ kihte\b/);
  assert.match(enIndex, /\b\d+ layers,/);
});

test('the index shows one part on its stage, starting in print replay', () => {
  for (const name of ['index.html', join('en', 'index.html')]) {
    assert.equal([...readFileSync(join(out, name), 'utf8').matchAll(STAGE_CONFIG)].length, 1, name);
    assert.equal(stageConfig(name).initial, 'print', name);
  }
  assert.equal(stageConfig(join('capsule-tower', 'index.html')).initial, undefined);
});
