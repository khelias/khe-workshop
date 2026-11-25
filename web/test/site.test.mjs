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
      const { stl, plates, closeUp, text } = JSON.parse(config);
      assert.equal(closeUp, undefined, `${name}: the room's wheel scrolls past its stage`);
      assert.match(text.zoom_hint, /\{key\}/, `${name}: the hint names the key to zoom with`);
      urls.push(stl, ...plates.flatMap((plate) => [plate.replay, ...(plate.inlay ? [plate.inlay.stl] : [])]));
    }
    for (const url of urls.filter((item) => !/^(?:https:|#)/.test(item))) {
      assert.ok(resolves(url), `${name} links ${url}, which the build did not write`);
      if (/\.(?:stl|gz)(?:\?|$)/.test(url)) assert.match(url, /\?v=[0-9a-f]{10}$/, `${name}: ${url} has no version`);
    }
    if (page.includes('data-stage-config')) assert.ok(page.includes('data-stage-hint') && page.includes('data-stage-home'), `${name}: the stage has its zoom hint and way back`);
    assert.equal((page.match(/<link rel="alternate" hreflang="(?:et|en)"/g) ?? []).length, 2, name);
    assert.ok(!page.includes('room__lang'), `${name} has its own language link`);
  }
});

function stageConfig(name) {
  const [[, config]] = readFileSync(join(out, name), 'utf8').matchAll(STAGE_CONFIG);
  return JSON.parse(config);
}

function stagePlate(name) {
  const { plates } = stageConfig(name);
  const stage = plates.filter((plate) => plate.stage);
  assert.equal(stage.length, 1, `${name} has one stage plate`);
  return stage[0];
}

test('a replay from above layer 1 says so, and its inlay sits in the stage mesh', () => {
  const config = { ...stageConfig(join('yarn-bowl', 'index.html')), ...stagePlate(join('yarn-bowl', 'index.html')) };
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
  assert.equal(stagePlate(join('capsule-tower', 'index.html')).first, 1);
});

test('a part printed on one plate keeps its replay, colour, first layer and labels on one stage plate', () => {
  const bowl = stageConfig(join('yarn-bowl', 'index.html'));
  assert.equal(bowl.plates.length, 1);
  assert.match(bowl.plates[0].replay, /^\/workshop\/data\/yarn-bowl\/replay\.bin\.gz\?v=/);
  assert.equal(bowl.plates[0].colour, '#C0201C');
  assert.equal(bowl.plates[0].top, undefined);
  for (const gone of ['replay', 'colour', 'first', 'top', 'below', 'inlay']) assert.ok(!(gone in bowl), `no top-level ${gone}`);
  const mount = stageConfig(join('u6lr-schuko-mount', 'index.html'));
  assert.equal(mount.plates.length, 1);
  assert.deepEqual({ ...mount.plates[0], replay: pathOf(mount.plates[0].replay) },
    { replay: 'data/u6lr-schuko-mount/replay.bin.gz', colour: '#F2754E', rotate: 0, first: 1, title: 'U6-LR hoidik pistikupessa', stage: true });
});

test('a part printed on several plates links a versioned replay for each, in print order', () => {
  const egg = stageConfig(join('soma-egg', 'index.html'));
  assert.deepEqual(egg.plates.map((plate) => pathOf(plate.replay)), ['blue', 'red', 'white'].map((id) => `data/soma-egg/replay-${id}.bin.gz`));
  for (const plate of egg.plates) assert.match(plate.replay, /\?v=[0-9a-f]{10}$/);
  assert.deepEqual(egg.plates.map((plate) => plate.colour), ['#4b8fe0', '#e23a2e', '#f5f3ee']);
  assert.deepEqual(egg.plates.map((plate) => plate.title), ['Muna ja kork', 'Neli punast tükki', 'Kolm valget tükki']);
  assert.ok(egg.plates.every((plate) => !plate.stage), 'the egg has no stage plate');
  const tower = stageConfig(join('capsule-tower', 'index.html'));
  assert.deepEqual(tower.plates.map((plate) => [plate.title, plate.stage]), [['Torn', true], ['Alus', false]]);
  assert.equal(tower.plates[0].top.label, 'valge tempel');
  assert.equal(tower.plates[1].top, undefined);
  assert.equal(stageConfig('index.html').plates.length, 2, 'the index hero is the tower on its two plates');
});

function facts(name) {
  const page = readFileSync(join(out, name), 'utf8');
  return page.slice(page.indexOf('<h2>Prinditöö</h2>') >= 0 ? page.indexOf('<h2>Prinditöö</h2>') : page.indexOf('<h2>The print</h2>'));
}

test('the facts of a part on several plates have a row per plate and the total, summed before rounding', () => {
  const egg = facts(join('soma-egg', 'index.html'));
  assert.match(egg, /<th scope="row">Kokku<\/th><td><\/td><td class="fact">2 h 18 min<\/td><td class="fact">58 g<\/td>/);
  assert.match(egg, /Muna ja kork<\/th><td class="fact">228<\/td><td class="fact">1 h 33 min<\/td><td class="fact">43 g/);
  assert.match(egg, /Neli punast tükki<\/th><td class="fact">99<\/td><td class="fact">24 min<\/td>/);
  assert.match(egg, /Kolm valget tükki<\/th><td class="fact">99<\/td><td class="fact">20 min<\/td>/);
  assert.match(facts(join('en', 'soma-egg', 'index.html')), /<th scope="row">Total<\/th><td><\/td><td class="fact">2 h 18 min<\/td><td class="fact">58 g<\/td>/);
  const tower = facts(join('capsule-tower', 'index.html'));
  assert.match(tower, /Kokku<\/th><td><\/td><td class="fact">15 h 47 min<\/td><td class="fact">603 g<\/td>/);
  assert.match(tower, /<dt>Täide<\/dt><dd class="fact">10%, 15%<\/dd>/, 'settings that differ list each value');
  assert.match(egg, /<dt>Täide<\/dt><dd class="fact">15%<\/dd>/, 'a shared setting is listed once');
  const bowl = facts(join('yarn-bowl', 'index.html'));
  assert.doesNotMatch(bowl, /Kokku|class="swatch"/, 'a part on one plate has no plate table');
  assert.match(bowl, /<dt>Kihte<\/dt>/);
});

test('fit tests are listed apart under their heading, and closed exports share one proof line', () => {
  for (const [name, heading] of [[join('soma-egg', 'index.html'), 'Sobivusproovid'], [join('en', 'u6lr-schuko-mount', 'index.html'), 'Fit tests']]) {
    const page = readFileSync(join(out, name), 'utf8');
    const files = page.slice(page.indexOf('id="files"'));
    const [main, tests] = files.split(`<h3>${heading}</h3>`);
    assert.ok(tests, `${name} has the ${heading} heading`);
    assert.doesNotMatch(main, /test-|lock-test|plug-test/, `${name} lists no fit test before the heading`);
    assert.match(tests.slice(0, tests.indexOf('</ul>')), /test/, `${name} lists its fit tests under the heading`);
  }
  const egg = readFileSync(join(out, 'soma-egg', 'index.html'), 'utf8');
  assert.match(egg, /<li>7 terviklikku mudelit, kõik mahuvad printeri 260 mm prindialusele\.<\/li>/);
  assert.equal((egg.match(/terviklik mudel, mahub/g) ?? []).length, 0);
});

test('index layer counts use Estonian partitive singular kihti and English layers', () => {
  const etIndex = readFileSync(join(out, 'index.html'), 'utf8');
  const enIndex = readFileSync(join(out, 'en', 'index.html'), 'utf8');
  assert.match(etIndex, /\b\d+ kihti,/);
  assert.doesNotMatch(etIndex, /\b\d+ kihte\b/);
  assert.match(enIndex, /\b\d+ layers,/);
  assert.match(etIndex, />3 plaati, 2 h 18 min</);
  assert.match(enIndex, />3 plates, 2 h 18 min</);
  assert.match(etIndex, />2 plaati, 15 h 47 min</);
});

test('a part has the model and cut views, print with a replay, parts with an assembly and plate with a batch', () => {
  for (const name of files.filter((file) => /^(?:en\/)?[\w-]+\/index\.html$/.test(file))) {
    const page = readFileSync(join(out, name), 'utf8');
    const views = [...page.matchAll(/data-view="(\w+)"/g)].map((match) => match[1]);
    const { assembly, plates, batch } = stageConfig(name);
    const expected = ['model', 'cut', ...(plates.length ? ['print'] : []), ...(assembly ? ['parts'] : []), ...(batch ? ['plate'] : [])];
    assert.deepEqual(views, expected, name);
    for (const item of assembly?.items ?? []) assert.ok(resolves(item.stl), `${name} links ${item.stl}, which the build did not write`);
  }
  assert.ok(stageConfig(join('soma-egg', 'index.html')).assembly, 'the Soma egg has its parts view');
  assert.equal(stageConfig(join('yarn-bowl', 'index.html')).assembly, undefined);
});

test('the index shows one part on its stage, starting in print replay', () => {
  for (const name of ['index.html', join('en', 'index.html')]) {
    assert.equal([...readFileSync(join(out, name), 'utf8').matchAll(STAGE_CONFIG)].length, 1, name);
    assert.equal(stageConfig(name).initial, 'print', name);
  }
  assert.equal(stageConfig(join('capsule-tower', 'index.html')).initial, undefined);
});

test('a draft is labelled beside its title and on its index row, with no print view or print facts', () => {
  const name = join('star-egg', 'index.html');
  const page = readFileSync(join(out, name), 'utf8');
  assert.match(page, /<h1>Kaheksakandi muna <span class="room__draft">Kavand, veel printimata<\/span><\/h1>/);
  assert.match(readFileSync(join(out, 'en', name), 'utf8'), /<span class="room__draft">Draft, not printed yet<\/span>/);
  const config = stageConfig(name);
  assert.deepEqual(config.plates, []);
  assert.deepEqual(config.stageItems.map((index) => config.assembly.items[index].colour),
    ['#c42d26', '#f2efe8', '#f2efe8', '#c42d26', '#2f8f4e', '#f2b81f', '#2f8f4e', '#f2b81f', '#c42d26', '#f2efe8', '#f2b81f', '#2f8f4e', '#2f8f4e', '#2f8f4e'],
    'the model view draws both halves in their colours');
  assert.equal(config.colour, '#c42d26');
  assert.ok(!page.includes('data-view="print"'));
  assert.doesNotMatch(facts(name), /<dt>(?:Kihte|Printimise aeg|Materjal)<\/dt>/);
  assert.doesNotMatch(page, /Prinditud \d/, 'no print date');
  const index = readFileSync(join(out, 'index.html'), 'utf8');
  const row = index.slice(index.indexOf('star-egg/'), index.indexOf('</li>', index.indexOf('star-egg/')));
  assert.match(row, /<span class="fact row__fact">Kavand, veel printimata<\/span>/);
  for (const source of ['star-egg/star-egg.scad', 'soma-egg/soma-egg.scad']) {
    assert.ok(page.includes(`href="https://github.com/khelias/khe-workshop/blob/main/parts/${source}"`), `the page links ${source}`);
  }
});

test('the plate view lays out the copies plate.py prints, for each batch plate', () => {
  const { batch, assembly } = stageConfig(join('star-egg', 'index.html'));
  assert.deepEqual(batch.map((plate) => plate.title), ['Alused', 'Korgid']);
  for (const [index, id] of ['bases', 'caps'].entries()) {
    const layout = JSON.parse(execFileSync('python3', [join(root, 'scripts', 'plate.py'), 'star-egg', id, '--json'], { encoding: 'utf8' }));
    assert.deepEqual(batch[index].positions, layout.positions, id);
    assert.equal(layout.positions.length, 25, `${id} fills the bed with a 5 x 5 grid`);
    for (const item of batch[index].items) assert.ok(assembly.items[item], `${id} names assembly item ${item}`);
  }
  const page = readFileSync(join(out, 'en', 'star-egg', 'index.html'), 'utf8');
  assert.match(page, /data-view="plate"[^>]*>Plate</);
  assert.equal(stageConfig(join('en', 'star-egg', 'index.html')).text.slider.plate, 'Eggs on the plate');
});
