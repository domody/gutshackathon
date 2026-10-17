import './styles.css';
import type { NormalizedLandmark } from '@mediapipe/tasks-vision';
import { accumulateDamage, coverageIndex, distance, smooth, updatePinchState, updateSideStep, type Point, type SideStepState } from './logic';
import { VisionTracker, type TrackerKind, type TrackingResult } from './tracking';

type Game = 'dalgona' | 'redlight' | 'tug' | 'bridge';
const gameMeta: Record<Game, { number: string; title: string; short: string; tracker: TrackerKind; distance: string }> = {
  dalgona: { number: '01', title: 'Dalgona trace', short: 'Pinch + guide', tracker: 'hand', distance: 'Sit 60–90 cm away. Keep one hand fully visible.' },
  redlight: { number: '02', title: 'Run / freeze', short: 'Move + stillness', tracker: 'pose', distance: 'Stand 1.5–2.5 m away with head, shoulders and hands visible.' },
  tug: { number: '03', title: 'Tug of war', short: 'Expression + relax', tracker: 'face', distance: 'Sit 50–80 cm away with your whole face evenly lit.' },
  bridge: { number: '04', title: 'Glass bridge', short: 'Head left + right', tracker: 'face', distance: 'Sit naturally 50–90 cm away. Only your face needs to stay visible.' },
};

const app = document.querySelector<HTMLDivElement>('#app')!;
app.innerHTML = `
  <main class="app">
    <header><div><div class="eyebrow">GUTS / webcam game collection</div><h1>Four games. Your camera is the controller.</h1><p class="subtitle">Pick a game, follow its three-step setup, then play—nothing leaves your browser.</p></div>
      <div class="statusbar"><i class="dot" id="status-dot"></i><span id="status-text">Camera off</span> · <span id="fps">0 FPS</span></div></header>
    <nav class="tabs" aria-label="Prototype selector">${(Object.keys(gameMeta) as Game[]).map((key) => `<button class="tab" data-game="${key}"><span>${gameMeta[key].number} / ${gameMeta[key].short}</span>${gameMeta[key].title}</button>`).join('')}</nav>
    <section class="workspace">
      <div class="stage">
        <video id="camera" playsinline muted></video><canvas id="canvas"></canvas>
        <div class="stage-top"><span class="pill" id="tracking-pill">● NOT TRACKING</span><span class="pill" id="stage-score">READY</span></div>
        <div class="stage-message" id="stage-message"><div><div class="eyebrow">Local processing · no video uploaded</div><h2>Allow camera access to begin</h2><p id="permission-copy">The first model may take a few seconds to load. Use bright, even lighting and follow the distance guide.</p><button class="primary" id="start-camera">Start camera</button></div></div>
      </div>
      <aside class="panel" id="panel"></aside>
    </section>
  </main>`;

const video = document.querySelector<HTMLVideoElement>('#camera')!;
const canvas = document.querySelector<HTMLCanvasElement>('#canvas')!;
const ctx = canvas.getContext('2d')!;
const tracker = new VisionTracker();
let stream: MediaStream | null = null;
let game: Game = 'dalgona';
let latest: TrackingResult = { landmarks: null };
let lastFrame = 0;
let lastInference = 0;
let fpsSamples: number[] = [];
let loading = false;
let events: string[] = [];
let previousTracked = false;
let tutorialUntil = 0;

const cfg = {
  sensitivity: 1, smoothing: 0.58, pinchOn: 0.25, pinchOff: 0.34, tolerance: 32, assist: false, debug: true,
  moveSensitivity: 1, grace: 0.65, expressionSensitivity: 1, stepThreshold: 0.4, cooldown: 0.55,
};
const dalgona = { cursor: null as Point | null, raw: null as Point | null, pinch: false, coverage: new Set<number>(), damage: 0, shape: 'triangle' as 'triangle' | 'circle', complete: false };
const redlight = { calibrated: false, baseline: 0.05, lastPoints: null as Point[] | null, movement: 0, distance: 0, phaseStarted: 0, green: true, caught: false };
const tug = { neutral: null as number | null, pull: null as number | null, raw: 0, score: 0, active: false, stamina: 100, rope: 0, won: false };
const bridge = { centre: null as number | null, state: { armed: true, choice: 0 } as SideStepState, progress: 0, route: [-1, 1, 1, -1, 1, -1] as (-1 | 1)[], previewUntil: 0, lastChoice: 0, failed: false };

function addEvent(message: string) {
  const stamp = new Date().toLocaleTimeString([], { minute: '2-digit', second: '2-digit' });
  events.unshift(`${stamp} — ${message}`); events = events.slice(0, 6);
  document.querySelector('.log ol')?.replaceChildren(...events.map((e) => Object.assign(document.createElement('li'), { textContent: e })));
}

function slider(label: string, key: keyof typeof cfg, min: number, max: number, step: number) {
  return `<div class="control"><label>${label}<output>${cfg[key]}</output></label><input type="range" data-config="${key}" min="${min}" max="${max}" step="${step}" value="${cfg[key]}"></div>`;
}

function metric(label: string, id: string, suffix = '') { return `<div class="metric"><label>${label}</label><strong id="${id}">0${suffix}</strong><div class="bar"><i id="${id}-bar"></i></div></div>`; }

function guide(steps: string[]) {
  return `<section class="howto"><div class="howto-title">How to play</div>${steps.map((step, index) => `<div class="howto-step"><b>${index + 1}</b><span>${step}</span></div>`).join('')}</section>`;
}

function renderPanel() {
  const meta = gameMeta[game];
  let body = '';
  if (game === 'dalgona') body = `
    ${guide(['Hold one hand up and move your <strong>index fingertip</strong> onto the outline.', '<strong>Pinch thumb and index finger</strong> to lower the needle and carve.', '<strong>Open your fingers</strong> to reposition. Trace new sections until coverage is complete.'])}
    <div class="feedback" id="feedback">Release your pinch to position the needle</div>
    <div class="metrics">${metric('Outline coverage', 'coverage', '%')}${metric('Cookie damage', 'damage', '%')}</div>
    <div class="controls">${slider('Cursor sensitivity', 'sensitivity', .65, 1.7, .05)}${slider('Motion smoothing', 'smoothing', 0, .9, .05)}${slider('Outline tolerance', 'tolerance', 14, 64, 2)}${slider('Pinch engage', 'pinchOn', .12, .38, .01)}${slider('Pinch release', 'pinchOff', .2, .5, .01)}
      <label class="toggle"><input type="checkbox" data-toggle="assist" ${cfg.assist ? 'checked' : ''}> Light outline assistance</label><label class="toggle"><input type="checkbox" data-toggle="debug" ${cfg.debug ? 'checked' : ''}> Debug landmarks + raw position</label>
      <div class="buttons"><button class="secondary" data-action="reset">Reset</button><button class="secondary" data-action="shape">Shape: ${dalgona.shape}</button></div></div>`;
  if (game === 'redlight') body = `
    ${guide(['Stand still in a comfortable pose and press <strong>Calibrate stillness</strong>.', 'On <strong>green</strong>, alternately swing your arms as if jogging—your feet can stay still.', 'On <strong>red</strong>, freeze before the grace timer ends. Reach 100% without being caught.'])}
    <div class="feedback" id="feedback">Calibrate while standing naturally and still</div>
    <div class="metrics">${metric('Movement', 'movement')}${metric('Course', 'course', '%')}</div>
    <div class="controls">${slider('Movement sensitivity', 'moveSensitivity', .5, 2, .05)}${slider('Red-light grace', 'grace', .2, 1.2, .05)}<div class="buttons"><button class="primary" data-action="calibrate">${redlight.calibrated ? 'Recalibrate stillness' : 'Calibrate stillness'}</button><button class="secondary" data-action="reset">Reset course</button></div></div>`;
  if (game === 'tug') body = `
    ${guide(['Relax your face and press <strong>Capture relaxed face</strong>.', 'Make one obvious “pull face”—for example open your mouth and furrow your brows—then capture it.', '<strong>Hold that same face to pull.</strong> Relax to recover stamina, then pull again.'])}
    <div class="feedback" id="feedback">First capture a relaxed neutral face</div>
    <div class="metrics">${metric('Expression score', 'expression', '%')}${metric('Stamina', 'stamina', '%')}</div>
    <div class="controls">${slider('Expression sensitivity', 'expressionSensitivity', .55, 1.8, .05)}<p class="cal-note">This reacts only to visible facial movement. It does not measure force, strain, effort or emotion.</p><div class="buttons"><button class="primary" data-action="calibrate">${tug.neutral == null ? 'Capture relaxed face' : tug.pull == null ? 'Capture pull face' : 'Recapture pull face'}</button>${tug.neutral != null ? '<button class="secondary" data-action="recalibrate">Start calibration over</button>' : ''}<button class="secondary" data-action="reset">Reset match</button></div></div>`;
  if (game === 'bridge') body = `
    ${guide(['Look straight at the camera and press <strong>Set centre</strong>.', 'Press <strong>Preview safe route</strong> and memorise the glowing left/right panes.', 'Move your <strong>head clearly left or right</strong>, then return to centre before the next choice.'])}
    <div class="feedback" id="feedback">Look straight ahead, then set your centre</div>
    <div class="metrics">${metric('Head movement', 'offset')}${metric('Bridge', 'bridge-progress', '%')}</div>
    <div class="controls">${slider('Head movement needed', 'stepThreshold', .2, .75, .05)}${slider('Choice cooldown', 'cooldown', .2, 1.2, .05)}<div class="buttons"><button class="primary" data-action="calibrate">${bridge.centre == null ? 'Set centre' : 'Reset centre'}</button><button class="secondary" data-action="preview">Preview safe route</button><button class="secondary" data-action="reset">Reset bridge</button></div></div>`;
  document.querySelector('#panel')!.innerHTML = `<div><div class="eyebrow">Game ${meta.number}</div><h2>${meta.title}</h2><p class="description">${meta.distance}</p></div>${body}<div class="log"><div class="log-title">Game activity</div><ol>${events.map((e) => `<li>${e}</li>`).join('')}</ol></div>`;
  bindPanel(); updateTabs();
}

function bindPanel() {
  document.querySelectorAll<HTMLInputElement>('[data-config]').forEach((input) => input.addEventListener('input', () => {
    const key = input.dataset.config as keyof typeof cfg; (cfg[key] as number) = Number(input.value);
    input.previousElementSibling!.querySelector('output')!.textContent = input.value;
    if (key === 'pinchOn' && cfg.pinchOff <= cfg.pinchOn) cfg.pinchOff = cfg.pinchOn + .05;
  }));
  document.querySelectorAll<HTMLInputElement>('[data-toggle]').forEach((input) => input.addEventListener('change', () => { (cfg[input.dataset.toggle as 'assist' | 'debug'] as boolean) = input.checked; }));
  document.querySelectorAll<HTMLButtonElement>('[data-action]').forEach((button) => button.addEventListener('click', () => action(button.dataset.action!)));
}

function action(name: string) {
  if (name === 'reset') {
    if (game === 'dalgona') Object.assign(dalgona, { coverage: new Set(), damage: 0, complete: false, cursor: null, pinch: false });
    if (game === 'redlight') Object.assign(redlight, { distance: 0, caught: false, phaseStarted: performance.now(), green: true });
    if (game === 'tug') Object.assign(tug, { stamina: 100, rope: 0, won: false });
    if (game === 'bridge') Object.assign(bridge, { progress: 0, failed: false, state: { armed: true, choice: 0 }, previewUntil: 0 });
    addEvent('Game reset'); return;
  }
  if (name === 'shape') { dalgona.shape = dalgona.shape === 'triangle' ? 'circle' : 'triangle'; action('reset'); renderPanel(); addEvent(`${dalgona.shape} outline selected`); }
  if (name === 'calibrate' && game === 'redlight' && latest.landmarks) { redlight.baseline = Math.max(.025, redlight.movement); redlight.calibrated = true; redlight.distance = 0; addEvent('Neutral movement calibrated'); }
  if (name === 'calibrate' && game === 'tug') {
    if (tug.neutral == null) { tug.neutral = tug.raw; addEvent('Neutral face captured'); }
    else { tug.pull = Math.max(tug.neutral + .08, tug.raw); addEvent('Pull expression captured'); }
    renderPanel();
  }
  if (name === 'recalibrate' && game === 'tug') { tug.neutral = null; tug.pull = null; tug.score = 0; tug.active = false; renderPanel(); addEvent('Face calibration restarted'); }
  if (name === 'calibrate' && game === 'bridge' && latest.landmarks) { bridge.centre = headPosition(latest.landmarks); bridge.state = { armed: true, choice: 0 }; renderPanel(); addEvent('Head centre calibrated'); }
  if (name === 'preview') { bridge.previewUntil = performance.now() + 3000; addEvent('Safe route previewed'); }
}

function updateTabs() {
  document.querySelectorAll<HTMLButtonElement>('.tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.game === game));
}

document.querySelectorAll<HTMLButtonElement>('.tab').forEach((tab) => tab.addEventListener('click', async () => {
  const next = tab.dataset.game as Game; if (next === game) return; game = next; events = []; tutorialUntil = performance.now() + 6500; renderPanel();
  if (stream) await loadTracker();
}));
document.querySelector('#start-camera')!.addEventListener('click', startCamera);

async function startCamera() {
  const message = document.querySelector('#stage-message')!; const copy = document.querySelector('#permission-copy')!;
  try {
    loading = true; copy.textContent = 'Requesting camera permission…';
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } }, audio: false });
    video.srcObject = stream; await video.play(); await loadTracker(); message.classList.add('hidden'); tutorialUntil = performance.now() + 8000; requestAnimationFrame(loop);
  } catch (error) {
    loading = false; document.querySelector('.stage-message h2')!.textContent = 'Camera could not start';
    copy.textContent = error instanceof Error ? `${error.message}. Check browser camera permissions, then try again.` : 'Check browser camera permissions, then try again.';
  }
}

async function loadTracker() {
  loading = true; setStatus('Loading model…', '');
  try { await tracker.load(gameMeta[game].tracker); addEvent(`${gameMeta[game].tracker} tracker ready`); loading = false; }
  catch (error) { loading = false; setStatus('Model failed', 'bad'); document.querySelector('#stage-message')!.classList.remove('hidden'); document.querySelector('.stage-message h2')!.textContent = 'Tracking model failed to load'; document.querySelector('#permission-copy')!.textContent = error instanceof Error ? error.message : 'Check your internet connection and reload.'; throw error; }
}

function setStatus(text: string, kind: '' | 'good' | 'bad') {
  document.querySelector('#status-text')!.textContent = text; document.querySelector('#status-dot')!.className = `dot ${kind}`;
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect(); const scale = Math.min(devicePixelRatio, 2);
  const w = Math.round(rect.width * scale), h = Math.round(rect.height * scale);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
}

function loop(now: number) {
  if (!stream) return; resizeCanvas(); const dt = Math.min(.1, (now - (lastFrame || now)) / 1000); lastFrame = now;
  if (!loading && video.readyState >= 2 && now - lastInference > 33) {
    const started = performance.now(); try { latest = tracker.detect(video, now); } catch { latest = { landmarks: null }; }
    const elapsed = performance.now() - started; fpsSamples.push(elapsed); if (fpsSamples.length > 30) fpsSamples.shift(); lastInference = now;
  }
  drawVideo(); const tracked = !!latest.landmarks;
  if (tracked !== previousTracked) { addEvent(tracked ? 'Tracking acquired' : 'Tracking lost — game paused'); previousTracked = tracked; }
  if (game === 'dalgona') updateDalgona(latest.landmarks, dt);
  if (game === 'redlight') updateRedLight(latest.landmarks, dt, now);
  if (game === 'tug') updateTug(latest, dt);
  if (game === 'bridge') updateBridge(latest.landmarks, now);
  drawLandmarks(latest.landmarks); drawTutorial(now);
  setStatus(tracked ? 'Tracking stable' : 'Find player…', tracked ? 'good' : 'bad');
  document.querySelector('#tracking-pill')!.textContent = tracked ? '● TRACKING' : '● PAUSED — NO TRACK';
  const avg = fpsSamples.reduce((a, b) => a + b, 0) / Math.max(1, fpsSamples.length); document.querySelector('#fps')!.textContent = `${Math.round(1000 / Math.max(1, avg))} infer/s · ${Math.round(avg)} ms`;
  requestAnimationFrame(loop);
}

function drawVideo() {
  ctx.save(); ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.translate(canvas.width, 0); ctx.scale(-1, 1);
  const scale = Math.max(canvas.width / video.videoWidth, canvas.height / video.videoHeight); const w = video.videoWidth * scale, h = video.videoHeight * scale;
  ctx.drawImage(video, (canvas.width - w) / 2, (canvas.height - h) / 2, w, h); ctx.restore();
  ctx.fillStyle = '#07100b42'; ctx.fillRect(0, 0, canvas.width, canvas.height);
}

function screenPoint(p: NormalizedLandmark): Point { return { x: (1 - p.x) * canvas.width, y: p.y * canvas.height }; }
function drawLandmarks(points: NormalizedLandmark[] | null) {
  if (!points || !cfg.debug) return; ctx.fillStyle = '#b1ff6aaa';
  const subset = game === 'dalgona' ? points : game === 'tug' || game === 'bridge' ? points.filter((_, i) => i % 8 === 0) : points;
  for (const point of subset) { const p = screenPoint(point); ctx.beginPath(); ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2); ctx.fill(); }
}

function tracePath(): Point[] {
  const cx = canvas.width * .5, cy = canvas.height * .53, size = Math.min(canvas.width, canvas.height) * .34;
  if (dalgona.shape === 'circle') return Array.from({ length: 65 }, (_, i) => ({ x: cx + Math.cos((i / 64) * Math.PI * 2) * size * .7, y: cy + Math.sin((i / 64) * Math.PI * 2) * size * .7 }));
  return [{ x: cx, y: cy - size }, { x: cx + size * .88, y: cy + size * .65 }, { x: cx - size * .88, y: cy + size * .65 }, { x: cx, y: cy - size }];
}

function drawPath(path: Point[]) {
  ctx.save(); ctx.lineJoin = 'round'; ctx.lineCap = 'round'; ctx.beginPath(); path.forEach((p, i) => i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y));
  ctx.strokeStyle = '#ad7937'; ctx.lineWidth = cfg.tolerance * 2; ctx.globalAlpha = .36; ctx.stroke(); ctx.globalAlpha = 1; ctx.strokeStyle = '#f5e4b7'; ctx.lineWidth = 4; ctx.stroke(); ctx.restore();
}

function updateDalgona(points: NormalizedLandmark[] | null, dt: number) {
  const path = tracePath(); drawCookie(); drawPath(path); const tracked = !!points;
  if (points) {
    const index = screenPoint(points[8]), thumb = screenPoint(points[4]); const wrist = screenPoint(points[0]); const middle = screenPoint(points[9]);
    const normalizedPinch = distance(index, thumb) / Math.max(20, distance(wrist, middle)); dalgona.pinch = updatePinchState(dalgona.pinch, normalizedPinch, cfg.pinchOn, cfg.pinchOff);
    const center = { x: canvas.width / 2, y: canvas.height / 2 }; let raw = { x: center.x + (index.x - center.x) * cfg.sensitivity, y: center.y + (index.y - center.y) * cfg.sensitivity }; dalgona.raw = raw;
    if (cfg.assist) { const snap = nearestOnPath(raw, path); if (snap.d < cfg.tolerance * 2.1) raw = { x: raw.x * .72 + snap.p.x * .28, y: raw.y * .72 + snap.p.y * .28 }; }
    dalgona.cursor = smooth(dalgona.cursor, raw, cfg.smoothing);
    const bin = coverageIndex(dalgona.cursor, path, cfg.tolerance, 120); const outside = bin == null;
    if (dalgona.pinch && !outside && !dalgona.complete) dalgona.coverage.add(bin);
    dalgona.damage = accumulateDamage(dalgona.damage, outside, dalgona.pinch, tracked, dt, 15);
    const coverage = dalgona.coverage.size / 120 * 100; if (coverage >= 88 && !dalgona.complete) { dalgona.complete = true; addEvent('Outline complete'); }
    drawCursor(dalgona.cursor, dalgona.pinch, outside); setMetric('coverage', coverage); setMetric('damage', dalgona.damage);
    setFeedback(dalgona.complete ? 'Complete — clean cut!' : dalgona.damage >= 100 ? 'Cookie cracked — reset to retry' : dalgona.pinch ? (outside ? 'Outside corridor — damage rising' : 'Carving correctly') : 'Repositioning — pinch to carve');
    document.querySelector('#stage-score')!.textContent = dalgona.pinch ? 'PINCH / CARVE' : 'OPEN / REPOSITION';
    if (cfg.debug && dalgona.raw) { ctx.strokeStyle = '#ff6c88'; ctx.beginPath(); ctx.moveTo(dalgona.raw.x - 7, dalgona.raw.y); ctx.lineTo(dalgona.raw.x + 7, dalgona.raw.y); ctx.moveTo(dalgona.raw.x, dalgona.raw.y - 7); ctx.lineTo(dalgona.raw.x, dalgona.raw.y + 7); ctx.stroke(); }
  } else { dalgona.pinch = false; setFeedback('Tracking paused — show one full hand'); }
}

function drawCookie() { ctx.fillStyle = '#9b6326dd'; ctx.beginPath(); ctx.arc(canvas.width / 2, canvas.height * .53, Math.min(canvas.width, canvas.height) * .42, 0, Math.PI * 2); ctx.fill(); }
function drawCursor(p: Point, engaged: boolean, outside: boolean) { ctx.beginPath(); ctx.arc(p.x, p.y, engaged ? 13 : 9, 0, Math.PI * 2); ctx.fillStyle = engaged ? (outside ? '#ff5d55' : '#b1ff6a') : '#ffffff'; ctx.fill(); ctx.strokeStyle = '#111'; ctx.lineWidth = 3; ctx.stroke(); }
function nearestOnPath(p: Point, path: Point[]) { let best = { p: path[0], d: Infinity }; for (let i = 0; i < path.length - 1; i++) { const a = path[i], b = path[i + 1], dx = b.x-a.x, dy=b.y-a.y, t = Math.max(0, Math.min(1, ((p.x-a.x)*dx+(p.y-a.y)*dy)/(dx*dx+dy*dy))); const q={x:a.x+dx*t,y:a.y+dy*t}, d=distance(p,q); if(d<best.d)best={p:q,d}; } return best; }

function updateRedLight(points: NormalizedLandmark[] | null, dt: number, now: number) {
  const greenLength = 3800, redLength = 2600, cycle = greenLength + redLength, cycleTime = now % cycle; const green = cycleTime < greenLength;
  if (green !== redlight.green) { redlight.green = green; redlight.phaseStarted = now; addEvent(green ? 'Green light' : 'Red light'); }
  ctx.fillStyle = green ? '#68d74355' : '#ef404055'; ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!points || !upperBodyVisible(points)) { setFeedback('Paused — keep head, shoulders and hands visible'); redlight.lastPoints = null; return; }
  const ids = [11,12,13,14,15,16]; const current = ids.map((i) => screenPoint(points[i])); const bodyScale = Math.max(50, distance(current[0], current[1]));
  if (redlight.lastPoints) { const raw = current.reduce((sum,p,i)=>sum+distance(p,redlight.lastPoints![i]),0)/current.length/bodyScale; redlight.movement = redlight.movement*.72+raw*.28; }
  redlight.lastPoints = current; const active = redlight.movement > redlight.baseline * (2.25 / cfg.moveSensitivity);
  if (redlight.calibrated && green && active && !redlight.caught) redlight.distance = Math.min(100, redlight.distance + dt * 14 * Math.min(2, redlight.movement / Math.max(.01, redlight.baseline)));
  const inGrace = !green && (now - redlight.phaseStarted) / 1000 < cfg.grace;
  if (redlight.calibrated && !green && !inGrace && redlight.movement > redlight.baseline * (2.8 / cfg.moveSensitivity) && !redlight.caught) { redlight.caught = true; addEvent('Movement detected on red'); }
  drawRunner(redlight.distance); setMetric('movement', Math.min(100, redlight.movement*700)); setMetric('course', redlight.distance);
  setFeedback(!redlight.calibrated ? 'Stand still, then calibrate neutral movement' : redlight.caught ? 'Caught moving — reset the course' : green ? (active ? 'Running detected — advancing' : 'GREEN — alternate your arms') : inGrace ? 'RED — stopping grace' : active ? 'Too much movement' : 'Frozen — good');
  document.querySelector('#stage-score')!.textContent = green ? 'GREEN LIGHT' : inGrace ? 'STOPPING…' : 'RED LIGHT';
}
function upperBodyVisible(p: NormalizedLandmark[]) { return [0,11,12,15,16].every(i => p[i] && (p[i].visibility ?? 1) > .45); }
function drawRunner(progress: number) { const y=canvas.height*.83; ctx.strokeStyle='#ffffff66';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(canvas.width*.12,y);ctx.lineTo(canvas.width*.88,y);ctx.stroke(); const x=canvas.width*(.12+.76*progress/100);ctx.fillStyle='#b1ff6a';ctx.beginPath();ctx.arc(x,y-22,16,0,Math.PI*2);ctx.fill(); }

function expressionRaw(blend: Record<string, number> = {}) { return (blend.jawOpen ?? 0)*.38 + ((blend.mouthSmileLeft??0)+(blend.mouthSmileRight??0))*.12 + ((blend.browDownLeft??0)+(blend.browDownRight??0))*.19; }
function updateTug(result: TrackingResult, dt: number) {
  if (!result.landmarks) { setFeedback('Paused — keep your full face visible'); return; }
  tug.raw = expressionRaw(result.blendshapes); let normalized = 0;
  if (tug.neutral != null && tug.pull != null) normalized = Math.max(0, Math.min(1.4, (tug.raw-tug.neutral)/(tug.pull-tug.neutral)*cfg.expressionSensitivity));
  tug.score = tug.score*.78+normalized*100*.22; const wasActive=tug.active; tug.active = wasActive ? tug.score>48 : tug.score>62;
  if (wasActive!==tug.active) addEvent(tug.active?'Pull activated':'Expression relaxed');
  if (!tug.won) { if(tug.active && tug.stamina>0){tug.rope+=dt*12;tug.stamina=Math.max(0,tug.stamina-dt*15);} else {tug.rope-=dt*5;tug.stamina=Math.min(100,tug.stamina+dt*18);} tug.rope=Math.max(-25,Math.min(100,tug.rope)); if(tug.rope>=100){tug.won=true;addEvent('Tug won');} }
  drawRope(); setMetric('expression',tug.score);setMetric('stamina',tug.stamina);
  setFeedback(tug.neutral==null?'Relax your face and capture neutral':tug.pull==null?'Make an exaggerated pull face, then capture it':tug.won?'Match won':tug.active?'Expression registered — pulling':'Relaxing — recovering stamina');
  document.querySelector('#stage-score')!.textContent=tug.active?'PULLING':'RECOVERING';
}
function drawRope(){const y=canvas.height*.72, mid=canvas.width*(.38+tug.rope/100*.24);ctx.strokeStyle='#d2b48c';ctx.lineWidth=10;ctx.beginPath();ctx.moveTo(canvas.width*.12,y);ctx.lineTo(canvas.width*.88,y);ctx.stroke();ctx.strokeStyle='#b1ff6a';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(mid,y-30);ctx.lineTo(mid,y+30);ctx.stroke();ctx.fillStyle='#fff';ctx.font=`600 ${canvas.width*.025}px Space Grotesk`;ctx.textAlign='center';ctx.fillText(tug.won?'YOU WIN':'EXPRESSION PULL',canvas.width/2,y-55);}

function headPosition(points: NormalizedLandmark[]) { return 1 - points[1].x; }
function faceWidth(points: NormalizedLandmark[]) { return Math.max(.08, Math.abs(points[234].x - points[454].x)); }
function updateBridge(points: NormalizedLandmark[] | null, now: number) {
  drawBridge(now); if(!points || !points[1] || !points[234] || !points[454]){drawHeadControl(null);setFeedback('Paused — keep your whole face visible');return;}
  const centre=headPosition(points); if(bridge.centre==null){drawHeadControl(0);setFeedback('Look straight ahead, then press Set centre');return;}
  const offset=(centre-bridge.centre)/faceWidth(points); drawHeadControl(offset); const previous=bridge.state; const next=updateSideStep(previous,offset,cfg.stepThreshold);
  if(next.choice!==0 && now-bridge.lastChoice>cfg.cooldown*1000&&!bridge.failed){bridge.lastChoice=now; const expected=bridge.route[bridge.progress]; if(next.choice===expected){bridge.progress++;addEvent(`Step ${next.choice<0?'left':'right'} — safe`);}else{bridge.failed=true;addEvent(`Step ${next.choice<0?'left':'right'} — glass broke`);}}
  if(!previous.armed&&next.armed)addEvent('Centre reached — rearmed'); bridge.state=next; setMetric('offset',Math.min(100,Math.abs(offset)/cfg.stepThreshold*50));setMetric('bridge-progress',bridge.progress/bridge.route.length*100);
  setFeedback(bridge.failed?'Wrong pane — reset the bridge':bridge.progress>=bridge.route.length?'Bridge crossed!':!bridge.state.armed?'Bring your head back to the centre':offset<-cfg.stepThreshold*.45?'Keep moving your head left':offset>cfg.stepThreshold*.45?'Keep moving your head right':'Centred and ready — choose left or right'); document.querySelector('#stage-score')!.textContent=bridge.state.armed?'CHOOSE A SIDE':'RETURN TO CENTRE';
}
function drawBridge(now:number){const preview=now<bridge.previewUntil;const w=canvas.width*.13,h=canvas.height*.085,gap=8,startY=canvas.height*.18;for(let i=0;i<bridge.route.length;i++){for(const side of [-1,1] as const){const x=canvas.width/2+side*(w*.55+gap/2)-w/2,y=startY+i*(h+gap);ctx.fillStyle=i<bridge.progress?'#b1ff6aaa':preview&&side===bridge.route[i]?'#b1ff6a88':'#bfe8ef33';ctx.strokeStyle='#d9f8ff88';ctx.lineWidth=2;ctx.fillRect(x,y,w,h);ctx.strokeRect(x,y,w,h);}}}
function drawHeadControl(offset: number | null){const y=canvas.height*.9,left=canvas.width*.24,right=canvas.width*.76;ctx.fillStyle='#0b0d0ddd';ctx.fillRect(left-18,y-30,right-left+36,60);ctx.strokeStyle='#ffffff55';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();const zone=cfg.stepThreshold/(cfg.stepThreshold+1);const centre=canvas.width/2,span=(right-left)/2;ctx.strokeStyle='#b1ff6a88';ctx.beginPath();ctx.moveTo(centre-span*zone,y-18);ctx.lineTo(centre-span*zone,y+18);ctx.moveTo(centre+span*zone,y-18);ctx.lineTo(centre+span*zone,y+18);ctx.stroke();ctx.fillStyle='#ffffffaa';ctx.font=`500 ${Math.max(10,canvas.width*.012)}px DM Mono`;ctx.textAlign='center';ctx.fillText('LEFT',left,y-10);ctx.fillText('CENTRE',centre,y-10);ctx.fillText('RIGHT',right,y-10);if(offset!==null){const marker=centre+Math.max(-1,Math.min(1,offset/(cfg.stepThreshold*1.4)))*span;ctx.fillStyle='#b1ff6a';ctx.beginPath();ctx.arc(marker,y,10,0,Math.PI*2);ctx.fill();}}

function setMetric(id:string,value:number){const text=document.querySelector(`#${id}`);const bar=document.querySelector<HTMLElement>(`#${id}-bar`);if(text)text.textContent=`${Math.round(value)}${['coverage','damage','course','expression','stamina','bridge-progress'].includes(id)?'%':''}`;if(bar)bar.style.width=`${Math.max(0,Math.min(100,value))}%`;}
function setFeedback(text:string){const el=document.querySelector('#feedback');if(el)el.textContent=text;}
function drawTutorial(now:number){if(now>tutorialUntil)return;const lines=game==='dalgona'?['Move your index finger to position','Pinch thumb + index to carve','Open your hand to reposition']:game==='redlight'?['Calibrate while completely still','Swing alternate arms on green','Freeze when the screen turns red']:game==='tug'?['Capture relaxed, then your pull face','Hold the pull face · relax to recover']:['Look straight ahead and set centre','Move only your head left or right','Return to centre after every choice'];ctx.fillStyle='#080a09ee';ctx.fillRect(canvas.width*.14,canvas.height*.34,canvas.width*.72,canvas.height*.32);ctx.strokeStyle='#b1ff6a55';ctx.strokeRect(canvas.width*.14,canvas.height*.34,canvas.width*.72,canvas.height*.32);ctx.fillStyle='#fff';ctx.textAlign='center';ctx.font=`600 ${Math.max(15,canvas.width*.021)}px Space Grotesk`;ctx.fillText('FIRST-TIME GUIDE',canvas.width/2,canvas.height*.41);ctx.font=`400 ${Math.max(12,canvas.width*.016)}px Space Grotesk`;lines.forEach((line,i)=>ctx.fillText(line,canvas.width/2,canvas.height*(.48+i*.055)));}

renderPanel();
