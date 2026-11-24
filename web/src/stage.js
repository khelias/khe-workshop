// The part's stage: one slider drives the model, the cut and the replay of the real print.
import * as THREE from '../vendor/three/three.module.js';
import { OrbitControls } from '../vendor/three/OrbitControls.js';
import { pathAt, reach } from './assembly.js';
import { buildToolpaths, decodeReplay, formatDuration, layerAt, loadBytes, plateAt, rowLayout, timeline, turnedBox, verticesAt } from './replay.js';
import { bounds, moveBy, parseStl, placeOnBed, trianglesWhere } from './stl.js';

const SLIDER_MAX = 1000;
const PLAY_MS = 24000;
const CHAMBER = '#14181b';
const CAP = '#e8b04a';
const NO_CLIP = [];

function hexToRgb(hex) {
  const value = parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

// A black print would vanish in the dark chamber, so very dark filament is drawn lighter.
function isDark([r, g, b]) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 60;
}

function pathPalette(rgb) {
  const wall = isDark(rgb) ? [176, 182, 186] : rgb;
  const dim = [92, 102, 112];
  const solid = [112, 142, 136];
  const palette = {
    'outer-wall': wall,
    'inner-wall': wall.map((value) => value * 0.62),
    infill: [84, 122, 130],
    solid,
    gap: solid,
    bridge: [214, 170, 90],
  };
  return (kind) => palette[kind] ?? dim;
}

function geometryOf(part) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(part.positions, 3));
  if (part.normals) geometry.setAttribute('normal', new THREE.BufferAttribute(part.normals, 3));
  return geometry;
}

function lineObject(set) {
  const geometry = geometryOf(set);
  geometry.setAttribute('color', new THREE.BufferAttribute(set.colours, 3, true));
  const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ vertexColors: true }));
  lines.frustumCulled = false;
  return lines;
}

function solidMaterial(colour, options = {}) {
  return new THREE.MeshStandardMaterial({ color: colour, roughness: 0.5, side: THREE.DoubleSide, ...options });
}

function solidMesh(geometry, material) {
  const mesh = new THREE.Mesh(geometry, material);
  mesh.renderOrder = 2;
  return mesh;
}

class Stage {
  constructor(root) {
    this.root = root;
    this.config = JSON.parse(root.querySelector('[data-stage-config]').textContent);
    this.text = this.config.text;
    this.plates = this.config.plates;
    this.stageIndex = this.plates.findIndex((plate) => plate.stage);
    this.stagePlate = this.plates[this.stageIndex];
    this.canvas = root.querySelector('canvas');
    this.slider = root.querySelector('[data-stage-slider]');
    this.readout = root.querySelector('[data-stage-readout]');
    this.status = root.querySelector('[data-stage-status]');
    this.play = root.querySelector('[data-stage-play]');
    this.timeline = root.querySelector('.stage__timeline');
    this.tabs = [...root.querySelectorAll('[data-view]')];
    this.view = 'model';
    this.values = { model: 0, cut: SLIDER_MAX / 2, print: SLIDER_MAX * 0.55, parts: (this.config.assembly?.start ?? 0) * SLIDER_MAX };
    this.loads = {};
    this.visible = true;
    this.frame = 0;
    this.playing = 0;
    this.size = [0, 0];
    this.lite = window.matchMedia('(max-width: 767px), (pointer: coarse)').matches;
    this.still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  async start() {
    const inlay = this.stagePlate?.inlay ? loadBytes(this.stagePlate.inlay.stl) : null;
    inlay?.catch(() => {});
    this.buildScene(parseStl(await loadBytes(this.config.stl)));
    this.bindControls();
    this.root.dataset.ready = 'true';
    const initial = this.config.initial === 'print' || this.config.initial === 'cut' ? this.config.initial : 'model';
    this.setView(initial);
    // The inlay is a detail: the stage works without it, so a failed load leaves no error.
    inlay?.then((bytes) => this.addInlay(parseStl(bytes))).catch(() => {});
  }

  // A part printed in another colour inside the stage mesh, loaded after the first view shows.
  addInlay(mesh) {
    moveBy(mesh, this.shift);
    // It fills the stage mesh's groove exactly, so it is drawn a little nearer to win.
    this.inlay = this.addSolid(geometryOf(mesh), this.stagePlate.inlay.colour, { polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -4 }, this.stageGroup);
    this.inlay.material.clippingPlanes = this.view === 'cut' ? this.clipped : NO_CLIP;
    this.inlay.visible = this.view !== 'parts';
    this.invalidate();
  }

  addSolid(geometry, colour, options = {}, parent = this.turntable) {
    const material = solidMaterial(colour, options);
    this.materials.push(material);
    const mesh = solidMesh(geometry, material);
    parent.add(mesh);
    return mesh;
  }

  buildScene(mesh) {
    const renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, stencil: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.localClippingEnabled = true;
    this.renderer = renderer;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(CHAMBER);
    this.scene = scene;
    scene.add(new THREE.HemisphereLight('#e8eff2', '#2a3136', 1.9));
    const key = new THREE.DirectionalLight('#ffffff', 2.8);
    key.position.set(240, 420, 300);
    scene.add(key);
    const rim = new THREE.DirectionalLight('#9fc4d4', 1.1);
    rim.position.set(-300, 180, -260);
    scene.add(rim);

    const bedMm = this.config.bed;
    this.bedMaterial = new THREE.MeshStandardMaterial({ color: '#262e33', roughness: 0.9 });
    const bed = new THREE.Mesh(new THREE.PlaneGeometry(bedMm, bedMm), this.bedMaterial);
    bed.rotation.x = -Math.PI / 2;
    bed.position.y = -0.3;
    scene.add(bed);
    const grid = new THREE.GridHelper(bedMm, 13, '#4c5961', '#3a454c');
    grid.position.y = -0.2;
    scene.add(grid);

    // Print coordinates are Z up; the scene is Y up.
    const world = new THREE.Group();
    world.rotation.x = -Math.PI / 2;
    scene.add(world);
    this.turntable = new THREE.Group();
    world.add(this.turntable);
    // What belongs to the stage plate's print goes into the row with it once it is done.
    this.stageGroup = new THREE.Group();
    this.turntable.add(this.stageGroup);

    const top = this.stagePlate?.top;
    const placed = placeOnBed(mesh, top ? top.above : null);
    this.size = placed.size;
    this.shift = placed.shift;
    this.clip = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0);
    this.clipped = [this.clip];
    const colour = (this.stagePlate ?? this.plates[0]).colour;
    const bodyGeometry = geometryOf(placed.body);
    this.materials = [new THREE.MeshStandardMaterial({ color: isDark(hexToRgb(colour)) ? '#676e74' : colour, roughness: 0.58, side: THREE.DoubleSide })];
    this.body = new THREE.Mesh(bodyGeometry, this.materials[0]);
    this.body.renderOrder = 2;
    this.turntable.add(this.body);

    if (placed.top.positions.length) this.top = this.addSolid(geometryOf(placed.top), top.colour, {}, this.stageGroup);

    // The layers printed before the replay starts stay in the print view as the model, cut just
    // under the replay's first layer: only the triangles that reach that low, for a light draw.
    const below = this.stagePlate?.below;
    if (below) {
      const cut = below.z - 0.02;
      const material = this.materials[0].clone();
      material.clippingPlanes = [new THREE.Plane(new THREE.Vector3(0, -1, 0), cut)];
      this.base = new THREE.Mesh(geometryOf(trianglesWhere(placed.body, (a, b, c) => Math.min(a, b, c) < cut)), material);
      this.base.renderOrder = 2;
      this.stageGroup.add(this.base);
    }

    this.buildCut(geometryOf({ positions: placed.whole.positions }));

    if (this.stagePlate) {
      this.ghost = new THREE.Mesh(bodyGeometry, new THREE.MeshBasicMaterial({ color: '#9fb4bd', transparent: true, opacity: 0.07, depthWrite: false, side: THREE.DoubleSide }));
      this.stageGroup.add(this.ghost);
    }

    this.head = new THREE.Mesh(new THREE.SphereGeometry(Math.max(this.size[2] / 110, 1.1), 16, 12), new THREE.MeshBasicMaterial({ color: CAP }));
    this.turntable.add(this.head);

    this.partFrame = { centre: new THREE.Vector3(0, this.size[2] / 2, 0), radius: Math.hypot(...this.size) / 2 };
    this.camera = new THREE.PerspectiveCamera(30, 1, 1, 4000);
    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enablePan = false;
    this.frameOn(this.partFrame);
    this.controls.maxPolarAngle = Math.PI * 0.52;
    // A plain wheel scrolls the page past the stage; Ctrl or Cmd with the wheel zooms, as does a trackpad pinch, which Chrome and Firefox send with Ctrl.
    this.canvas.parentElement.addEventListener('wheel', (event) => {
      if (!event.ctrlKey && !event.metaKey) event.stopPropagation();
    }, { capture: true, passive: true });
    this.controls.addEventListener('change', () => this.invalidate());
    this.aim(0.62, 0.32);
  }

  buildCut(whole) {
    const stencil = (side, op) => {
      const mask = new THREE.Mesh(whole, new THREE.MeshBasicMaterial({
        depthWrite: false, depthTest: false, colorWrite: false, side, clippingPlanes: this.clipped,
        stencilWrite: true, stencilFunc: THREE.AlwaysStencilFunc, stencilFail: op, stencilZFail: op, stencilZPass: op,
      }));
      mask.renderOrder = 1;
      return mask;
    };
    this.cutMasks = new THREE.Group();
    this.cutMasks.add(stencil(THREE.BackSide, THREE.IncrementWrapStencilOp), stencil(THREE.FrontSide, THREE.DecrementWrapStencilOp));
    this.turntable.add(this.cutMasks);
    const reach = this.config.bed * 2;
    this.cap = new THREE.Mesh(new THREE.PlaneGeometry(reach, reach), new THREE.MeshStandardMaterial({
      color: CAP, roughness: 0.7, stencilWrite: true, stencilRef: 0, stencilFunc: THREE.NotEqualStencilFunc,
      stencilFail: THREE.ReplaceStencilOp, stencilZFail: THREE.ReplaceStencilOp, stencilZPass: THREE.ReplaceStencilOp,
    }));
    this.cap.rotation.y = Math.PI / 2;
    this.cap.renderOrder = 1.5;
    this.cap.onAfterRender = (renderer) => renderer.clearStencil();
    this.scene.add(this.cap);
  }

  // What the camera keeps in view: the part, or in the parts view the items spread apart.
  frameOn(frame) {
    this.framing = frame;
    this.controls.target.copy(frame.centre);
    this.controls.minDistance = frame.radius * 1.3;
    this.controls.maxDistance = frame.radius * 6;
  }

  aim(azimuth, elevation) {
    const { centre, radius } = this.framing;
    const distance = (radius / Math.sin((this.camera.fov * Math.PI) / 360)) * 1.12;
    this.camera.position.setFromSphericalCoords(distance, Math.PI / 2 - elevation, azimuth).add(centre);
    this.controls.update();
  }

  bindControls() {
    this.tabs.forEach((tab) => tab.addEventListener('click', () => this.setView(tab.dataset.view)));
    this.slider.addEventListener('input', () => {
      this.stopPlaying();
      this.values[this.view] = Number(this.slider.value);
      this.apply();
    });
    this.play.addEventListener('click', () => (this.playing ? this.stopPlaying() : this.startPlaying()));
    new ResizeObserver(() => this.resize()).observe(this.canvas.parentElement);
    new IntersectionObserver(([entry]) => {
      this.visible = entry.isIntersecting;
      if (this.visible) this.invalidate();
      else this.stopPlaying();
    }).observe(this.root);
    this.resize();
  }

  resize() {
    const { clientWidth: width, clientHeight: height } = this.canvas.parentElement;
    if (!width || !height || (width === this.width && height === this.height)) return;
    this.width = width;
    this.height = height;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.invalidate();
  }

  async setView(view) {
    this.stopPlaying();
    this.view = view;
    this.tabs.forEach((tab) => tab.setAttribute('aria-pressed', String(tab.dataset.view === view)));
    this.slider.value = this.values[view];
    this.slider.setAttribute('aria-label', this.text.slider[view]);
    this.play.hidden = true;
    this.showStatus('');
    const reframe = () => {
      const frame = { print: this.printFrame, parts: this.spreadFrame }[view] ?? this.partFrame;
      if (this.framing === frame) return;
      this.frameOn(frame);
      this.aim(0.62, 0.32);
    };
    if (view !== 'parts') reframe();
    if (view === 'cut') this.aim(1.15, this.size[2] < 80 ? 0.55 : 0.2);
    // The print and parts views load their data when first opened.
    const loader = { print: !this.printPlates && 'loadPaths', parts: !this.items && 'loadItems' }[view];
    if (loader) {
      this.configureView();
      this.invalidate();
      this.showStatus(view === 'parts' ? this.text.loading_parts : this.text.loading);
      this.loads[loader] ??= this[loader]();
      try {
        await this.loads[loader];
      } catch {
        this.loads[loader] = null;
        this.showStatus(this.text.error);
        return;
      }
      if (this.view !== view) return;
      this.showStatus('');
    }
    if (view === 'parts' || view === 'print') reframe();
    this.play.hidden = view !== 'print' || this.still;
    this.configureView();
    this.apply();
  }

  async loadPaths() {
    const replays = await Promise.all(this.plates.map(async (plate) => decodeReplay(await loadBytes(plate.replay))));
    const isPrint = this.view === 'print';
    this.printPlates = replays.map((replay, index) => {
      const plate = this.plates[index];
      const built = buildToolpaths(replay, plate.rotate, pathPalette(hexToRgb(plate.colour)), this.lite);
      const group = index === this.stageIndex ? this.stageGroup : new THREE.Group();
      const full = lineObject(built.all);
      full.visible = isPrint;
      group.add(full);
      let walls = null;
      if (this.lite) {
        walls = lineObject(built.outer);
        walls.visible = isPrint;
        group.add(walls);
      }
      if (group !== this.stageGroup) this.turntable.add(group);
      const { meta } = replay;
      return {
        meta, group, full, walls, layerVertex: built.all.layerVertex, wallVertex: built.outer.layerVertex,
        span: [meta.start_seconds ?? 0, meta.seconds], box: turnedBox(meta.walls, plate.rotate), height: meta.layers.at(-1)[0],
      };
    });
    this.spans = this.printPlates.map((plate) => plate.span);
    // The readout counts each earlier plate's whole print, cut layers included.
    let before = 0;
    for (const plate of this.printPlates) {
      plate.before = before;
      before += plate.meta.print_seconds;
    }
    this.totalSeconds = before;
    const row = rowLayout(this.printPlates.map((plate) => plate.box));
    row.offsets.forEach((offset, index) => { this.printPlates[index].offset = offset; });
    this.printFrame = this.partFrame;
    if (row.offsets.length) {
      this.printFrame = this.rowFrame(row.end);
      this.buildShelf(row.end + 20);
    }
    this.buildMarks();
  }

  // The largest plate at the centre and every finished plate in the row beside it.
  rowFrame(end) {
    const boxes = this.printPlates.map((plate) => plate.box);
    const low = -Math.max(...boxes.map(([width]) => width)) / 2;
    const deepest = Math.max(...boxes.map(([, depth]) => depth));
    const height = Math.max(this.size[2], ...this.printPlates.map((plate) => plate.height));
    return { centre: new THREE.Vector3((low + end) / 2, height / 2, 0), radius: Math.hypot(end - low, deepest, height) / 2 };
  }

  // Where the row runs past the bed, the surface goes on under it, without the bed's grid.
  buildShelf(end) {
    const half = this.config.bed / 2;
    if (end <= half) return;
    this.shelf = new THREE.Mesh(new THREE.PlaneGeometry(end - half, this.config.bed), this.bedMaterial);
    this.shelf.rotation.x = -Math.PI / 2;
    this.shelf.position.set((half + end) / 2, -0.3, 0);
    this.shelf.visible = this.view === 'print';
    this.scene.add(this.shelf);
  }

  // A mark where each later plate starts, and one at each colour change inside a plate's replay.
  buildMarks() {
    const { before, total } = timeline(this.spans);
    const at = [];
    this.printPlates.forEach((plate, index) => {
      if (index) at.push([before[index], this.text.plate_mark]);
      const { first } = this.plates[index];
      const last = first + plate.meta.layers.length - 1;
      for (const change of plate.meta.colour_changes) {
        if (change.layer >= first && change.layer <= last) at.push([before[index] + change.seconds - plate.span[0], this.text.colour_change]);
      }
    });
    this.marks = at.map(([seconds, title]) => {
      const mark = document.createElement('span');
      mark.className = 'stage__mark';
      mark.title = title;
      mark.hidden = this.view !== 'print';
      mark.style.insetInlineStart = `${Math.min(Math.max(seconds / total, 0), 1) * 100}%`;
      this.timeline.append(mark);
      return mark;
    });
  }

  async loadItems() {
    const { items } = this.config.assembly;
    const meshes = await Promise.all(items.map(async (item) => parseStl(await loadBytes(item.stl))));
    const materials = new Map();
    const group = new THREE.Group();
    const spread = meshes.map((mesh, index) => {
      moveBy(mesh, this.shift);
      const { colour, path } = items[index];
      if (!materials.has(colour)) materials.set(colour, solidMaterial(colour));
      const solid = solidMesh(geometryOf(mesh), materials.get(colour));
      solid.userData.path = path;
      group.add(solid);
      return { ...bounds(mesh.positions), path };
    });
    // Print coordinates are Z up, the scene Y up with print Y pointing away.
    const { min, max } = reach(spread);
    const centre = new THREE.Vector3((min[0] + max[0]) / 2, (min[2] + max[2]) / 2, -(min[1] + max[1]) / 2);
    this.spreadFrame = { centre, radius: Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2 };
    group.visible = this.view === 'parts';
    this.items = group;
    this.turntable.add(group);
  }

  // What depends on the view only, set once when the view opens.
  configureView() {
    const isCut = this.view === 'cut';
    const isPrint = this.view === 'print';
    const isParts = this.view === 'parts';
    this.materials.forEach((material) => { material.clippingPlanes = isCut ? this.clipped : NO_CLIP; });
    this.cutMasks.visible = isCut;
    this.cap.visible = isCut;
    this.body.visible = !isPrint && !isParts;
    if (this.base) this.base.visible = isPrint;
    if (this.ghost) this.ghost.visible = isPrint;
    this.head.visible = false;
    if (this.top) this.top.visible = !isPrint && !isParts;
    if (this.inlay) this.inlay.visible = !isParts;
    if (this.items) this.items.visible = isParts;
    if (!isPrint) {
      this.stageGroup.visible = true;
      this.stageGroup.position.x = 0;
    }
    for (const plate of this.printPlates ?? []) {
      plate.full.visible = isPrint;
      if (plate.walls) plate.walls.visible = isPrint;
    }
    for (const mark of this.marks ?? []) mark.hidden = !isPrint;
    if (this.shelf) this.shelf.visible = isPrint;
    if (this.view !== 'model') this.turntable.rotation.z = 0;
  }

  apply() {
    const value = this.values[this.view];
    if (this.view === 'model') {
      this.turntable.rotation.z = (value / SLIDER_MAX) * Math.PI * 2;
      this.setReadout(this.text.turned.replace('{deg}', Math.round((value / SLIDER_MAX) * 360)));
    } else if (this.view === 'cut') {
      this.applyCut(value);
    } else if (this.view === 'parts') {
      if (this.items) this.applyParts(value);
    } else if (this.printPlates) {
      this.applyPrint(value);
    }
    this.invalidate();
  }

  applyCut(value) {
    const half = this.size[0] / 2;
    const x = half - (value / SLIDER_MAX) * this.size[0];
    this.clip.constant = x;
    this.cap.position.set(x, this.size[2] / 2, 0);
    const mm = Math.abs(x).toFixed(1).replace('.', this.config.lang === 'et' ? ',' : '.');
    this.setReadout(this.text.cut.replace('{mm}', mm));
  }

  applyParts(value) {
    const t = value / SLIDER_MAX;
    this.items.children.forEach((solid) => solid.position.set(...pathAt(solid.userData.path, t)));
    this.setReadout(this.text.apart.replace('{pct}', Math.round(t * 100)));
  }

  applyPrint(value) {
    const { plate: current, seconds } = plateAt(this.spans, value, SLIDER_MAX);
    const finished = value >= SLIDER_MAX;
    this.printPlates.forEach((plate, index) => {
      plate.group.visible = index <= current;
      plate.group.position.x = index < current ? plate.offset : 0;
      if (index < current) {
        // A phone draws a finished plate's outer walls only, to keep its line count low.
        plate.full.visible = !this.lite;
        plate.full.geometry.setDrawRange(0, plate.layerVertex.at(-1));
        if (plate.walls) plate.walls.geometry.setDrawRange(0, plate.wallVertex.at(-1));
      }
    });
    const plate = this.printPlates[current];
    const { meta } = plate;
    const position = layerAt(meta.layers, meta.seconds, seconds);
    const full = verticesAt(plate.layerVertex, position);
    plate.full.visible = true;
    if (this.lite) {
      plate.walls.geometry.setDrawRange(0, verticesAt(plate.wallVertex, position).start);
      plate.full.geometry.setDrawRange(full.start, full.upTo - full.start);
    } else {
      plate.full.geometry.setDrawRange(0, full.upTo);
    }
    const stageDone = this.stageIndex >= 0 && (this.stageIndex < current || (this.stageIndex === current && finished));
    if (this.top) this.top.visible = stageDone;
    if (this.ghost) this.ghost.visible = this.stageIndex === current;
    const points = plate.full.geometry.attributes.position.array;
    const last = full.upTo - 1;
    this.head.visible = !finished && last >= 0;
    if (last >= 0) this.head.position.set(points[last * 3], points[last * 3 + 1], points[last * 3 + 2]);
    let text = this.text.print
      .replace('{time}', formatDuration(plate.before + seconds))
      .replace('{total}', formatDuration(this.totalSeconds))
      .replace('{plates}', this.plates.length)
      .replace('{plate}', current + 1)
      .replace('{layers}', meta.total_layers)
      .replace('{layer}', position.index + this.plates[current].first);
    const stage = this.stagePlate;
    if (finished && stage?.top) text += `, ${stage.top.label}`;
    if (this.stageIndex === current && seconds <= plate.span[0] && stage.below) text += `, ${stage.below.label}`;
    this.setReadout(text);
  }

  setReadout(text) {
    if (text === this.readout.textContent) return;
    this.readout.textContent = text;
    this.slider.setAttribute('aria-valuetext', text);
  }

  showStatus(message) {
    this.status.textContent = message;
    this.status.hidden = !message;
  }

  startPlaying() {
    if (this.values.print >= SLIDER_MAX) this.values.print = 0;
    const started = performance.now();
    const from = this.values.print;
    this.play.textContent = this.text.pause;
    const step = (now) => {
      if (!this.playing) return;
      const value = Math.min(from + ((now - started) / PLAY_MS) * SLIDER_MAX, SLIDER_MAX);
      this.values.print = value;
      this.slider.value = value;
      this.apply();
      if (value >= SLIDER_MAX) this.stopPlaying();
      else this.playing = requestAnimationFrame(step);
    };
    this.playing = requestAnimationFrame(step);
  }

  stopPlaying() {
    if (this.playing) cancelAnimationFrame(this.playing);
    this.playing = 0;
    this.play.textContent = this.text.play;
  }

  invalidate() {
    if (this.frame || !this.visible) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.renderer.render(this.scene, this.camera);
    });
  }
}

export function startStage(root) {
  const stage = new Stage(root);
  stage.start().catch(() => stage.showStatus(stage.text.error));
}
