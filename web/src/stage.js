// The part's stage: one slider drives the model, the cut and the replay of the real print.
import * as THREE from '../vendor/three/three.module.js';
import { OrbitControls } from '../vendor/three/OrbitControls.js';
import { buildToolpaths, decodeReplay, formatDuration, layerAt, loadBytes, sliderToSeconds, verticesAt } from './replay.js';
import { parseStl, placeOnBed } from './stl.js';

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

class Stage {
  constructor(root) {
    this.root = root;
    this.config = JSON.parse(root.querySelector('[data-stage-config]').textContent);
    this.text = this.config.text;
    this.canvas = root.querySelector('canvas');
    this.slider = root.querySelector('[data-stage-slider]');
    this.readout = root.querySelector('[data-stage-readout]');
    this.status = root.querySelector('[data-stage-status]');
    this.play = root.querySelector('[data-stage-play]');
    this.mark = root.querySelector('[data-stage-mark]');
    this.tabs = [...root.querySelectorAll('[data-view]')];
    this.view = 'model';
    this.values = { model: 0, cut: SLIDER_MAX / 2, print: SLIDER_MAX * 0.55 };
    this.visible = true;
    this.frame = 0;
    this.playing = 0;
    this.size = [0, 0];
    this.lite = window.matchMedia('(max-width: 767px), (pointer: coarse)').matches;
    this.still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  async start() {
    const mesh = parseStl(await loadBytes(this.config.stl));
    this.buildScene(mesh);
    this.bindControls();
    this.root.dataset.ready = 'true';
    this.setView('model');
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
    const bed = new THREE.Mesh(new THREE.PlaneGeometry(bedMm, bedMm), new THREE.MeshStandardMaterial({ color: '#262e33', roughness: 0.9 }));
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

    const top = this.config.top;
    const placed = placeOnBed(mesh, top ? top.above : null);
    this.size = placed.size;
    this.clip = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0);
    this.clipped = [this.clip];
    const rgb = hexToRgb(this.config.colour);
    const bodyGeometry = geometryOf(placed.body);
    this.materials = [new THREE.MeshStandardMaterial({ color: isDark(rgb) ? '#676e74' : this.config.colour, roughness: 0.58, side: THREE.DoubleSide })];
    this.body = new THREE.Mesh(bodyGeometry, this.materials[0]);
    this.body.renderOrder = 2;
    this.turntable.add(this.body);

    if (placed.top.positions.length) {
      this.materials.push(new THREE.MeshStandardMaterial({ color: top.colour, roughness: 0.5, side: THREE.DoubleSide }));
      this.top = new THREE.Mesh(geometryOf(placed.top), this.materials[1]);
      this.top.renderOrder = 2;
      this.turntable.add(this.top);
    }

    this.buildCut(geometryOf({ positions: placed.whole.positions }));

    this.ghost = new THREE.Mesh(bodyGeometry, new THREE.MeshBasicMaterial({ color: '#9fb4bd', transparent: true, opacity: 0.07, depthWrite: false, side: THREE.DoubleSide }));
    this.turntable.add(this.ghost);

    this.head = new THREE.Mesh(new THREE.SphereGeometry(Math.max(this.size[2] / 110, 1.1), 16, 12), new THREE.MeshBasicMaterial({ color: CAP }));
    this.turntable.add(this.head);

    this.centre = new THREE.Vector3(0, this.size[2] / 2, 0);
    this.radius = Math.hypot(...this.size) / 2;
    this.camera = new THREE.PerspectiveCamera(30, 1, 1, 4000);
    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.target.copy(this.centre);
    this.controls.enablePan = false;
    this.controls.minDistance = this.radius * 1.3;
    this.controls.maxDistance = this.radius * 6;
    this.controls.maxPolarAngle = Math.PI * 0.52;
    this.canvas.style.touchAction = 'pan-y';
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

  aim(azimuth, elevation) {
    const distance = (this.radius / Math.sin((this.camera.fov * Math.PI) / 360)) * 1.12;
    this.camera.position.setFromSphericalCoords(distance, Math.PI / 2 - elevation, azimuth).add(this.centre);
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
    this.play.hidden = view !== 'print' || this.still;
    this.showStatus('');
    if (view === 'cut') this.aim(1.15, this.size[2] < 80 ? 0.55 : 0.2);
    if (view === 'print' && !this.fullLines) {
      this.showStatus(this.text.loading);
      this.loading ??= this.loadPaths();
      try {
        await this.loading;
      } catch {
        this.loading = null;
        this.play.hidden = true;
        this.showStatus(this.text.error);
        return;
      }
      if (this.view !== 'print') return;
      this.showStatus('');
    }
    this.configureView();
    this.apply();
  }

  async loadPaths() {
    const replay = await decodeReplay(await loadBytes(this.config.replay));
    const built = buildToolpaths(replay, this.config.rotate, pathPalette(hexToRgb(this.config.colour)), this.lite);
    this.meta = replay.meta;
    this.layerVertex = built.all.layerVertex;
    this.fullLines = lineObject(built.all);
    this.turntable.add(this.fullLines);
    if (this.lite) {
      this.wallVertex = built.outer.layerVertex;
      this.wallLines = lineObject(built.outer);
      this.turntable.add(this.wallLines);
    }
    const change = this.meta.colour_changes[0];
    if (change) this.mark.style.insetInlineStart = `${Math.min(change.seconds / this.meta.seconds, 1) * 100}%`;
  }

  // What depends on the view only, set once when the view opens.
  configureView() {
    const isCut = this.view === 'cut';
    const isPrint = this.view === 'print';
    this.materials.forEach((material) => { material.clippingPlanes = isCut ? this.clipped : NO_CLIP; });
    this.cutMasks.visible = isCut;
    this.cap.visible = isCut;
    this.body.visible = !isPrint;
    this.ghost.visible = isPrint;
    this.head.visible = false;
    if (this.top) this.top.visible = !isPrint;
    if (this.fullLines) this.fullLines.visible = isPrint;
    if (this.wallLines) this.wallLines.visible = isPrint;
    this.mark.hidden = !(isPrint && this.meta?.colour_changes.length);
    if (this.view !== 'model') this.turntable.rotation.z = 0;
  }

  apply() {
    const value = this.values[this.view];
    if (this.view === 'model') {
      this.turntable.rotation.z = (value / SLIDER_MAX) * Math.PI * 2;
      this.setReadout(this.text.turned.replace('{deg}', Math.round((value / SLIDER_MAX) * 360)));
    } else if (this.view === 'cut') {
      this.applyCut(value);
    } else if (this.meta) {
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

  applyPrint(value) {
    const meta = this.meta;
    const seconds = sliderToSeconds(value, SLIDER_MAX, meta.seconds);
    const position = layerAt(meta.layers, meta.seconds, seconds);
    const full = verticesAt(this.layerVertex, position);
    const finished = value >= SLIDER_MAX;
    if (this.lite) {
      this.wallLines.geometry.setDrawRange(0, verticesAt(this.wallVertex, position).start);
      this.fullLines.geometry.setDrawRange(full.start, full.upTo - full.start);
    } else {
      this.fullLines.geometry.setDrawRange(0, full.upTo);
    }
    if (this.top) this.top.visible = finished;
    const points = this.fullLines.geometry.attributes.position.array;
    const last = full.upTo - 1;
    this.head.visible = !finished && last >= 0;
    if (last >= 0) this.head.position.set(points[last * 3], points[last * 3 + 1], points[last * 3 + 2]);
    let text = this.text.print
      .replace('{time}', formatDuration(seconds))
      .replace('{layer}', position.index + 1)
      .replace('{total}', meta.total_layers);
    if (finished && this.config.top) text += `, ${this.config.top.label}`;
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
