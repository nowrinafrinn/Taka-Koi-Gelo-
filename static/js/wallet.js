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

  // Coins: two peeking out of the top, three stacked beside the wallet
  const coinMaterials = buildCoinMaterials(makeCoinFaceTexture());
  const coinGeometry = new THREE.CylinderGeometry(0.34, 0.34, 0.07, 48);

  const peeking = [];
  [[-0.45, 0.98, -0.05, 0.12], [0.18, 1.08, 0.02, -0.08]].forEach(([x, y, z, tilt]) => {
    const coin = new THREE.Mesh(coinGeometry, coinMaterials);
    coin.rotation.set(Math.PI / 2, 0, tilt);   // stand upright, face the camera
    coin.position.set(x, y, z);
    coin.userData.baseY = y;
    root.add(coin);
    peeking.push(coin);
  });
  // Peeking coins sit behind the wallet's top edge so they look tucked in.
  peeking.forEach((coin) => { coin.renderOrder = -1; });

  const stack = new THREE.Group();
  for (let i = 0; i < 3; i += 1) {
    const coin = new THREE.Mesh(coinGeometry, coinMaterials);
    coin.position.set((i % 2) * 0.03, i * 0.075, (i % 2) * -0.02);
    coin.rotation.y = i * 0.6;
    stack.add(coin);
  }
  stack.position.set(-1.85, -0.82, 0.35);
  scene.add(stack);  // the stack rests on the "table", it does not float

  const shadow = makeContactShadow();
  shadow.position.y = -0.98;
  scene.add(shadow);

  // Lighting: soft environment for reflections + a warm key light
  scene.add(new THREE.HemisphereLight(0xfff6e5, 0x20352b, 0.45));
  const key = new THREE.DirectionalLight(0xfff1d6, 1.4);
  key.position.set(3, 4, 5);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xbfe8d6, 0.6);
  rim.position.set(-4, 2, -3);
  scene.add(rim);

  return { scene, root, peeking, stack };
}

/* ---------------------------------------------------------------------------
 * Controller
 * ------------------------------------------------------------------------- */

/**
 * Add the 3D wallet to `stage`. Returns a controller, or null when 3D is not
 * possible (the SVG fallback is then left exactly as it was).
 */
export async function initWallet(stage, { reducedMotion = prefersReducedMotion() } = {}) {
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

  const { scene, root, peeking } = buildScene();
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

    renderer.render(scene, camera);
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

  return {
    get isAnimating() { return running; },
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
  initWallet(stage)
    .then((controller) => { stage.wallet = controller; })
    .catch((error) => {
      console.warn('3D wallet failed to start, keeping the illustration.', error);
      stage.classList.remove('is-loading', 'is-3d');
      stage.querySelector('canvas.wallet-canvas')?.remove();
    });
}
