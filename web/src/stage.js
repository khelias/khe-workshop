// The part's stage: one slider drives the model, the cut and the replay of the real print.
import * as THREE from '../vendor/three/three.module.js';
import { OrbitControls } from '../vendor/three/OrbitControls.js';
import { pathAt, reach } from './assembly.js';
import { corners, fitPoints, pinchDelta } from './frame.js';
import { buildToolpaths, decodeReplay, formatDuration, layerAt, loadBytes, plateAt, rowLayout, timeline, turnedBox, verticesAt } from './replay.js';
import { bounds, moveBy, parseStl, placeOnBed, trianglesWhere } from './stl.js';

const SLIDER_MAX = 1000;
const PLAY_MS = 24000;
// The bed is a plate this thick, its top just under the part.
const BED_MM = 2;
const BED_TOP = -0.3;
const CAP = '#e8b04a';
const NO_CLIP = [];
// The print view's own bed per plate, for a part on several plates.
const PAD_MARGIN = 12;
const PAD_GAP = 24;
const GRID_MM = 20;
const GRID_COLOURS = ['#4c5961', '#3a454c'];
// How far below the horizon the camera may go: in the model view far enough to see the part's
// underside, elsewhere just under the bed's edge.
const BELOW_MODEL = Math.PI * 0.97;
const BELOW_OTHERS = Math.PI * 0.52;
// Azimuth and elevation the camera starts from. A tall view looks along a row of plates, so they
// stand one behind another and fill its height.
const FIRST_AIM = [0.62, 0.32];
const ALONG_ROW_AIM = [1.2, 0.45];
const HINT_MS = 1500;

function hexToRgb(hex) {
  const value = parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

// A black print would vanish on the dark bed, so very dark filament is drawn lighter.
function isDark([r, g, b]) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 60;
}

// A replay in several tool colours keeps dark filament darker, so it still differs from the light ones.
const DARK_WALL = [176, 182, 186];
const DARK_TOOL_WALL = [104, 110, 116];

function pathPalette(rgb, darkWall = DARK_WALL) {
  const wall = isDark(rgb) ? darkWall : rgb;
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
  const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ vertexColors: true, toneMapped: false }));
  lines.frustumCulled = false;
  return lines;
}

// Printed plastic: a soft sheen and a faint clear coat catch the studio's soft boxes.
function solidMaterial(colour, options = {}) {
  return new THREE.MeshPhysicalMaterial({
    color: colour, roughness: 0.46, clearcoat: 0.08, clearcoatRoughness: 0.6, sheen: 0.15, sheenRoughness: 0.8, sheenColor: '#ffffff',
    side: THREE.DoubleSide, clipShadows: true, ...options,
  });
}

function solidMesh(geometry, material) {
  const mesh = new THREE.Mesh(geometry, material);
  mesh.renderOrder = 2;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

// Soft boxes in a warm room, turned into the light the plastic reflects.
function studioLight(renderer) {
  const room = new THREE.Scene();
  room.add(new THREE.Mesh(new THREE.SphereGeometry(50, 32, 16), new THREE.MeshBasicMaterial({ color: '#8a847c', side: THREE.BackSide })));
  const softBox = (colour, [width, height], position) => {
    const box = new THREE.Mesh(new THREE.PlaneGeometry(width, height), new THREE.MeshBasicMaterial({ color: colour, side: THREE.DoubleSide }));
    box.position.set(...position);
    box.lookAt(0, 0, 0);
    room.add(box);
  };
  softBox('#ffffff', [30, 20], [-25, 30, 20]);
  softBox('#fff2e0', [20, 40], [35, 10, 10]);
  softBox('#dfe8ff', [30, 10], [0, -10, -40]);
  softBox('#ffffff', [40, 40], [0, 45, 0]);
  const generator = new THREE.PMREMGenerator(renderer);
  const texture = generator.fromScene(room, 0.02).texture;
  generator.dispose();
  room.traverse((object) => {
    object.geometry?.dispose();
    object.material?.dispose();
  });
  return texture;
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
    this.hint = root.querySelector('[data-stage-hint]');
    this.home = root.querySelector('[data-stage-home]');
    this.timeline = root.querySelector('.stage__timeline');
    this.tabs = [...root.querySelectorAll('[data-view]')];
    this.view = 'model';
    this.values = { model: 0, cut: SLIDER_MAX / 2, print: SLIDER_MAX * 0.55, parts: (this.config.assembly?.start ?? 0) * SLIDER_MAX, plate: SLIDER_MAX };
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
    // A part printed in several colours at once shows its colour parts; without them it shows one body.
    const coloured = this.config.stageItems ? this.itemMeshes().catch(() => null) : null;
    this.buildScene(parseStl(await loadBytes(this.config.stl)));
    this.bindControls();
    this.root.dataset.ready = 'true';
    const { initial: asked } = this.config;
    const initial = asked === 'cut' || (asked === 'print' && this.plates.length) ? asked : 'model';
    this.setView(initial);
    // The colour parts take the body's place once loaded; until then, or without them, the body shows.
    coloured?.then((meshes) => {
      if (!meshes) return;
      this.addColourParts(meshes);
      this.configureView();
      this.invalidate(true);
    });
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
    this.invalidate(true);
  }

  // The colour parts in place of the one-colour body, in the model and cut views.
  addColourParts(meshes) {
    this.colourParts = new THREE.Group();
    this.colourParts.position.set(...this.shift.map((value) => -value));
    for (const index of this.config.stageItems) {
      const material = this.itemMaterial(this.config.assembly.items[index].colour);
      if (!this.materials.includes(material)) this.materials.push(material);
      this.colourParts.add(solidMesh(meshes[index].geometry, material));
    }
    this.turntable.add(this.colourParts);
  }

  addSolid(geometry, colour, options = {}, parent = this.turntable) {
    const material = solidMaterial(colour, options);
    this.materials.push(material);
    const mesh = solidMesh(geometry, material);
    parent.add(mesh);
    return mesh;
  }

  buildScene(mesh) {
    // The canvas is transparent: the paper behind the part is the view's background in the room's CSS.
    const renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, stencil: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.localClippingEnabled = true;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    // The light is fixed in the room, so orbiting needs no new shadows; only a change to the scene does.
    renderer.shadowMap.autoUpdate = false;
    this.renderer = renderer;

    const scene = new THREE.Scene();
    scene.environment = studioLight(renderer);
    scene.environmentIntensity = 0.75;
    this.scene = scene;
    scene.add(new THREE.HemisphereLight('#ffffff', '#b8a990', 0.5));
    // One key light from the camera's left and above, its shadow falling behind the part.
    const key = new THREE.DirectionalLight('#fff4e8', 2);
    // The plate view stands its beds in a row, so the shadows and the ground reach past one bed.
    const extent = this.config.bed * (this.config.batch ? this.config.batch.length + 0.2 : 1);
    key.position.set(-50, 420, 240);
    key.castShadow = true;
    key.shadow.mapSize.setScalar(this.lite ? 1024 : 2048);
    key.shadow.radius = 4;
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 0.4;
    Object.assign(key.shadow.camera, { left: -extent, right: extent, top: extent, bottom: -extent, near: 1, far: 1200 });
    scene.add(key);

    const ground = new THREE.Mesh(new THREE.PlaneGeometry(extent * 2, extent * 2), new THREE.ShadowMaterial({ opacity: 0.18 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = BED_TOP - BED_MM;
    ground.receiveShadow = true;
    scene.add(ground);
    this.ground = ground;

    this.bedMaterial = new THREE.MeshStandardMaterial({ color: '#2b2d30', roughness: 0.7 });
    this.bed = this.bedSurface(this.config.bed, 0);
    scene.add(this.bed);

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
    // A draft, not printed yet, has no plate to take the colour from.
    const colour = (this.stagePlate ?? this.plates[0])?.colour ?? this.config.colour;
    const bodyGeometry = geometryOf(placed.body);
    this.materials = [solidMaterial(isDark(hexToRgb(colour)) ? '#676e74' : colour)];
    this.body = solidMesh(bodyGeometry, this.materials[0]);
    this.turntable.add(this.body);

    if (placed.top.positions.length) this.top = this.addSolid(geometryOf(placed.top), top.colour, {}, this.stageGroup);

    // The layers printed before the replay starts stay in the print view as the model, cut just
    // under the replay's first layer: only the triangles that reach that low, for a light draw.
    const below = this.stagePlate?.below;
    if (below) {
      const cut = below.z - 0.02;
      const material = this.materials[0].clone();
      material.clippingPlanes = [new THREE.Plane(new THREE.Vector3(0, -1, 0), cut)];
      this.base = solidMesh(geometryOf(trianglesWhere(placed.body, (a, b, c) => Math.min(a, b, c) < cut)), material);
      this.stageGroup.add(this.base);
    }

    this.buildCut(geometryOf({ positions: placed.whole.positions }));

    if (this.stagePlate) {
      this.ghost = new THREE.Mesh(bodyGeometry, new THREE.MeshBasicMaterial({ color: '#9fb4bd', transparent: true, opacity: 0.07, depthWrite: false, side: THREE.DoubleSide, toneMapped: false }));
      this.stageGroup.add(this.ghost);
    }

    this.head = new THREE.Mesh(new THREE.SphereGeometry(Math.max(this.size[2] / 110, 1.1), 16, 12), new THREE.MeshBasicMaterial({ color: CAP, toneMapped: false }));
    this.turntable.add(this.head);

    this.partFrame = { centre: new THREE.Vector3(0, this.size[2] / 2, 0), radius: Math.hypot(...this.size) / 2 };
    this.camera = new THREE.PerspectiveCamera(24, 1, 1, 4000);
    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enablePan = Boolean(this.config.closeUp);
    this.frameOn(this.partFrame);
    this.controls.maxPolarAngle = BELOW_OTHERS;
    this.bindZoom();
    // A move of the visitor's own offers the way back to where the view started; a click alone moves nothing.
    let moving = false;
    this.controls.addEventListener('start', () => { moving = true; });
    this.controls.addEventListener('end', () => { moving = false; });
    this.controls.addEventListener('change', () => {
      if (moving) this.home.hidden = false;
      this.showFloor();
      this.invalidate();
    });
    this.aim(...FIRST_AIM);
  }

  bindZoom() {
    const view = this.canvas.parentElement;
    // The wheel zooms where the pointer is, so a tall part's top comes close too. A touch pinch zooms
    // to the middle: OrbitControls places it by page coordinates, which a scrolled page shifts.
    this.controls.zoomToCursor = true;
    const touches = new Set();
    const touching = (event) => {
      if (event.pointerType !== 'touch') return;
      if (event.type === 'pointerdown') touches.add(event.pointerId);
      else touches.delete(event.pointerId);
      this.controls.zoomToCursor = !touches.size;
    };
    for (const type of ['pointerdown', 'pointerup', 'pointercancel']) view.addEventListener(type, touching, { capture: true });
    // Safari sends a trackpad pinch as gesture events only, so the stage passes it on as a wheel with Ctrl,
    // and keeps Safari's own wheel, should it send one too, from zooming twice. A pinch on a touch screen
    // sends gesture events too, but OrbitControls zooms it from the touches already.
    let pinching = false;
    let scale = 1;
    const pinch = (event) => {
      event.preventDefault();
      if (event.type === 'gesturestart') [pinching, scale] = [!touches.size, 1];
      else if (event.type === 'gestureend') pinching = false;
      else if (pinching && !touches.size) {
        const deltaY = pinchDelta(event.scale / scale);
        scale = event.scale;
        this.canvas.dispatchEvent(new WheelEvent('wheel', { deltaY, ctrlKey: true, clientX: event.clientX, clientY: event.clientY, cancelable: true }));
      }
    };
    for (const type of ['gesturestart', 'gesturechange', 'gestureend']) view.addEventListener(type, pinch);
    // A plain wheel scrolls the page past the stage and says how to zoom: Ctrl or Cmd with the wheel,
    // or a trackpad pinch, which Chrome and Firefox send as a wheel with Ctrl.
    const key = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl';
    this.hint.textContent = this.text.zoom_hint.replace('{key}', key);
    let hide = 0;
    view.addEventListener('wheel', (event) => {
      if (pinching) {
        if (event.isTrusted) event.stopPropagation();
        return;
      }
      if (this.config.closeUp || event.ctrlKey || event.metaKey) return;
      event.stopPropagation();
      if (!event.deltaY) return;
      this.hint.dataset.shown = 'true';
      clearTimeout(hide);
      hide = setTimeout(() => delete this.hint.dataset.shown, HINT_MS);
    }, { capture: true, passive: true });
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
    this.cap = new THREE.Mesh(new THREE.PlaneGeometry(reach, reach), new THREE.MeshBasicMaterial({
      color: CAP, toneMapped: false, stencilWrite: true, stencilRef: 0, stencilFunc: THREE.NotEqualStencilFunc,
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
    this.controls.minDistance = frame.radius * (this.config.closeUp ? 0.2 : frame.points ? 0.6 : 1.3);
    this.controls.maxDistance = frame.radius * 6;
    // Zooming toward the pointer moves the point the camera turns around, but never off the part.
    this.controls.cursor.copy(frame.centre);
    this.controls.maxTargetRadius = frame.radius;
  }

  // `zoom` scales the fitted distance, so a refit keeps how far the visitor has zoomed; without it the
  // view starts afresh.
  aim(azimuth, elevation, zoom) {
    const { centre, radius, points } = this.framing;
    if (points) {
      // A row of plates is fitted by each plate's box and lifted to the middle of the view.
      const { distance, lift, back, up } = this.rowFit(azimuth, elevation);
      this.controls.target.copy(centre).addScaledVector(new THREE.Vector3(...up), lift);
      this.camera.position.copy(this.controls.target).addScaledVector(new THREE.Vector3(...back), distance * (zoom ?? 1));
    } else {
      const distance = (radius / Math.sin((this.camera.fov * Math.PI) / 360)) * 1.12;
      this.controls.target.copy(centre);
      this.camera.position.setFromSphericalCoords(distance, Math.PI / 2 - elevation, azimuth).add(centre);
    }
    this.controls.update();
    if (zoom === undefined) this.home.hidden = true;
  }

  rowFit(azimuth, elevation) {
    return fitPoints(this.framing.points, azimuth, elevation, this.camera.fov, this.camera.aspect);
  }

  bindControls() {
    this.tabs.forEach((tab) => tab.addEventListener('click', () => this.setView(tab.dataset.view)));
    this.slider.addEventListener('input', () => {
      this.stopPlaying();
      this.values[this.view] = Number(this.slider.value);
      this.apply();
    });
    this.play.addEventListener('click', () => (this.playing ? this.stopPlaying() : this.startPlaying()));
    this.home.addEventListener('click', () => this.aim(...this.startAim()));
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
    // A row fitted to its box fits for one aspect, so a new one fits it again from where it is seen,
    // or, when the view turns between wide and tall, from where that one starts.
    const angles = this.framing?.points && [this.controls.getAzimuthalAngle(), Math.PI / 2 - this.controls.getPolarAngle()];
    const zoom = angles && this.camera.position.distanceTo(this.controls.target) / this.rowFit(...angles).distance;
    const wasTall = this.camera.aspect < 1;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    if (angles && wasTall !== this.camera.aspect < 1) this.aim(...this.firstAim());
    else if (angles) this.aim(...angles, zoom);
    this.invalidate();
  }

  firstAim() {
    return this.framing.points && this.camera.aspect < 1 ? ALONG_ROW_AIM : FIRST_AIM;
  }

  startAim() {
    return this.view === 'cut' ? [1.15, this.size[2] < 80 ? 0.55 : 0.2] : this.firstAim();
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
      const frame = { print: this.printFrame, parts: this.spreadFrame, plate: this.batchFrame }[view] ?? this.partFrame;
      if (this.framing === frame) return;
      this.frameOn(frame);
      this.aim(...this.firstAim());
    };
    if (view !== 'parts' && view !== 'plate') reframe();
    if (view === 'cut') this.aim(...this.startAim());
    // The print, parts and plate views load their data when first opened.
    const loader = { print: !this.printPlates && 'loadPaths', parts: !this.items && 'loadItems', plate: !this.batch && 'loadBatch' }[view];
    if (loader) {
      this.configureView();
      this.invalidate(true);
      this.showStatus(view === 'print' ? this.text.loading : this.text.loading_parts);
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
    if (view === 'parts' || view === 'print' || view === 'plate') reframe();
    this.play.hidden = view !== 'print' || this.still;
    this.configureView();
    this.apply();
  }

  async loadPaths() {
    const replays = await Promise.all(this.plates.map(async (plate) => decodeReplay(await loadBytes(plate.replay))));
    const isPrint = this.view === 'print';
    this.printPlates = replays.map((replay, index) => {
      const plate = this.plates[index];
      const darkWall = new Set(replay.meta.tool_colours).size > 1 ? DARK_TOOL_WALL : DARK_WALL;
      const palettes = new Map();
      const paletteOf = (colour) => {
        if (!palettes.has(colour)) palettes.set(colour, pathPalette(hexToRgb(colour), darkWall));
        return palettes.get(colour);
      };
      const built = buildToolpaths(replay, plate.rotate, (kind, colour) => paletteOf(colour ?? plate.colour)(kind), this.lite);
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
    for (const plate of this.printPlates) plate.pad = Math.max(...plate.box) + 2 * PAD_MARGIN;
    const row = rowLayout(this.printPlates.map((plate) => [plate.pad, plate.pad]), PAD_GAP);
    row.offsets.forEach((offset, index) => { this.printPlates[index].offset = offset; });
    this.printFrame = this.partFrame;
    if (this.plates.length > 1) {
      this.printFrame = this.rowFrame(row);
      this.buildPads();
    }
    this.buildMarks();
  }

  // The whole row from the start: no plate moves, so the camera need not either.
  rowFrame({ low, high }) {
    const height = Math.max(this.size[2], ...this.printPlates.map((plate) => plate.height));
    const centre = new THREE.Vector3((low + high) / 2, height / 2, 0);
    // Each plate's bed up to the height printed on it, the stage plate's to its model's top.
    const points = this.printPlates.flatMap((plate, index) => {
      const top = index === this.stageIndex ? this.size[2] : plate.height;
      const x = plate.offset - centre.x;
      return corners([x - plate.pad / 2, -centre.y, -plate.pad / 2], [x + plate.pad / 2, top - centre.y, plate.pad / 2]);
    });
    return { centre, radius: Math.max(...points.map((point) => Math.hypot(...point))), points };
  }

  // Every plate's bed is there from the start, so the plates still to come show as empty beds.
  buildPads() {
    this.pads = new THREE.Group();
    for (const plate of this.printPlates) this.pads.add(this.bedSurface(plate.pad, plate.offset));
    this.pads.visible = this.view === 'print';
    this.scene.add(this.pads);
  }

  bedSurface(size, x) {
    const surface = new THREE.Group();
    const plate = new THREE.Mesh(new THREE.BoxGeometry(size, BED_MM, size), this.bedMaterial);
    plate.position.y = BED_TOP - BED_MM / 2;
    plate.castShadow = true;
    plate.receiveShadow = true;
    const grid = new THREE.GridHelper(size, Math.max(1, Math.round(size / GRID_MM)), ...GRID_COLOURS);
    grid.material.toneMapped = false;
    grid.position.y = BED_TOP + 0.1;
    surface.add(plate, grid);
    surface.position.x = x;
    return surface;
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

  // The assembly's items as printed, each with one geometry the parts and plate views share.
  itemMeshes() {
    this.loads.meshes ??= Promise.all(this.config.assembly.items.map(async (item) => {
      const mesh = parseStl(await loadBytes(item.stl));
      return { ...bounds(mesh.positions), geometry: geometryOf(mesh) };
    })).catch((error) => {
      this.loads.meshes = null;
      throw error;
    });
    return this.loads.meshes;
  }

  itemMaterial(colour) {
    this.itemMaterials ??= new Map();
    if (!this.itemMaterials.has(colour)) this.itemMaterials.set(colour, solidMaterial(colour));
    return this.itemMaterials.get(colour);
  }

  async loadItems() {
    const { items } = this.config.assembly;
    const meshes = await this.itemMeshes();
    // The items keep their print coordinates; the group moves them by the stage mesh's shift.
    const group = new THREE.Group();
    group.position.set(...this.shift.map((value) => -value));
    const spread = meshes.map(({ min, max, geometry }, index) => {
      const { colour, path } = items[index];
      const solid = solidMesh(geometry, this.itemMaterial(colour));
      solid.userData.path = path;
      group.add(solid);
      return { min: min.map((value, axis) => value - this.shift[axis]), max: max.map((value, axis) => value - this.shift[axis]), path };
    });
    // Print coordinates are Z up, the scene Y up with print Y pointing away.
    const { min, max } = reach(spread);
    const centre = new THREE.Vector3((min[0] + max[0]) / 2, (min[2] + max[2]) / 2, -(min[1] + max[1]) / 2);
    this.spreadFrame = { centre, radius: Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2 };
    group.visible = this.view === 'parts';
    this.items = group;
    this.turntable.add(group);
  }

  // Each batch plate on a bed of its own in one row, its copies drawn as instances of the items,
  // each copy's floor on the bed and its centre on its position.
  async loadBatch() {
    const meshes = await this.itemMeshes();
    const { items } = this.config.assembly;
    const bed = this.config.bed;
    const row = rowLayout(this.config.batch.map(() => [bed, bed]), PAD_GAP);
    const pads = new THREE.Group();
    const copies = new THREE.Group();
    let height = 0;
    const place = new THREE.Matrix4();
    this.batch = this.config.batch.map((plate, index) => {
      const { min: low, max: high } = reach(plate.items.map((item) => meshes[item]));
      height = Math.max(height, high[2] - low[2]);
      const offset = row.offsets[index];
      pads.add(this.bedSurface(bed, offset));
      const instances = plate.items.map((item) => {
        const mesh = new THREE.InstancedMesh(meshes[item].geometry, this.itemMaterial(items[item].colour), plate.positions.length);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        plate.positions.forEach(([x, y], copy) => {
          mesh.setMatrixAt(copy, place.makeTranslation(offset + x - (low[0] + high[0]) / 2, y - (low[1] + high[1]) / 2, -low[2]));
        });
        copies.add(mesh);
        return mesh;
      });
      return { instances, count: plate.positions.length, sliced: plate.sliced };
    });
    this.batchCount = Math.max(...this.batch.map((plate) => plate.count));
    const centre = new THREE.Vector3((row.low + row.high) / 2, height / 2, 0);
    const points = row.offsets.flatMap((offset) => corners([offset - centre.x - bed / 2, -centre.y, -bed / 2], [offset - centre.x + bed / 2, height - centre.y, bed / 2]));
    this.batchFrame = { centre, radius: Math.max(...points.map((point) => Math.hypot(...point))), points };
    this.batchPads = pads;
    this.batchCopies = copies;
    pads.visible = copies.visible = this.view === 'plate';
    this.scene.add(pads);
    this.turntable.add(copies);
  }

  // What depends on the view only, set once when the view opens.
  configureView() {
    const isCut = this.view === 'cut';
    const isPrint = this.view === 'print';
    const isParts = this.view === 'parts';
    const isPlate = this.view === 'plate';
    this.controls.maxPolarAngle = this.view === 'model' ? BELOW_MODEL : BELOW_OTHERS;
    // Leaving the model view from below brings the camera back up within the other views' limit.
    this.controls.update();
    this.materials.forEach((material) => { material.clippingPlanes = isCut ? this.clipped : NO_CLIP; });
    this.cutMasks.visible = isCut;
    this.cap.visible = isCut;
    this.body.visible = !isPrint && !isParts && !isPlate && !this.colourParts;
    if (this.colourParts) this.colourParts.visible = !isPrint && !isParts && !isPlate;
    if (this.base) this.base.visible = isPrint;
    if (this.ghost) this.ghost.visible = isPrint;
    this.head.visible = false;
    if (this.top) this.top.visible = !isPrint && !isParts && !isPlate;
    if (this.inlay) this.inlay.visible = !isParts && !isPlate;
    if (this.items) this.items.visible = isParts;
    if (!isPrint) this.stageGroup.visible = true;
    for (const plate of this.printPlates ?? []) {
      plate.group.position.x = isPrint ? plate.offset : 0;
      plate.full.visible = isPrint;
      if (plate.walls) plate.walls.visible = isPrint;
    }
    for (const mark of this.marks ?? []) mark.hidden = !isPrint;
    if (this.pads) this.pads.visible = isPrint;
    if (this.batchPads) this.batchPads.visible = this.batchCopies.visible = isPlate;
    this.showFloor();
    if (this.view !== 'model') this.turntable.rotation.z = 0;
  }

  // The bed and its shadow go when the camera looks from below them, so the part's underside shows.
  showFloor() {
    const below = this.controls.getPolarAngle() > BELOW_OTHERS;
    this.ground.visible = !below;
    this.bed.visible = !below && this.view !== 'plate' && !(this.view === 'print' && this.pads);
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
    } else if (this.view === 'plate') {
      if (this.batch) this.applyPlate(value);
    } else if (this.printPlates) {
      this.applyPrint(value);
    }
    this.invalidate(true);
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

  // From one copy on each plate to full plates; a plate's sliced time and changes are for it full.
  applyPlate(value) {
    const count = 1 + Math.round((value / SLIDER_MAX) * (this.batchCount - 1));
    let halves = 0;
    for (const plate of this.batch) {
      const shown = Math.min(count, plate.count);
      for (const mesh of plate.instances) mesh.count = shown;
      halves += shown;
    }
    const full = count === this.batchCount && this.batch.every((plate) => plate.sliced);
    const text = full ? this.text.batch_sliced
      .replace('{time}', formatDuration(this.batch.reduce((sum, plate) => sum + plate.sliced.seconds, 0)))
      .replace('{changes}', this.batch.reduce((sum, plate) => sum + plate.sliced.changes, 0)) : this.text.batch;
    this.setReadout(text.replace('{n}', halves));
  }

  applyPrint(value) {
    const { plate: current, seconds } = plateAt(this.spans, value, SLIDER_MAX);
    const finished = value >= SLIDER_MAX;
    this.printPlates.forEach((plate, index) => {
      plate.group.visible = index <= current;
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
    if (last >= 0) this.head.position.set(points[last * 3] + plate.offset, points[last * 3 + 1], points[last * 3 + 2]);
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

  // `moved` when a solid moved or changed, so the shadows are drawn again.
  invalidate(moved = false) {
    if (moved) this.renderer.shadowMap.needsUpdate = true;
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
