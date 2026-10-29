/**
 * The 3D wallet on the dashboard.
 *
 * Progressive enhancement: the page already shows a static SVG wallet and
 * every money figure as HTML text. This module only *adds* a 3D version on
 * top when the browser supports WebGL. If anything fails, the SVG stays.
 *
 * Everything here is decoration. No financial number is calculated in JS.
 */
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const COLORS = {
  note: 0x0e6b4f,
  noteDark: 0x0a5640,
  coin: 0xd4a23a,
  coinDark: 0x7d5810,
};

// [x, y, z, tilt] for each coin that can peek out of the wallet, in the
// order they appear as the balance grows.
const PEEK_SLOTS = [
  [-0.45, 0.98, -0.05, 0.12],
  [0.18, 1.08, 0.02, -0.08],
  [-0.05, 0.92, -0.12, 0.04],
  [0.62, 0.95, -0.08, -0.18],
  [-0.85, 0.9, -0.1, 0.22],
];
const MAX_STACK = 8;
const STACK_STEP = 0.075;   // height of one coin in the stack
const RING_INNER = 1.62;
const RING_OUTER = 1.74;
const RING_COLORS = { ok: 0x1f9a6f, warning: 0xd99a1e, over: 0xc0392b };

/* ---------------------------------------------------------------------------
 * Capability checks
 * ------------------------------------------------------------------------- */

export function supportsWebGL() {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/* ---------------------------------------------------------------------------
 * Procedural geometry (no 3D model files to download)
 * ------------------------------------------------------------------------- */

function roundedRectShape(width, height, radius) {
  const x = -width / 2;
  const y = -height / 2;
  const shape = new THREE.Shape();
  shape.moveTo(x + radius, y);
  shape.lineTo(x + width - radius, y);
  shape.quadraticCurveTo(x + width, y, x + width, y + radius);
  shape.lineTo(x + width, y + height - radius);
  shape.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  shape.lineTo(x + radius, y + height);
  shape.quadraticCurveTo(x, y + height, x, y + height - radius);
  shape.lineTo(x, y + radius);
  shape.quadraticCurveTo(x, y, x + radius, y);
  return shape;
}

function roundedSlab(width, height, depth, radius, bevel = 0.05) {
  const geometry = new THREE.ExtrudeGeometry(roundedRectShape(width, height, radius), {
    depth,
    bevelEnabled: true,
    bevelThickness: bevel,
    bevelSize: bevel,
    bevelSegments: 4,
    curveSegments: 12,
  });
  geometry.center();
  return geometry;
}

/** Coin face: a gold disc with a ring and the ৳ sign, drawn on a canvas. */
function makeCoinFaceTexture() {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');

  const gradient = ctx.createRadialGradient(size * 0.4, size * 0.35, size * 0.1, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, '#f0c862');
  gradient.addColorStop(1, '#c08a22');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  ctx.strokeStyle = '#8a6212';
  ctx.lineWidth = 10;
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size * 0.38, 0, Math.PI * 2);
  ctx.stroke();

  ctx.fillStyle = '#6b4a0c';
  ctx.font = `700 ${size * 0.5}px "Hind Siliguri", "Noto Sans Bengali", sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('৳', size / 2, size * 0.54);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  // Cylinder caps map UVs at 90° to how the coins are stood up; turn the
  // drawing so the ৳ reads upright to the viewer.
  texture.center.set(0.5, 0.5);
  texture.rotation = Math.PI / 2;
  return texture;
}

/** Soft round shadow under the wallet. Cheaper than real shadow maps. */
function makeContactShadow() {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, 'rgba(0,0,0,0.35)');
  gradient.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);

  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(4.2, 1.4),
    new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, depthWrite: false }),
  );
  mesh.rotation.x = -Math.PI / 2;
  return mesh;
}

function buildCoinMaterials(faceTexture) {
  const side = new THREE.MeshStandardMaterial({ color: COLORS.coin, metalness: 0.85, roughness: 0.3 });
  const face = new THREE.MeshStandardMaterial({ map: faceTexture, metalness: 0.6, roughness: 0.35 });
  // CylinderGeometry material order: [side, top, bottom]
  return [side, face, face];
}

function buildScene() {
  const scene = new THREE.Scene();
  const root = new THREE.Group();          // everything that floats together
  scene.add(root);

  // Wallet body
  const leather = new THREE.MeshStandardMaterial({ color: COLORS.note, roughness: 0.62, metalness: 0.05 });
  const leatherDark = new THREE.MeshStandardMaterial({ color: COLORS.noteDark, roughness: 0.55, metalness: 0.05 });
  const body = new THREE.Mesh(roundedSlab(2.6, 1.7, 0.45, 0.24, 0.07), leather);
  root.add(body);

  // Top flap band across the front
  const flap = new THREE.Mesh(roundedSlab(2.62, 0.42, 0.05, 0.16, 0.03), leatherDark);
  flap.position.set(0, 0.62, 0.3);
  root.add(flap);

  // Clasp tab on the right with a gold press-stud
  const clasp = new THREE.Mesh(roundedSlab(0.78, 0.6, 0.06, 0.16, 0.03), leatherDark);
  clasp.position.set(1.0, -0.05, 0.31);
  root.add(clasp);

  const stud = new THREE.Mesh(
    new THREE.CylinderGeometry(0.13, 0.13, 0.06, 32),
    new THREE.MeshStandardMaterial({ color: COLORS.coin, metalness: 0.9, roughness: 0.25 }),
  );
  stud.rotation.x = Math.PI / 2;
  stud.position.set(0.86, -0.05, 0.38);
  root.add(stud);

  // Coins peeking out of the top: up to 5 slots, shown according to the
  // balance (see services.wallet_coin_count). They sit inside the wallet
  // body, so only their top halves are visible.
  const coinMaterials = buildCoinMaterials(makeCoinFaceTexture());
  const coinGeometry = new THREE.CylinderGeometry(0.34, 0.34, 0.07, 48);

  const peeking = [];
  PEEK_SLOTS.forEach(([x, y, z, tilt]) => {
    const coin = new THREE.Mesh(coinGeometry, coinMaterials);
    coin.rotation.set(Math.PI / 2, 0, tilt);   // stand upright, face the camera
    coin.position.set(x, y, z);
    coin.userData.baseY = y;
    coin.visible = false;
    root.add(coin);
    peeking.push(coin);
  });

  // "Spent" stack on the table: one coin per expense this month (max 8).
  const stack = new THREE.Group();
  for (let i = 0; i < MAX_STACK; i += 1) {
    const coin = new THREE.Mesh(coinGeometry, coinMaterials);
    coin.position.set((i % 2) * 0.03, i * STACK_STEP, (i % 2) * -0.02);
    coin.rotation.y = i * 0.6;
    coin.visible = false;
    stack.add(coin);
  }
  stack.position.set(-2.2, -0.93, 0.5);
  scene.add(stack);  // the stack rests on the "table", it does not float

  const shadow = makeContactShadow();
  shadow.position.y = -0.98;
  scene.add(shadow);

  // Budget ring on the table around the wallet. The track is always there;
  // the coloured arc is rebuilt from the data.
  const ringGroup = new THREE.Group();
  ringGroup.rotation.x = -Math.PI / 2;
  ringGroup.position.y = -0.97;
  const track = new THREE.Mesh(
    new THREE.RingGeometry(RING_INNER, RING_OUTER, 128),
    new THREE.MeshBasicMaterial({ color: 0x1c2b24, transparent: true, opacity: 0.08, depthWrite: false, toneMapped: false }),
  );
  ringGroup.add(track);
  ringGroup.visible = false;
  scene.add(ringGroup);

  // Lighting: soft environment for reflections + a warm key light
  scene.add(new THREE.HemisphereLight(0xfff6e5, 0x20352b, 0.45));
  const key = new THREE.DirectionalLight(0xfff1d6, 1.4);
  key.position.set(3, 4, 5);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xbfe8d6, 0.6);
  rim.position.set(-4, 2, -3);
  scene.add(rim);

  return { scene, root, peeking, stack, ringGroup, coinGeometry, coinMaterials };
}

/** Show the right number of coins and the budget arc for this user's data. */
function applyData(parts, data) {
  const { peeking, stack, ringGroup } = parts;
  peeking.forEach((coin, i) => { coin.visible = i < data.coins; });
  stack.children.forEach((coin, i) => { coin.visible = i < data.spentCoins; });

  // Replace the previous arc, if any.
  const old = ringGroup.getObjectByName('budget-arc');
  if (old) {
    old.geometry.dispose();
    old.material.dispose();
    ringGroup.remove(old);
  }
  ringGroup.visible = Boolean(data.budgetRing);
  if (data.budgetRing && data.budgetRing.fraction > 0) {
    const arc = new THREE.Mesh(
      // Starts at the front of the table and runs round as the budget is used.
      new THREE.RingGeometry(RING_INNER, RING_OUTER, 128, 1, -Math.PI / 2, data.budgetRing.fraction * Math.PI * 2),
      new THREE.MeshBasicMaterial({ color: RING_COLORS[data.budgetRing.state] ?? RING_COLORS.ok, toneMapped: false }),
    );
    arc.name = 'budget-arc';
    arc.position.z = 0.001;  // just above the track
    ringGroup.add(arc);
  }
}

/** Accept only the shapes we expect; anything odd becomes a safe default. */
export function readWalletData(raw) {
  const int = (value, max) => Math.max(0, Math.min(max, Number.parseInt(value, 10) || 0));
  let ring = null;
  if (raw && raw.budgetRing) {
    const fraction = Number.parseFloat(raw.budgetRing.fraction);
    ring = {
      fraction: Number.isFinite(fraction) ? Math.max(0, Math.min(1, fraction)) : 0,
      state: ['ok', 'warning', 'over'].includes(raw.budgetRing.state) ? raw.budgetRing.state : 'ok',
    };
  }
  return {
    coins: int(raw?.coins, PEEK_SLOTS.length),
    spentCoins: int(raw?.spentCoins, MAX_STACK),
    budgetRing: ring,
    event: ['income', 'expense'].includes(raw?.event) ? raw.event : null,
  };
}

/* ---------------------------------------------------------------------------
 * Controller
 * ------------------------------------------------------------------------- */

/**
 * Add the 3D wallet to `stage`. Returns a controller, or null when 3D is not
 * possible (the SVG fallback is then left exactly as it was).
 */
export async function initWallet(stage, {
  reducedMotion = prefersReducedMotion(),
  data = readWalletData(null),
} = {}) {
  if (!stage || !supportsWebGL()) return null;

  stage.classList.add('is-loading');

  // Wait (briefly) for the Bangla font so the ৳ on the coins renders correctly.
  try {
    await Promise.race([
      document.fonts.load('700 128px "Hind Siliguri"', '৳'),
      new Promise((resolve) => setTimeout(resolve, 1500)),
    ]);
  } catch { /* fall back to whatever font is available */ }

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  } catch (error) {
    console.warn('3D wallet unavailable, keeping the illustration.', error);
    stage.classList.remove('is-loading');
    return null;
  }

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  // Neutral tone mapping keeps the brand green close to its real colour
  // (ACES shifted it towards pale mint).
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.0;

  const canvas = renderer.domElement;
  canvas.setAttribute('aria-hidden', 'true');
  canvas.className = 'wallet-canvas';
  stage.appendChild(canvas);

  const parts = buildScene();
  const { scene, root, peeking, stack, coinGeometry, coinMaterials } = parts;
  applyData(parts, data);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.55;  // reflections for the gold, without flattening the leather
  pmrem.dispose();

  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
  const lookAt = new THREE.Vector3(0, 0.1, 0);

  // ---- sizing --------------------------------------------------------------
  function resize() {
    const width = stage.clientWidth;
    const height = stage.clientHeight;
    if (!width || !height) return;
    const aspect = width / height;
    camera.aspect = aspect;
    // Move the camera back on narrow screens so the whole scene fits.
    const distance = aspect < 1.25 ? 8.2 / Math.max(aspect, 0.6) : 7.2;
    camera.position.set(0, 1.1, distance);
    camera.lookAt(lookAt);
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
    if (!running) renderer.render(scene, camera);
  }

  // ---- subtle pointer tilt ---------------------------------------------------
  const tilt = { x: 0, y: 0, targetX: 0, targetY: 0 };
  function onPointerMove(event) {
    const rect = stage.getBoundingClientRect();
    const nx = (event.clientX - rect.left) / rect.width - 0.5;   // -0.5 .. 0.5
    const ny = (event.clientY - rect.top) / rect.height - 0.5;
    tilt.targetY = nx * 0.5;
    tilt.targetX = ny * 0.25;
  }
  function onPointerLeave() {
    tilt.targetX = 0;
    tilt.targetY = 0;
  }

  // ---- animation loop --------------------------------------------------------
  const startTime = performance.now();
  let running = false;
  let visible = true;

  function frame() {
    const t = (performance.now() - startTime) / 1000;  // seconds
    tilt.x += (tilt.targetX - tilt.x) * 0.08;
    tilt.y += (tilt.targetY - tilt.y) * 0.08;

    root.position.y = Math.sin(t * 0.9) * 0.04;
    root.rotation.y = -0.32 + Math.sin(t * 0.35) * 0.06 + tilt.y;
    root.rotation.x = 0.06 + tilt.x;
    peeking.forEach((coin, i) => {
      coin.position.y = coin.userData.baseY + Math.sin(t * 1.3 + i * 1.7) * 0.025;
    });
    runTweens();

    renderer.render(scene, camera);
  }

  // ---- tiny tween system for the save animations ------------------------------
  const tweens = [];
  function tween(duration, update, done) {
    tweens.push({ start: performance.now(), duration, update, done });
  }
  function runTweens() {
    const now = performance.now();
    for (let i = tweens.length - 1; i >= 0; i -= 1) {
      const item = tweens[i];
      const progress = Math.min(1, (now - item.start) / item.duration);
      item.update(progress);
      if (progress >= 1) {
        tweens.splice(i, 1);
        item.done?.();
      }
    }
  }
  const easeIn = (p) => p * p;
  const easeOut = (p) => 1 - (1 - p) ** 3;
  const easeInOut = (p) => (p < 0.5 ? 4 * p ** 3 : 1 - (-2 * p + 2) ** 3 / 2);

  /** A loose coin: an upright coin inside a group we can spin around Y. */
  function makeLooseCoin() {
    const group = new THREE.Group();
    const coin = new THREE.Mesh(coinGeometry, coinMaterials);
    coin.rotation.x = Math.PI / 2;
    group.add(coin);
    return { group, coin };
  }

  /** Income: a coin drops into the wallet, which gives a small squash. */
  function playIncome() {
    const { group } = makeLooseCoin();
    root.add(group);  // in wallet space, so it lines up with the opening
    tween(900, (p) => {
      group.position.set(0.05, 3.0 - easeIn(p) * 2.7, -0.05);
      group.rotation.y = (1 - p) * Math.PI * 4;
    }, () => {
      root.remove(group);
      tween(300, (p) => {
        const s = Math.sin(p * Math.PI);
        root.scale.set(1 + 0.03 * s, 1 - 0.05 * s, 1);
      }, () => root.scale.set(1, 1, 1));
    });
  }

  /** Expense: a coin rises out of the wallet and lands on the spent stack. */
  function playExpense() {
    const { group, coin } = makeLooseCoin();
    scene.add(group);  // world space: it travels between wallet and stack
    const from = root.localToWorld(new THREE.Vector3(0.05, 0.4, -0.05));
    const top = from.clone().setY(from.y + 1.3);
    const index = Math.max(0, data.spentCoins - 1);
    const landing = stack.children[index];
    const to = stack.localToWorld(new THREE.Vector3(0, index * STACK_STEP, 0));
    if (landing) landing.visible = false;  // revealed when the flying coin lands

    group.position.copy(from);
    tween(450, (p) => {
      group.position.lerpVectors(from, top, easeOut(p));
      group.rotation.y = p * Math.PI * 2;
    }, () => {
      tween(700, (p) => {
        const e = easeInOut(p);
        group.position.lerpVectors(top, to, e);
        group.position.y += Math.sin(p * Math.PI) * 0.5;   // gentle arc
        coin.rotation.x = Math.PI / 2 * (1 - e);           // lie flat as it lands
        group.rotation.y = Math.PI * 2 + p * Math.PI * 2;
      }, () => {
        scene.remove(group);
        if (landing) landing.visible = data.spentCoins > 0;
      });
    });
  }

  /** Play a save animation. Never called for a failed save (see views.py). */
  function play(kind) {
    if (reducedMotion || !running) return false;
    if (kind === 'income') playIncome();
    else if (kind === 'expense') playExpense();
    else return false;
    return true;
  }

  function updateLoop() {
    const shouldRun = !reducedMotion && visible && !document.hidden;
    if (shouldRun === running) return;
    running = shouldRun;
    renderer.setAnimationLoop(running ? frame : null);
    if (!running) renderer.render(scene, camera);
  }

  // Pause when the wallet is scrolled off screen or the tab is hidden.
  const intersection = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    updateLoop();
  });
  intersection.observe(stage);
  document.addEventListener('visibilitychange', updateLoop);

  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(stage);

  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  function onMotionChange(event) {
    reducedMotion = event.matches;
    updateLoop();
  }
  motionQuery.addEventListener('change', onMotionChange);

  if (!reducedMotion) {
    stage.addEventListener('pointermove', onPointerMove);
    stage.addEventListener('pointerleave', onPointerLeave);
  }

  // ---- teardown --------------------------------------------------------------
  function dispose() {
    renderer.setAnimationLoop(null);
    running = false;
    intersection.disconnect();
    resizeObserver.disconnect();
    document.removeEventListener('visibilitychange', updateLoop);
    motionQuery.removeEventListener('change', onMotionChange);
    stage.removeEventListener('pointermove', onPointerMove);
    stage.removeEventListener('pointerleave', onPointerLeave);
    scene.traverse((object) => {
      if (object.geometry) object.geometry.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.filter(Boolean).forEach((material) => {
        if (material.map) material.map.dispose();
        material.dispose();
      });
    });
    renderer.dispose();
    canvas.remove();
    stage.classList.remove('is-3d', 'is-loading');
  }

  // If the GPU drops the context (driver reset, low memory), go back to the SVG.
  canvas.addEventListener('webglcontextlost', (event) => {
    event.preventDefault();
    console.warn('WebGL context lost, showing the illustration instead.');
    dispose();
  });

  resize();
  renderer.render(scene, camera);
  stage.classList.remove('is-loading');
  stage.classList.add('is-3d');
  updateLoop();

  // A save just happened: play its animation once the canvas has faded in.
  if (data.event) setTimeout(() => play(data.event), 450);

  return {
    get isAnimating() { return running; },
    get activeTweens() { return tweens.length; },
    data,
    play,
    renderer,
    scene,
    dispose,
  };
}

/* ---------------------------------------------------------------------------
 * Auto-start on the dashboard
 * ------------------------------------------------------------------------- */

const stage = document.getElementById('wallet-stage');
if (stage) {
  let raw = null;
  try {
    raw = JSON.parse(document.getElementById('wallet-data')?.textContent || 'null');
  } catch { /* bad data: show the default wallet */ }
  initWallet(stage, { data: readWalletData(raw) })
    .then((controller) => { stage.wallet = controller; })
    .catch((error) => {
      console.warn('3D wallet failed to start, keeping the illustration.', error);
      stage.classList.remove('is-loading', 'is-3d');
      stage.querySelector('canvas.wallet-canvas')?.remove();
    });
}
